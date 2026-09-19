"""
数据库连接管理
==============
小白理解:数据库就是系统的"档案室",所有需要长期保存的东西(用户账号、聊天记录、
文档台账)都放进去。这个文件负责"开档案室的门"和"登记进出"。

技术说明:用 SQLAlchemy 2.x 的异步模式 + SQLite 数据库文件。
SQLite 的好处是整个数据库就是一个文件(data/app.db),不用单独安装数据库软件。
"""
import os
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import DATA_DIR
from app.utils.logger import logger

# 数据库文件位置:data/app.db(整个数据库就这一个文件,方便备份)
# 自动化测试时会把 DB_FILENAME 指向 test.db,用独立的测试库,不污染真实数据
DB_FILENAME = os.environ.get("DB_FILENAME", "app.db")
DB_PATH = DATA_DIR / DB_FILENAME
DB_URL = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"


class Base(DeclarativeBase):
    """所有数据表的"祖宗类":每张表都继承它,才能被数据库识别"""


# 数据库引擎:相当于"档案室的大门",整个程序共用一个
#
# 下面这几个参数是"压力测试"测出来之后专门调的(见 docs/压力测试报告.md):
#   调之前:100 人同时使用时,日志里出现 3282 次"数据库被锁",
#           并且连接池只有 15 个名额,请求排队 30 秒后直接失败。
#   调之后:读和写可以同时进行,写操作遇到冲突会排队等待而不是报错。
engine = create_async_engine(
    DB_URL,
    echo=False,          # 设为 True 会打印每条 SQL(调试用,平时关掉更清爽)
    pool_pre_ping=True,  # 借出连接前先"试试还活着吗",避免用到断掉的连接
    # ---------- 连接池:把"同时进档案室的名额"放宽 ----------
    pool_size=20,        # 常驻连接数(原来默认 5 个,太少了)
    max_overflow=40,     # 高峰期可临时增加的连接数(上限 20+40=60)
    pool_timeout=30,     # 排队等名额最多等 30 秒
    pool_recycle=1800,   # 连接用满 30 分钟就换新的,避免久置失效
    # ---------- 写锁等待:遇到别人正在写时,等一会儿而不是立刻报错 ----------
    connect_args={"timeout": 30},
)


@event.listens_for(engine.sync_engine, "connect")
def _configure_sqlite(dbapi_connection, connection_record) -> None:
    """
    每建立一条数据库连接,就顺手做三项设置(只在建连接时跑一次,开销可忽略)。

    小白理解:SQLite 默认的"档案室规矩"在人多的时候很吃亏,这三条是改规矩:

      ① WAL 模式(读写并行)
         默认模式:一次只允许一个人进档案室 —— 哪怕只是拿张纸,别人也得等。
         WAL 模式:读的人可以随便进,写的人单独排队。这是 SQLite 官方推荐的并发方案。
         实测效果:压测中 3282 次"数据库被锁"的错误由此消除。

      ② busy_timeout(排队等待)
         默认行为:发现别人正在写,立刻报错"数据库被锁"。
         改后行为:耐心等最多 30 秒,等到了就继续干活 —— 把"报错"变成"稍等一下"。

      ③ synchronous=NORMAL(兼顾安全与速度)
         在 WAL 模式下这是官方推荐档位:既保证断电不丢数据,写入又快得多。
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")       # 读写并行
    cursor.execute("PRAGMA busy_timeout=30000")     # 遇到写锁等 30 秒(单位:毫秒)
    cursor.execute("PRAGMA synchronous=NORMAL")     # 安全与速度兼顾
    cursor.close()

# 会话工厂:每次操作数据库都从这里"借一个会话",用完自动归还
SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # 提交后对象数据不过期,避免再查一次数据库
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 依赖注入用:每个请求自动分配一个数据库会话,请求结束自动关闭。
    用法:def 接口函数(db: AsyncSession = Depends(get_db))
    """
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()  # 出错时回滚,保证数据不写一半
            raise


async def init_db() -> None:
    """建表:程序启动时调用,把还没创建的表一次性建好(已存在则跳过,不会丢数据)"""
    # 先导入所有模型,Base 才知道有哪些表要建(这行不能删)
    from app import models  # noqa: F401

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info(f"📦 数据库就绪: {DB_PATH}")
