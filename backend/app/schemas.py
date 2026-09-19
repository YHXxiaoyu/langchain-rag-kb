"""
数据结构定义(接口的"表格模板")
==============================
小白理解:浏览器和后端之间传数据,就像寄快递——这个文件规定每种快递
"箱子里装什么、每样东西什么规格"。好处是:寄错格式会被自动拦下并提示,
也自动生成接口文档(访问 http://127.0.0.1:8000/docs 能看到)。

命名约定:xxxRequest = 前端发来的数据;xxxOut = 后端返回的数据
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings


# ==================== 用户相关 ====================

class RegisterRequest(BaseModel):
    """注册请求:用户填的用户名和密码"""

    username: str = Field(..., min_length=3, max_length=20, description="用户名,3~20 个字符")
    password: str = Field(..., min_length=6, max_length=64, description="密码,至少 6 位")

    @field_validator("username")
    @classmethod
    def username_no_space(cls, v: str) -> str:
        """用户名不允许包含空格(前后空格自动去掉)"""
        v = v.strip()
        if " " in v:
            raise ValueError("用户名不能包含空格")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """密码校验:至少满足 6 位(这是最低门槛,以后可加更严规则)"""
        if len(v) < settings.min_password_length:
            raise ValueError(f"密码至少 {settings.min_password_length} 位")
        return v


class LoginRequest(BaseModel):
    """登录请求"""

    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class ChangePasswordRequest(BaseModel):
    """修改密码请求:需先验证旧密码"""

    old_password: str = Field(..., description="当前密码")
    new_password: str = Field(..., min_length=6, max_length=64, description="新密码,至少 6 位")

    @field_validator("new_password")
    @classmethod
    def new_password_strength(cls, v: str) -> str:
        if len(v) < settings.min_password_length:
            raise ValueError(f"新密码至少 {settings.min_password_length} 位")
        return v


class UserOut(BaseModel):
    """返回给前端的用户信息(注意:绝不包含密码或密码哈希)"""

    model_config = ConfigDict(from_attributes=True)  # 允许直接从数据库对象转换

    id: int
    username: str
    role: str
    created_at: datetime

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class LoginResponse(BaseModel):
    """登录成功的返回:令牌 + 用户信息"""

    access_token: str = Field(..., description="登录令牌,后续请求放在请求头里")
    token_type: str = "bearer"
    user: UserOut


class MessageOut(BaseModel):
    """通用提示信息(例如"注册成功""密码已修改")"""

    message: str


# ==================== 知识库相关 ====================

class DocumentOut(BaseModel):
    """文档信息:管理列表里每份文件的一行"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    file_type: str
    size: int                                  # 字节数
    status: str                                # pending / processing / completed / failed
    progress: int                              # 处理进度 0~100
    chunk_count: int                           # 切成了多少张知识卡片
    error_msg: str | None = None               # 失败原因(仅失败时有值)
    created_at: datetime


class KbStats(BaseModel):
    """知识库总览统计(管理页顶部的数字卡片)"""

    document_count: int      # 文档总数
    completed_count: int     # 已完成
    processing_count: int    # 处理中(含排队)
    failed_count: int        # 失败
    chunk_count: int         # 知识卡片总数(向量库里的实际数量)
    total_size: int          # 文件总大小(字节)


# ==================== 会话与问答 ====================

class ConversationOut(BaseModel):
    """会话信息(左侧会话列表里的一行)"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationCreate(BaseModel):
    """新建会话"""

    title: str = Field(default="新对话", max_length=100)


class ConversationRename(BaseModel):
    """重命名会话"""

    title: str = Field(..., min_length=1, max_length=100, description="新标题")


class ChatMessageOut(BaseModel):
    """一条聊天消息(用户问的 或 AI 答的)"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str                                  # user / assistant
    content: str
    citations: list | None = None              # AI 回答引用的知识片段
    feedback: str | None = None                # like / dislike / None
    created_at: datetime


class ChatRequest(BaseModel):
    """提问请求"""

    conversation_id: int | None = Field(default=None, description="会话编号;为空则自动新建会话")
    question: str = Field(..., min_length=1, max_length=2000, description="用户的问题")


class FeedbackRequest(BaseModel):
    """对某条回答点赞或点踩"""

    feedback: str = Field(..., description="like=点赞, dislike=点踩, none=取消")

    @field_validator("feedback")
    @classmethod
    def check_feedback(cls, v: str) -> str:
        if v not in ("like", "dislike", "none"):
            raise ValueError("反馈类型只能是 like、dislike 或 none")
        return v
