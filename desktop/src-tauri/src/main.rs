// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager,
};
use tokio::sync::Mutex;
use tokio_tungstenite::{
    connect_async,
    tungstenite::{client::IntoClientRequest, http::HeaderValue, Message},
};

// ═══════════════════════════════════════════════════════════════════════════
// State
// ═══════════════════════════════════════════════════════════════════════════

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Notification {
    title: String,
    message: String,
    priority: String,
    source: String,
    timestamp: f64,
}

struct AppState {
    server_url: Arc<Mutex<String>>,
    token: Arc<Mutex<String>>,
    notifications: Arc<Mutex<Vec<Notification>>>,
    ws_handle: Arc<Mutex<Option<tauri::async_runtime::JoinHandle<()>>>>,
}

// ═══════════════════════════════════════════════════════════════════════════
// Config persistence
// ═══════════════════════════════════════════════════════════════════════════

fn config_path() -> std::path::PathBuf {
    dirs_next::home_dir()
        .unwrap_or_default()
        .join(".anotify.json")
}

fn read_config() -> (String, String) {
    let path = config_path();
    if let Ok(content) = std::fs::read_to_string(&path) {
        if let Ok(cfg) = serde_json::from_str::<serde_json::Value>(&content) {
            return (
                cfg["server"]
                    .as_str()
                    .unwrap_or("wss://notify.bioinfo.pro/ws")
                    .to_string(),
                cfg["token"].as_str().unwrap_or("").to_string(),
            );
        }
    }
    // Also try environment variables
    let server =
        std::env::var("ANOTIFY_SERVER").unwrap_or_else(|_| "wss://notify.bioinfo.pro/ws".into());
    let token = std::env::var("ANOTIFY_TOKEN").unwrap_or_default();
    (server, token)
}

fn save_config(server: &str, token: &str) -> Result<(), String> {
    let cfg = serde_json::json!({
        "server": server,
        "token": token,
    });
    let path = config_path();
    std::fs::write(
        &path,
        serde_json::to_string_pretty(&cfg).unwrap_or_else(|_| cfg.to_string()),
    )
    .map_err(|e| format!("Failed to save config: {}", e))
}

// ═══════════════════════════════════════════════════════════════════════════
// Tauri Commands (called from frontend JS)
// ═══════════════════════════════════════════════════════════════════════════

fn api_endpoint(server: &str, path: &str) -> String {
    server
        .replace("wss://", "https://")
        .replace("ws://", "http://")
        .trim_end_matches("/ws")
        .trim_end_matches('/')
        .to_string()
        + path
}

#[tauri::command]
async fn get_notifications(state: tauri::State<'_, AppState>) -> Result<Vec<Notification>, String> {
    let n = state.notifications.lock().await;
    Ok(n.clone())
}

#[tauri::command]
async fn update_config(
    state: tauri::State<'_, AppState>,
    server: String,
    token: String,
) -> Result<(), String> {
    *state.server_url.lock().await = server.clone();
    *state.token.lock().await = token.clone();
    save_config(&server, &token)?;
    Ok(())
}

#[tauri::command]
async fn get_config(state: tauri::State<'_, AppState>) -> Result<(String, String), String> {
    let server = state.server_url.lock().await.clone();
    let token = state.token.lock().await.clone();
    Ok((server, token))
}

#[tauri::command]
async fn clear_notifications(state: tauri::State<'_, AppState>) -> Result<(), String> {
    state.notifications.lock().await.clear();
    Ok(())
}

#[tauri::command]
async fn send_test_notification(state: tauri::State<'_, AppState>) -> Result<String, String> {
    let server = state.server_url.lock().await.clone();
    let token = state.token.lock().await.clone();
    let endpoint = api_endpoint(&server, "/api/notify");

    let response = reqwest::Client::new()
        .post(&endpoint)
        .bearer_auth(token)
        .json(&serde_json::json!({
            "title": "anotify test",
            "message": "Settings test notification",
            "priority": "high",
            "source": "anotify-desktop"
        }))
        .send()
        .await
        .map_err(|e| format!("Failed to send test: {}", e))?;

    let status = response.status();
    let body = response
        .text()
        .await
        .unwrap_or_else(|_| "<empty response>".to_string());
    if status.is_success() {
        Ok(body)
    } else {
        Err(format!("{} {}", status, body))
    }
}

