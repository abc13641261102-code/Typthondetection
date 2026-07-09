@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ========================================
echo   台风快讯监控系统
echo ========================================
echo.
echo 安装依赖...
pip install -r requirements.txt -q
echo.
echo 启动服务...
python web_server.py
pause
