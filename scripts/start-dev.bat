@echo off
REM ClipForge DEVELOPER launcher (hot reload). Normal use: double-click ClipForge.bat instead.
REM Needs: ClipForge.bat run once (creates backend\.venv-win), and Node.js 18+ for the UI dev server.

echo Starting ClipForge backend on http://127.0.0.1:8000 (auto-reload) ...
start "ClipForge Backend" cmd /k "cd /d %~dp0..\backend && .venv-win\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

timeout /t 2 /nobreak >nul

echo Starting the UI dev server on http://localhost:5173 (proxies /api to the backend) ...
start "ClipForge UI (dev)" cmd /k "cd /d %~dp0..\frontend && (if not exist node_modules npm install) && npm run dev"

echo Both are starting in separate windows. Close them to stop.
echo When you change the UI, run "npm run build" in frontend\ so ClipForge.bat serves the new version.
