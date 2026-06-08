@echo off
echo ============================================
echo   anotify Desktop — Build Script
echo ============================================
echo.

REM Check prerequisites
where rustc >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Rust not found. Installing via rustup...
    curl -sSf https://win.rustup.rs/x86_64 -o rustup-init.exe
    rustup-init.exe -y --default-toolchain stable
    del rustup-init.exe
    set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
    echo [+] Rust installed.
)

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Node.js not found. Please install from https://nodejs.org/
    pause
    exit /b 1
)

where pnpm >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] pnpm not found. Installing...
    npm install -g pnpm
)

echo.
echo [1/3] Installing dependencies...
cd /d "%~dp0"
pnpm install

echo.
echo [2/3] Building Tauri app...
pnpm tauri build

echo.
echo [3/3] Done!
echo.
echo Output: src-tauri\target\release\bundle\
echo   - MSI installer (Windows)
echo   - EXE portable
echo.
pause
