@echo off
echo Starting FastAPI server...
start /B venv\Scripts\python api_server.py

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

echo Starting Vite Frontend...
cd frontend
start npm run dev

echo.
echo =======================================================
echo App is running in Web Mode!
echo Open your browser to http://localhost:5173
echo.
echo NOTE: "Open File" and "Open Folder" buttons will not work
echo in the web browser due to security sandboxing.
echo For those features, please install Rust and run dev.bat
echo =======================================================
echo.
echo Press any key to stop the API server and exit...
pause >nul

taskkill /IM python.exe /F /FI "WINDOWTITLE eq DocuWise API*"
