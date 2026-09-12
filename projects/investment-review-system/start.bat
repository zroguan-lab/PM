@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [决策复盘] 正在启动...
if not exist node_modules (
  echo 首次运行，正在安装依赖...
  call npm install
  if errorlevel 1 goto error
)
start "" http://localhost:3000
call npm run dev
goto end
:error
echo.
echo 启动失败，请确认已安装 Node.js 20 或更高版本。
pause
:end
