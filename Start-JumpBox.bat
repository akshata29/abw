@echo off
rem Agents Behind the Wall - jump box launcher. Double-click: starts the VM if it is stopped, opens it in the Azure portal
rem and copies its password (kept out of clipboard history, cleared after 2 minutes). Then: VM page > Connect > Bastion.
setlocal
cd /d "%~dp0"
title Agents Behind the Wall - Jump box

where pwsh >nul 2>nul
if errorlevel 1 (
  echo.
  echo   PowerShell 7 ^(pwsh^) is required:  winget install Microsoft.PowerShell
  echo.
  pause
  exit /b 1
)

pwsh -NoProfile -ExecutionPolicy Bypass -File "scripts\jumpbox.ps1" -Start -OpenPortal -CopyPassword
if errorlevel 1 (
  echo.
  echo   The jump box script stopped with an error - see the message above.
  pause
  exit /b 1
)
echo   You can close this window. The password leaves the clipboard on its own.
timeout /t 20 >nul
endlocal
