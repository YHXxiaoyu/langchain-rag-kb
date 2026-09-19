"""
问答接口(流式输出 + 引用溯源)
============================
小白理解:这是系统的"心脏"。用户提问后,整个流程是:

  ① 找到会话(没有就新建一个,用问题当前几个字做标题)
  ② 取出之前聊过的内容(让 AI 记得上下文)
  ③ 把用户这次的问题存进数据库
  ④ 检索知识库,找出最相关的 4 张知识卡片
  ⑤ 一边让 AI 写回答,一边把文字"挤牙膏"式地推给浏览器(打字机效果)
  ⑥ 回答写完,连同"引用了哪几张卡片"一起存档

技术说明:用的是 SSE(服务器推送事件)技术。为什么不用普通请求?
因为 AI 生成一段回答要好几秒,普通请求会让用户盯着空白屏幕干等;
流式输出则是"写一个字就发一个字",用户 1 秒内就能看到内容开始出现。
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.models import Conversation, Message, User
from app.rag.pipeline import build_citations, rewrite_query, stream_answer
from app.rag.retriever import hybrid_retrieve
from app.schemas import ChatRequest, FeedbackRequest, MessageOut
from app.utils.cache import answer_cache
from app.utils.limiter import limiter
from app.utils.logger import logger

router = APIRouter(prefix="/api", tags=["问答"])

# SSE 响应的统一请求头(防止中间环节缓存或缓冲流式内容)
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(payload: dict) -> str:
    """
    把数据打包成 SSE 格式。
    格式规定:每行以 "data: " 开头,以两个换行结尾 —— 浏览器才知道"这条消息发完了"。
    """
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _build_cached_response(cached: dict, conversation_id: int, question: str) -> StreamingResponse:
    """
    用缓存里的旧答案拼一个"流式响应"。
    格式与真实生成完全一致(前端无需特殊处理),只是多带一个 cached 标记,
    前端可以据此显示"⚡ 来自缓存"。
    """
    answer = cached.get("answer", "")
    citations = cached.get("citations", [])

    async def event_stream():
        yield _sse({"type": "citations", "data": citations, "search_query": question, "cached": True})
        yield _sse({"type": "delta", "content": answer})

        # 缓存命中的回答同样要存进数据库,保证历史记录完整
        async with SessionLocal() as db2:
            msg = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=answer,
                citations=citations or None,
                tokens=0,  # 没有调用 AI,不产生 token 消耗
            )
            db2.add(msg)
            await db2.commit()
            await db2.refresh(msg)
            message_id = msg.id

        yield _sse(
            {
                "type": "done",
                "message_id": message_id,
                "conversation_id": conversation_id,
                "tokens": {},
                "cached": True,
            }
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


# 历史对话的总长度上限(字符数)。
# 小白理解:AI 的"记性"是有成本的 —— 塞给它的旧对话越长,反应越慢、花费越高。
# 所以我们采用"滑动窗口"策略:只记最近几轮,并且总长度不超过 3000 字,
# 更早的内容自动淡出。这是聊天类产品的通用做法(上下文窗口管理)。
_HISTORY_MAX_CHARS = 3000


async def _load_history(db: AsyncSession, conversation_id: int, max_rounds: int) -> list[tuple[str, str]]:
    """
    取出最近几轮对话,整理成 [(用户问的, AI 答的), ...] 的形式,喂给 AI 保持上下文。
    双重限制:最多 max_rounds 轮 + 总长度不超过 _HISTORY_MAX_CHARS 字。
    """
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(max_rounds * 2)
    )
    recent = list(reversed(result.scalars().all()))  # 倒序取出来后要翻回正序

    history: list[tuple[str, str]] = []
    pending_question: str | None = None
    for msg in recent:
        if msg.role == "user":
            pending_question = msg.content
        elif msg.role == "assistant" and pending_question is not None:
            history.append((pending_question, msg.content))
            pending_question = None

    # 从最近的一轮开始往前保留,累计超过字数上限就不再往前取
    selected: list[tuple[str, str]] = []
    total_chars = 0
    for question, answer in reversed(history):
        cost = len(question) + len(answer)
        if selected and total_chars + cost > _HISTORY_MAX_CHARS:
            break
        selected.append((question, answer))
        total_chars += cost

    return list(reversed(selected))


@router.post("/chat")
@limiter.limit(settings.chat_rate_limit)  # 限流:每个用户每分钟最多 20 次提问
async def chat(
    request: Request,  # slowapi 限流器需要它来识别"是谁在请求"(函数内用不到)
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    提问接口(流式返回)。

    返回的数据像这样一串"小包裹":
      {"type": "citations", "data": [...]}        先告诉前端"参考了哪些资料"
      {"type": "delta", "content": "电池"}        一个词一个词地推文字
      {"type": "done",  "message_id": 12, ...}    结束,附上消息编号和用量
    """
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    # ---------- ① 找到会话,没有就新建 ----------
    if req.conversation_id:
        conv = await db.get(Conversation, req.conversation_id)
        if conv is None or conv.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    else:
        # 用问题的前 20 个字给会话起个标题,方便日后在列表里认出来
        conv = Conversation(user_id=user.id, title=question[:20])
        db.add(conv)
        await db.commit()
        await db.refresh(conv)

    # ---------- ② 先读历史(此时还没存本轮问题,读到的都是"之前"的对话) ----------
    history = await _load_history(db, conv.id, settings.history_max_rounds)

    # ---------- ③ 保存用户这次的提问 ----------
    db.add(Message(conversation_id=conv.id, role="user", content=question))
    conv.updated_at = datetime.now()  # 更新活跃时间,让会话排到列表最前面
    await db.commit()

    conversation_id = conv.id

    # ---------- ④ 先查缓存(只对"独立完整的问题"启用) ----------
    # 为什么只缓存首轮提问?因为追问("它的屏幕多大?")的含义依赖上下文,
    # 同一个问句在不同对话里指的可能是不同商品,缓存了会答非所问。
    use_cache = not history
    if use_cache:
        cached = answer_cache.get(question)
        if cached:
            logger.info(f"⚡ 缓存命中,秒回: {question[:30]}")
            return _build_cached_response(cached, conversation_id, question)

    # ---------- ⑤ 检索知识库 ----------
    # 先做"查询改写":把"它保修多久?"这类依赖上下文的问题,补全成"星辰X1手机保修多久?"
    # 再用改写后的问题去检索 —— 这是多轮问答能答准的关键一步
    search_query = await rewrite_query(question, history)
    chunks = await hybrid_retrieve(search_query)
    citations = build_citations(chunks)
    logger.info(f"💬 用户 {user.username} 提问: {question[:40]}(检索到 {len(chunks)} 张卡片)")

    # ---------- ⑤⑥ 流式生成并保存 ----------
    async def event_stream():
        # 第一帧:先把引用资料推给前端(这样界面上可以立刻显示"参考资料"区域)
        # search_query 是改写后的检索语句,前端可展示"系统理解为:xxx",体现检索过程
        yield _sse({"type": "citations", "data": citations, "search_query": search_query})

        full_text = ""
        usage: dict = {}

        async for delta, u in stream_answer(question, chunks, history):
            if delta:
                full_text += delta
                yield _sse({"type": "delta", "content": delta})
            if u:
                usage = u

        # 回答完整落库。注意这里单开一个数据库会话:
        # 因为请求用的那个会话此刻可能已经随响应结束而关闭了。
        try:
            async with SessionLocal() as db2:
                ai_msg = Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=full_text,
                    citations=citations or None,
                    tokens=usage.get("tokens", 0),
                )
                db2.add(ai_msg)
                await db2.commit()
                await db2.refresh(ai_msg)
                message_id = ai_msg.id
        except Exception as exc:
            logger.exception(f"保存 AI 回答失败: {exc}")
            message_id = -1

        # 首轮问题答完后写入缓存:下次同样的提问可以秒回,而且不花一分钱
        # (生成失败的回答不缓存,免得把错误答案记下来)
        if use_cache and full_text and not full_text.startswith("\n\n(抱歉"):
            answer_cache.set(question, {"answer": full_text, "citations": citations})

        yield _sse(
            {
                "type": "done",
                "message_id": message_id,
                "conversation_id": conversation_id,
                "tokens": usage,
            }
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/messages/{msg_id}/feedback", response_model=MessageOut)
async def submit_feedback(
    msg_id: int,
    req: FeedbackRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    给 AI 的回答点赞 / 点踩(用来收集回答质量反馈,持续改进回答效果)。
    取消评价传 "none"。
    """
    msg = await db.get(Message, msg_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="消息不存在")

    # 确认这条消息属于当前用户的某个会话(越权检查)
    conv = await db.get(Conversation, msg.conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="消息不存在")

    if msg.role != "assistant":
        raise HTTPException(status_code=400, detail="只能评价 AI 的回答")

    msg.feedback = None if req.feedback == "none" else req.feedback
    await db.commit()
    return MessageOut(message="感谢反馈!")
