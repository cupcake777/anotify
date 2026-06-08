@echo off
echo ============================================
echo   anotify - Remote Desktop Notification Tool
echo ============================================
echo.
echo Installing anotify with GUI support...
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo Please install Python from: https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM Install anotify with GUI support
echo [1/2] Installing anotify...
pip install "anotify[gui]" -q

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Installation failed. Trying with --user flag...
    pip install "anotify[gui]" --user -q
)

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Installation failed. Please try running this script as Administrator.
    pause
    exit /b 1
)

echo.
echo [2/2] Creating configuration...
echo.

REM Create config directory
if not exist "%APPDATA%\anotify" mkdir "%APPDATA%\anotify"

REM Check if config exists
if not exist "%APPDATA%\anotify\config.json" (
    echo # anotify configuration > "%APPDATA%\anotify\config.json"
    echo Please run anotify.bat to configure your connection.
) else (
    echo Configuration already exists at: %APPDATA%\anotify\config.json
)

echo.
echo ============================================
echo   Installation Complete!
echo ============================================
echo.
echo Next steps:
echo   1. Get your token from the server admin
echo   2. Double-click anotify.bat to start
echo   3. Configure your token in the settings
echo.
pause
