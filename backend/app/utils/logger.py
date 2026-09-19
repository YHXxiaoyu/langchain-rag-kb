"""
统一日志
========
小白理解:日志就是"系统的值班日记"。程序什么时候做了什么、出了什么错,
都写在 logs/ 文件夹里,出问题时翻日记就能找到原因(企业级系统标配)。

用法:在别的文件里写 from app.utils.logger import logger,然后 logger.info("消息")
"""
import sys

from loguru import logger

from app.config import LOG_DIR

# 0. 修正 Windows 控制台中文乱码:强制用 UTF-8 编码输出
#    (Windows 默认用 GBK 编码,中文日志会显示成乱码)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 1. 先移除 loguru 自带的默认输出(避免重复打印)
logger.remove()

# 2. 屏幕输出:彩色、简洁,方便开发时直接看
logger.add(
    sys.stderr,
    level="DEBUG",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    colorize=True,
)

# 3. 文件输出:完整信息,按天自动切分,保留 30 天
LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.add(
    LOG_DIR / "app_{time:YYYY-MM-DD}.log",
    level="INFO",
    rotation="00:00",        # 每天零点换一个新文件
    retention="30 days",     # 只保留最近 30 天
    encoding="utf-8",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
)

__all__ = ["logger"]
