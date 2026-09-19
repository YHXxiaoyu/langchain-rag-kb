"""
AI 模型封装(连接阿里云百炼的三个模型)
====================================
小白理解:这里相当于给系统装上"三个 AI 员工",统一从这里招聘:

  get_llm()        —— 对话员工:负责读懂问题、组织回答(qwen-plus)
  get_embeddings() —— 翻译员工:把文字翻译成"语义坐标"(一串数字),
                       让电脑能算出哪两段文字意思相近(text-embedding-v4)
  get_reranker()   —— 筛选员工:负责把候选资料按相关度重新排名(qwen3-rerank)

为什么要包一层?因为以后想把模型换成别的(比如 qwen-max),只改这一个文件,
其他代码完全不用动。
"""
from functools import lru_cache

import httpx
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import settings


@lru_cache(maxsize=4)
def get_llm(temperature: float | None = None, streaming: bool = False) -> ChatOpenAI:
    """
    获取对话大模型(通义千问)。

    参数:
      temperature —— 回答的"发散程度":0=最严谨保守,1=最天马行空。
                     知识库问答要的是准确,所以默认用配置里的 0.3(偏严谨)。
      streaming   —— 是否开启流式输出(打字机效果)。问答接口会用 True。

    说明:通过"OpenAI 兼容接口"调用通义千问 —— 阿里云官方支持这种调用方式,
    好处是能用上 LangChain 成熟的封装,流式输出最稳定。
    """
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        temperature=settings.llm_temperature if temperature is None else temperature,
        max_tokens=settings.llm_max_tokens,
        streaming=streaming,
        # 流式模式下默认拿不到 token 用量,打开这个开关才会在最后一帧带回统计数据
        # (用于成本统计功能,也是性能与成本分析的数据来源)
        stream_usage=True,
        timeout=120,  # 超时 2 分钟(生成较长回答时需要)
        max_retries=2,  # 网络抖动自动重试 2 次
    )


@lru_cache(maxsize=1)
def get_embeddings() -> OpenAIEmbeddings:
    """
    获取向量化模型(把文字变成"语义坐标")。

    关键参数 check_embedding_ctx_length=False:
      默认情况下,LangChain 会先把文字转成 token 编号再发出去(这是 OpenAI 的老规矩);
      但阿里云的接口只认原文字,不认编号。关掉它才能正常调用 —— 踩过这个坑。
    """
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        dimensions=settings.embedding_dim,       # 向量维度:1024 维
        check_embedding_ctx_length=False,        # 必须关闭,否则阿里云接口报错
        chunk_size=10,                           # 阿里云限制:每次最多 10 段文字
        timeout=120,
        max_retries=2,
    )


# ==================== 重排序(单独调用阿里云原生接口) ====================

# 重排序接口地址:阿里云百炼的"原生风格"接口
# (旧版 gte-rerank 已于 2026-05-30 停用,现用 qwen3-rerank)
RERANK_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"


async def rerank_documents(query: str, documents: list[str], top_n: int) -> list[dict]:
    """
    把候选资料按"和问题的相关程度"重新排序,返回最相关的若干条。

    小白理解:向量检索像是"撒大网捞鱼"(可能捞上来一堆沾边的),
    重排序则是"老师傅挑鱼"——逐条仔细看,把真正对口的排到最前面。

    返回格式:[{"index": 原始位置, "relevance_score": 相关度分数}, ...]
    """
    if not documents:
        return []

    payload = {
        "model": settings.rerank_model,
        "input": {"query": query, "documents": documents},
        "parameters": {"top_n": min(top_n, len(documents)), "return_documents": False},
    }
    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(RERANK_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    # 解析返回结果:results 里按相关度从高到低排列
    return data.get("output", {}).get("results", [])
