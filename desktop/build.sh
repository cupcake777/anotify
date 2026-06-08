#!/bin/bash
set -e

echo "============================================"
echo "  anotify Desktop — Build Script"
echo "============================================"
echo

# Check prerequisites
if ! command -v rustc &>/dev/null; then
    echo "[!] Rust not found. Installing via rustup..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source "$HOME/.cargo/env"
    echo "[+] Rust installed."
fi

if ! command -v node &>/dev/null; then
    echo "[!] Node.js not found. Please install from https://nodejs.org/"
    exit 1
fi

if ! command -v pnpm &>/dev/null; then
    echo "[!] pnpm not found. Installing..."
    npm install -g pnpm
fi

cd "$(dirname "$0")"

echo "[1/3] Installing dependencies..."
pnpm install

echo
echo "[2/3] Building Tauri app..."
pnpm tauri build

echo
echo "[3/3] Done!"
echo
echo "Output: src-tauri/target/release/bundle/"
case "$(uname -s)" in
    Darwin*)  echo "  - .dmg installer (macOS)" ;;
    Linux*)   echo "  - .deb / .AppImage (Linux)" ;;
esac
