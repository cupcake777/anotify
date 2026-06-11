<p align="center">
  <img src="https://raw.githubusercontent.com/cupcake777/anotify/master/assets/banner.png" alt="anotify banner" width="100%" onerror="this.style.display='none'"/>
</p>

<h1 align="center">
  <code>anotify</code>
</h1>

<h3 align="center">Your AI agents deserve a voice.</h3>

<p align="center">
  <strong>Send desktop notifications from any remote host — HPC, VPS, CI/CD — to your local machine.</strong><br/>
  One command. Zero config on remote. Native popups on Windows, macOS, and Linux.
</p>

<p align="center">
  <a href="https://pypi.org/project/anotify/"><img src="https://img.shields.io/pypi/v/anotify?style=flat-square&color=E59A63" alt="PyPI"/></a>
  <img src="https://img.shields.io/badge/python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+"/>
  <img src="https://img.shields.io/badge/license-MIT-2EA44F?style=flat-square" alt="MIT"/>
  <img src="https://img.shields.io/badge/platform-Win%20%7C%20macOS%20%7C%20Linux-blue?style=flat-square" alt="Platforms"/>
  <a href="https://github.com/cupcake777/anotify/actions"><img src="https://img.shields.io/github/actions/workflow/status/cupcake777/anotify/ci.yml?style=flat-square&label=CI" alt="CI"/></a>
</p>

<br/>

<p align="center">
  <em>You launch a training job on an HPC cluster. It takes 6 hours.<br/>
  You can't install agents on the cluster. You want to know the moment it finishes.</em>
</p>

<p align="center">
  <strong>→ <code>anotify send "Job #1234 done"</code> — toast pops up on your desktop.</strong>
</p>

<br/>

---

<br/>

## How it works

```
┌──────────────────────┐        HTTP POST         ┌───────────────────────┐
│                      │  ───────────────────────► │                       │
│   Remote Host        │    anotify send "done"    │   anotify-server      │
│                      │                           │                       │
│   • HPC cluster      │                           │   • FastAPI + WS      │
│   • VPS / cloud      │                           │   • Token auth        │
│   • CI/CD runner     │                           │   • History buffer    │
│   • Any SSH session  │                           │   • Self-hosted    │
│                      │                           │                       │
└──────────────────────┘                           └───────────┬───────────┘
                                                               │
                                                        WebSocket push
                                                               │
                                                               ▼
                                                  ┌───────────────────────┐
                                                  │                       │
                                                  │   Your Desktop        │
                                                  │                       │
                                                  │   • System tray icon  │
                                                  │   • Toast / popup     │
                                                  │   • Sound alerts      │
                                                  │   • Auto-reconnect    │
                                                  │                       │
                                                  └───────────────────────┘
```

<br/>

## Quick Start

<br/>

**① Install** — one line, any machine:

```sh
pip install anotify
```

<br/>

**② Configure** — point to your server:

```sh
anotify config --server https://your-server.com --token YOUR_TOKEN
```

<sub>Or set `ANOTIFY_SERVER` and `ANOTIFY_TOKEN` env vars.</sub>

<br/>

**③ Receive** — from any remote host:

```sh
anotify send "Training finished" --title "HPC" --priority high
```

<br/>

**④ Ask for a decision** — block until you tap Approve/Deny:

```sh
# exits 0 if approved, 1 if denied, 2 on timeout — gate anything on it
if anotify approve "Deploy to prod?" --agent claude-code; then
    ./deploy.sh
fi
```

<sub>Outbound-only: the remote host just makes HTTP requests, so this works on locked-down clusters too.</sub>

<br/>

**⑤ Done!** — on your desktop:

```sh
anotify-client        # with system tray icon
anotify-gui           # settings window
```

<br/>

---

<br/>

## Why not email / Slack / ntfy?

<br/>

| | **anotify** | email | Slack webhook | ntfy.sh |
|---|:---:|:---:|:---:|:---:|
| **Zero setup on remote host** | ✅ CLI only | ❌ SMTP | ❌ curl + webhook | ⚠️ HTTP endpoint |
| **Works on locked-down HPC** | ✅ | ❌ | ⚠️ | ⚠️ |
| **Native desktop notifications** | ✅ | ❌ | ❌ | ❌ |
| **System tray with status** | ✅ | ❌ | ❌ | ❌ |
| **Sound alerts** | ✅ | ❌ | ❌ | ❌ |
| **Standalone exe (no Python)** | ✅ | ❌ | ❌ | ❌ |
| **Auto-reconnect** | ✅ | — | — | ✅ |

