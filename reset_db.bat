@echo off
echo Stopping API Server if running...
wmic process where "name='python.exe' and commandline like '%%api_server.py%%'" call terminate >nul 2>&1

echo.
echo Deleting database...
if exist "storage\docuwise.db" (
    del "storage\docuwise.db"
    echo Successfully deleted storage\docuwise.db!
) else (
    echo Database file not found. It might already be clean.
)

echo.
echo Database has been completely wiped. 
echo The system will automatically generate a fresh database next time you run dev.bat.
pause
