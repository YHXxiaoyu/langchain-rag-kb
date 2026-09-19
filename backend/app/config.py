"""
配置中心
========
所有可以调整的设置都放在 backend/.env 文件里,改配置不用改代码。
比如以后想把大模型从 qwen-plus 换成更强的 qwen3-max,只需要改 .env 里一行。

小白理解:这个文件就像"电器的设置面板",把插头(密钥)、音量(模型选择)、
旋钮(检索条数)都集中在这里,代码里用多少,都来这里取。
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------- 路径常量(整个项目统一从这里取) ----------------
BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/ 目录
PROJECT_ROOT = BACKEND_DIR.parent                     # 项目根目录
DATA_DIR = PROJECT_ROOT / "data"                      # 运行时数据(不传 Git)
UPLOAD_DIR = DATA_DIR / "uploads"                     # 用户上传的原始文件
CHROMA_DIR = DATA_DIR / "chroma"                      # 向量库存放目录
LOG_DIR = PROJECT_ROOT / "logs"                       # 日志文件目录


class Settings(BaseSettings):
    """全部配置项 —— 每一项都可以被 .env 文件里的同名变量覆盖(大写不敏感)"""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",   # 读取 backend/.env
        env_file_encoding="utf-8",
        extra="ignore",                  # .env 里多余的变量不报错
    )

    # ---------- 应用信息 ----------
    app_name: str = "小鱼知识库问答系统"
    debug: bool = True                   # 开发模式:代码改动自动重启

    # ---------- 阿里云百炼 DashScope(大模型的"门禁卡") ----------
    dashscope_api_key: str = ""          # 在 .env 里填写,不写进代码
    # OpenAI 兼容接口地址:让 LangChain 用标准 OpenAI 协议调用通义千问
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # ---------- 模型选择(换模型只改这里) ----------
    llm_model: str = "qwen-plus"             # 对话大模型:性价比主力
    llm_temperature: float = 0.3             # 回答随机性:0=最严谨,1=最发散
    llm_max_tokens: int = 2048               # 单次回答最长长度
    embedding_model: str = "text-embedding-v4"  # 文本向量化模型
    embedding_dim: int = 1024                # 向量维度(v4 支持 64~2048)
    rerank_model: str = "qwen3-rerank"       # 重排序模型(旧的 gte-rerank 已停用)

    # ---------- 安全 ----------
    secret_key: str = "please-change-me"     # JWT 签名密钥(.env 里填随机值)
    access_token_expire_minutes: int = 1440  # 登录令牌有效期(分钟),默认 24 小时
    admin_username: str = "admin"            # 初始管理员账号
    admin_password: str = "123456"           # 初始管理员密码(存库时加密)
    min_password_length: int = 6             # 密码最短长度

    # ---------- 文件上传 ----------
    max_upload_mb: int = 20                  # 单个文件最大体积(兆)
    # 允许上传的格式白名单(白名单比黑名单安全:没列出的一律拒绝)
    allowed_extensions: str = ".pdf,.docx,.txt,.md,.xlsx,.csv"

    # ---------- RAG 检索参数(调优时的旋钮) ----------
    chunk_size: int = 500          # 每段文字约多少字
    chunk_overlap: int = 50        # 相邻两段重叠多少字(避免答案被切断)
    retrieve_top_k: int = 12       # 向量/关键词各自先捞回多少条
    rerank_top_n: int = 4          # 重排序后最终送给大模型几段
    history_max_rounds: int = 6    # 上下文里保留最近几轮完整对话
    cache_ttl_seconds: int = 3600  # 问答缓存有效期(秒)
    chat_rate_limit: str = "20/minute"  # 每个用户每分钟最多提问次数

    # ---------- 兼容属性 ----------
    @property
    def allowed_ext_list(self) -> list[str]:
        """把逗号分隔的扩展名字符串拆成列表:'.pdf,.txt' -> ['.pdf', '.txt']"""
        return [e.strip().lower() for e in self.allowed_extensions.split(",") if e.strip()]


@lru_cache  # 缓存:整个程序只创建一次配置对象,避免重复读文件
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
