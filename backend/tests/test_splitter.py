"""
文本切分器测试(把长文档剪成"小卡片")
====================================
小白理解:一本书没法整本塞给 AI 看,要剪成一张张卡片,每张卡片一个知识点。
剪得好不好直接决定检索准不准:
  - 剪太碎:一句话被切两半,回答时缺头少尾
  - 剪太长:一张卡片里混着好几件事,AI 抓不住重点

这些测试检查:该保留的来源信息有没有丢、编号有没有排好、会不会乱切。
"""
from langchain_core.documents import Document

from app.config import settings
from app.rag.splitter import get_splitter, split_documents


class TestSplitter:
    """切分器本身的行为"""

    def test_short_text_kept_whole(self):
        """短文本不该被切开(一句话本来就该是一张卡片)"""
        docs = [Document(page_content="星辰X1电池容量5000mAh", metadata={"page": 1})]
        chunks = split_documents(docs)
        assert len(chunks) == 1
        assert chunks[0].page_content == "星辰X1电池容量5000mAh"

    def test_long_text_is_split(self):
        """超长文本要切成多张卡片(否则一张卡片塞爆 AI 的上下文)"""
        long_text = "这是一段关于星辰X1手机的详细说明。" * 200  # 约 3400 字
        docs = [Document(page_content=long_text, metadata={})]
        chunks = split_documents(docs)
        assert len(chunks) > 1

    def test_chunk_size_respected(self):
        """每张卡片不能明显超过设定的字数上限(留点余量给标点)"""
        long_text = "商品参数说明。" * 400
        chunks = split_documents([Document(page_content=long_text, metadata={})])
        for chunk in chunks:
            assert len(chunk.page_content) <= settings.chunk_size + 60

    def test_metadata_preserved(self):
        """来源信息必须跟着卡片走 —— 丢了就不知道引用的是哪份文件、第几页"""
        docs = [Document(page_content="商品介绍内容", metadata={"page": 3, "filename": "说明书.pdf"})]
        chunks = split_documents(docs)
        assert chunks[0].metadata["page"] == 3
        assert chunks[0].metadata["filename"] == "说明书.pdf"

    def test_chunk_index_assigned(self):
        """每张卡片要有连续编号(从 0 开始),用于删除文档时精确清理"""
        long_text = "商品参数说明。" * 400
        chunks = split_documents([Document(page_content=long_text, metadata={})])
        assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))

    def test_multiple_documents_share_numbering(self):
        """多份文档一起切时,编号在整个批次里连续(不能每份都从 0 重新数)"""
        docs = [
            Document(page_content="第一份文档内容", metadata={"filename": "a.txt"}),
            Document(page_content="第二份文档内容", metadata={"filename": "b.txt"}),
        ]
        chunks = split_documents(docs)
        assert [c.metadata["chunk_index"] for c in chunks] == [0, 1]

    def test_empty_input(self):
        """空输入不报错(上传空文件时不能把程序搞崩)"""
        assert split_documents([]) == []


class TestSeparators:
    """切分标尺:中文文档要优先在句子边界切"""

    def test_splits_at_chinese_period(self):
        """优先在句号处切开:每张卡片都该是完整的句子,而不是被切成半句或几个字"""
        # 用 6 句不同的话反复说,模拟真实文档(单一句话重复会被算法压成纯文本再硬切)
        sentences = [
            "星辰X1手机的电池容量是5000mAh。",
            "该机型支持65W有线快充。",
            "屏幕采用6.7英寸OLED材质。",
            "整机重量约为185克。",
            "保修期为两年,支持全国联保。",
            "包装内附赠原装充电器一个。",
        ]
        text = "".join(sentences) * 20
        chunks = split_documents([Document(page_content=text, metadata={})])

        assert len(chunks) > 1
        # 每张卡片里都要有完整句子(句号),说明没有被切成一堆零碎字符
        for chunk in chunks:
            assert "。" in chunk.page_content
            assert len(chunk.page_content) > 50  # 不能切出太碎的片段

    def test_overlap_configured(self):
        """相邻卡片要留重叠(像贴瓷砖留缝,防止关键信息正好卡在接缝上)"""
        splitter = get_splitter()
        assert splitter._chunk_overlap == settings.chunk_overlap
        assert splitter._chunk_overlap > 0
