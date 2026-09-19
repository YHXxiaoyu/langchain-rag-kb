"""
安全模块:密码加密 + 登录令牌
============================
小白理解:

【密码加密】用户注册时,我们不保存原始密码,而是保存一串"加密乱码"(哈希值)。
  就像把纸条烧成灰——能验证"这张纸条是不是原来的那张",但没法从灰里还原出原话。
  即使数据库被偷,小偷也拿不到真实密码。用的是 bcrypt 算法(业界标准)。

【登录令牌】登录成功后,系统发一张"电子通行证"(JWT),24 小时内有效。
  之后每次请求浏览器都带着它,后端一看就知道"你是谁、是不是管理员"。
  这张证上有防伪签名,别人改一个字符就会失效。
"""
import asyncio
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings
from app.utils.logger import logger

# 加密算法与令牌算法(固定值,不用改)
_BCRYPT_MAX_BYTES = 72           # bcrypt 算法最多只认前 72 个字节(超过部分要截掉)
_JWT_ALGORITHM = "HS256"         # JWT 的签名算法


def hash_password(password: str) -> str:
    """
    把明文密码变成加密乱码(注册、改密时调用)。
    返回值形如:$2b$12$xxxxx... 这串乱码存进数据库,不可逆推原密码。
    """
    pw_bytes = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]  # 超长密码截断,防止算法报错
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """
    校验密码是否正确(登录、改密验证旧密码时调用)。
    原理:把输入的密码用同样方式加密,和数据库里的乱码对比是否一致。
    """
    try:
        pw_bytes = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(pw_bytes, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # 数据库里的哈希格式异常时,一律当作"密码错误",不让程序崩掉
        return False


async def hash_password_async(password: str) -> str:
    """
    异步版密码加密(接口里用这个,而不是上面的 hash_password)。
    返回异步任务,让主线程可以先去接待别的请求。

    小白理解:为什么要有这个?—— 密码加密是"体力活",一次要算 0.1~0.3 秒,
    而且必须由主线程亲自算完。系统只有一个主线程,如果站着等它算完,
    其他人的请求(哪怕只是刷新一下页面)都得在门口排队。
    压力测试实测:100 人同时登录时,响应时间从 0.3 秒劣化到 4.5 秒,
    连 3 毫秒就能完成的健康检查都被拖慢到 130 毫秒(慢了 43 倍)。

    asyncio.to_thread 的作用:把这道"体力活"交给旁边的助手去做,
    主线程该干嘛干嘛,算完了再回来取结果。
    """
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    """异步版密码校验(登录、改密时用这个)。原理同上:交给旁边的助手算,不卡住主线程。"""
    return await asyncio.to_thread(verify_password, password, password_hash)


def create_access_token(user_id: int, username: str, role: str) -> str:
    """
    签发登录令牌(登录成功后调用)。
    令牌里装了:用户编号、用户名、角色、有效期,并由密钥签名防伪。
    """
    # 注意:令牌的时间必须用国际标准时间(UTC),不能用北京时间。
    # 因为校验令牌的库按 UTC 比对,若用本地时间(比 UTC 快 8 小时),
    # 令牌会被误判为"签发于未来"而直接失效。
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),                      # 用户编号
        "username": username,                     # 用户名
        "role": role,                             # 角色(admin / user)
        "iat": now,                               # 签发时间
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),  # 过期时间
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    """
    验证并解析令牌。
    返回令牌内容(字典);如果令牌被篡改、过期、或格式错误,返回 None。
    """
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.debug("令牌已过期")
        return None
    except jwt.InvalidTokenError as exc:
        logger.warning(f"无效令牌: {exc}")
        return None
