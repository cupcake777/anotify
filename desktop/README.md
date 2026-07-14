# anotify desktop

The primary anotify desktop experience is a Tauri 2 app with a live inbox,
custom penguin toasts, connection state, silence mode, and approval actions.

## Public beta

Unsigned installers are available on the
[Releases](https://github.com/cupcake777/anotify/releases/latest) page. Verify a
download against `SHA256SUMS.txt`, or build the app from source using the steps
below.

## Build from source

### Prerequisites

- [Rust](https://rustup.rs/) stable
- [Node.js](https://nodejs.org/) 22+
- pnpm 10
- The platform prerequisites listed in the
  [Tauri documentation](https://v2.tauri.app/start/prerequisites/)

### Development

```bash
cd desktop
pnpm install --frozen-lockfile
pnpm tauri dev
```

### Release build

```bash
cd desktop
pnpm install --frozen-lockfile
pnpm tauri build
```

Packages are written under `src-tauri/target/release/bundle/`:

- Windows: `.msi` and `.exe`
- macOS: `.dmg` or `.app`
- Linux: `.deb`, `.rpm`, and `.AppImage`

## Configuration

Open the Settings view and enter the HTTPS base URL of your relay and its auth
token. The desktop app shares `~/.anotify.json` with the Python CLI:

```json
{
  "server": "https://your-relay.example.com",
  "token": "your-secret-token"
}
```

Use TLS for every relay exposed beyond localhost. See
[`../server/README.md`](../server/README.md) for relay setup and security notes.

## Architecture

```text
relay ── WebSocket ──► Rust backend ──► custom toast overlay
                              └───────► dashboard inbox

dashboard / toast ── approval decision ──► relay ──► waiting agent
```

The implementation details and on-device verification checklist are in
[`INTEGRATION.md`](INTEGRATION.md).