#[tauri::command]
async fn respond_approval(
    state: tauri::State<'_, AppState>,
    approval_id: String,
    choice: String,
    callback_url: String,
) -> Result<String, String> {
    let server = state.server_url.lock().await.clone();
    let token = state.token.lock().await.clone();
    let endpoint = api_endpoint(&server, "/api/approval/respond");

    let response = reqwest::Client::new()
        .post(&endpoint)
        .bearer_auth(token)
        .json(&serde_json::json!({
            "approval_id": approval_id,
            "choice": choice,
            "callback_url": callback_url,
        }))
        .send()
        .await
        .map_err(|e| format!("Failed to send approval response: {}", e))?;

    let status = response.status();
    let body = response
        .text()
        .await
        .unwrap_or_else(|_| "<empty response>".to_string());
    if status.is_success() {
        Ok(body)
    } else {
        Err(format!("{} {}", status, body))
    }
}

#[tauri::command]
async fn reconnect(
    state: tauri::State<'_, AppState>,
    app_handle: tauri::AppHandle,
) -> Result<(), String> {
    // Abort old WebSocket task
    if let Some(handle) = state.ws_handle.lock().await.take() {
        handle.abort();
    }

    let server_url = state.server_url.lock().await.clone();
    let token = state.token.lock().await.clone();
    let notifications = state.notifications.clone();

    let handle = tauri::async_runtime::spawn(async move {
        start_ws_connection(server_url, token, app_handle, notifications).await;
    });
    *state.ws_handle.lock().await = Some(handle);

    Ok(())
}

// ═══════════════════════════════════════════════════════════════════════════
// WebSocket connection
// ═══════════════════════════════════════════════════════════════════════════

