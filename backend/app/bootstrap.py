"""
启动初始化
==========
小白理解:就像新店开业前的"布置工作":
  1. 检查管理员账号是否存在,不存在就自动创建一个(方便你第一次就能登录)
  2. 创建管理员时,密码在数据库里也是加密存储的

账号密码从 .env 读取(默认 admin / 123456),可在配置文件里修改。
"""
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.security import hash_password_async
from app.utils.logger import logger


async def ensure_admin_exists() -> None:
    """确保管理员账号存在:没有就创建,已有就跳过(重启不会重置密码)"""
    async with SessionLocal() as db:
        # 按 .env 里配置的管理员用户名查找
        result = await db.execute(select(User).where(User.username == settings.admin_username))
        admin = result.scalar_one_or_none()

        if admin is not None:
            # 已存在:只做一个保险动作 —— 确保它的角色确实是 admin
            if admin.role != "admin":
                admin.role = "admin"
                await db.commit()
                logger.warning(f"已修正 {admin.username} 的角色为管理员")
            else:
                logger.info(f"👤 管理员账号就绪: {admin.username}")
            return

        # 不存在:创建管理员(密码加密后存储,日志里绝不打印密码)
        admin = User(
            username=settings.admin_username,
            password_hash=await hash_password_async(settings.admin_password),
            role="admin",
        )
        db.add(admin)
        await db.commit()
        logger.info(f"👑 已自动创建管理员账号: {settings.admin_username}(密码见 .env 配置)")
