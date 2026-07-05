@echo off
REM Shim that activates the venv and runs a python script.
REM Usage:  py.bat scripts\foo.py [args...]
SETLOCAL
SET "ROOT=%~dp0"
CALL "%ROOT%venv\Scripts\activate.bat" >NUL 2>&1
"%ROOT%venv\Scripts\python.exe" %*
ENDLOCAL
