"""
文档入库流水线(把上传的文件变成"AI 能查的资料")
==============================================
小白理解:一条自动流水线,共五道工序:

  ① 解析:把 PDF/Word/Excel 读成文字          —— 进度 5% → 20%
  ② 切分:把长文剪成一张张知识卡片             —— 进度 20% → 40%
  ③ 向量化:把每张卡片翻译成"语义坐标"         —— 进度 40% → 90%
  ④ 入库:卡片存进"智能档案柜"(Chroma)        —— 包含在③中
  ⑤ 记账:在数据库登记每张卡片,更新文档状态    —— 进度 90% → 100%

为什么用"后台队列"?
  大文件处理要好几十秒。如果让用户在前台干等,网页会卡住甚至超时。
  所以我们把任务丢进队列就立刻回复"收到了",后台工人慢慢处理,
  网页上通过进度条看进展 —— 这就是"企业级"的做法。
"""
import asyncio
from pathlib import Path

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import Chunk, Document
from app.rag.loader import load_document
from app.rag.retriever import invalidate_bm25
from app.rag.splitter import split_documents
from app.rag.vectorstore import add_chunks, delete_document_vectors
from app.utils.cache import answer_cache
from app.utils.errors import friendly_api_error
from app.utils.logger import logger

# 待处理任务队列(存放文档编号)
_queue: asyncio.Queue[int] = asyncio.Queue()

# 每批提交多少张卡片去向量化(批量提交比一张张提交快得多)
_EMBED_BATCH = 50


async def _update_status(
    doc_id: int,
    status: str | None = None,
    progress: int | None = None,
    chunk_count: int | None = None,
    error_msg: str | None = None,
) -> None:
    """更新文档的处理状态(界面上进度条靠它驱动)"""
    async with SessionLocal() as db:
        doc = await db.get(Document, doc_id)
        if doc is None:
            return  # 文档可能已被删除,忽略即可
        if status is not None:
            doc.status = status
        if progress is not None:
            doc.progress = progress
        if chunk_count is not None:
            doc.chunk_count = chunk_count
        if error_msg is not None:
            doc.error_msg = error_msg
        await db.commit()


async def _process_document(doc_id: int) -> None:
    """处理单份文档:完整的五道工序"""
    async with SessionLocal() as db:
        doc = await db.get(Document, doc_id)
        if doc is None:
            logger.warning(f"待处理文档不存在(可能已被删除): #{doc_id}")
            return
        file_path = Path(doc.file_path)
        filename = doc.filename

    # 开始处理前,先清掉这份文档的旧数据(支持"重新处理")
    await _clear_document_data(doc_id)

    try:
        await _update_status(doc_id, status="processing", progress=5, error_msg="")

        # ---------- 工序 ①:解析文件 ----------
        if not file_path.exists():
            raise FileNotFoundError(f"文件已丢失: {file_path}")
        # to_thread:解析是"体力活",放到旁路线程去做,不占用主线程
        raw_docs = await asyncio.to_thread(load_document, file_path)
        await _update_status(doc_id, progress=20)
        if not raw_docs:
            raise ValueError("文件里没有可用的文字内容")

        # ---------- 工序 ②:切分成知识卡片 ----------
        chunks = await asyncio.to_thread(split_documents, raw_docs)
        await _update_status(doc_id, progress=40)
        if not chunks:
            raise ValueError("切分后没有得到任何内容")

        # ---------- 工序 ③④:向量化 + 存入向量库(分批,边做边报进度) ----------
        total = len(chunks)
        chroma_ids: list[str] = []
        for start in range(0, total, _EMBED_BATCH):
            batch = chunks[start : start + _EMBED_BATCH]
            ids = await asyncio.to_thread(add_chunks, batch, doc_id, filename)
            chroma_ids.extend(ids)
            # 进度从 40% 平滑推进到 90%
            percent = 40 + int(50 * (start + len(batch)) / total)
            await _update_status(doc_id, progress=min(percent, 90))

        # ---------- 工序 ⑤:在数据库登记每张卡片 ----------
        async with SessionLocal() as db:
            records = [
                Chunk(
                    document_id=doc_id,
                    chunk_index=i,
                    content=chunk.page_content,
                    meta_json={k: v for k, v in chunk.metadata.items() if isinstance(v, (str, int, float))},
                    chroma_id=chroma_ids[i] if i < len(chroma_ids) else None,
                )
                for i, chunk in enumerate(chunks)
            ]
            db.add_all(records)
            await db.commit()

        # ---------- 完成 ----------
        await _update_status(doc_id, status="completed", progress=100, chunk_count=total)
        # 通知关键词检索索引:知识库有变化,下次检索前先重建索引
        invalidate_bm25()
        # 知识库变了,之前缓存的答案可能已过时 —— 整本缓存作废
        answer_cache.clear()
        logger.info(f"✅ 文档入库完成: {filename}({total} 张卡片)")

    except Exception as exc:
        # 任何一步出错,记录失败原因(翻译成人话),供管理员在界面上查看和重试
        logger.exception(f"❌ 文档入库失败: {filename} -> {exc}")
        await _update_status(doc_id, status="failed", progress=0, error_msg=friendly_api_error(exc))


async def _clear_document_data(doc_id: int) -> None:
    """清掉一份文档的旧卡片(数据库记录 + 向量库数据),用于重新处理前的清理"""
    async with SessionLocal() as db:
        await db.execute(delete(Chunk).where(Chunk.document_id == doc_id))
        await db.commit()
    await asyncio.to_thread(delete_document_vectors, doc_id)


async def worker() -> None:
    """
    后台工人:不停地从队列取任务来处理,一次只处理一个。
    为什么要"排队一个个来"?因为向量库不喜欢多人同时写入,
    串行处理最稳当(这也是企业系统的常规做法)。
    """
    logger.info("👷 入库队列工人已上岗")
    while True:
        doc_id = await _queue.get()
        try:
            await _process_document(doc_id)
        except Exception:
            # 兜底:工人绝不能因为单个任务出错而"罢工"
            logger.exception(f"处理文档 #{doc_id} 时发生意外错误")
        finally:
            _queue.task_done()


def enqueue_document(doc_id: int) -> None:
    """把一份文档加入待处理队列(上传接口调用)"""
    _queue.put_nowait(doc_id)
    logger.info(f"📥 文档 #{doc_id} 已加入处理队列(当前排队 {_queue.qsize()} 个)")


async def requeue_unfinished() -> None:
    """
    程序启动时的"补漏":上次运行中途关闭时,可能有文档卡在"处理中"状态,
    启动后自动把它们重新排队,免得永远停在半路。
    """
    async with SessionLocal() as db:
        result = await db.execute(select(Document).where(Document.status.in_(["pending", "processing"])))
        pending_docs = result.scalars().all()

    for doc in pending_docs:
        # 先把状态改回排队中,再重新入队
        await _update_status(doc.id, status="pending", progress=0)
        enqueue_document(doc.id)

    if pending_docs:
        logger.info(f"🔄 已重新排队 {len(pending_docs)} 份未处理完的文档")
