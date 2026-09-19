"""
接口限流(防止有人"猛按门铃")
============================
小白理解:每个用户每分钟最多提问 20 次,超过就被挡下来说"慢点儿"。
为什么要做?因为每次提问都要花真金白银调用 AI 接口,
如果不限制,有人写个脚本狂刷,几分钟就能把账户余额刷光。
(这也是企业系统的必备防护)

限流标识的选取:已登录的用户按"用户"算(即使换浏览器也跑不掉),
未登录的按"网络地址(IP)"算。
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.security import decode_token


def rate_limit_key(request: Request) -> str:
    """
    决定"这是谁"的规则。
    优先从登录令牌里认出用户;认不出来(没登录/令牌无效)就按 IP 地址算。
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        payload = decode_token(auth[7:])
        if payload and payload.get("sub"):
            return f"user:{payload['sub']}"
    return f"ip:{get_remote_address(request)}"


# 全局限流器:具体限制规则在各个接口上用装饰器单独声明
limiter = Limiter(key_func=rate_limit_key)
