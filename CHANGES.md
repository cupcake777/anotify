# Changelog

## 0.2.1 — end-to-end approvals + Tauri desktop

This release adds an interactive **approval** flow across every surface and
fills in the Tauri desktop app (backend + dashboard) that was previously only
partially present.

### Added — end-to-end Accept/Deny

- **`anotify approve`** — a new CLI subcommand that requests a yes/no decision
  and blocks until the user responds, then exits `0` (approved), `1` (denied),
  or `2` (timeout) so scripts can gate on it:
  `if anotify approve "Deploy?"; then ./deploy.sh; fi`. Supports `--action`,
  `--target`, `--agent`, `--timeout`, and an optional local `--callback`.
- **Outbound-only delivery (design fix).** The original approval path required
  the relay to POST back to the agent's `127.0.0.1`, so it only worked when the
  agent and relay were co-located — contradicting anotify's "outbound-only from
  a locked-down host" premise. The server now records each decision and exposes
  `GET /api/approval/wait/{id}` (long-poll); the CLI makes one outbound POST
  then long-polls. The legacy local-callback path still works and its tests
  still pass. (`server/server.py`, `src/anotify/cli.py`)
- **`kind` / `action` / `target`** added to the server notification model so a
  notification's visual classification and approval detail propagate end to end
  to the toast and dashboard. (`server/server.py`)
- **Python client approvals.** Approval notifications now trigger an interactive
  prompt (macOS `osascript` dialog, tkinter fallback) and post the decision
  back to the relay; pluggable via `NotifyClient.on_approval(...)`.
  (`src/anotify/approval.py`, `src/anotify/client.py`)

### Added — Tauri desktop app

- **`main.rs` + `ws.rs`** (new) — the Rust backend that was missing entirely.
  A WebSocket client (auto-reconnect with jittered backoff, id dedup, history
  baseline/replay), forwarding each notification to both the toast overlay and
  the dashboard. Exposes the frontend commands `get_config`, `update_config`,
  `verify_connection`, `reconnect`, `get_notifications`, `clear_notifications`,
  and `respond_approval` (relays a decision back to the agent). The token is
  masked (`__SET__`) when handed to the frontend.
- **Dashboard `src/index.html`** (new) — a complete dashboard built in the
  toast's visual language (cream/navy, Baloo 2, the bird reflecting live
  state): connection status, a live inbox with inline Approve/Deny, and
  settings (server/token/DND/autostart).
- **`toast.html`** wired in, plus the sprite + brand assets, and the supporting
  Tauri files: `capabilities/default.json`, a `respond_approval` permission,
  `build.rs`, and an updated `Cargo.toml` / `tauri.conf.json` (the `main`
  window now loads `index.html`).
- `desktop/INTEGRATION.md` rewritten to describe the now-real implementation.

### Tests

- 93 → 108. New coverage: server approval long-poll (record/wait/timeout/auth
  and kind propagation), the Python approval module (respond + prompt routing +
  client dispatch), and `anotify approve` exit codes. Rust parses cleanly
  (rustfmt); both HTML JS bundles pass `node --check`. The full approval chain
  was verified against a live relay for both accept and deny.

---

## 0.1.1 — popup-mechanism & UI fixes

This is a bug-fix pass focused on the desktop client's popup mechanism and the
settings/tray UI. No public API changed; one method was added
(`NotifyClient.reconnect()`).

### Fixed — CLI

- **Global `--server`/`--token` were rejected after the subcommand.** The
  README shows `anotify send "msg" --server …` style, but those flags were only
  defined on the top-level parser, so that ordering errored with "unrecognized
  arguments." They now work before *or* after the subcommand. The `test`
  subcommand also no longer crashes with `AttributeError` on send-only fields.
  (`src/anotify/cli.py`)

### Fixed — popup mechanism

- **"Test Notification" popped twice on macOS.** The menu-bar Test action fired
  a *local* toast and then round-tripped the same notification through the
  relay, which came back over the WebSocket as a second toast. It now does the
  real end-to-end round-trip (the more useful test — it exercises auth +
  delivery) and only falls back to a direct local popup when no relay is
  configured or the round-trip fails. A correctly configured setup shows the
  toast exactly once. (`src/anotify/mac_app.py`)

- **Settings changes didn't take effect until the next disconnect.** Editing
  the server URL or token updated the in-memory field but never reconnected, so
  the client kept talking to the old endpoint until a dropout happened. Added
  `NotifyClient.reconnect()` — thread-safe, closes the live socket so the run
  loop reconnects immediately with the new URL/token — and wired it into the
  settings Save button. (`src/anotify/client.py`, `src/anotify/gui.py`)

### Fixed — tray & settings UI

- **Opening Settings could freeze or crash the tray.** The settings window ran
  `tk.Tk().mainloop()` directly inside the pystray menu callback, i.e. on the
  tray's event-loop thread. That blocks the tray (its status dot can no longer
  update) on Windows/Linux and hard-crashes on macOS, where Cocoa UI must stay
  on its own thread. The window now runs on a dedicated thread, with a
  single-instance guard so repeated clicks don't stack windows. (`gui.py`)

- **Tray icon was a flat colored dot;** the bird mascot was never used. The
  tray now composites the bundled bird (`08_tray.png`) with a small status dot
  (green = connected, red = disconnected, gray = DND), matching the macOS
  menu-bar look, and falls back to a drawn disc if the asset is missing.
  (`gui.py`)

- **Missing `tkinter` disabled the whole tray.** `gui.py` imported tkinter at
  module top, so a Python build without Tk (common on minimal/Homebrew
  installs) lost the *tray* too — even though the tray only needs `pystray`.
  tkinter is now imported lazily; if it's unavailable, Settings falls back to
  opening `~/.anotify.json` in the OS default editor instead of crashing.
  (`gui.py`)

- **`anotify-gui` (standalone) exited immediately.** It launched the window on
  a daemon thread and returned, so the process ended before the UI appeared.
  Standalone now builds the window on the main thread (which is also what
  tkinter wants). (`gui.py`)

- **The Test button blocked the UI thread** — it shelled out to the OS notifier
  (multi-second timeout) synchronously. Now runs off-thread. (`gui.py`)

- **The token couldn't be cleared from the settings window** — saving an empty
  token was silently replaced by the previous one. Empty is now honored, and
  other config keys (e.g. `muted_sources`) are preserved on save. (`gui.py`)

- Added a live **Do Not Disturb** toggle to the settings window, reflecting and
  controlling the running client, plus a 1s status refresh tick. (`gui.py`)

### Fixed — robustness

- **A non-object config file crashed every caller.** If `~/.anotify.json`
  contained a top-level array/string/number (`[]`, `"x"`, `42`), every
  `load_config().get(...)` raised `AttributeError`. `load_config()` now returns
  `{}` for any non-object root. (`src/anotify/config.py`)

### Tests

- 82 → 93 tests. New regression tests cover the config non-object guard, the
  `reconnect()` mechanics (safe no-op before `run()`; schedules the socket
  close on the loop thread and resets backoff), and CLI argument ordering.

### Known gaps (not addressed here — need product decisions / missing files)

- **Approval UI:** the server has a full approval flow
  (`/api/approval/respond`, `callback_url`), but no desktop surface shows
  Accept/Deny, so it's currently unreachable from the Python apps.
- **Tauri desktop toast overlay:** `INTEGRATION.md` describes `src/toast.html`,
  `src-tauri/src/main.rs`, and `tauri.conf.json`, but those files are not in the
  archive (only `Cargo.toml` and permission TOMLs are). The custom bird-toast
  overlay couldn't be reviewed or fixed.
