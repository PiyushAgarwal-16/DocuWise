@echo off
echo Cleaning up old processes...
wmic process where "name='python.exe' and commandline like '%%api_server.py%%'" call terminate >nul 2>&1

echo Starting FastAPI server in the background...
start "" /B venv\Scripts\python api_server.py

timeout /t 2 /nobreak >nul

echo Starting Tauri Frontend...
cd frontend
call npm run tauri dev

echo.
echo Stopping API Server...
wmic process where "name='python.exe' and commandline like '%%api_server.py%%'" call terminate >nul 2>&1
echo Done.
