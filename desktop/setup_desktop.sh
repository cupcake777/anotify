#!/bin/bash
# anotify Desktop — macOS setup & build script
# Run on your Mac: bash setup_desktop.sh

set -e
cd "$(dirname "$0")"

echo "🐦 anotify Desktop Setup"
echo "========================"

# ── 1. Check prerequisites ──
echo ""
echo "📦 Checking prerequisites..."

if ! command -v cargo &>/dev/null; then
    echo "Installing Rust..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source "$HOME/.cargo/env"
fi

if ! command -v node &>/dev/null; then
    echo "❌ Node.js required. Install from https://nodejs.org"
    exit 1
fi

echo "  ✅ Rust: $(cargo --version)"
echo "  ✅ Node: $(node --version)"

# ── 2. Generate .icns from PNG ──
echo ""
echo "🎨 Generating .icns icon..."

ICONS_DIR="src-tauri/icons"
PNG_SRC="$ICONS_DIR/128x128.png"

# Create temporary iconset
ICONSET="anotify.iconset"
mkdir -p "$ICONSET"

sips -z 16 16     "$PNG_SRC" --out "$ICONSET/icon_16x16.png"
sips -z 32 32     "$PNG_SRC" --out "$ICONSET/icon_16x16@2x.png"
sips -z 32 32     "$PNG_SRC" --out "$ICONSET/icon_32x32.png"
sips -z 64 64     "$PNG_SRC" --out "$ICONSET/icon_32x32@2x.png"
sips -z 128 128   "$PNG_SRC" --out "$ICONSET/icon_128x128.png"
sips -z 256 256   "$PNG_SRC" --out "$ICONSET/icon_128x128@2x.png"
sips -z 256 256   "$PNG_SRC" --out "$ICONSET/icon_256x256.png"
sips -z 512 512   "$PNG_SRC" --out "$ICONSET/icon_256x256@2x.png"
sips -z 512 512   "$PNG_SRC" --out "$ICONSET/icon_512x512.png"
sips -z 1024 1024 "$PNG_SRC" --out "$ICONSET/icon_512x512@2x.png"

iconutil -c icns "$ICONSET" -o "$ICONS_DIR/icon.icns"
rm -rf "$ICONSET"
echo "  ✅ icon.icns generated"

# ── 3. Install npm deps ──
echo ""
echo "📦 Installing npm dependencies..."
npm install

# ── 4. Build ──
echo ""
echo "🔨 Building Tauri app..."
npx tauri build

echo ""
echo "🎉 Done! App is in src-tauri/target/release/bundle/"
ls -la src-tauri/target/release/bundle/macos/ 2>/dev/null || echo "(check src-tauri/target/release/bundle/)"
