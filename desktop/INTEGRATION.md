# anotify desktop — custom toast overlay integration

This wires the cute pixel-bird toast UI into the Tauri app, **replacing the
native OS notification** with a custom transparent always-on-top overlay.

## What changed

- **`src/toast.html`** (new) — the toast overlay frontend. Slices the bundled
  sprite strips into frames at runtime, listens for the Tauri `notification`
  event, and renders the animated toasts (sprite enter→idle, ping-pong loop,
  per-kind sound, critical = sticky with Acknowledge, approval = Accept/Deny).
  Starts hidden and shows/hides the window as toasts appear/clear.
- **`src/assets/sprites/bird_<kind>_8f.png`** (new) — transparent 1024×128
  strips (8 frames, baseline-aligned), one per state.
- **`src-tauri/tauri.conf.json`** — added a second window `toasts`
  (`transparent`, `alwaysOnTop`, `decorations:false`, `skipTaskbar`,
  `focus:false`, `visible:false`), plus `withGlobalTauri:true` and
  `macOSPrivateApi:true` (required for a transparent window on macOS).
- **`src-tauri/capabilities/default.json`** — the `toasts` window is added and
  granted event + window show/hide/size/position/monitor permissions.
- **`src-tauri/src/main.rs`** — the WS handler no longer calls the native
  notification; it now `emit_to("toasts", "notification", &data)` with the full
  payload (so `summary/cwd/host/agent/kind/id` reach the toast). The dashboard
  still gets the typed `notification` event for its history list.

## Run

```bash
cd desktop
pnpm install          # or npm install
pnpm tauri dev        # cargo + tauri must be installed
```

Point it at your relay (Settings tab, or `~/.anotify.json` /
`ANOTIFY_SERVER` + `ANOTIFY_TOKEN`), then from any machine:

```bash
anotify send "build done" --title "HPC" --source slurm@hpc-login \
  --script smr_sweep.sh --priority medium
```

A bird toast should slide in at the bottom-right.

## Test checklist (needs an on-device run — can't be verified headless)

- [ ] Toast window is transparent (no white box) on your OS.
- [ ] Bird is **crisp** (eyes are two dots, not blurry) — fixed via LANCZOS
      frames + `image-rendering:auto`. Verify on Windows specifically.
- [ ] Sprite plays its enter animation, then settles (occasional idle blink).
- [ ] Per-kind sound fires; burst within ~150ms merges into one; same kind is
      throttled to once / 10s.
- [ ] **Critical** stays until you click **Acknowledge** or **×** (this was the
      bug — verify it now closes), and re-pings every 60s until acknowledged.
- [ ] **Approval** shows Accept/Deny and does not auto-dismiss.
- [ ] When the last toast clears, the overlay window hides (no dead click-box).

## Known v1 limitations (candidates for v1.1)

- The overlay captures clicks within its 400×660 corner box **while visible**
  (it hides when empty). True per-toast click-through (`setIgnoreCursorEvents`
  toggled by cursor hit-testing) is a refinement.
- DND / motion / sound settings are defaults in the overlay; wiring the
  dashboard Settings → overlay via a `toast-settings` event is stubbed
  (`listen('toast-settings', …)`) but not yet driven by the dashboard UI.
- Accept/Deny currently resolve **locally** (visual). Sending the decision back
  to the agent needs a relay back-channel — a separate feature.
- Offline replay (missed-while-asleep) lives in the Python client; the overlay
  shows live events only for now.
- The dashboard (main window) still uses the original history/settings UI; the
  richer Inbox + Settings from the preview can be ported next.
