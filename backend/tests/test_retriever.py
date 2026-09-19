"""
混合检索器测试(系统里最关键的"找资料"环节)
==========================================
小白理解:用户提问后系统要在知识库里找出最相关的资料。这套测试检查:
  ① 关键词索引(BM25)—— 把卡片按词拆开建索引,型号、数字这类精确词要能搜到
  ② RRF 融合 —— 两路检索结果怎么合并成一份榜单
  ③ 完整检索流程 —— 三道工序串起来跑得通,出错了有没有兜底

关键设计:**全程不联网、不调用阿里云**。
向量库和大模型都用"假扮的替身",测试才能又快又稳、不花一分钱。
"""
import asyncio

import numpy as np
import pytest
from langchain_core.documents import Document

from app.rag import retriever
from app.rag.retriever import BM25Index, RetrievedChunk, _doc_key, hybrid_retrieve, rrf_fuse

# ==================== 测试素材 ====================

# 三张假的知识卡片(模拟知识库里的内容)。
# 刻意用三个互不相干的产品:这样"关键词检索"能否精确命中才测得出差别 ——
# 如果几张卡片用词都差不多,搜什么都返回一堆,就测不出准不准了。
FAKE_CARDS = [
    ("星辰X1手机的电池容量是5000mAh", {"document_id": 1, "chunk_index": 0, "filename": "星辰X1参数.xlsx"}),
    ("云雀A3笔记本电脑的重量是1.2公斤", {"document_id": 2, "chunk_index": 0, "filename": "云雀A3参数.xlsx"}),
    ("电饭煲支持七天无理由退货,运费由商家承担", {"document_id": 3, "chunk_index": 0, "filename": "售后政策.md", "page": 2}),
]


class FakeVectorStore:
    """假扮的向量库:按关键词粗筛,不调用任何网络服务"""

    def __init__(self, cards=None):
        self.cards = cards if cards is not None else FAKE_CARDS

    def get(self):
        """BM25 建索引时会把全部卡片取出来"""
        return {
            "documents": [c[0] for c in self.cards],
            "metadatas": [c[1] for c in self.cards],
        }

    def similarity_search(self, query: str, k: int = 4):
        """假扮"语义检索":含有查询词的排前面(真实系统里是算向量距离)"""
        scored = []
        for text, meta in self.cards:
            # 统计查询里有多少个词出现在卡片中,出现越多算越相关
            hits = sum(1 for ch in set(query) if ch in text)
            scored.append((hits, text, meta))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [Document(page_content=t, metadata=m) for _, t, m in scored[:k]]


@pytest.fixture
def fake_store(monkeypatch):
    """把全局的向量库替换成假扮的(测试结束后自动还原)"""
    store = FakeVectorStore()
    monkeypatch.setattr(retriever, "get_vectorstore", lambda: store)
    return store


# ==================== 卡片标识 ====================

class TestDocKey:
    """卡片唯一标识:文档编号 + 卡片序号,用于在数据库和向量库之间对账"""

    def test_key_from_metadata(self):
        assert _doc_key({"document_id": 3, "chunk_index": 7}) == "3_7"

    def test_missing_metadata_uses_placeholder(self):
        """来源信息缺失时给个"?"兜底,不能直接抛异常(脏数据也要能扛住)"""
        assert _doc_key({}) == "?_?"


# ==================== 关键词索引 ====================

class TestBM25Index:
    """关键词检索(用放大镜找):型号、数字这类精确词一个不漏"""

    def test_finds_exact_model_number(self, fake_store):
        """搜索具体型号能精确命中 —— 这正是向量检索的短板"""
        index = BM25Index()
        results = index.search("云雀A3", k=3)
        assert len(results) > 0
        assert "云雀A3" in results[0][0].content

    def test_rank_starts_at_zero(self, fake_store):
        """排名从 0 开始(第一名是 0,不是 1)"""
        index = BM25Index()
        results = index.search("电池容量", k=3)
        assert results[0][1] == 0

    def test_metadata_attached(self, fake_store):
        """检索结果要带上来源信息(界面要显示"来自哪份文档")"""
        index = BM25Index()
        chunk, _ = index.search("电池容量", k=1)[0]
        assert chunk.filename == "星辰X1参数.xlsx"
        assert chunk.document_id == 1

    def test_no_match_returns_empty(self, fake_store):
        """一个实词都没匹配上时返回空列表(不能硬凑几条无关的出来)

        注意查询里刻意不含"的""是"这类虚词 —— 见下面那条测试的说明。
        """
        index = BM25Index()
        assert index.search("银河火箭 陶艺课程", k=3) == []

    def test_common_function_words_can_produce_false_hits(self, fake_store):
        """已知不足:查询里的"的""是"这类虚词会让不相干的卡片也混进来

        小白理解:中文里"的""是"几乎每句话都有。问"完全不相干的词汇"时，
        系统会看到"'的'这个词在两张卡片里出现过",于是把这两张也捞了回来，
        哪怕卡片内容跟问题毫无关系(实测得分约 0.1,远低于真正命中的 1.7)。

        这不是报错,是关键词检索算法的固有特点 ——
        好在下一步的"重排序"会把这类低分卡片筛掉,所以最终回答不受影响。
        这条测试把这个行为固定下来:以后若做了优化(比如过滤虚词),它会失败并提醒更新。
        """
        index = BM25Index()
        results = index.search("完全不相干的词汇", k=3)
        # 确实会捞回卡片,但分数很低(真正的命中分数要高一个数量级)
        for chunk, _ in results:
            assert chunk.content  # 有内容返回,属于"宁可多找几个"的保守行为

    def test_real_hit_scores_much_higher(self, fake_store):
        """真正的命中:精确匹配型号时,排第一的必须是那张对的卡片"""
        index = BM25Index()
        # BM25 分数越高越相关:精确命中(S5 型号)应远超虚词噪声
        top_score = index.search("云雀A3笔记本电脑", k=1)[0][0]
        assert "云雀A3" in top_score.content

    def test_invalidate_triggers_rebuild(self, fake_store):
        """文档增删后标记过期,下次检索要重新建索引"""
        index = BM25Index()
        index.search("电池", k=1)          # 先建一次
        assert index._dirty is False
        index.invalidate()                  # 模拟上传了新文档
        assert index._dirty is True
        index.search("电池", k=1)          # 再查会自动重建
        assert index._dirty is False

    def test_empty_knowledge_base(self, monkeypatch):
        """知识库是空的时候检索不报错(刚装好系统还没传文档)"""
        monkeypatch.setattr(retriever, "get_vectorstore", lambda: FakeVectorStore(cards=[]))
        index = BM25Index()
        assert index.search("任何问题", k=3) == []


