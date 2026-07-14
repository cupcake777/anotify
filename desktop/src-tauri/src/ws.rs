//! WebSocket client task for the anotify desktop backend.
//!
//! Connects to the relay, authenticates with a Bearer token, handles the
//! history baseline/replay frames, dedups by id, and dispatches each live
//! notification to the toast + dashboard windows. Reconnects with exponential
//! backoff and full jitter, and drops the socket immediately when the app asks
//! for a reconnect (e.g. after the server/token changed).

use std::collections::{HashSet, VecDeque};
use std::sync::Arc;
use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use serde_json::Value;
use tauri::AppHandle;
use tauri::Emitter;
use tauri::Manager;
use tokio::sync::Notify;
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::http::header::AUTHORIZATION;
use tokio_tungstenite::tungstenite::Message;

use crate::{dispatch_notification, emit_status, ensure_ws_url, push_history, AppState};

const MAX_SEEN: usize = 500;

/// Stable dedup id for a notification (falls back to content).
fn notif_id(n: &Value) -> String {
    if let Some(id) = n.get("id").and_then(|v| v.as_str()) {
        if !id.is_empty() {
            return id.to_string();
        }
    }
    format!(
        "{}|{}|{}",
        n.get("timestamp")
            .map(|v| v.to_string())
            .unwrap_or_default(),
        n.get("title").and_then(|v| v.as_str()).unwrap_or_default(),
        n.get("message")
            .and_then(|v| v.as_str())
            .unwrap_or_default(),
    )
}

struct Dedup {
    seen: HashSet<String>,
    order: VecDeque<String>,
}
impl Dedup {
    fn new() -> Self {
        Self {
            seen: HashSet::new(),
            order: VecDeque::new(),
        }
    }
    /// Returns true if the id is new (not seen before).
    fn mark(&mut self, id: String) -> bool {
        if self.seen.contains(&id) {
            return false;
        }
        self.seen.insert(id.clone());
        self.order.push_back(id);
        if self.order.len() > MAX_SEEN {
            if let Some(old) = self.order.pop_front() {
                self.seen.remove(&old);
            }
        }
        true
    }
}

pub async fn run(app: AppHandle, reconnect: Arc<Notify>) {
    let mut delay = 1.0_f64;
    let mut dedup = Dedup::new();
    let mut seeded = false;

    loop {
        let (url, token) = {
            let state = app.state::<AppState>();
            let c = state.cfg.lock().unwrap();
            (ensure_ws_url(&c.server), c.token.clone())
        };

        if url.contains("your-server.example") || url == "wss:///ws" {
            // Nothing configured yet — wait for a reconnect signal instead of
            // hammering a placeholder host.
            emit_status(&app, false);
            reconnect.notified().await;
            continue;
        }

        match connect(&app, &url, &token, &mut dedup, &mut seeded, &reconnect).await {
            Ok(_) => { /* clean close (reconnect requested) → loop immediately */ }
            Err(e) => {
                emit_status(&app, false);
                eprintln!("[anotify] connection lost: {e}");
            }
        }

        // Backoff with full jitter, interruptible by a reconnect request.
        let base = delay.min(30.0);
        let jittered = base * (0.5 + rand_unit());
        tokio::select! {
            _ = tokio::time::sleep(Duration::from_secs_f64(jittered)) => {}
            _ = reconnect.notified() => { delay = 1.0; continue; }
        }
        delay = (delay * 2.0).min(30.0);
    }
}

/// Cheap [0,1) pseudo-random without pulling in the `rand` crate.
fn rand_unit() -> f64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    let n = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.subsec_nanos())
        .unwrap_or(0);
    (n % 1_000_000) as f64 / 1_000_000.0
}

async fn send_hello(write: &mut (impl SinkExt<Message> + Unpin)) {
    let host = std::env::var("COMPUTERNAME")
        .or_else(|_| std::env::var("HOSTNAME"))
        .unwrap_or_else(|_| "desktop".to_string());
    let payload = serde_json::json!({
        "type": "hello",
        "name": host,
        "host": host,
        "platform": std::env::consts::OS,
    });
    let _ = write.send(Message::Text(payload.to_string().into())).await;
}

