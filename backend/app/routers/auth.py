"""
注册 / 登录 / 修改密码 接口
==========================
小白理解:这是"用户系统的办事窗口",提供四个服务:

  POST /api/auth/register        办注册
  POST /api/auth/login           办登录(发通行证)
  GET  /api/auth/me              查自己的信息(前端用来判断是不是管理员)
  POST /api/auth/change-password 办改密码
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, get_user_by_username
from app.models import User
from app.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    MessageOut,
    RegisterRequest,
    UserOut,
)
from app.security import create_access_token, hash_password, verify_password
from app.utils.logger import logger

router = APIRouter(prefix="/api/auth", tags=["用户"])


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    注册新用户。
    注册成功直接返回登录令牌(相当于注册完自动登录,省得再输一遍)。
    新用户一律是普通用户(user),管理员只能由系统预置,不能注册出来。
    """
    # 1. 查重:用户名被别人占用了就拒绝
    if await get_user_by_username(db, req.username):
        raise HTTPException(status_code=400, detail="该用户名已被注册,换一个试试")

    # 2. 建用户:密码加密后保存
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        role="user",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)  # 刷新一下,拿到数据库自动分配的编号
    logger.info(f"新用户注册: {user.username}")

    # 3. 直接签发令牌,实现"注册即登录"
    token = create_access_token(user.id, user.username, user.role)
    return LoginResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    登录:验证用户名和密码,成功后发一张 24 小时有效的电子通行证。
    注意:用户名不存在和密码错误返回同一句提示,不给攻击者"猜用户名"的机会。
    """
    user = await get_user_by_username(db, req.username)
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(user.id, user.username, user.role)
    logger.info(f"用户登录: {user.username} (角色: {user.role})")
    return LoginResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)):
    """
    查看当前登录的是谁。
    前端每次刷新页面都会调用它:既验证令牌是否还有效,也顺便拿到角色(好决定显示哪些菜单)。
    """
    return UserOut.model_validate(user)


@router.post("/change-password", response_model=MessageOut)
async def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    修改密码:必须先验证旧密码,防止"有人趁你没锁屏幕偷偷改密"。
    """
    # 1. 验证旧密码
    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")

    # 2. 新旧密码不能一样(不然等于没改)
    if req.old_password == req.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")

    # 3. 更新为新密码的哈希
    user.password_hash = hash_password(req.new_password)
    await db.commit()
    logger.info(f"用户修改密码: {user.username}")
    return MessageOut(message="密码修改成功,请用新密码重新登录")
