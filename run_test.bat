@echo off
echo ========================================
echo   TransparencyApp Test Runner
echo ========================================
echo.

REM Check if virtual environment exists
if exist ".venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
) else (
    echo Warning: No virtual environment found at .venv
    echo Running with system Python...
)

echo.
echo Starting TransparencyApp...
echo Press Ctrl+C to stop the application.
echo.

python TransparencyApp.py

echo.
echo Application closed.
pause
