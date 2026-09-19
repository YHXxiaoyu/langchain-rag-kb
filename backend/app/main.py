"""
FastAPI 应用入口
================
小白理解:这个文件是后端的"大门总控"。所有浏览器发来的请求(登录、提问、
管理文档)都要先经过这里,再由它转交给对应的"办事窗口"(routers 里的各个文件)。

启动方式:在 backend 目录执行  python run.py
启动后:浏览器打开 http://127.0.0.1:8000/docs 可以看到自动生成的接口文档
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import asyncio

from slowapi.errors import RateLimitExceeded

from app.bootstrap import ensure_admin_exists
from app.config import settings
from app.database import init_db
from app.rag.ingest import requeue_unfinished, worker
from app.routers import auth, chat, conversations, kb, stats
from app.utils.limiter import limiter
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """程序启动/关闭时要做的事(这里是应用生命周期钩子)"""
    logger.info(f"🚀 {settings.app_name} 后端启动中...")

    # 1. 建表:确保五张数据表都存在(已存在则自动跳过)
    await init_db()
    # 2. 创建管理员账号:没有就建一个,已有则跳过
    await ensure_admin_exists()
    # 3. 启动"入库队列工人":负责在后台把上传的文档慢慢消化掉
    worker_task = asyncio.create_task(worker())
    # 4. 补漏:上次关闭时没处理完的文档,重新排队
    await requeue_unfinished()

    logger.info(f"   大模型: {settings.llm_model} | 向量模型: {settings.embedding_model}")
    logger.info(f"   接口文档: http://127.0.0.1:8000/docs")
    yield

    # 关闭时:叫停后台工人,避免残留任务
    worker_task.cancel()
    logger.info(f"👋 {settings.app_name} 后端已关闭")


# 创建应用实例
app = FastAPI(
    title=settings.app_name,
    description="基于 LangChain 的电商商品知识库 RAG 问答系统",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------- CORS 跨域配置 ----------
# 小白理解:前端页面(5173 端口)和后端(8000 端口)住在两个"小区",
# 不加这个配置,浏览器会以"安全"为由拦截它们之间的通信。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",     # Vite 开发服务器
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 限流:防止有人狂刷接口把 API 额度刷光 ----------
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc: RateLimitExceeded):
    """被限流时返回友好的中文提示(而不是默认的英文错误)"""
    logger.warning(f"触发限流: {request.client.host if request.client else '?'} -> {request.url.path}")
    return JSONResponse(
        status_code=429,
        content={"detail": "提问太频繁了,请稍等片刻再试"},
    )


# ---------- 注册各功能模块的接口 ----------
app.include_router(auth.router)          # 注册 / 登录 / 改密码
app.include_router(kb.router)            # 知识库管理(仅管理员)
app.include_router(conversations.router) # 会话列表 / 历史消息
app.include_router(chat.router)          # 问答(流式) / 反馈
app.include_router(stats.router)         # 管理员统计面板


# ---------- 全局异常兜底 ----------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    """任何没被单独处理的错误都会走到这里:记日志 + 给用户友好提示"""
    logger.exception(f"未处理的异常: {request.method} {request.url.path} -> {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误,请稍后重试(详细原因已记入日志)"},
    )


# ---------- 健康检查接口(用于验证服务是否活着) ----------
@app.get("/api/health", tags=["系统"])
async def health_check():
    """体检接口:返回 ok 说明后端正常运行"""
    return {
        "status": "ok",
        "app": settings.app_name,
        "llm_model": settings.llm_model,
        "api_key_configured": bool(settings.dashscope_api_key),  # 密钥是否已配置
    }
