@echo off
REM Arranque todo-en-uno del prototipo (doble-click o "start.bat" en la terminal).
cd /d "%~dp0"
python start.py %*
pause