<br/>

---

<br/>

## Integration

<br/>

<details>
<summary><strong>OpenAI Codex</strong></summary>

```bash
# In your Codex environment or shell profile
export ANOTIFY_SERVER=https://your-server.com
export ANOTIFY_TOKEN=your_token

# After task completion
anotify send "Codex task completed" -t "Codex" -p medium
```
</details>

<details>
<summary><strong>Claude Code</strong></summary>

```bash
# In your Claude Code workflow or post-hook
anotify send "Claude finished: $(date)" -t "Claude Code" -p medium
```
</details>

<details>
<summary><strong>Hermes Agent</strong></summary>

```python
import subprocess
subprocess.run(["anotify", "send", "Pipeline done!", "--priority", "high"])
```
</details>

<details>
<summary><strong>Shell / Bash</strong></summary>

```bash
#!/bin/bash
python train.py --epochs 100

if [ $? -eq 0 ]; then
    anotify send "Training succeeded" -t "ML Pipeline" -p high
else
    anotify send "Training FAILED" -t "ML Pipeline" -p critical
fi
```
</details>

<details>
<summary><strong>GitHub Actions</strong></summary>

```yaml
- name: Notify on completion
  if: always()
  run: |
    pip install anotify
    anotify send "CI ${{ job.status }}" -t "GitHub" -p high
  env:
    ANOTIFY_SERVER: ${{ secrets.ANOTIFY_SERVER }}
    ANOTIFY_TOKEN: ${{ secrets.ANOTIFY_TOKEN }}
```
</details>

<br/>

---

<br/>

## Platform Support

<br/>

| Platform | Notifications | Tray Icon | Auto-start | Sound |
|----------|:---:|:---:|:---:|:---:|
| **Windows 10/11** | Toast | ✅ | Startup folder | ✅ |
| **macOS** | osascript | ✅ | LaunchAgent | ✅ |
| **Linux (GNOME/KDE)** | notify-send | ✅ | .desktop | ✅ |
| **Linux (headless)** | stderr | — | systemd | — |

<br/>

---

<br/>

## Installation

<br/>

### pip (recommended)

```sh
pip install anotify

# With GUI tray support
pip install anotify[gui]
```

### Standalone Windows exe

```sh
# Build yourself — single file, no Python needed
pip install pyinstaller
python build_exe.py
# → dist/anotify.exe
```

### From source

```sh
git clone https://github.com/cupcake777/anotify.git
cd anotify
pip install -e .
```

<br/>

---

<br/>

## Self-Hosting

<br/>

A free public relay is available at [`your-server.example`](https://huggingface.co/spaces/cupcake777/anotify) — rate-limited (30 req/min, 2KB payload).

For production use, self-host your own:

```sh
cd server/
pip install fastapi uvicorn websockets
python server.py --port 7799 --token YOUR_SECRET
```

See [`server/README.md`](server/README.md) for Docker deployment and API docs.

<br/>

---

<br/>

## Configuration

<br/>

Settings resolve: **CLI flags → env vars → config file** (`~/.anotify.json`).

| Setting | Env Variable | Config Key | Default |
|---------|-------------|------------|---------|
| Server URL | `ANOTIFY_SERVER` | `server` | `wss://your-server.com/ws` |
| Auth Token | `ANOTIFY_TOKEN` | `token` | — |

```json
{
  "server": "https://your-server.com",
  "token": "your-secret-token",
  "autostart": true
}
```

<br/>

---

<br/>

## Contributing

<br/>

Contributions welcome — big PRs and small ones, both welcome.

```sh
git clone https://github.com/cupcake777/anotify.git
cd anotify
pip install -e ".[gui]"
pip install ruff mypy

ruff check src/
mypy src/
```

**Help wanted:**
- Wayland-native notifications (Linux)
- Windows exe auto-updater
- Notification history in GUI
- Documentation translations

<br/>

---

<br/>

<p align="center">
  <sub>Made with ❤️ for anyone whose agents run while they sleep.</sub><br/>
  <sub>MIT License · © anotify contributors</sub>
</p>
