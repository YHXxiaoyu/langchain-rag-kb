"""
数据表定义
==========
小白理解:这里定义"档案室里有哪些柜子、每个柜子放什么表格"。
共 5 张表,各司其职:

  users         —— 用户柜:谁注册了、密码(加密后)、是不是管理员
  conversations —— 会话柜:每个用户的每个"聊天窗口"标题与时间
  messages      —— 消息柜:每句问答的原文、引用片段、点赞点踩
  documents     —— 文档柜:知识库里每份文件的名字、状态、切了多少段
  chunks        —— 片段柜:文档切成的每小段文字(方便精确删除和统计)
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    """用户表:注册登录的基础"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 用户名:唯一且加索引(查重、登录时查找更快)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    # 密码哈希:存的是"加密后的乱码",绝不存明文(即使数据库泄露也解不出原密码)
    password_hash: Mapped[str] = mapped_column(String(200))
    # 角色:admin=管理员(能管知识库), user=普通用户(只能问答)
    role: Mapped[str] = mapped_column(String(20), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # 关系:一个用户拥有多个会话(删除用户时级联删除其会话)
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_admin(self) -> bool:
        """是不是管理员(代码里统一用这个判断,避免到处写字符串比较)"""
        return self.role == "admin"


class Conversation(Base):
    """会话表:一个会话 = 聊天软件里左侧一个对话窗口"""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # 会话标题:默认"新对话",首次提问后自动用问题前几个字当标题
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # 最后活跃时间:会话列表按它倒序排列(最近聊的排最上面)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    """消息表:一问一答都存这里(历史记录就是按时间读这张表)"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    # 角色:user=用户问的, assistant=AI 答的
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    # 引用快照:AI 回答时参考了哪些知识片段(存 JSON,含文档名/原文/得分)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 用户反馈:like=点赞, dislike=点踩, NULL=没评价
    feedback: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # 本轮消耗的 token 数(用于成本统计)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Document(Base):
    """文档表:知识库里每份上传文件的"户口本"(记录状态方便显示进度)"""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))          # 原始文件名
    file_path: Mapped[str] = mapped_column(String(500))         # 保存在磁盘的位置
    file_type: Mapped[str] = mapped_column(String(20))          # pdf / docx / xlsx ...
    size: Mapped[int] = mapped_column(Integer, default=0)       # 文件大小(字节)
    # 处理状态:pending=排队中 processing=处理中 completed=已完成 failed=失败
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)   # 进度百分比 0~100
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)  # 切成了多少段
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)  # 失败原因
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    """片段表:文档被切成的每一小段(删除文档时按它精确清理向量库)"""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)     # 是文档里的第几段(从 0 开始)
    content: Mapped[str] = mapped_column(Text)            # 这一段的文字内容
    # 附加信息(JSON):页码、表格行号等,用于界面上显示"来自第几页"
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    chroma_id: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 向量库编号
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    document: Mapped["Document"] = relationship(back_populates="chunks")
