# anotify client installation

> [!NOTE]
> Public installers and a public Python package have not been released yet. The
> project named `anotify` on PyPI is unrelated. Install this repository from
> source during the source-preview phase.

## Install the Python CLI

```bash
git clone https://github.com/cupcake777/anotify.git
cd anotify
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[gui]"
anotify config --server https://your-relay.example.com --token YOUR_TOKEN
```

## Tauri desktop app

The Tauri app is the primary desktop experience. Until installers are attached
to a public release, build it from source:

```bash
cd desktop
pnpm install --frozen-lockfile
pnpm tauri build
```

Packages are written under `desktop/src-tauri/target/release/bundle/`.

## macOS menu bar compatibility client

```bash
python -m pip install -e ".[mac]"
anotify config --server https://your-relay.example.com --token YOUR_TOKEN
anotify-mac
```

The optional Python menu-bar compatibility client can be launched manually with
`anotify-mac`. Add that command to a user LaunchAgent if you want it to start
at login.

## Windows Python compatibility client

```powershell
py -m pip install -e ".[gui]"
anotify config --server https://your-relay.example.com --token YOUR_TOKEN
anotify-client --silent
```

To build a standalone executable from the repository root:

```powershell
py build_exe.py
```

The executable is written to `dist/anotify.exe`.

## Linux Python compatibility client

```bash
python -m pip install -e ".[gui]"
anotify config --server https://your-relay.example.com --token YOUR_TOKEN
anotify-client --no-tray
```

## Test the connection

```bash
anotify test
anotify send "Test message" --title "Test" --priority high
```

See the main [README](README.md) for relay setup, approval flows, security notes,
and local development.
