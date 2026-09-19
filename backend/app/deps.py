"""
权限检查(依赖注入)
==================
小白理解:这里是公司门口的"保安岗"。

  get_current_user —— 查证件:每个需要登录才能用的接口,先调用它确认"你是谁"
  require_admin    —— 查权限:知识库管理这类接口,先调用它确认"你是管理员"

用法(写在接口函数的参数里,系统会自动先过安检):
    async def 某接口(user: User = Depends(require_admin)):
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.security import decode_token

# 从请求头 "Authorization: Bearer <令牌>" 中提取令牌
# auto_error=False 表示:没带令牌时不自动报错,由我们统一给中文提示
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    查验登录令牌,返回当前登录用户。
    令牌缺失 / 无效 / 过期 / 用户已不存在 → 一律返回 401(未登录)。
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已过期或未登录,请重新登录",
    )

    if credentials is None:
        raise unauthorized

    payload = decode_token(credentials.credentials)
    if payload is None:
        raise unauthorized

    # 按令牌里的用户编号去数据库查人
    # (每次都查库而不只信令牌,是为了:用户被删除/角色被改动时能立即生效)
    user_id = int(payload.get("sub", 0))
    user = await db.get(User, user_id)
    if user is None:
        raise unauthorized

    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """
    在"已登录"的基础上再查一道:必须管理员才能通过。
    普通用户访问会收到 403(已登录,但没权限)。
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可以执行此操作",
        )
    return user


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    """按用户名查用户(注册查重、登录验证都用它)"""
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()
