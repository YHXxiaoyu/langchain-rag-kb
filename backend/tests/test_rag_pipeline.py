"""
RAG 流水线测试(检索之后、生成之前的那段"组装"工作)
==================================================
小白理解:知识卡片找出来以后,还要做两件事才能送给 AI:
  ① 整理成"引用清单"—— 告诉界面"这段资料来自哪个文件、第几页、相关度多少"
  ② 组装成一段完整的"指令"—— 把卡片编号排好,连同历史对话一起递过去

这两个环节出错的表现很隐蔽:AI 还是能答,但引用会错位、页码会串 ——
用户看到的"来源"就是假的。所以必须测。

注意:这里**不调用阿里云**(不花钱、不联网),只测本地的字符串拼装逻辑。
"""
import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.rag.pipeline import (
    SYSTEM_PROMPT,
    _build_context,
    build_citations,
    build_messages,
    rewrite_query,
    stream_answer,
)
from app.rag.retriever import RetrievedChunk


def _chunk(
    content: str = "电池容量为 5000mAh",
    filename: str = "星辰X1参数表.xlsx",
    page: int | None = None,
    doc_id: int = 1,
    **kwargs,
) -> RetrievedChunk:
    """造一张假的知识卡片(测试用的素材,不用真去检索)"""
    return RetrievedChunk(
        key=f"{doc_id}_0",
        content=content,
        filename=filename,
        document_id=doc_id,
        page=page,
        **kwargs,
    )


# ==================== 引用清单 ====================

class TestBuildCitations:
    """把检索结果整理成前端要展示的"引用清单" """

    def test_index_starts_at_one(self):
        """编号要从 1 开始 —— 因为回答里写的是 [1][2],不是 [0][1]"""
        citations = build_citations([_chunk(), _chunk(content="第二段")])
        assert [c["index"] for c in citations] == [1, 2]

    def test_carries_source_info(self):
        """来源信息必须齐全:文件名、原文、页码、文档编号"""
        c = build_citations([_chunk(page=3, doc_id=7)])[0]
        assert c["filename"] == "星辰X1参数表.xlsx"
        assert c["content"] == "电池容量为 5000mAh"
        assert c["page"] == 3
        assert c["document_id"] == 7

    def test_score_rounded(self):
        """相关度分数保留 4 位小数(界面显示太长的数字不好看)"""
        c = build_citations([_chunk(rerank_score=0.123456789)])[0]
        assert c["score"] == 0.1235

    def test_score_none_becomes_zero(self):
        """没有重排序分数时给 0,不能让界面显示 null"""
        assert build_citations([_chunk()])[0]["score"] == 0

    def test_rank_info_kept(self):
        """两路检索的排名要带上 —— 界面靠它显示"语义检索第2名/关键词检索第1名" """
        c = build_citations([_chunk(vector_rank=1, bm25_rank=0)])[0]
        assert c["vector_rank"] == 1
        assert c["bm25_rank"] == 0

    def test_empty_list(self):
        """一条资料都没检索到时返回空清单,不能报错"""
        assert build_citations([]) == []


# ==================== 参考资料拼装 ====================

class TestBuildContext:
    """把卡片拼成 AI 能读的"参考资料"文本"""

    def test_numbered_and_sourced(self):
        """每段资料要带编号和出处 —— AI 才能照着写 [1] 并说清来自哪个文件"""
        text = _build_context([_chunk(), _chunk(content="保修两年", filename="保修卡.pdf")])
        assert "[1] 来源:《星辰X1参数表.xlsx》" in text
        assert "[2] 来源:《保修卡.pdf》" in text

    def test_page_shown_when_present(self):
        """有页码的要写上"第 N 页",没有的不能硬编一个"""
        assert "第 3 页" in _build_context([_chunk(page=3)])
        assert "第" not in _build_context([_chunk(page=None)]).split("\n")[0]

    def test_empty_chunks_placeholder(self):
        """没找到资料时给一句明确的占位说明(AI 才知道该说"暂无资料")"""
        assert "没有检索到任何参考资料" in _build_context([])


# ==================== 消息组装 ====================

class TestBuildMessages:
    """组装发给 AI 的完整消息(系统设定 + 历史对话 + 本轮问题)"""

    def test_first_message_is_system_prompt(self):
        """第一条永远是角色设定,不能被打乱"""
        messages = build_messages("电池多大", [_chunk()])
        assert isinstance(messages[0], SystemMessage)
        assert messages[0].content == SYSTEM_PROMPT

    def test_last_message_contains_question_and_context(self):
        """最后一条是本次提问,里面同时装着参考资料和问题"""
        messages = build_messages("电池多大", [_chunk()])
        last = messages[-1]
        assert isinstance(last, HumanMessage)
        assert "电池多大" in last.content
        assert "5000mAh" in last.content

    def test_history_included_in_order(self):
        """历史对话要按顺序放在中间,让 AI 理解"它"指的是什么"""
        history = [("星辰X1电池多大", "5000mAh"), ("它保修多久", "两年")]
        messages = build_messages("它的重量呢", [_chunk()], history)
        # 1 条系统设定 + 2 轮历史(4 条) + 本轮 1 条 = 6 条
        assert len(messages) == 6
        assert isinstance(messages[1], HumanMessage)
        assert messages[1].content == "星辰X1电池多大"
        assert isinstance(messages[2], AIMessage)
        assert messages[2].content == "5000mAh"

    def test_no_history_still_works(self):
        """第一轮提问没有历史,也要能正常组装"""
        assert len(build_messages("问题", [_chunk()], None)) == 2


