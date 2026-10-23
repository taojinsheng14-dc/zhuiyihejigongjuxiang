@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先运行“首次安装.bat”。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "tools\fast-sale\export_diagnostics.py"
pause