async fn start_ws_connection(
    server_url: String,
    token: String,
    app_handle: tauri::AppHandle,
    notifications: Arc<Mutex<Vec<Notification>>>,
) {
    let ws_url = server_url
        .replace("https://", "wss://")
        .replace("http://", "ws://");
    let full_url = if ws_url.ends_with("/ws") {
        ws_url
    } else {
        format!("{}/ws", ws_url)
    };

    loop {
        let request_result = (|| -> Result<_, String> {
            let mut request = full_url
                .clone()
                .into_client_request()
                .map_err(|e| e.to_string())?;
            if !token.is_empty() {
                let header = HeaderValue::from_str(&format!("Bearer {}", token))
                    .map_err(|e| e.to_string())?;
                request.headers_mut().insert("Authorization", header);
            }
            Ok(request)
        })();
        let request = match request_result {
            Ok(request) => request,
            Err(e) => {
                eprintln!("[anotify] Invalid WebSocket request: {} — retrying in 5s", e);
                let _ = app_handle.emit("ws-status", "disconnected");
                tokio::time::sleep(std::time::Duration::from_secs(5)).await;
                continue;
            }
        };

        match connect_async(request).await {
            Ok((ws_stream, _)) => {
                println!("[anotify] Connected to {}", full_url);
                let _ = app_handle.emit("ws-status", "connected");

                let (_, mut read) = ws_stream.split();
                while let Some(msg) = read.next().await {
                    match msg {
                        Ok(Message::Text(text)) => {
                            if let Ok(data) = serde_json::from_str::<serde_json::Value>(&text) {
                                // Skip history messages
                                if data.get("type").map_or(false, |t| t == "history") {
                                    continue;
                                }

                                let notif = Notification {
                                    title: data["title"].as_str().unwrap_or("").to_string(),
                                    message: data["message"].as_str().unwrap_or("").to_string(),
                                    priority: data["priority"]
                                        .as_str()
                                        .unwrap_or("medium")
                                        .to_string(),
                                    source: data["source"]
                                        .as_str()
                                        .unwrap_or("unknown")
                                        .to_string(),
                                    timestamp: data["timestamp"].as_f64().unwrap_or(0.0),
                                };

                                // Store in history
                                {
                                    let mut n = notifications.lock().await;
                                    n.push(notif.clone());
                                    if n.len() > 200 {
                                        n.remove(0);
                                    }
                                }

                                // Keep dashboard history and toast overlay separate.
                                // A global event is delivered to both windows and makes the
                                // transparent toast overlay render duplicates.
                                let _ = app_handle.emit_to("main", "notification", &notif);
                                let _ = app_handle.emit_to("toasts", "notification", &data);
                            }
                        }
                        Ok(Message::Close(_)) => break,
                        Err(e) => {
                            eprintln!("[anotify] WS error: {}", e);
                            break;
                        }
                        _ => {}
                    }
                }
            }
            Err(e) => {
                eprintln!("[anotify] Connection failed: {} — retrying in 5s", e);
            }
        }

        let _ = app_handle.emit("ws-status", "disconnected");
        tokio::time::sleep(std::time::Duration::from_secs(5)).await;
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// App entry
// ═══════════════════════════════════════════════════════════════════════════

fn main() {
    // Log panics to file for debugging
    std::panic::set_hook(Box::new(|info| {
        let log_path = dirs_next::data_dir()
            .unwrap_or_else(|| std::path::PathBuf::from("."))
            .join("anotify-crash.log");
        let msg = format!(
            "[{:?}] {}\n",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs(),
            info
        );
        let _ = std::fs::write(&log_path, &msg);
        eprintln!("{}", msg);
    }));

    // Log startup to file
    let log_path = dirs_next::data_dir()
        .unwrap_or_else(|| std::path::PathBuf::from("."))
        .join("anotify-crash.log");
    let _ = std::fs::write(&log_path, "anotify starting...\n");

    if let Err(e) = run_app() {
        let log_path = dirs_next::data_dir()
            .unwrap_or_else(|| std::path::PathBuf::from("."))
            .join("anotify-crash.log");
        let _ = std::fs::write(&log_path, format!("FATAL: {}\n", e));
        eprintln!("anotify fatal error: {}", e);
        std::process::exit(1);
    }
}

fn run_app() -> Result<(), Box<dyn std::error::Error>> {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec!["--minimized"]),
        ))
        .setup(|app| {
            // Read persisted config
            let (server_url, token) = read_config();

            let notifications: Arc<Mutex<Vec<Notification>>> = Arc::new(Mutex::new(vec![]));

            // Manage state
            let ws_handle: Arc<Mutex<Option<tauri::async_runtime::JoinHandle<()>>>> =
                Arc::new(Mutex::new(None));
            app.manage(AppState {
                server_url: Arc::new(Mutex::new(server_url.clone())),
                token: Arc::new(Mutex::new(token.clone())),
                notifications: notifications.clone(),
                ws_handle: ws_handle.clone(),
            });

            // Start WebSocket connection (use tauri async runtime, not bare tokio::spawn)
            let app_handle = app.handle().clone();
            let notif_ref = notifications.clone();
            let handle = tauri::async_runtime::spawn(async move {
                start_ws_connection(server_url, token, app_handle, notif_ref).await;
            });
            *ws_handle.blocking_lock() = Some(handle);

            // ── Window close → hide to tray instead of exit ──
            let app_handle_for_close = app.handle().clone();
            if let Some(window) = app.get_webview_window("main") {
                window.on_window_event(move |event| {
                    if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        if let Some(w) = app_handle_for_close.get_webview_window("main") {
                            let _ = w.hide();
                        }
                    }
                });
            }

            // ── System Tray ──
            let show = MenuItemBuilder::with_id("show", "Show Dashboard").build(app)?;
            let settings = MenuItemBuilder::with_id("settings", "Settings...").build(app)?;
            let separator = tauri::menu::PredefinedMenuItem::separator(app)?;
            let quit = MenuItemBuilder::with_id("quit", "Quit").build(app)?;

            let menu = MenuBuilder::new(app)
                .item(&show)
                .item(&settings)
                .item(&separator)
                .item(&quit)
                .build()?;

            let tray_icon = match app.default_window_icon().cloned() {
                Some(icon) => icon,
                None => {
                    match tauri::image::Image::from_bytes(include_bytes!("../icons/tray-icon.png"))
                    {
                        Ok(icon) => icon,
                        Err(e) => {
                            eprintln!("[anotify] Failed to load tray icon: {}", e);
                            // Create a minimal 1x1 transparent icon as fallback
                            tauri::image::Image::new(&[0, 0, 0, 0], 1, 1)
                        }
                    }
                }
            };
            let _tray = TrayIconBuilder::new()
                .icon(tray_icon)
                .menu(&menu)
                .tooltip("anotify")
                .on_menu_event(move |app_handle, event| match event.id().as_ref() {
                    "show" => {
                        if let Some(window) = app_handle.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "settings" => {
                        if let Some(window) = app_handle.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                            let _ = window.emit("navigate", "settings");
                        }
                    }
                    "quit" => {
                        app_handle.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_notifications,
            update_config,
            get_config,
            clear_notifications,
            send_test_notification,
            respond_approval,
            reconnect,
        ])
        .run(tauri::generate_context!())?;
    Ok(())
}
