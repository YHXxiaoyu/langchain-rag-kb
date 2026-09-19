"""
管理员统计面板接口
=================
小白理解:给管理员看的"经营看板" —— 多少人注册了、聊了多少句、
花了多少钱(token 消耗)、回答质量怎么样(点赞点踩比例)、
缓存帮我们省了多少次 AI 调用。

这些数据也是系统性能分析的素材来源。
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import require_admin
from app.models import Conversation, Document, Message, User
from app.utils.cache import answer_cache

router = APIRouter(prefix="/api/admin", tags=["管理员统计"])


@router.get("/stats")
async def admin_stats(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """平台全景数据(仅管理员可见)"""

    # ---------- 用户与会话 ----------
    total_users = await db.scalar(select(func.count(User.id))) or 0
    admin_users = await db.scalar(select(func.count(User.id)).where(User.role == "admin")) or 0
    total_conversations = await db.scalar(select(func.count(Conversation.id))) or 0

    # ---------- 消息与 token 消耗 ----------
    total_messages = await db.scalar(select(func.count(Message.id))) or 0
    total_questions = await db.scalar(
        select(func.count(Message.id)).where(Message.role == "user")
    ) or 0
    total_tokens = await db.scalar(select(func.coalesce(func.sum(Message.tokens), 0))) or 0

    # ---------- 回答质量反馈 ----------
    likes = await db.scalar(
        select(func.count(Message.id)).where(Message.feedback == "like")
    ) or 0
    dislikes = await db.scalar(
        select(func.count(Message.id)).where(Message.feedback == "dislike")
    ) or 0
    rated = likes + dislikes
    like_rate = round(likes / rated * 100, 1) if rated else 0.0

    # ---------- 知识库 ----------
    total_docs = await db.scalar(
        select(func.count(Document.id)).where(Document.status == "completed")
    ) or 0
    total_chunks = await db.scalar(select(func.coalesce(func.sum(Document.chunk_count), 0))) or 0

    # ---------- 最近 7 天每日提问数(给趋势图用) ----------
    seven_days_ago = datetime.now() - timedelta(days=6)
    rows = await db.execute(
        select(func.date(Message.created_at), func.count(Message.id))
        .where(Message.role == "user", Message.created_at >= seven_days_ago)
        .group_by(func.date(Message.created_at))
    )
    daily_map = {str(day): count for day, count in rows.all()}

    # 补齐没有提问的日期(显示为 0,图表才连续)
    daily_trend = []
    for offset in range(6, -1, -1):
        day = (datetime.now() - timedelta(days=offset)).strftime("%Y-%m-%d")
        daily_trend.append({"date": day[5:], "count": daily_map.get(day, 0)})  # 只显示"月-日"

    # ---------- 缓存效果 ----------
    cache_stats = {
        "size": answer_cache.size,
        "hits": answer_cache.hits,
        "misses": answer_cache.misses,
        "hit_rate": answer_cache.hit_rate,
    }

    return {
        "users": {"total": total_users, "admins": admin_users},
        "conversations": {"total": total_conversations},
        "messages": {
            "total": total_messages,
            "questions": total_questions,
            "likes": likes,
            "dislikes": dislikes,
            "like_rate": like_rate,
        },
        "tokens": {"total": int(total_tokens)},
        "knowledge": {"documents": total_docs, "chunks": int(total_chunks)},
        "daily_trend": daily_trend,
        "cache": cache_stats,
    }
