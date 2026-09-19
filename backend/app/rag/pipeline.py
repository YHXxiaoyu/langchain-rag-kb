"""
问答流水线(把"问题"变成"有依据的回答")
====================================
小白理解:这是整个系统的"答题流程",共三步:

  ① 找资料:调用混合检索,找出最相关的 4 张知识卡片
  ② 写提示词:把卡片编号,连同历史对话一起组装成一段"指令"发给 AI
  ③ 收答案:AI 边写我们边收(流式),同时记下它引用了哪几张卡片

关于"引用"是怎么实现的?
  我们在指令里要求 AI:"引用资料时在句尾标 [1][2]"。因为我们知道 [1] 对应哪张卡片,
  所以界面上就能把 [1] 变成可点击的来源标签 —— 这就是"回答有据可查"。
"""
from collections.abc import AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.rag.llm import get_llm
from app.rag.retriever import RetrievedChunk
from app.utils.errors import friendly_api_error
from app.utils.logger import logger

# 系统提示词:对 AI 的角色设定和回答规则(这段写得好不好,直接决定回答质量)
SYSTEM_PROMPT = """你是电商平台的智能客服助手,负责解答顾客关于商品的问题。

【回答规则】
1. 只依据下方"参考资料"中的内容回答,绝不编造资料里没有的信息。
2. 引用参考资料时,在相应句子末尾标注编号,例如:电池容量为 5000mAh [1]。
3. 若参考资料中没有相关信息,如实回答"知识库中暂时没有相关资料",并建议顾客联系人工客服。
4. 回答要简洁、准确、友好,适合客服场景;信息较多时可用列表呈现,方便阅读。
5. 始终使用中文回答。"""


REWRITE_PROMPT = """你是一个搜索查询改写助手。请把用户的最新提问改写成一句**独立完整、不依赖上下文**的搜索查询语句。

改写规则:
1. 如果最新提问里有"它""这个""那个""该产品"等指代词,根据对话历史替换成具体的商品或事物名称
2. 如果最新提问已经很完整,原样返回即可
3. 只输出改写后的查询语句,不要输出任何解释、标点补充或前后缀
4. 严格保持原意,不要添加对话历史中没有出现过的信息

【对话历史】
{history}

【最新提问】
{question}

改写后的查询语句:"""


async def rewrite_query(question: str, history: list[tuple[str, str]] | None) -> str:
    """
    查询改写(也叫"问题重写")—— 让模糊的追问也能被检索到。

    小白理解:用户前面聊的是"星辰X1手机",接着问"它保修多久?"。
    如果直接拿"它保修多久"去知识库里搜,"它"字搜不出任何东西。
    所以我们先请 AI 做一次"翻译":把"它保修多久"改写成"星辰X1手机保修多久",
    再拿这句完整的话去检索 —— 命中率立刻不一样了。

    改写出错或不必要时,自动回退到原问题,绝不影响主流程。
    """
    if not history:
        return question  # 没有历史,谈不上指代,直接用原问题

    # 只取最近 3 轮对话作为改写依据(够用且省 token)
    recent = history[-3:]
    history_text = "\n".join(f"用户: {q}\n客服: {a[:120]}" for q, a in recent)

    try:
        llm = get_llm(temperature=0.0)  # 温度设为 0:改写要稳,不要发挥
        prompt = REWRITE_PROMPT.format(history=history_text, question=question)
        resp = await llm.ainvoke(prompt)
        rewritten = (resp.content or "").strip()

        # 改写结果异常(空、太长、带了引号)时,回退用原问题
        if not rewritten or len(rewritten) > 200:
            return question

        # 去掉 AI 顺手加上的引号/书名号(它会自己加说明性符号,直接拿去检索会搜不准)
        rewritten = rewritten.strip("“”\"'。 「」『』")
        if rewritten != question:
            logger.info(f"🔄 查询改写: 「{question}」 → 「{rewritten}」")
        return rewritten or question

    except Exception as exc:
        # 改写只是"锦上添花",失败就用原问题,保证功能可用
        logger.warning(f"查询改写失败,使用原问题: {exc}")
        return question


def build_citations(chunks: list[RetrievedChunk]) -> list[dict]:
    """
    把检索到的卡片整理成"引用清单"(编号从 1 开始)。
    这份清单会随回答一起发给前端,用于展示"本回答参考了哪些资料"。
    """
    return [
        {
            "index": i,
            "filename": chunk.filename,
            "content": chunk.content,
            "page": chunk.page,
            "score": round(chunk.rerank_score or 0, 4),
            "document_id": chunk.document_id,
            # 以下三个排名用于界面上展示"检索过程"(哪一路找到了它、排第几)
            "vector_rank": chunk.vector_rank,
            "bm25_rank": chunk.bm25_rank,
        }
        for i, chunk in enumerate(chunks, start=1)
    ]


def _build_context(chunks: list[RetrievedChunk]) -> str:
    """把卡片拼成编号的"参考资料"文本,供 AI 阅读"""
    if not chunks:
        return "(没有检索到任何参考资料)"

    parts = []
    for i, chunk in enumerate(chunks, start=1):
        page_info = f",第 {chunk.page} 页" if chunk.page else ""
        parts.append(f"[{i}] 来源:《{chunk.filename}》{page_info}\n{chunk.content}")
    return "\n\n".join(parts)


def build_messages(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[tuple[str, str]] | None = None,
) -> list:
    """
    组装发给 AI 的完整消息。

    参数:
      question —— 用户这次的提问
      chunks   —— 检索到的参考资料
      history  —— 历史对话 [(用户说的, AI 答的), ...],用于理解"它""这个"这类指代
    """
    messages: list = [SystemMessage(content=SYSTEM_PROMPT)]

    # 历史对话:让 AI 知道前面聊过什么(控制轮数,避免太长)
    for user_said, ai_said in history or []:
        messages.append(HumanMessage(content=user_said))
        messages.append(AIMessage(content=ai_said))

    # 本轮问题 + 参考资料
    user_content = f"""【参考资料】
{_build_context(chunks)}

【顾客的问题】
{question}"""
    messages.append(HumanMessage(content=user_content))
    return messages


async def stream_answer(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[tuple[str, str]] | None = None,
) -> AsyncGenerator[tuple[str, dict], None]:
    """
    流式生成回答:每收到一小段文字就立刻交出去(网页上就是打字机效果)。

    产出:(文字片段, 用量信息)
      - 中间每次产出:("这是一小段话", {})
      - 最后一次产出:("", {"tokens": 123, "prompt_tokens": 100, "completion_tokens": 23})
    """
    llm = get_llm(streaming=True)
    messages = build_messages(question, chunks, history)

    usage: dict = {}
    try:
        async for event in llm.astream(messages):
            # 文字增量
            text = event.content
            if isinstance(text, str) and text:
                yield text, {}

            # 用量信息(通常在最后一个数据块里)
            meta = getattr(event, "usage_metadata", None)
            if meta:
                usage = {
                    "prompt_tokens": meta.get("input_tokens", 0),
                    "completion_tokens": meta.get("output_tokens", 0),
                    "tokens": meta.get("total_tokens", 0),
                }
    except Exception as exc:
        logger.exception(f"生成回答时出错: {exc}")
        # 出错也要给用户一句交代(翻译成人话),而不是一片空白
        yield f"\n\n(抱歉,{friendly_api_error(exc)})", {}

    yield "", usage
