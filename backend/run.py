"""
后端启动脚本
============
小白理解:双击运行这个文件(或在命令行输入 python run.py),后端服务就开张了。
代码改动会自动重启(reload=True),方便开发调试。
"""
import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",   # 只监听本机,局域网内其他电脑访问不到(开发期更安全)
        port=8000,
        reload=settings.debug,  # 开发模式下:改代码自动重启
        reload_dirs=["app", "tools"],  # 只盯代码目录(不盯 venv 依赖包,重载更快更稳)
        log_level="info",
    )
