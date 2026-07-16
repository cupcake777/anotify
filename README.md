<p align="center">
  <img src="desktop/src/assets/brand/07_app_icon.png" alt="anotify" width="112"/>
</p>

<h1 align="center">anotify</h1>

<p align="center">
  <strong>Desktop notifications for remote agents, jobs, and approvals.</strong><br/>
  <sub>Self-hosted relay. Native toast. One token to connect.</sub>
</p>

<p align="center">
  <a href="https://github.com/cupcake777/anotify/releases/tag/v0.2.1"><img src="https://img.shields.io/badge/release-v0.2.1%20beta-E59A63?style=flat-square" alt="v0.2.1 beta"/></a>
  <img src="https://img.shields.io/badge/platforms-Windows%20%7C%20macOS%20%7C%20Linux-24446F?style=flat-square" alt="Windows, macOS, Linux"/>
  <img src="https://img.shields.io/badge/stack-Python%203.9%2B%20%2B%20Tauri%202-3776AB?style=flat-square" alt="Python 3.9+ and Tauri 2"/>
  <img src="https://img.shields.io/badge/relay-self--hosted-48B079?style=flat-square" alt="Self-hosted relay"/>
  <img src="https://img.shields.io/badge/license-MIT-111827?style=flat-square" alt="MIT License"/>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#approvals">Approvals</a> ·
  <a href="#security">Security</a> ·
  <a href="#project-status">Status</a>
</p>

<p align="center">
  <img src=".github/readme-flow.svg" alt="anotify event flow: agent to relay to desktop" width="920"/>
</p>

