# Start the uvicorn backend in a detached fashion on Windows.
# Delegate to the Python helper so we only keep one startup path.

$ErrorActionPreference = 'Stop'

$venvPy = "C:\Users\ЗС\OneDrive\Рабочий стол\Телеграмм парсер\src\backend\venv\Scripts\python.exe"
$script = "C:\Users\ЗС\OneDrive\Рабочий стол\Телеграмм парсер\src\backend\scripts\start_backend_detached.py"
$disabledFlag = "C:\Users\ЗС\OneDrive\Рабочий стол\Телеграмм парсер\src\backend\scripts\backend_autostart.disabled"

if (Test-Path $disabledFlag) {
    Write-Host "Backend autostart is disabled via $disabledFlag"
    exit 0
}

if (-not (Test-Path $venvPy)) {
    throw "Python venv not found: $venvPy"
}

if (-not (Test-Path $script)) {
    throw "Start script not found: $script"
}

& $venvPy $script
