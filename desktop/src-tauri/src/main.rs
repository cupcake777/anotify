// Prevent an extra console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! anotify desktop backend.
//!
//! Connects to the anotify relay over WebSocket, forwards every notification to
//! the transparent `toasts` overlay window (which renders the bird toasts) and
//! to the `main` dashboard window (which keeps a history list). Exposes the
//! commands the frontend calls: config get/update, connection verify/reconnect,
//! notification history get/clear, and `respond_approval` (the Accept/Deny
//! decision from a toast, relayed back to the agent).

use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIcon, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, State, WindowEvent};
use tokio::sync::Notify;

mod ws;

const MAX_HISTORY: usize = 200;

// ── Persisted config (~/.anotify.json, shared with the Python CLI) ──────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Config {
    #[serde(default)]
    pub server: String,
    #[serde(default)]
    pub token: String,
    #[serde(default)]
    pub autostart: bool,
    #[serde(default)]
    pub dnd: bool,
    #[serde(default = "default_response_length")]
    pub response_length: String,
    #[serde(default = "default_notification_style")]
    pub notification_style: String,
    #[serde(default)]
    pub muted_sources: Vec<String>,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            server: String::new(),
            token: String::new(),
            autostart: false,
            dnd: false,
            response_length: default_response_length(),
            notification_style: default_notification_style(),
            muted_sources: Vec::new(),
        }
    }
}

fn default_response_length() -> String {
    "balanced".to_string()
}

fn default_notification_style() -> String {
    "default".to_string()
}

fn sanitize_response_length(value: &str) -> String {
    match value {
        "concise" | "balanced" | "detailed" => value.to_string(),
        _ => default_response_length(),
    }
}

fn sanitize_notification_style(value: &str) -> String {
    match value {
        "default" | "explanatory" | "formal" | "friendly" => value.to_string(),
        _ => default_notification_style(),
    }
}

fn config_path() -> std::path::PathBuf {
    if let Ok(p) = std::env::var("ANOTIFY_CONFIG") {
        return std::path::PathBuf::from(p);
    }
    let home = dirs_next::home_dir().unwrap_or_else(|| std::path::PathBuf::from("."));
    home.join(".anotify.json")
}

fn load_config() -> Config {
    let path = config_path();
    let mut cfg = match std::fs::read_to_string(&path) {
        Ok(s) => serde_json::from_str(&s).unwrap_or_default(),
        Err(_) => Config::default(),
    };
    cfg.response_length = sanitize_response_length(&cfg.response_length);
    cfg.notification_style = sanitize_notification_style(&cfg.notification_style);
    cfg
}

fn save_config(cfg: &Config) -> Result<(), String> {
    let path = config_path();
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    let body = serde_json::to_string_pretty(cfg).map_err(|e| e.to_string())?;
    std::fs::write(&path, body + "\n").map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600));
    }
    Ok(())
}

// ── Shared application state ────────────────────────────────────────────────

pub struct AppState {
    pub cfg: Mutex<Config>,
    pub connected: Mutex<bool>,
    pub history: Mutex<VecDeque<Value>>,
    pub tray: Mutex<Option<TrayIcon>>,
    /// Bumped to ask the WS task to drop its socket and reconnect now.
    pub reconnect: Arc<Notify>,
}

impl AppState {
    fn new(cfg: Config) -> Self {
        Self {
            cfg: Mutex::new(cfg),
            connected: Mutex::new(false),
            history: Mutex::new(VecDeque::with_capacity(MAX_HISTORY)),
            tray: Mutex::new(None),
            reconnect: Arc::new(Notify::new()),
        }
    }
}

/// Normalize a user-entered URL to an `ws://`/`wss://` `/ws` endpoint.
/// Mirrors `anotify.config.ensure_ws_url` on the Python side.
pub fn ensure_ws_url(input: &str) -> String {
    let mut url = input.trim().to_string();
    if let Some(rest) = url.strip_prefix("http://") {
        url = format!("ws://{rest}");
    } else if let Some(rest) = url.strip_prefix("https://") {
        url = format!("wss://{rest}");
    }
    if !url.starts_with("ws") {
        url = format!("wss://{url}");
    }
    while url.ends_with('/') {
        url.pop();
    }
    if !url.ends_with("/ws") {
        url.push_str("/ws");
    }
    url
}

