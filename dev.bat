@echo off
echo Cleaning up old processes...
wmic process where "name='python.exe' and commandline like '%%api_server.py%%'" call terminate >nul 2>&1

echo Starting FastAPI server in the background...
start "" /B venv\Scripts\python api_server.py

echo Waiting for backend to be ready (loading AI models may take 10-20s)...
set /a _tries=0
:waitbackend
set /a _tries+=1
curl -s -f -o nul http://127.0.0.1:8765/api/health
if not errorlevel 1 goto backendready
if %_tries% geq 60 (
    echo WARNING: Backend did not respond after 60s. Starting frontend anyway...
    goto backendready
)
timeout /t 1 /nobreak >nul
goto waitbackend
:backendready
echo Backend is ready.

echo Starting Tauri Frontend...
cd frontend
call npm run tauri dev

echo.
echo Stopping API Server...
wmic process where "name='python.exe' and commandline like '%%api_server.py%%'" call terminate >nul 2>&1
echo Done.
