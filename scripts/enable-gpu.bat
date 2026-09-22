@echo off
REM ============================================================
REM  ClipForge.bat does this automatically when it finds an NVIDIA GPU.
REM  Run this only to retry manually. Lets transcription use the GPU.
REM  Downloads NVIDIA's cuBLAS + cuDNN runtime libraries (~1.5 GB)
REM  into ClipForge's private Python environment. Run ClipForge.bat
REM  at least once first. Without this, ClipForge still works on CPU.
REM ============================================================
setlocal
cd /d "%~dp0..\backend"
set "PY=%~dp0..\backend\.venv-win\Scripts\python.exe"
if not exist "%PY%" (
  echo Run ClipForge.bat once first, then run this again.
  pause
  exit /b 1
)
where nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo No NVIDIA GPU driver was found ^(nvidia-smi is missing^). ClipForge will keep using the CPU.
  pause
  exit /b 1
)
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
echo.
echo Installing NVIDIA runtime libraries for transcription (large download)...
"%PY%" -m pip install "nvidia-cublas-cu12" "nvidia-cudnn-cu12==9.*" --disable-pip-version-check
if errorlevel 1 (
  echo Install failed. ClipForge will keep using the CPU.
  pause
  exit /b 1
)
echo ok> "%~dp0..\backend\.venv-win\gpu-libs.installed"
echo.
echo Done. Restart ClipForge -- transcription will now use your GPU when possible
echo (and automatically fall back to the CPU if anything goes wrong).
pause