# ==================== 查询改写 ====================

class TestRewriteQuery:
    """查询改写:把"它保修多久"补全成"星辰X1保修多久" """

    def test_no_history_returns_original(self):
        """没有历史对话时直接返回原问题,不必浪费一次 AI 调用"""
        result = asyncio.run(rewrite_query("电池多大", None))
        assert result == "电池多大"

    def test_llm_failure_falls_back(self, monkeypatch):
        """AI 调用失败时退回原问题 —— 改写只是锦上添花,不能拖垮主流程"""

        class BrokenLLM:
            async def ainvoke(self, _):
                raise RuntimeError("网络断了")

        monkeypatch.setattr("app.rag.pipeline.get_llm", lambda **_: BrokenLLM())
        result = asyncio.run(rewrite_query("它保修多久", [("星辰X1怎么样", "很好")]))
        assert result == "它保修多久"

    def test_overlong_result_falls_back(self, monkeypatch):
        """AI 返回一长串废话时判定为异常,退回原问题"""
        from langchain_core.messages import AIMessage

        class VerboseLLM:
            async def ainvoke(self, _):
                return AIMessage(content="这是一段非常啰嗦的解释" * 50)

        monkeypatch.setattr("app.rag.pipeline.get_llm", lambda **_: VerboseLLM())
        result = asyncio.run(rewrite_query("它保修多久", [("星辰X1怎么样", "很好")]))
        assert result == "它保修多久"

    def test_rewritten_result_used(self, monkeypatch):
        """正常的改写结果要被采用,并且去掉多余的引号"""
        from langchain_core.messages import AIMessage

        class GoodLLM:
            async def ainvoke(self, _):
                return AIMessage(content="「星辰X1手机保修多久」")

        monkeypatch.setattr("app.rag.pipeline.get_llm", lambda **_: GoodLLM())
        result = asyncio.run(rewrite_query("它保修多久", [("星辰X1怎么样", "很好")]))
        assert result == "星辰X1手机保修多久"


# ==================== 流式生成 ====================

class TestStreamAnswer:
    """流式生成回答:一个字一个字地吐出来(网页上的打字机效果)"""

    def test_yields_text_then_usage(self, monkeypatch):
        """先吐出文字片段,最后附带 token 用量(用于成本统计)"""

        class FakeEvent:
            def __init__(self, content, usage=None):
                self.content = content
                self.usage_metadata = usage

        class FakeLLM:
            async def astream(self, _):
                yield FakeEvent("电池")
                yield FakeEvent("容量5000mAh")
                yield FakeEvent("", {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})

        monkeypatch.setattr("app.rag.pipeline.get_llm", lambda **_: FakeLLM())

        async def collect():
            return [item async for item in stream_answer("电池多大", [_chunk()])]

        results = asyncio.run(collect())
        texts = "".join(t for t, _ in results)
        assert texts == "电池容量5000mAh"
        assert results[-1][1]["tokens"] == 120  # 最后一条带用量

    def test_api_error_becomes_friendly_message(self, monkeypatch):
        """AI 调用出错时,要吐出一句人话给用户,而不是白屏"""

        class BrokenLLM:
            async def astream(self, _):
                raise RuntimeError("Arrearage: account is overdue")
                yield  # pragma: no cover —— 让这个函数保持"生成器"身份

        monkeypatch.setattr("app.rag.pipeline.get_llm", lambda **_: BrokenLLM())

        async def collect():
            return [item async for item in stream_answer("问题", [_chunk()])]

        results = asyncio.run(collect())
        text = "".join(t for t, _ in results)
        assert "余额不足" in text  # 英文报错被翻译成了中文提示

    def test_empty_content_skipped(self, monkeypatch):
        """空片段不往外发(避免前端收到一堆没用的空消息)"""

        class FakeEvent:
            def __init__(self, content, usage=None):
                self.content = content
                self.usage_metadata = usage

        class FakeLLM:
            async def astream(self, _):
                yield FakeEvent("")
                yield FakeEvent("有内容")
                yield FakeEvent("")

        monkeypatch.setattr("app.rag.pipeline.get_llm", lambda **_: FakeLLM())

        async def collect():
            return [item async for item in stream_answer("问题", [_chunk()])]

        results = asyncio.run(collect())
        texts = [t for t, _ in results if t]
        assert texts == ["有内容"]