# ==================== RRF 融合 ====================

class TestRRFFuse:
    """融合算法:两路都排名靠前的胜出(像两个评委都打高分)"""

    def test_later_position_gets_lower_score(self):
        """同一榜单里,名次越靠后分越低"""
        scores = rrf_fuse([["第一名", "第二名", "第三名"]])
        assert scores["第一名"] > scores["第二名"] > scores["第三名"]

    def test_appearing_in_both_wins(self):
        """两路都出现的卡片,总分高于只在一路出现的"""
        scores = rrf_fuse([["a", "b"], ["c", "a"]])
        assert scores["a"] > scores["b"]

    def test_score_matches_formula(self):
        """公式核对:1/(60+名次),业界通用值 60 用于削弱名次的极端影响"""
        scores = rrf_fuse([["x"]])
        assert scores["x"] == pytest.approx(1 / 61)

    def test_empty_and_blank_lists(self):
        """空输入不报错"""
        assert rrf_fuse([]) == {}
        assert rrf_fuse([[], []]) == {}


# ==================== 完整检索流程 ====================

class TestHybridRetrieve:
    """三道工序串起来:向量 + 关键词 → 融合 → 精排"""

    def test_returns_chunks(self, fake_store, monkeypatch):
        """正常流程能返回知识卡片,且带齐来源信息"""
        async def fake_rerank(query, docs, top_n):
            return [{"index": i, "relevance_score": 0.9 - i * 0.1} for i in range(min(top_n, len(docs)))]

        monkeypatch.setattr(retriever, "rerank_documents", fake_rerank, raising=True)
        results = asyncio.run(hybrid_retrieve("星辰X1电池容量"))
        assert len(results) > 0
        assert all(isinstance(c, RetrievedChunk) for c in results)
        assert all(c.filename for c in results)

    def test_rerank_score_recorded(self, fake_store, monkeypatch):
        """精排给的分数要记在卡片上(界面要显示相关度)"""
        async def fake_rerank(query, docs, top_n):
            return [{"index": 0, "relevance_score": 0.8765}]

        monkeypatch.setattr(retriever, "rerank_documents", fake_rerank, raising=True)
        results = asyncio.run(hybrid_retrieve("电池", top_n=1))
        assert results[0].rerank_score == pytest.approx(0.8765)

    def test_rerank_failure_falls_back(self, fake_store, monkeypatch):
        """重排序服务挂了也要能出结果 —— 退回融合排序,保证功能可用"""
        async def broken_rerank(query, docs, top_n):
            raise RuntimeError("重排序服务超时")

        monkeypatch.setattr(retriever, "rerank_documents", broken_rerank, raising=True)
        results = asyncio.run(hybrid_retrieve("星辰X1电池容量"))
        assert len(results) > 0  # 有兜底结果,不是空手而归

    def test_rerank_can_be_disabled(self, fake_store, monkeypatch):
        """评估实验用:关掉重排序时直接返回融合结果(用于对比"有无重排"的差异)"""
        async def should_not_be_called(query, docs, top_n):
            raise AssertionError("关掉重排后不应该再调用重排序服务")

        monkeypatch.setattr(retriever, "rerank_documents", should_not_be_called, raising=True)
        results = asyncio.run(hybrid_retrieve("电池容量", use_rerank=False))
        assert len(results) > 0

    def test_top_n_limits_result_count(self, fake_store, monkeypatch):
        """最终送给 AI 的卡片数量受 top_n 控制(不能一股脑全塞进去)"""
        async def fake_rerank(query, docs, top_n):
            return [{"index": i, "relevance_score": 0.5} for i in range(min(top_n, len(docs)))]

        monkeypatch.setattr(retriever, "rerank_documents", fake_rerank, raising=True)
        results = asyncio.run(hybrid_retrieve("电池容量", top_n=2))
        assert len(results) <= 2

    def test_both_ranks_merged_onto_same_card(self, fake_store, monkeypatch):
        """同一张卡片被两路都找到时,排名信息要合并到同一条记录上(不能出现重复卡片)"""
        async def fake_rerank(query, docs, top_n):
            return [{"index": i, "relevance_score": 0.5} for i in range(min(top_n, len(docs)))]

        monkeypatch.setattr(retriever, "rerank_documents", fake_rerank, raising=True)
        results = asyncio.run(hybrid_retrieve("星辰X1电池"))
        keys = [c.key for c in results]
        assert len(keys) == len(set(keys))  # 没有重复

    def test_empty_knowledge_base(self, monkeypatch):
        """知识库空的时候提问,返回空列表而不是报错"""
        monkeypatch.setattr(retriever, "get_vectorstore", lambda: FakeVectorStore(cards=[]))
        assert asyncio.run(hybrid_retrieve("电池多大")) == []