/// Convert a `ws(s)://…/ws` URL to the matching `http(s)://…` REST base.
pub fn http_base(ws_url: &str) -> String {
    let mut base = if let Some(rest) = ws_url.strip_prefix("wss://") {
        format!("https://{rest}")
    } else if let Some(rest) = ws_url.strip_prefix("ws://") {
        format!("http://{rest}")
    } else {
        ws_url.to_string()
    };
    while base.ends_with('/') {
        base.pop();
    }
    if base.ends_with("/ws") {
        base.truncate(base.len() - 3);
    }
    base
}

// ── Commands ────────────────────────────────────────────────────────────────

#[tauri::command]
fn get_config(state: State<AppState>) -> Config {
    // Never hand the raw token to the frontend; the dashboard only needs to
    // know whether one is set.
    let mut c = state.cfg.lock().unwrap().clone();
    if !c.token.is_empty() {
        c.token = "__SET__".to_string();
    }
    c
}

#[derive(Deserialize)]
struct ConfigUpdate {
    server: Option<String>,
    token: Option<String>,
    autostart: Option<bool>,
    dnd: Option<bool>,
    response_length: Option<String>,
    notification_style: Option<String>,
}

#[tauri::command]
fn update_config(update: ConfigUpdate, state: State<AppState>) -> Result<Config, String> {
    let mut cfg = state.cfg.lock().unwrap();
    if let Some(s) = update.server {
        cfg.server = s.trim().to_string();
    }
    if let Some(t) = update.token {
        // "__SET__" is the masked sentinel get_config hands out — ignore it so a
        // round-tripped form doesn't overwrite the real token with the mask.
        if t != "__SET__" {
            cfg.token = t;
        }
    }
    if let Some(a) = update.autostart {
        cfg.autostart = a;
    }
    if let Some(d) = update.dnd {
        cfg.dnd = d;
    }
    if let Some(v) = update.response_length {
        cfg.response_length = sanitize_response_length(v.trim());
    }
    if let Some(v) = update.notification_style {
        cfg.notification_style = sanitize_notification_style(v.trim());
    }
    save_config(&cfg)?;
    let snapshot = cfg.clone();
    drop(cfg);
    // Apply immediately by forcing a reconnect with the new server/token.
    state.reconnect.notify_waiters();
    let mut masked = snapshot;
    if !masked.token.is_empty() {
        masked.token = "__SET__".to_string();
    }
    Ok(masked)
}

#[tauri::command]
fn verify_connection(state: State<AppState>) -> bool {
    *state.connected.lock().unwrap()
}

#[tauri::command]
fn reconnect(state: State<AppState>) {
    state.reconnect.notify_waiters();
}

#[tauri::command]
fn get_notifications(state: State<AppState>) -> Vec<Value> {
    state.history.lock().unwrap().iter().cloned().collect()
}

#[tauri::command]
fn clear_notifications(state: State<AppState>) {
    state.history.lock().unwrap().clear();
}

/// Relay an Accept/Deny/Acknowledge decision from a toast back to the agent.
///
/// POSTs to the relay's `/api/approval/respond`; the relay records it for the
/// agent's long-poll (and forwards to a local `callback_url` if one was set).
/// A successful long-poll submission is not final: the UI stays pending until
/// the originating agent confirms consumption through the relay.
#[tauri::command]
async fn send_test_notification(state: State<'_, AppState>) -> Result<Value, String> {
    let (server, token, response_length, notification_style) = {
        let c = state.cfg.lock().unwrap();
        (
            c.server.clone(),
            c.token.clone(),
            c.response_length.clone(),
            c.notification_style.clone(),
        )
    };
    let base = http_base(&ensure_ws_url(&server));
    if base.is_empty() || base.contains("your-server.example") {
        return Err("No relay server configured".into());
    }
    let message = format!(
        "Live desktop test. Response length: {response_length}; style: {notification_style}."
    );
    let body = json!({
        "title": "anotify test",
        "message": message,
        "source": "anotify-desktop",
        "priority": "medium",
        "kind": "default",
        "response_length": response_length,
        "notification_style": notification_style
    });
    let mut req = reqwest::Client::new()
        .post(format!("{base}/api/notify"))
        .json(&body);
    if !token.is_empty() {
        req = req.bearer_auth(token);
    }
    let resp = req.send().await.map_err(|e| e.to_string())?;
    let status = resp.status();
    let value: Value = resp
        .json()
        .await
        .unwrap_or_else(|_| json!({ "ok": status.is_success() }));
    if !status.is_success() {
        let detail = value
            .get("detail")
            .and_then(|d| d.as_str())
            .unwrap_or("test notification failed");
        return Err(format!("{} ({})", detail, status.as_u16()));
    }
    Ok(value)
}

