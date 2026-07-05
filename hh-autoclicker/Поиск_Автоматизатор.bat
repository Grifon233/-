@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================================
echo ЗАПУСК ПОИСКА ВАКАНСИЙ ДЛЯ АВТОМАТИЗАТОРА
echo ВНИМАНИЕ: ИДЕТ РЕАЛЬНАЯ РАССЫЛКА ОТКЛИКОВ!
echo Лимит откликов: 200.
echo ========================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "Search.ps1"

echo.
pause