> [!NOTE]
> `v0.2.1` is the first public beta. Desktop installers are available from [GitHub Releases](https://github.com/cupcake777/anotify/releases/tag/v0.2.1). The PyPI package named `anotify` is a different project; install the Python CLI from this repository.

---

## Why anotify

Remote work rarely fails loudly. A coding agent finishes on a VPS, a Slurm job exits after six hours, CI fails while you are offline, or an agent needs a production decision. Email and chat channels bury those signals. SSH tabs do not scale.

anotify is a thin notification layer for that gap:

1. a Python CLI sends events from any host
2. a self-hosted FastAPI relay fans them out over WebSocket
3. a Tauri desktop app shows native toasts and keeps a small inbox

The remote side only needs outbound HTTP. No inbound ports. No chat workspace. No remote shell.

---

## Install

### Desktop app

| Platform | Package |
|----------|---------|
| Windows | [MSI](https://github.com/cupcake777/anotify/releases/download/v0.2.1/anotify_0.2.1_x64_en-US.msi) · [Setup EXE](https://github.com/cupcake777/anotify/releases/download/v0.2.1/anotify_0.2.1_x64-setup.exe) |
| macOS (Apple Silicon) | [DMG](https://github.com/cupcake777/anotify/releases/download/v0.2.1/anotify_0.2.1_aarch64.dmg) |
| Linux | [AppImage](https://github.com/cupcake777/anotify/releases/download/v0.2.1/anotify_0.2.1_amd64.AppImage) · [DEB](https://github.com/cupcake777/anotify/releases/download/v0.2.1/anotify_0.2.1_amd64.deb) · [RPM](https://github.com/cupcake777/anotify/releases/download/v0.2.1/anotify-0.2.1-1.x86_64.rpm) |

Checksums: [`SHA256SUMS.txt`](https://github.com/cupcake777/anotify/releases/download/v0.2.1/SHA256SUMS.txt)

After install, open the app, paste the relay URL and token, then leave it in the system tray.

> Installers are currently **unsigned**. macOS Gatekeeper and Windows SmartScreen may ask for an extra confirmation.

### Python CLI

```bash
git clone https://github.com/cupcake777/anotify.git
cd anotify
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[server]"
```

Sender-only install:

```bash
python -m pip install -e .
```

---

## How it works

```
 Remote host                     Relay                        Desktop
 ┌──────────────────┐     HTTPS  ┌──────────────────┐  WS   ┌──────────────────┐
 │ HPC / VPS        │  POST /api │  anotify-server  │ ────► │ Tauri tray app   │
 │ AI agent         │ ─────────► │  FastAPI + token │       │ toast + inbox    │
 │ CI runner        │            │  in-memory queue │       │ approval actions │
 └──────────────────┘            └──────────────────┘       └──────────────────┘
          ▲                                │                          │
          └──────── approval poll / callback ─────────────────────────┘
```

| Component | Role |
|-----------|------|
| `anotify` | Python CLI for send / approve / config |
| `anotify-server` | Self-hosted FastAPI relay with token auth |
| Desktop app | Tauri 2 tray client with native notifications |

Design constraints:

- relay stays small: no database, no hosted SaaS dependency, no message broker
- history is bounded and in-memory on the server side
- desktop and CLI share `~/.anotify.json`

---

## Quick start

### 1. Run a local relay

```bash
ANOTIFY_TOKEN=local-dev-token \
  python server/server.py --host 127.0.0.1 --port 7799
```

Health check:

```bash
curl http://127.0.0.1:7799/api/health
```

### 2. Point the CLI and desktop app at it

```bash
anotify config \
  --server http://127.0.0.1:7799 \
  --token local-dev-token
```

Desktop app:

```bash
cd desktop
pnpm install
pnpm tauri dev
```

### 3. Send an event

```bash
anotify send "Training finished" \
  --title "HPC" \
  --priority high \
  --agent codex \
  --script train.py
```

The toast appears on the desktop and lands in the inbox.

---

## Event types

| Type | When to use |
|------|-------------|
| `complete` | Job or agent task finished cleanly |
| `error` | Failure that needs attention |
| `message` | Informational note from an agent or script |
| `approval` | Decision required before the remote side continues |

Native delivery uses the platform notification surface: Windows toast, macOS Notification Center, and Linux `notify-send` equivalents through Tauri.

---

## Approvals

Some workflows need more than a one-way ping. The remote agent can wait for a decision; the desktop client returns accept or deny through the relay.

```bash
anotify approve "Deploy to production?" \
  --agent codex \
  --timeout 300
```

Important boundary: anotify transports the decision. The calling script still owns validation, authorization, and execution.

---

## Common setups

### AI coding agents

```bash
anotify send "Build finished" --title "Codex" --priority high
anotify approve "Push the release tag?" --agent codex --timeout 300
```

Useful for Claude Code, Codex, Hermes, Cline, or any agent that can shell out.

### HPC / batch jobs

```bash
anotify send "Job $SLURM_JOB_ID done" --title "RNA-seq" --priority high
```

Drop one line into a Slurm epilogue, PBS hook, or long-running notebook finish block.

### CI / CD

```yaml
- name: Notify desktop
  run: anotify send "CI: ${{ job.status }}" --title "${{ github.repository }}"
```

Works the same from GitHub Actions, GitLab CI, or Jenkins as long as the runner can reach your relay over HTTPS.

---

## Self-host the relay

```bash
pip install -e ".[server]"
ANOTIFY_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
install -d -m 700 /etc/anotify
printf '%s\n' "$ANOTIFY_TOKEN" > /etc/anotify/token
chmod 600 /etc/anotify/token

anotify-server --host 127.0.0.1 --port 7799 --token-file /etc/anotify/token
```

Put TLS in front with nginx, Caddy, or Cloudflare Tunnel. Production clients should only talk to `https://...`.

Agent-facing handoff template:

```text
Relay ready.

  Server: https://notify.example.com
  Token:  <generated-token>
```

Or write the shared config directly:

```json
{"server":"https://notify.example.com","token":"<generated-token>"}
```

More deployment notes live in [`server/README.md`](server/README.md).

---

## Configuration

Precedence: CLI flags > environment variables > `~/.anotify.json`

| Setting | CLI | Environment | Config key |
|---------|-----|-------------|------------|
| Relay URL | `--server` | `ANOTIFY_SERVER` | `server` |
| Token | `--token` | `ANOTIFY_TOKEN` | `token` |
| Config path | — | `ANOTIFY_CONFIG` | — |

```bash
anotify config --server https://notify.example.com --token your-secret-token
```

On Unix, the config file is created with mode `0600`. The Tauri backend masks existing tokens when returning settings to the webview.

---

## Security

- **Token auth on every request.** Prefer `Authorization: Bearer ...`; query-parameter tokens exist only as a compatibility fallback.
- **TLS in production.** Without HTTPS, tokens and notification bodies travel in cleartext.
- **Prefer `--token-file`.** Keeps secrets out of process listings and shell history.
- **Bounded in-memory history.** Server restart clears relay history. Desktop history is also capped.
- **Approval is not a sandbox.** The remote script decides what "accept" actually executes.

---

## Project layout

```text
anotify/
├── src/anotify/        Python sender CLI + compatibility desktop client
├── server/             FastAPI relay + deployment notes
├── desktop/            Tauri 2 tray application
├── tests/              Python, relay, security, and UI integration tests
└── .github/workflows/  Desktop package builds + Python CI
```

Build prerequisites for source development: Python 3.9+, Rust stable, Node.js 22+, pnpm 10.

---

## Project status

| Area | State |
|------|-------|
| Python sender CLI | Implemented |
| Self-hosted relay | Implemented |
| Tauri desktop app | Implemented |
| Approval round-trip | Implemented |
| Cross-platform installers | Published for `v0.2.1` beta |
| Code signing | Not yet |
| PyPI package under this name | Not available; name collision with an unrelated project |

Beta expectations:

- desktop packages may still change config paths and UI details
- review the source before using approvals as a production control plane
- relay storage is intentionally temporary, not durable event history

Client install notes: [`CLIENT_INSTALL.md`](CLIENT_INSTALL.md)

---

## License

MIT. See [`LICENSE`](LICENSE).

<p align="center">
  <sub>Self-hosted relay. Native toast. One token to connect.</sub>
</p>
