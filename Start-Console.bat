@echo off
rem Agents Behind the Wall - Demo Console launcher. Double-click to start; close this window to stop.
setlocal
cd /d "%~dp0"
title Agents Behind the Wall - Demo Console
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo   The Python environment is missing. One-time setup, from this folder:
  echo       python -m venv .venv
  echo       .venv\Scripts\python.exe -m pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" console\server.py %*
if errorlevel 1 (
  echo.
  echo   The console stopped with an error - see the message above.
  pause
)
endlocal
