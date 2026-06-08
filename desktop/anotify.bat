@echo off
echo ============================================
echo   anotify - Starting...
echo ============================================
echo.
echo Starting anotify in background...
echo Look for the green dot icon in your system tray.
echo.
echo To stop: Right-click the tray icon -> Quit
echo.

REM Run anotify client with GUI (tray icon)
start /min pythonw -m anotify.client --server wss://your-server.example/ws --token-file "%APPDATA%\anotify\token.txt"

echo If the tray icon doesn't appear, check if Python is installed correctly.
echo.
echo Press any key to close this window...
pause >nul
