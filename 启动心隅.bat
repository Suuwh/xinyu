@echo off
title 心隅AI校园心理健康护航平台
cd /d "%~dp0"

rem 离线环境变量
set "HF_HOME=%~dp0hf_cache"
set "HF_HUB_OFFLINE=1"
set "TRANSFORMERS_OFFLINE=1"
set "TOKENIZERS_PARALLELISM=false"

echo ============================================================
echo            心隅AI校园心理健康护航平台
echo ============================================================
echo.
echo   正在启动本地服务，首次启动AI模型约需30-90秒，请耐心等待。
echo   浏览器将自动打开；若未打开，请手动访问http://127.0.0.1:5000
echo.
echo   演示账号：学生student1 / 咨询师counselor，密码均为123456
echo.
echo   使用完毕后，直接关闭本窗口即可停止服务。
echo ------------------------------------------------------------
echo.
rem 8秒后自动打开浏览器
start "" /b cmd /c "ping 127.0.0.1 -n 8 >nul 2>nul & start http://127.0.0.1:5000"
rem 启动内置便携Python
"%~dp0python\python.exe" "%~dp0app.py"
echo.
echo 服务已停止。如上方出现报错，请截图反馈。
pause
