@echo off
REM ClipForge dev launcher (Windows).
REM One-time setup first (see README.md): create backend/.venv, pip install,
REM npm install in frontend/, and copy both .env.example files to .env.

echo Starting ClipForge backend on http://localhost:8000 ...
start "ClipForge Backend" cmd /k "cd /d %~dp0..\backend && .venv\Scripts\activate && uvicorn app.main:app --reload --port 8000"

timeout /t 2 /nobreak >nul

echo Starting ClipForge frontend on http://localhost:5173 ...
start "ClipForge Frontend" cmd /k "cd /d %~dp0..\frontend && npm run dev"

echo Both processes are starting in separate windows. Close those windows to stop them.
