@echo off
echo ============================================
echo   anotify - Token Setup
echo ============================================
echo.
echo This will configure your connection token.
echo You should have received a token from the server admin.
echo.

REM Create config directory
if not exist "%APPDATA%\anotify" mkdir "%APPDATA%\anotify"

REM Prompt for token
set /p TOKEN="Enter your token: "

if "%TOKEN%"=="" (
    echo.
    echo [ERROR] Token cannot be empty.
    pause
    exit /b 1
)

REM Save token
echo %TOKEN% > "%APPDATA%\anotify\token.txt"

echo.
echo ============================================
echo   Token saved successfully!
echo ============================================
echo.
echo Token location: %APPDATA%\anotify\token.txt
echo.
echo You can now double-click anotify.bat to start.
echo.
pause