#[tauri::command]
async fn respond_approval(
    app_handle: tauri::AppHandle,
    approval_id: String,
    choice: String,
    callback_url: Option<String>,
    state: State<'_, AppState>,
) -> Result<Value, String> {
    let (server, token) = {
        let c = state.cfg.lock().unwrap();
        (c.server.clone(), c.token.clone())
    };
    let base = http_base(&ensure_ws_url(&server));
    if base.is_empty() || base.contains("your-server.example") {
        return Err("No relay server configured".into());
    }

    // Relay the decision first. A network error must not be represented as a
    // locally resolved approval.
    let mut body = json!({ "approval_id": approval_id.clone(), "choice": choice.clone() });
    if let Some(cb) = callback_url {
        if !cb.is_empty() {
            body["callback_url"] = json!(cb);
        }
    }

    let mut req = reqwest::Client::new()
        .post(format!("{base}/api/approval/respond"))
        .json(&body);
    if !token.is_empty() {
        req = req.bearer_auth(token);
    }

    let resp = req.send().await.map_err(|e| e.to_string())?;
    let status = resp.status();
    let value: Value = resp
        .json()
        .await
        .unwrap_or_else(|_| json!({ "ok": status.is_success() }));

    if !status.is_success() {
        let detail = value
            .get("detail")
            .and_then(|d| d.as_str())
            .unwrap_or("approval failed");
        return Err(format!("{} ({})", detail, status.as_u16()));
    }

    // Mirror the relay's two-phase state. A submitted click remains pending;
    // only an agent-confirmed response is final.
    let event_name = if value.get("status").and_then(|v| v.as_str()) == Some("confirmed") {
        "approval-resolved"
    } else {
        "approval-submitted"
    };
    let event = json!({ "approval_id": approval_id, "choice": choice });
    let _ = app_handle.emit(event_name, event.clone());
    let _ = app_handle.emit_to("main", event_name, event.clone());
    let _ = app_handle.emit_to("toasts", event_name, event);

    Ok(value)
}

// ── Helpers shared with the WS task ──────────────────────────────────────────

/// Record a notification in the bounded history buffer.
pub fn push_history(state: &AppState, n: &Value) {
    let mut h = state.history.lock().unwrap();
    if h.len() >= MAX_HISTORY {
        h.pop_front();
    }
    h.push_back(n.clone());
}

/// Forward a live notification to both windows.
pub fn dispatch_notification(app: &AppHandle, n: &Value) {
    // Check DND before popping toast overlay; still always add to inbox.
    let dnd = app
        .try_state::<AppState>()
        .map(|s| s.cfg.lock().unwrap().dnd)
        .unwrap_or(false);
    if !dnd {
        let _ = app.emit_to("toasts", "notification", n.clone());
    }
    let _ = app.emit_to("main", "notification", n.clone());
}

/// Push a connection-status change to the dashboard.
pub fn emit_status(app: &AppHandle, connected: bool) {
    if let Some(state) = app.try_state::<AppState>() {
        *state.connected.lock().unwrap() = connected;
    }
    let _ = app.emit_to("main", "connection", json!({ "connected": connected }));
}

// ── Entry point ───────────────────────────────────────────────────────────

fn main() {
    let cfg = load_config();
    let state = AppState::new(cfg);
    let reconnect_signal = state.reconnect.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            get_config,
            update_config,
            verify_connection,
            reconnect,
            get_notifications,
            clear_notifications,
            send_test_notification,
            respond_approval,
        ])
        .setup(move |app| {
            let show_item = MenuItem::with_id(app, "show", "Show Dashboard", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit anotify", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &quit_item])?;
            let tray_icon =
                tauri::image::Image::from_bytes(include_bytes!("../icons/tray-icon.png"))?;
            let tray = TrayIconBuilder::new()
                .icon(tray_icon)
                .tooltip("anotify")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app_handle, event| match event.id.as_ref() {
                    "show" => show_dashboard(app_handle),
                    "quit" => app_handle.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_dashboard(tray.app_handle());
                    }
                })
                .build(app)?;
            if let Some(state) = app.try_state::<AppState>() {
                *state.tray.lock().unwrap() = Some(tray);
            }

            let app_handle_for_close = app.handle().clone();
            if let Some(window) = app.get_webview_window("main") {
                window.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        if let Some(main) = app_handle_for_close.get_webview_window("main") {
                            let _ = main.hide();
                        }
                    }
                });
            }

            let handle = app.handle().clone();
            // Spawn the WebSocket client on Tauri's async runtime.
            tauri::async_runtime::spawn(async move {
                ws::run(handle, reconnect_signal).await;
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running anotify");
}

fn show_dashboard(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}
