@echo off
chcp 936 >nul
title 小鱼知识库问答系统 - 启动器

echo.
echo ============================================================
echo            小鱼知识库问答系统  启动中...
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/2] 正在启动后端服务(端口 8000)...
start "小鱼-后端服务" cmd /k "cd /d %~dp0backend && venv\Scripts\python.exe run.py"

echo [2/2] 正在启动前端页面(端口 5173)...
start "小鱼-前端页面" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo 等待服务启动(约 12 秒)...
timeout /t 12 /nobreak >nul

echo 正在打开浏览器...
start http://localhost:5173

echo.
echo ============================================================
echo   启动完成!
echo.
echo   浏览器地址:http://localhost:5173
echo   管理员账号:admin / 123456
echo.
echo   提示:关闭那两个黑色的命令行窗口,即可停止服务
echo ============================================================
echo.
pause
