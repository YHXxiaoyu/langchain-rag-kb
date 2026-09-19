"""
会话管理接口
============
小白理解:会话 = 聊天软件左侧的一个个"对话窗口"。这个文件提供:

  GET    /api/conversations                我的会话列表(按最近活跃排序)
  POST   /api/conversations                新建一个会话
  PATCH  /api/conversations/{id}           给会话改个名字
  DELETE /api/conversations/{id}           删除会话(连同里面的聊天记录)
  GET    /api/conversations/{id}/messages  查看某个会话的历史消息

安全说明:每个接口都会检查"这个会话是不是你自己的" —— 别人的会话你看不到也删不掉。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import Conversation, Message, User
from app.schemas import ChatMessageOut, ConversationCreate, ConversationOut, ConversationRename, MessageOut
from app.utils.logger import logger

router = APIRouter(prefix="/api/conversations", tags=["会话"])


async def get_own_conversation(conv_id: int, user: User, db: AsyncSession) -> Conversation:
    """
    取出会话并确认归属:不是自己的会话一律当作"不存在"。
    (这样连"这个编号存不存在"都不会泄露给别人,更安全)
    """
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return conv


@router.get("", response_model=list[ConversationOut])
async def list_conversations(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """我的会话列表:最近聊过的排在最上面"""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
    )
    return [ConversationOut.model_validate(c) for c in result.scalars().all()]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    req: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """新建会话(用户点"新对话"按钮时调用)"""
    conv = Conversation(user_id=user.id, title=req.title.strip() or "新对话")
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return ConversationOut.model_validate(conv)


@router.patch("/{conv_id}", response_model=ConversationOut)
async def rename_conversation(
    conv_id: int,
    req: ConversationRename,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """给会话改名"""
    conv = await get_own_conversation(conv_id, user, db)
    conv.title = req.title.strip()
    await db.commit()
    await db.refresh(conv)
    return ConversationOut.model_validate(conv)


@router.delete("/{conv_id}", response_model=MessageOut)
async def delete_conversation(
    conv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除会话:里面的聊天记录会一起删除(数据库自动级联)"""
    conv = await get_own_conversation(conv_id, user, db)
    title = conv.title
    await db.delete(conv)
    await db.commit()
    logger.info(f"🗑️  用户 {user.username} 删除会话: {title}")
    return MessageOut(message=f"会话「{title}」已删除")


@router.get("/{conv_id}/messages", response_model=list[ChatMessageOut])
async def list_messages(
    conv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    查看会话的历史消息(登录后找回历史对话靠的就是这个接口)。
    按时间正序返回,前端直接从上往下渲染即可。
    """
    await get_own_conversation(conv_id, user, db)

    result = await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at.asc(), Message.id.asc())
    )
    return [ChatMessageOut.model_validate(m) for m in result.scalars().all()]


@router.delete("/{conv_id}/messages", response_model=MessageOut)
async def clear_messages(
    conv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """清空会话里的消息(保留会话本身)"""
    await get_own_conversation(conv_id, user, db)
    await db.execute(sql_delete(Message).where(Message.conversation_id == conv_id))
    await db.commit()
    return MessageOut(message="聊天记录已清空")
