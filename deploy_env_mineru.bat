@echo off
chcp 65001 >nul
set SCRIPT_DIR=%~dp0

REM 优先尝试 Python 版本 (更稳定，支持 Windows 原生路径)
where python >nul 2>nul
if %errorlevel%==0 (
    echo [INFO] 检测到 Python，优先启动 Python 部署脚本...
    python "%SCRIPT_DIR%deploy_env_mineru.py"
    if %errorlevel% neq 0 pause
    exit /b
)

REM 次选 Git Bash 版本
where bash >nul 2>nul
if %errorlevel%==0 (
    echo [INFO] 未检测到 Python，尝试通过 Git Bash 启动 Shell 脚本...
    bash "%SCRIPT_DIR%deploy_env_mineru.sh"
    pause
    exit /b
)

echo [ERROR] 未检测到 Python 或 Git Bash，无法执行部署。
echo 请确保已安装 Python (推荐) 或 Git Bash。
pause