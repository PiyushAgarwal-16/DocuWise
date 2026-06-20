@echo off
echo Starting FastAPI server...
start /B venv\Scripts\python api_server.py

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
