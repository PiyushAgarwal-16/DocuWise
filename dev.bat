@echo off
echo Starting FastAPI server in the background...

:: Ensure any orphaned API servers are killed before starting
taskkill /IM python.exe /F /FI "WINDOWTITLE eq DocuWise API" >nul 2>&1

:: Start the python server in a new minimized window so it isolates the process
start "DocuWise API" /MIN cmd /c "venv\Scripts\python api_server.py"

:: Wait a moment for the server to bind
timeout /t 2 /nobreak >nul

echo Starting Tauri Frontend...
cd frontend
call npm run tauri dev

echo.
echo Stopping API Server...
taskkill /IM python.exe /F /FI "WINDOWTITLE eq DocuWise API" >nul 2>&1
echo Done.
