@echo off
setlocal
where pwsh >nul 2>nul
if %errorlevel%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0zhka-video.ps1" %*
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0zhka-video.ps1" %*
)
if errorlevel 1 pause
