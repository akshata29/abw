@echo off
rem Agents Behind the Wall - put the Demo Console on the jump box. Double-click: starts the VM if it is stopped, installs
rem Python / Azure CLI / PowerShell 7 on it when missing, copies the console and its proof evidence, and checks it from inside the VM.
rem Safe to re-run: it sends only what changed. Extra switches pass through:  -Status  -Verify  -Remove  -WhatIf  -Force
rem Persona sign-in files stay on the laptop unless you ask:  -IncludePersonaFiles  to copy them,  -RemovePersonaFiles  to delete them from the VM.
setlocal
cd /d "%~dp0"
title Agents Behind the Wall - Deploy the console to the jump box

where pwsh >nul 2>nul
if errorlevel 1 (
  echo.
  echo   PowerShell 7 ^(pwsh^) is required:  winget install Microsoft.PowerShell
  echo.
  pause
  exit /b 1
)

pwsh -NoProfile -ExecutionPolicy Bypass -File "scripts\jumpbox-console.ps1" %*
if errorlevel 1 (
  echo.
  echo   The jump box console script stopped with an error - see the message above.
  pause
  exit /b 1
)
echo   You can close this window.
timeout /t 20 >nul
endlocal