async fn connect(
    app: &AppHandle,
    url: &str,
    token: &str,
    dedup: &mut Dedup,
    seeded: &mut bool,
    reconnect: &Arc<Notify>,
) -> Result<(), String> {
    let mut request = url.into_client_request().map_err(|e| e.to_string())?;
    if !token.is_empty() {
        request.headers_mut().insert(
            AUTHORIZATION,
            format!("Bearer {token}")
                .parse()
                .map_err(|_| "bad token header".to_string())?,
        );
    }

    let (ws_stream, _) = tokio_tungstenite::connect_async(request)
        .await
        .map_err(|e| e.to_string())?;
    let (mut write, mut read) = ws_stream.split();

    emit_status(app, true);
    send_hello(&mut write).await;
    eprintln!("[anotify] connected to {url}");

    loop {
        tokio::select! {
            // Reconnect requested (config changed) → close and return Ok so the
            // outer loop reconnects immediately with fresh settings.
            _ = reconnect.notified() => {
                let _ = write.send(Message::Close(None)).await;
                return Ok(());
            }
            msg = read.next() => {
                match msg {
                    Some(Ok(Message::Text(txt))) => {
                        if let Ok(data) = serde_json::from_str::<Value>(&txt) {
                            handle_message(app, &data, dedup, seeded);
                        }
                    }
                    Some(Ok(Message::Ping(_))) | Some(Ok(Message::Pong(_))) => {}
                    Some(Ok(Message::Close(_))) | None => {
                        return Err("socket closed".into());
                    }
                    Some(Ok(_)) => {}
                    Some(Err(e)) => return Err(e.to_string()),
                }
            }
        }
    }
}

fn handle_message(app: &AppHandle, data: &Value, dedup: &mut Dedup, seeded: &mut bool) {
    if data.get("type").and_then(|t| t.as_str()) == Some("clients") {
        let _ = app.emit_to("main", "clients", data.clone());
        return;
    }
    if data.get("type").and_then(|t| t.as_str()) == Some("history") {
        handle_history(app, data, dedup, seeded);
        return;
    }
    if data.get("type").and_then(|t| t.as_str()) == Some("approval-submitted") {
        let _ = app.emit("approval-submitted", data.clone());
        let _ = app.emit_to("main", "approval-submitted", data.clone());
        let _ = app.emit_to("toasts", "approval-submitted", data.clone());
        return;
    }
    if data.get("type").and_then(|t| t.as_str()) == Some("approval-resolved") {
        let _ = app.emit("approval-resolved", data.clone());
        let _ = app.emit_to("main", "approval-resolved", data.clone());
        let _ = app.emit_to("toasts", "approval-resolved", data.clone());
        if let (Some(approval_id), Some(choice)) = (
            data.get("approval_id").and_then(|v| v.as_str()),
            data.get("choice").and_then(|v| v.as_str()),
        ) {
            if let Some(state) = app.try_state::<AppState>() {
                let mut history = state.history.lock().unwrap();
                for item in history.iter_mut() {
                    if item.get("approval_id").and_then(|v| v.as_str()) == Some(approval_id) {
                        item["_resolved"] = Value::String(choice.to_string());
                    }
                }
            }
        }
        return;
    }
    // Live notification — dedup so a rebroadcast can't double-toast.
    if !dedup.mark(notif_id(data)) {
        return;
    }
    let n = annotate(data);
    if let Some(state) = app.try_state::<AppState>() {
        push_history(&state, &n);
    }
    dispatch_notification(app, &n);
}

fn handle_history(_app: &AppHandle, data: &Value, dedup: &mut Dedup, seeded: &mut bool) {
    let items = match data.get("notifications").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return,
    };

    // History is only a dedup baseline. It must never repopulate the dashboard
    // inbox or spawn replay toasts on app start/reopen.
    for n in items {
        dedup.mark(notif_id(n));
    }
    *seeded = true;
}

/// Tag a notification with a visual `kind` if the server didn't already.
fn annotate(n: &Value) -> Value {
    let mut n = n.clone();
    let has_kind = n
        .get("kind")
        .and_then(|k| k.as_str())
        .map(|s| !s.is_empty())
        .unwrap_or(false);
    if !has_kind {
        let kind = classify(
            n.get("title").and_then(|v| v.as_str()).unwrap_or(""),
            n.get("message").and_then(|v| v.as_str()).unwrap_or(""),
            n.get("source").and_then(|v| v.as_str()).unwrap_or(""),
            n.get("priority")
                .and_then(|v| v.as_str())
                .unwrap_or("medium"),
        );
        n["kind"] = Value::String(kind);
    }
    n
}

/// Mirror of `anotify.events.classify` (kept in sync with the Python rules).
fn classify(title: &str, message: &str, source: &str, priority: &str) -> String {
    let text = format!("{source} {title} {message}").to_lowercase();
    const RULES: &[(&[&str], &str)] = &[
        (
            &["error", "fail", "failed", "crash", "exception", "traceback"],
            "error",
        ),
        (
            &[
                "approval",
                "approve",
                "permission",
                "confirm",
                "authorize",
                "review",
            ],
            "approval",
        ),
        (
            &[
                "complete",
                "completed",
                "done",
                "success",
                "succeeded",
                "finished",
                "passed",
            ],
            "complete",
        ),
        (&["message", "msg", "reply", "new "], "message"),
    ];
    for (keys, kind) in RULES {
        if keys.iter().any(|k| text.contains(k)) {
            return kind.to_string();
        }
    }
    if priority == "critical" {
        "critical".to_string()
    } else {
        "info".to_string()
    }
}
