@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
py -3.13 -c "import sys,tkinter; assert sys.maxsize > 2**32" >nul 2>&1
if errorlevel 1 (
  echo Please install Python 3.13 64-bit from python.org with Tcl/Tk and the Python launcher.
  echo Then run this file again.
  pause
  exit /b 1
)
py -3.13 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Installation completed. Run START_TOOLBOX.bat next.
pause
exit /b 0
:failed
echo Installation failed. Check the error above and try again.
pause
exit /b 1
