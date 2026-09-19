"""
本地模拟器(压力测试 / 断网演练专用)
==================================
小白理解:压力测试要模拟 100 个人同时提问。如果每次都真的调用阿里云,会碰到三个麻烦:
  ① 花钱 —— 100 人提问就是几百次付费调用
  ② 被限速 —— 阿里云对调用频率有限制,测出来的其实是"阿里云能扛多少"
  ③ 结果不稳定 —— 网络抖动会让每次测试的数据都不太一样

所以这里安排三位"替身演员",把 AI 的活儿原地接管:

  MockChatModel    —— 假装会聊天的 AI:按真人打字的速度,一个字一个字地"写"出回答
  MockEmbeddings   —— 假装会把文字变成坐标:用文字内容算出一个固定的假坐标
  mock_rerank()    —— 假装是重排序服务:按原有顺序给递减的分数

**关键:除了不联网,其它一切照旧** —— 请求照样走完整个流程
(HTTP 接口 → 权限校验 → 检索 → 组装提示词 → 流式返回 → 存数据库),
所以测出来的并发数据仍然真实反映本系统的能力。

怎么开启?启动后端时设置环境变量 MOCK_LLM=1(或在 .env 里加一行)。
不设置时一切照旧 —— 开关默认关闭,不影响任何真实功能。
"""
import asyncio
import hashlib
import random
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage

from app.config import settings

# ==================== 模拟参数(按真实模型的速度特征设定)====================
# 真实的大模型:"思考"约 0.3~1 秒才吐出第一个字,之后每秒吐几十个字。
# 模拟器照这个节奏来,压测的"首字延迟""回答总时长"才有参考价值。
_FIRST_TOKEN_DELAY = 0.35   # 吐第一个字之前"思考"多久(秒)
_CHUNK_DELAY = 0.02         # 每小段之间的间隔(秒)
_CHUNK_SIZE = 12            # 每小段多少个字

# 模拟回答的正文(内容固定 —— 固定才能让多次压测的结果可对比)
_MOCK_ANSWER = (
    "根据知识库中的商品资料,为您解答如下:\n\n"
    "1. 该商品的核心参数与官方说明书一致,电池容量为 5000mAh,支持 65W 有线快充 [1]。\n"
    "2. 屏幕采用 6.7 英寸 OLED 材质,整机重量约 185 克 [1]。\n"
    "3. 售后方面支持七天无理由退换,保修期为两年,可享受全国联保 [2]。\n"
    "4. 如需进一步确认其它参数,建议查阅商品详情页或联系人工客服。\n\n"
    "(本条回答由本地模拟器生成,用于压力测试,未调用真实 AI)"
)


# ==================== 替身一:会聊天的 AI ====================

@dataclass
class _MockChunk:
    """
    模拟"流式返回的一小段数据"。
    结构刻意与真实模型保持一致(content 是文字,usage_metadata 是用量),
    这样上层代码不用做任何修改就能接住。
    """
    content: str
    usage_metadata: dict | None = field(default=None)


def _extract_question(messages) -> str:
    """
    从发给"AI"的内容里,把用户这次的问题摘出来。
    用途:查询改写时,模拟器要"假装改写完成",把它原样返回即可。
    """
    text = messages if isinstance(messages, str) else ""
    if not text:
        # 不是字符串,那就是消息列表 —— 取最后一条有内容的
        for msg in reversed(list(messages)):
            content = getattr(msg, "content", None)
            if content:
                text = content
                break

    # 改写用的提示词里,问题写在"【最新提问】"后面
    marker = "【最新提问】"
    if marker in text:
        text = text.split(marker, 1)[1]

    return text.strip() or "(模拟提问)"


class MockChatModel:
    """
    模拟的对话模型:对外表现和真实的 ChatOpenAI 一样(有 ainvoke 和 astream),
    但内部不联网,只是按固定节奏吐出预先写好的文字。
    """

    def __init__(self, temperature: float | None = None, streaming: bool = False) -> None:
        self.temperature = temperature      # 保留参数只为接口一致,模拟器不做发挥
        self.streaming = streaming

    async def ainvoke(self, messages) -> AIMessage:
        """
        非流式调用(用在"查询改写"环节)。
        真实模型会把"它保修多久"改写成"星辰X1保修多久";
        模拟器直接把问题原样返回 —— 对压测来说效果等价(检索照常执行)。
        """
        await asyncio.sleep(_FIRST_TOKEN_DELAY)
        return AIMessage(content=_extract_question(messages))

    async def astream(self, messages) -> AsyncGenerator[_MockChunk, None]:
        """
        流式调用(用在"生成回答"环节)。
        先"思考"一会儿,再一小段一小段地吐字,最后附上 token 用量。
        """
        await asyncio.sleep(_FIRST_TOKEN_DELAY)

        for start in range(0, len(_MOCK_ANSWER), _CHUNK_SIZE):
            await asyncio.sleep(_CHUNK_DELAY)
            yield _MockChunk(content=_MOCK_ANSWER[start:start + _CHUNK_SIZE])

        # 最后一段只带用量信息(和真实模型的行为一致:用量在最后一帧返回)
        prompt_tokens = 800 + random.randint(0, 200)
        completion_tokens = len(_MOCK_ANSWER)
        yield _MockChunk(
            content="",
            usage_metadata={
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )


# ==================== 替身二:文字变坐标 ====================

class MockEmbeddings(Embeddings):
    """
    模拟的向量化模型:把文字变成一串假的"语义坐标"。
    规则:同样的文字永远得到同样的坐标(用文字内容的指纹当随机种子)。

    注意:假坐标和真实坐标算出来的"相似度"没有意义 ——
    但这不影响压测,因为我们要测的是"系统能扛多少并发请求",
    而不是"检索得准不准"(检索质量另有专门的评估报告)。
    """

    def _vector(self, text: str) -> list[float]:
        """根据文字内容算出一个固定的假坐标(维度与真实模型一致)"""
        fingerprint = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
        rng = random.Random(int(fingerprint, 16))
        return [rng.uniform(-1.0, 1.0) for _ in range(settings.embedding_dim)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量:入库时用(把多段文字转成坐标)"""
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        """单条:提问时用"""
        return self._vector(text)


# ==================== 替身三:重排序服务 ====================

async def mock_rerank(query: str, documents: list[str], top_n: int) -> list[dict]:
    """
    模拟的重排序服务:不做真正的相关度计算,按原顺序给递减的分数。

    返回格式与真实服务完全一致:[{"index": 位置, "relevance_score": 分数}, ...]
    """
    await asyncio.sleep(_CHUNK_DELAY)  # 模拟一次网络往返的耗时
    count = min(top_n, len(documents))
    return [
        {"index": i, "relevance_score": round(1.0 - i * 0.1, 4)}
        for i in range(count)
    ]
