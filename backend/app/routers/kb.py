"""
知识库管理接口(仅管理员可用)
============================
小白理解:知识库的"管理窗口",共五个功能:

  GET    /api/kb/documents              看文档列表
  POST   /api/kb/documents              上传文档(可一次传多个)
  DELETE /api/kb/documents/{id}         删除文档(连同它的知识卡片一起清掉)
  POST   /api/kb/documents/{id}/retry   重新处理(失败或想更新时用)
  GET    /api/kb/stats                  看知识库总览数据

安全说明:每个接口的"门禁"都是 require_admin —— 普通用户即使伪造请求也会被拒绝。
"""
import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import UPLOAD_DIR, settings
from app.database import get_db
from app.deps import require_admin
from app.models import Chunk, Document, User
from app.rag.ingest import enqueue_document
from app.rag.retriever import invalidate_bm25
from app.rag.vectorstore import count_vectors, delete_document_vectors
from app.utils.cache import answer_cache
from app.schemas import DocumentOut, KbStats, MessageOut
from app.utils.logger import logger

router = APIRouter(prefix="/api/kb", tags=["知识库管理"])


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    _: User = Depends(require_admin),  # 下划线表示"这个变量我用不到,只是过个安检"
    db: AsyncSession = Depends(get_db),
):
    """文档列表:按上传时间倒序(最新的排最上面)"""
    result = await db.execute(select(Document).order_by(Document.created_at.desc()))
    return [DocumentOut.model_validate(d) for d in result.scalars().all()]


@router.post("/documents", response_model=list[DocumentOut])
async def upload_documents(
    files: list[UploadFile] = File(..., description="要上传的文件,可一次选多个"),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    上传文档:校验格式和大小 → 存盘 → 登记到数据库 → 丢进后台队列慢慢处理。
    接口会立刻返回(不等处理完),前端靠轮询进度条展示处理进展。
    """
    if not files:
        raise HTTPException(status_code=400, detail="没有收到任何文件")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    results: list[Document] = []
    rejected: list[str] = []

    for file in files:
        original_name = file.filename or "未命名文件"
        ext = Path(original_name).suffix.lower()

        # ① 格式检查:只放行白名单里的格式
        if ext not in settings.allowed_ext_list:
            rejected.append(f"{original_name}(不支持 {ext} 格式)")
            continue

        # ② 读取内容并检查大小
        content = await file.read()
        if len(content) > max_bytes:
            rejected.append(f"{original_name}(超过 {settings.max_upload_mb}MB)")
            continue
        if not content:
            rejected.append(f"{original_name}(空文件)")
            continue

        # ③ 存盘:用随机编号做文件名,防止同名覆盖和恶意文件名
        #    (原始文件名只记在数据库里给用户看,不参与磁盘路径)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}{ext}"
        stored_path = UPLOAD_DIR / stored_name
        await asyncio.to_thread(stored_path.write_bytes, content)

        # ④ 登记到数据库
        doc = Document(
            filename=original_name,
            file_path=str(stored_path),
            file_type=ext.lstrip("."),
            size=len(content),
            status="pending",
            uploaded_by=user.id,
        )
        db.add(doc)
        results.append(doc)

    if results:
        await db.commit()
        for doc in results:
            await db.refresh(doc)
            enqueue_document(doc.id)  # 丢进后台处理队列
        logger.info(f"📤 管理员 {user.username} 上传了 {len(results)} 份文档")

    # 全部被拒绝的情况:直接报错说明原因
    if not results:
        raise HTTPException(status_code=400, detail="上传失败:" + ";".join(rejected))

    # 部分成功:把被拒的文件通过日志记录(前端也会看到成功的那些)
    if rejected:
        logger.warning(f"以下文件被拒绝: {'; '.join(rejected)}")

    return [DocumentOut.model_validate(d) for d in results]


@router.delete("/documents/{doc_id}", response_model=MessageOut)
async def delete_document(
    doc_id: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    删除文档:三处一起清 —— 数据库记录、磁盘文件、向量库里的卡片。
    (只删一半会造成"幽灵引用":AI 还能检索到一段查不到出处的文字)
    """
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在或已被删除")

    filename = doc.filename
    file_path = Path(doc.file_path)

    # ① 清向量库里的卡片,并通知关键词索引失效(下次检索时自动重建)
    await asyncio.to_thread(delete_document_vectors, doc_id)
    invalidate_bm25()
    answer_cache.clear()  # 知识库变了,缓存的答案可能过时,一并清掉
    # ② 清数据库里的卡片记录 + 文档记录
    await db.execute(sql_delete(Chunk).where(Chunk.document_id == doc_id))
    await db.delete(doc)
    await db.commit()
    # ③ 删磁盘文件(失败也不影响流程,只记日志)
    try:
        if file_path.exists():
            await asyncio.to_thread(file_path.unlink)
    except OSError as exc:
        logger.warning(f"删除文件失败(不影响数据): {file_path} -> {exc}")

    logger.info(f"🗑️  管理员删除文档: {filename}")
    return MessageOut(message=f"已删除「{filename}」及其全部知识卡片")


@router.post("/documents/{doc_id}/retry", response_model=MessageOut)
async def retry_document(
    doc_id: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """重新处理:把文档重新丢进队列(失败的可以重试,改过的文件可以重新入库)"""
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")

    if doc.status == "processing":
        raise HTTPException(status_code=400, detail="该文档正在处理中,请等它完成")

    doc.status = "pending"
    doc.progress = 0
    doc.error_msg = None
    await db.commit()
    enqueue_document(doc_id)

    logger.info(f"🔄 文档重新入队: {doc.filename}")
    return MessageOut(message=f"「{doc.filename}」已重新加入处理队列")


@router.get("/stats", response_model=KbStats)
async def kb_stats(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """知识库总览:文档数、各状态数量、卡片总数、占用空间"""
    # 按状态分组统计文档数量(一条 SQL 查完,比逐个查快得多)
    rows = await db.execute(select(Document.status, func.count(Document.id)).group_by(Document.status))
    status_counts = {status: count for status, count in rows.all()}

    total_size = await db.scalar(select(func.coalesce(func.sum(Document.size), 0)))
    # 卡片总数直接问向量库(它才是真实生效的数据)
    chunk_total = await asyncio.to_thread(count_vectors)

    return KbStats(
        document_count=sum(status_counts.values()),
        completed_count=status_counts.get("completed", 0),
        processing_count=status_counts.get("processing", 0) + status_counts.get("pending", 0),
        failed_count=status_counts.get("failed", 0),
        chunk_count=chunk_total,
        total_size=int(total_size or 0),
    )
