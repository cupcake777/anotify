# anotify Desktop

Cross-platform desktop app for anotify. Runs in system tray, shows native OS notifications.

## Features

- **System tray** — runs in background, green/red dot for connection status
- **Native notifications** — Windows Toast, macOS Notification Center, Linux notify-send
- **Auto-start** — optionally launch on login
- **History** — browse past notifications in the app
- **Zero CLI** — double-click to run, GUI settings, no terminal needed

## Quick Start (End Users)

Download the installer for your OS from [Releases](https://github.com/cupcake777/anotify/releases):

| Platform | File |
|----------|------|
| Windows  | `anotify_x.x.x_x64-setup.exe` |
| macOS    | `anotify_x.x.x_aarch64.dmg` |
| Linux    | `anotify_x.x.x_amd64.deb` |

Install, open, enter your token, done.

## Build from Source

### Prerequisites

- [Rust](https://rustup.rs/) (stable)
- [Node.js](https://nodejs.org/) (18+)
- pnpm (`npm install -g pnpm`)

### Build

**Windows:**
```
build.bat
```

**macOS / Linux:**
```
./build.sh
```

Output goes to `src-tauri/target/release/bundle/`:
- Windows: `.msi` and `.exe`
- macOS: `.dmg`
- Linux: `.deb` and `.AppImage`

## Architecture

```
┌─────────────────────────────────────────┐
│  Tauri (Rust)                           │
│  ┌──────────────┐  ┌─────────────────┐  │
│  │ WebSocket    │  │ Native OS       │  │
│  │ Client       │  │ Notifications   │  │
│  │ (tokio-tung) │  │ (tauri-plugin)  │  │
│  └──────┬───────┘  └────────┬────────┘  │
│         │ emit("notif")     │ show()    │
│  ┌──────┴───────────────────┴────────┐  │
│  │ WebView (HTML/JS/CSS)            │  │
│  │ - Notification history           │  │
│  │ - Settings (server, token)       │  │
│  │ - Connection status              │  │
│  └──────────────────────────────────┘  │
│                                         │
│  Config: ~/.anotify.json               │
│  Tray: Show / Settings / Quit          │
└─────────────────────────────────────────┘
         │ WebSocket
         ▼
  wss://your-server.example/ws
```

## Configuration

Settings are stored in `~/.anotify.json`:

```json
{
  "server": "wss://your-server.example/ws",
  "token": "your-token-here"
}
```

You can edit this file directly or use the Settings tab in the app.

## Development

```bash
pnpm install
pnpm tauri dev
```

This opens the app with hot-reload for the frontend.
