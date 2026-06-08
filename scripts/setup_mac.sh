#!/bin/bash
# anotify macOS setup script
# Run this on your Mac:
#   ANOTIFY_TOKEN="your-token" bash setup_mac.sh
#
# Or just: bash setup_mac.sh (will prompt for token)

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🐦 anotify macOS Setup${NC}"
echo "======================"

# ── Config ──
APP_DIR="$HOME/code/anotify"
PLIST="$HOME/Library/LaunchAgents/com.anotify.client.plist"
LOG_FILE="$HOME/.anotify.log"
SERVER="${ANOTIFY_SERVER:-wss://your-server.example/ws}"

# ── Token ──
if [ -z "$ANOTIFY_TOKEN" ]; then
    read -rsp "Enter anotify token: " ANOTIFY_TOKEN
    echo
fi
if [ -z "$ANOTIFY_TOKEN" ]; then
    echo -e "${RED}Error: Token required${NC}"
    exit 1
fi

# ── 1. Clone repo ──
echo ""
echo -e "${BLUE}📦 Step 1: Clone anotify...${NC}"
if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR" && git pull
else
    mkdir -p "$(dirname "$APP_DIR")"
    git clone https://github.com/cupcake777/anotify.git "$APP_DIR"
fi

# ── 2. Install ──
echo ""
echo -e "${BLUE}📦 Step 2: pip install...${NC}"
cd "$APP_DIR"
pip install -e ".[mac]"

# ── 3. Configure ──
echo ""
echo -e "${BLUE}⚙  Step 3: Configure...${NC}"
anotify config --server "$SERVER" --token "$ANOTIFY_TOKEN"

# ── 4. Stop old client ──
echo ""
echo -e "${BLUE}🛑 Step 4: Stop old client...${NC}"
launchctl unload "$PLIST" 2>/dev/null || true
killall anotify-mac 2>/dev/null || true
sleep 1

# ── 5. launchd auto-start ──
echo ""
echo -e "${BLUE}🚀 Step 5: Setup auto-start...${NC}"
PYTHON_BIN="$(which python3)"

cat > "$PLIST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.anotify.client</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>-m</string>
        <string>anotify.mac_app</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_FILE</string>
    <key>StandardErrorPath</key>
    <string>$LOG_FILE</string>
</dict>
</plist>
PLIST_EOF

launchctl load "$PLIST"

# ── 6. Verify ──
echo ""
echo -e "${GREEN}✅ Done!${NC}"
sleep 3
echo ""
echo "launchd status:"
launchctl list | grep anotify || echo "(loading... wait a few seconds)"
echo ""
echo "Check logs: tail -f $LOG_FILE"
echo ""
echo -e "${GREEN}🐦 The bird icon should appear in your menu bar.${NC}"
echo "   Click → Open Dashboard to see the app."
echo ""
echo "   Test: anotify send 'Hello!' -t '🐦 Test' -p high"
