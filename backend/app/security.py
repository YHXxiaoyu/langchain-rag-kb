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
