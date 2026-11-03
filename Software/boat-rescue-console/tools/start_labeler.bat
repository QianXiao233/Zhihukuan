@echo off
REM X-AnyLabeling launcher - isolated venv (avoids conda Qt6 / PyQt6 ABI clash)
REM Usage: double-click, or drag an image folder onto this file.
REM This file is pure ASCII on purpose: cmd.exe on zh-CN Windows uses GBK (cp936).

setlocal EnableExtensions

set "LABELER_PY=D:\tools\labeler-venv\Scripts\python.exe"
set "LAUNCHER=%~dp0launch_labeler.py"

if not exist "%LABELER_PY%" (
  echo [ERROR] Labeling env not found: %LABELER_PY%
  pause
  exit /b 1
)
if not exist "%LAUNCHER%" (
  echo [ERROR] Launcher script not found: %LAUNCHER%
  pause
  exit /b 1
)

if exist "C:\Windows\Fonts" set "QT_QPA_FONTDIR=C:\Windows\Fonts"

echo Starting X-AnyLabeling ...
if "%~1"=="" (
  "%LABELER_PY%" "%LAUNCHER%"
) else (
  "%LABELER_PY%" "%LAUNCHER%" "%~1"
)

set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo [ERROR] exit code %RC%
  pause
)
endlocal & exit /b %RC%
