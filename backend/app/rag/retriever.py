"""
混合检索器(系统里最关键的"找资料"环节)
======================================
小白理解:用户提问后,系统要在知识库里找出最相关的几段资料。我们用了
"三道工序",层层筛选,保证找得又全又准:

  第一道:向量检索(撒大网)
    把问题和所有知识卡片都变成"语义坐标",找出坐标距离最近的 12 张。
    优点:能理解意思 —— 问"电池能用多久",能找到写着"续航时间"的卡片。
    缺点:对精确的型号、编号不敏感 —— 问"X1-Pro",可能找到一堆别的型号。

  第二道:关键词检索(BM25,用放大镜找)
    把问题和卡片都按词拆开,精确匹配关键词,找出最对得上的 12 张。
    优点:型号、数字这类精确词一个不漏。
    缺点:不理解同义词 —— 问"续航",找不到只写着"电池容量"的卡片。

  第三道:合二为一 + 精排
    把两路结果用 RRF 算法合并(两路都排前面的,说明是真好),
    再请"筛选专家"(qwen3-rerank)逐条细看,挑出最相关的 4 张送进 AI。

这套组合拳就是"企业级 RAG"的标准做法,业界称为 Hybrid Retrieval + Rerank。
"""
import asyncio
from dataclasses import dataclass, field

import jieba
import numpy as np
from langchain_core.documents import Document

from app.config import settings
from app.rag.llm import rerank_documents
from app.rag.vectorstore import get_vectorstore
from app.utils.logger import logger

# RRF 融合算法的平滑参数(业界常用值 60,作用是让排名靠前的优势不那么极端)
_RRF_K = 60


@dataclass
class RetrievedChunk:
    """检索到的一张知识卡片(含来源信息,用于界面上的引用展示)"""

    key: str                       # 唯一标识(document_id_chunk_index)
    content: str                   # 卡片文字
    filename: str                  # 来自哪份文档
    document_id: int               # 文档编号
    page: int | None = None        # 页码(如果有)
    vector_rank: int | None = None  # 在向量检索里的排名
    bm25_rank: int | None = None    # 在关键词检索里的排名
    rerank_score: float | None = None  # 重排序给的相关度分数


def _doc_key(meta: dict) -> str:
    """给每张卡片生成唯一标识:文档编号 + 卡片序号"""
    return f"{meta.get('document_id', '?')}_{meta.get('chunk_index', '?')}"


# ==================== BM25 关键词索引 ====================

class BM25Index:
    """
    关键词索引:把知识库里所有卡片用中文分词切开,建一个"词 → 卡片"的倒排表。
    文档有增删时需要重建(用 dirty 标记控制,不是每次都重建)。
    """

    def __init__(self) -> None:
        self._bm25 = None                 # BM25 模型
        self._keys: list[str] = []        # 每张卡片的唯一标识
        self._texts: list[str] = []       # 每张卡片的原文
        self._metas: list[dict] = []      # 每张卡片的来源信息
        self._dirty = True                # 是否需要重建

    def invalidate(self) -> None:
        """标记索引已过期(文档增删后调用,下次检索时自动重建)"""
        self._dirty = True

    def _rebuild(self) -> None:
        """重建索引:从向量库拉取全部卡片,分词后建立 BM25 模型"""
        from rank_bm25 import BM25Okapi

        store = get_vectorstore()
        data = store.get()  # 取出所有卡片
        texts = data.get("documents") or []
        metas = data.get("metadatas") or []

        if not texts:
            self._bm25 = None
            self._dirty = False
            return

        # 中文分词:jieba 把"星辰X1智能手机"切成 ["星辰", "X1", "智能", "手机"]
        tokenized = [list(jieba.cut(t)) for t in texts]
        self._bm25 = BM25Okapi(tokenized)
        self._keys = [_doc_key(m) for m in metas]
        self._texts = texts
        self._metas = metas
        self._dirty = False
        logger.info(f"🔍 关键词索引已建立: {len(texts)} 张卡片")

    def search(self, query: str, k: int) -> list[tuple[RetrievedChunk, int]]:
        """按关键词检索,返回 [(卡片, 排名), ...],排名从 0 开始"""
        if self._dirty:
            self._rebuild()
        if self._bm25 is None:
            return []

        tokens = list(jieba.cut(query))
        scores = np.asarray(self._bm25.get_scores(tokens))

        # 取分数最高的 k 个(分数为 0 的不要 —— 一个关键词都没匹配上)
        top_idx = np.argsort(scores)[::-1][:k]
        results = []
        for rank, idx in enumerate(top_idx):
            if scores[idx] <= 0:
                break
            meta = self._metas[idx]
            results.append(
                (
                    RetrievedChunk(
                        key=self._keys[idx],
                        content=self._texts[idx],
                        filename=meta.get("filename", "未知文档"),
                        document_id=meta.get("document_id", 0),
                        page=meta.get("page"),
                        bm25_rank=rank,
                    ),
                    rank,
                )
            )
        return results


