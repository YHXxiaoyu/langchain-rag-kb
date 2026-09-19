"""
向量库封装(知识卡片的"智能档案柜")
==================================
小白理解:切好的知识卡片存进这个"智能档案柜"。它最厉害的地方是:
你问"电池能用多久",它不仅能找到写着"电池"的卡片,还能找到写着"续航时间"的卡片
—— 因为它存的是"语义坐标",意思相近的内容坐标也相近。

技术说明:用的是 Chroma(本地文件型向量数据库),数据存在 data/chroma 目录,
不需要额外安装任何数据库软件。整个系统共用一个连接(单例模式)。
"""
from functools import lru_cache

import chromadb
from langchain_chroma import Chroma

from app.config import CHROMA_DIR
from app.rag.llm import get_embeddings
from app.utils.logger import logger

# 集合名称:相当于"档案柜里那个抽屉的名字"
COLLECTION_NAME = "knowledge"


@lru_cache(maxsize=1)
def get_vectorstore() -> Chroma:
    """
    获取向量库(全系统共用一个实例)。
    第一次调用时创建,之后一直复用 —— 反复创建会拖慢速度。
    """
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    store = Chroma(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),  # 用阿里云向量模型把文字转成坐标
    )
    logger.info(f"🗂️  向量库就绪: {CHROMA_DIR}")
    return store


def add_chunks(chunks: list, document_id: int, filename: str) -> list[str]:
    """
    把知识卡片存入向量库,返回每张卡片的"柜号"(向量库编号)。
    每个卡片都打上"来自哪份文档"的标签,删除文档时才能精确清干净。
    """
    if not chunks:
        return []

    # 给每张卡片补充身份信息
    metadatas = []
    for chunk in chunks:
        meta = dict(chunk.metadata)          # 页码、行号等原有信息
        meta["document_id"] = document_id    # 所属文档编号(删除时按它找)
        meta["filename"] = filename          # 文件名(引用展示时显示)
        metadatas.append(meta)

    store = get_vectorstore()
    ids = store.add_texts(
        texts=[c.page_content for c in chunks],
        metadatas=metadatas,
    )
    logger.info(f"📥 已入库 {len(ids)} 张知识卡片(文档编号 {document_id})")
    return ids


def delete_document_vectors(document_id: int) -> int:
    """
    删除某份文档的全部向量(删除文档时调用)。
    返回删除的卡片数量。
    """
    store = get_vectorstore()
    # 先数一数有多少张(Chroma 删除接口不返回数量,只能先查再删)
    existing = store.get(where={"document_id": document_id})
    count = len(existing.get("ids", []))

    if count > 0:
        store.delete(ids=existing["ids"])
        logger.info(f"🗑️  已从向量库删除 {count} 张卡片(文档编号 {document_id})")
    return count


def count_vectors() -> int:
    """统计向量库里一共有多少张知识卡片(管理页面显示用)"""
    store = get_vectorstore()
    return store._collection.count()
