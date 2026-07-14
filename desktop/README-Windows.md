# anotify desktop on Windows

## Build the Tauri app

### Prerequisites

- Windows 10 or 11
- [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
- [WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)
- [Rust](https://rustup.rs/) stable
- Node.js 22+
- pnpm 10

From the repository root:

```powershell
cd desktop
pnpm install --frozen-lockfile
pnpm tauri build
```

The MSI and NSIS packages are written under
`src-tauri\target\release\bundle\`.

## Run in development

```powershell
cd desktop
pnpm install --frozen-lockfile
pnpm tauri dev
```

Open Settings in the app and enter your HTTPS relay URL and auth token.

## Python compatibility client

If you only need traditional Windows notifications and a tray icon:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -e ".[gui]"
anotify config --server https://your-relay.example.com --token YOUR_TOKEN
anotify-client --silent
```

## Troubleshooting

- No toast: allow notifications for anotify in Windows Settings and disable
  Focus Assist / Do Not Disturb while testing.
- Build cannot find a linker: install the Desktop development with C++ workload
  from Visual Studio Build Tools.
- Blank WebView: repair or install the WebView2 Runtime.
- Cannot connect: verify the relay URL uses `https://`, the token matches, and
  the reverse proxy supports WebSocket upgrades.
