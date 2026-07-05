@echo off
chcp 65001 >nul
echo Запускаем бота...
cd /d "%~dp0"
python start.py
pause
