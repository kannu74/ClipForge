@echo off
REM ============================================================
REM  ClipForge - double-click to set up (first time) and start.
REM  Needs Python 3.10+ (python.org). Nothing else: FFmpeg, the
REM  YouTube downloader and the web UI are all included.
REM ============================================================
setlocal EnableExtensions
title ClipForge
cd /d "%~dp0backend"

set "VENV=%~dp0backend\.venv-win"
set "PY=%VENV%\Scripts\python.exe"

if exist "%PY%" goto have_venv

echo.
echo [ClipForge] First-time setup: creating a private Python environment...
set "MADE="
for %%V in (3.12 3.11 3.10 3.13) do (
  if not defined MADE (
    py -%%V -c "import sys" >nul 2>&1 && (
      py -%%V -m venv "%VENV%" && set "MADE=1"
    )
  )
)
if not defined MADE (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && (
    python -m venv "%VENV%" && set "MADE=1"
  )
)
if not defined MADE (
  for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python31*") do (
    if not defined MADE if exist "%%D\python.exe" (
      "%%D\python.exe" -m venv "%VENV%" && set "MADE=1"
    )
  )
)
if not defined MADE (
  echo.
  echo  Python 3.10 or newer was not found.
  echo  Install it from https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  echo  then double-click ClipForge.bat again.
  echo.
  pause
  exit /b 1
)

:have_venv
REM Install / update components whenever requirements.txt changes.
fc /b "requirements.txt" "%VENV%\requirements.installed.txt" >nul 2>&1
if errorlevel 1 (
  echo.
  echo [ClipForge] Installing / updating components. The first time this takes a few minutes...
  "%PY%" -m pip install --upgrade pip --disable-pip-version-check -q
  "%PY%" -m pip install -r requirements.txt --disable-pip-version-check
  if errorlevel 1 (
    echo.
    echo  Installing components failed. Check your internet connection and run ClipForge.bat again.
    echo  If it keeps failing, send the text above to whoever set up ClipForge for you.
    pause
    exit /b 1
  )
  copy /y "requirements.txt" "%VENV%\requirements.installed.txt" >nul
)

if not exist ".env" copy ".env.example" ".env" >nul

echo.
echo [ClipForge] Starting... your browser will open automatically.
"%PY%" run.py
echo.
echo ClipForge has stopped.
pause