# 全局单例:整个程序共用一个索引
_bm25_index = BM25Index()


def invalidate_bm25() -> None:
    """通知索引失效(文档上传完成、删除后调用)"""
    _bm25_index.invalidate()


# ==================== RRF 融合 ====================

def rrf_fuse(rank_lists: list[list[str]]) -> dict[str, float]:
    """
    RRF(倒数排名融合)算法:把多路检索结果合并成一个总分。

    小白理解:就像两个评委分别给选手排名。一个选手在两份榜单里都靠前,
    说明他确实优秀。分数公式 = 1/(60+名次),两路得分相加,总分高的排前面。
    """
    scores: dict[str, float] = {}
    for ranks in rank_lists:
        for position, key in enumerate(ranks):
            scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + position + 1)
    return scores


# ==================== 对外接口:检索 ====================

async def hybrid_retrieve(
    query: str,
    top_k_each: int | None = None,
    top_n: int | None = None,
    use_rerank: bool = True,
) -> list[RetrievedChunk]:
    """
    完整的三道工序检索,返回最终精选的知识卡片列表。

    参数:
      query      —— 用户的问题(或改写后的问题)
      top_k_each —— 前两道工序各召回多少张(默认 12)
      top_n      —— 最终送给 AI 几张卡片(默认 4)
      use_rerank —— 是否启用第三道工序的重排序。
                    平时都是 True;评估脚本会关掉它来对比"有无重排"的效果差异。
    """
    top_k_each = top_k_each or settings.retrieve_top_k
    top_n = top_n or settings.rerank_top_n

    store = get_vectorstore()

    # ---------- 工序一:向量检索(撒大网) ----------
    def _vector_search() -> list[Document]:
        return store.similarity_search(query, k=top_k_each)

    vector_docs = await asyncio.to_thread(_vector_search)
    vector_keys = [_doc_key(d.metadata) for d in vector_docs]

    # ---------- 工序二:关键词检索(放大镜) ----------
    bm25_results = await asyncio.to_thread(_bm25_index.search, query, top_k_each)

    # ---------- 工序三之一:RRF 融合两边结果 ----------
    fuse_scores = rrf_fuse([vector_keys, [c.key for c, _ in bm25_results]])

    # 把两路结果按 key 汇总成字典,方便后面查取内容
    pool: dict[str, RetrievedChunk] = {}
    for rank, doc in enumerate(vector_docs):
        key = _doc_key(doc.metadata)
        pool[key] = RetrievedChunk(
            key=key,
            content=doc.page_content,
            filename=doc.metadata.get("filename", "未知文档"),
            document_id=doc.metadata.get("document_id", 0),
            page=doc.metadata.get("page"),
            vector_rank=rank,
        )
    for chunk, rank in bm25_results:
        if chunk.key in pool:
            pool[chunk.key].bm25_rank = rank  # 补上关键词检索的名次
        else:
            pool[chunk.key] = chunk

    # 按融合分数排序,取前 8 进入精排(候选池不大不小,兼顾速度与精度)
    sorted_keys = sorted(fuse_scores, key=lambda k: fuse_scores[k], reverse=True)
    candidates = [pool[k] for k in sorted_keys[: max(top_n * 2, 8)] if k in pool]

    if not candidates:
        return []

    # 评估模式:跳过重排序,直接返回融合结果(用于对比实验)
    if not use_rerank:
        return candidates[:top_n]

    # ---------- 工序三之二:重排序精选 ----------
    try:
        ranked = await rerank_documents(
            query, [c.content for c in candidates], top_n=min(top_n, len(candidates))
        )
        final: list[RetrievedChunk] = []
        for item in ranked:
            idx = item["index"]
            if 0 <= idx < len(candidates):
                chunk = candidates[idx]
                chunk.rerank_score = float(item.get("relevance_score", 0))
                final.append(chunk)
        if final:
            logger.info(
                f"🔎 检索完成: 向量{len(vector_keys)}条 + 关键词{len(bm25_results)}条 "
                f"→ 融合{len(candidates)}条 → 精排{len(final)}条"
            )
            return final
    except Exception as exc:
        # 重排序失败不影响主流程:退回融合排序的结果,保证功能可用
        logger.warning(f"重排序失败,使用融合结果兜底: {exc}")

    return candidates[:top_n]
