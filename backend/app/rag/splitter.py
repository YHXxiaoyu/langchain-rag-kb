"""
文本切分器(把长文档剪成"小卡片")
================================
小白理解:一本书没法整本塞给 AI 看,要剪成一张张小卡片,每张卡片一个知识点。
以后提问时,系统只找出最相关的几张卡片递给 AI。

为什么不能剪太碎也不能剪太长?
  - 剪太碎:一句话被切两半,回答时缺头少尾
  - 剪太长:一张卡片里混着好几件事,AI 抓不住重点
本项目取 500 字左右一张,相邻卡片留 50 字重叠(像贴瓷砖留缝,防止意思被切断)。
"""
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.utils.logger import logger

# 中文友好的切分标尺:优先在"段落 → 换行 → 句号 → 感叹号/问号 → 分号 → 逗号"处切,
# 尽量不把一句话拦腰截断。
_SEPARATORS = [
    "\n\n",  # 段落之间
    "\n",    # 换行
    "。",    # 中文句号
    "!",     # 中文感叹号
    "?",
    "?",     # 中文问号
    ";",
    ";",     # 中文分号
    ",",     # 中文逗号
    " ",     # 空格
    "",      # 实在没办法,按字数硬切
]


def get_splitter() -> RecursiveCharacterTextSplitter:
    """创建切分器(参数来自配置文件,可在 .env 里调整)"""
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,        # 每张卡片大约多少字
        chunk_overlap=settings.chunk_overlap,  # 相邻卡片的重叠字数
        separators=_SEPARATORS,
        length_function=len,                   # 按字符数计算长度(对中文更直观)
        keep_separator=True,                   # 切分时保留标点符号
    )


def split_documents(docs: list[Document]) -> list[Document]:
    """
    把解析出来的文字块切成小卡片。
    每个卡片保留来源信息(文件名、页码、行号),并标上序号,方便日后引用展示。
    """
    splitter = get_splitter()
    chunks = splitter.split_documents(docs)

    # 给每张卡片编号(第 0 张、第 1 张……)
    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index

    logger.info(f"✂️  切分完成: {len(docs)} 个文字块 → {len(chunks)} 张知识卡片")
    return chunks
