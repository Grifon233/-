@echo off
title LeadOrchestra B2B Enricher
echo ===================================================
echo   LeadOrchestra Mail Enricher & Validator Launcher
echo ===================================================
echo.
echo [1/3] Проверка node_modules...
if not exist node_modules (
    echo Папка node_modules не найдена. Устанавливаем Express...
    call npm install
) else (
    echo Зависимости уже установлены.
)
echo.
echo [2/3] Открытие приложения в браузере...
start "" "http://localhost:3000"
echo.
echo [3/3] Запуск локального сервера (порт 3000)...
echo Для остановки сервера закройте это окно.
echo ---------------------------------------------------
node server.js
pause
