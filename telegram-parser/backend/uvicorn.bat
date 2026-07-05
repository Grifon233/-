@echo off
REM Shim that activates the venv and runs uvicorn.
REM Usage:  uvicorn.bat [uvicorn args...]
SETLOCAL
SET "ROOT=%~dp0"
CALL "%ROOT%venv\Scripts\activate.bat" >NUL 2>&1
"%ROOT%venv\Scripts\python.exe" -m uvicorn %*
ENDLOCAL
