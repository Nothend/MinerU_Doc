@echo off
chcp 65001 >nul
set SCRIPT_DIR=%~dp0

REM Try Python first (more stable)
where python >nul 2>nul
if %errorlevel%==0 (
    echo [INFO] Python detected, starting build script...
    python "%SCRIPT_DIR%build_env_mineru_pack.py"
    if %errorlevel% neq 0 pause
    exit /b
)

echo [ERROR] Python not found, cannot perform build.
echo Please install Python 3.10+ and add it to PATH.
pause
