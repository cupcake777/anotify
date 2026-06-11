use std::sync::Arc;
use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tauri::{AppHandle, Manager};
use tokio::sync::Notify;
use tokio_tungstenite::{
    connect_async,
    tungstenite::{client::IntoClientRequest, http::HeaderValue, Message},
};

use crate::{dispatch_notification, emit_status, ensure_ws_url, push_history, AppState};

pub async fn run(app: AppHandle, reconnect: Arc<Notify>) {
    loop {
        let (server, token) = match app.try_state::<AppState>() {
            Some(state) => {
                let cfg = state.cfg.lock().unwrap().clone();
                (cfg.server, cfg.token)
            }
            None => {
                tokio::time::sleep(Duration::from_secs(2)).await;
                continue;
            }
        };

        let ws_url = ensure_ws_url(&server);
        if ws_url.trim().is_empty() || ws_url.contains("your-server.example") {
            emit_status(&app, false);
            reconnect.notified().await;
            continue;
        }

        match connect(&app, &reconnect, &ws_url, &token).await {
            Ok(()) => {}
            Err(_) => {
                emit_status(&app, false);
                tokio::select! {
                    _ = reconnect.notified() => {}
                    _ = tokio::time::sleep(Duration::from_secs(5)) => {}
                }
            }
        }
    }
}

async fn connect(
    app: &AppHandle,
    reconnect: &Notify,
    ws_url: &str,
    token: &str,
) -> Result<(), String> {
    let mut request = ws_url
        .into_client_request()
        .map_err(|err| err.to_string())?;
    if !token.is_empty() {
        let value = HeaderValue::from_str(&format!("Bearer {token}"))
            .map_err(|err| err.to_string())?;
        request.headers_mut().insert("Authorization", value);
    }

    let (socket, _) = connect_async(request).await.map_err(|err| err.to_string())?;
    emit_status(app, true);

    let (mut write, mut read) = socket.split();
    loop {
        tokio::select! {
            _ = reconnect.notified() => {
                let _ = write.close().await;
                emit_status(app, false);
                return Ok(());
            }
            message = read.next() => {
                match message {
                    Some(Ok(Message::Text(text))) => handle_text(app, &text),
                    Some(Ok(Message::Binary(bytes))) => {
                        if let Ok(text) = String::from_utf8(bytes) {
                            handle_text(app, &text);
                        }
                    }
                    Some(Ok(Message::Ping(payload))) => {
                        let _ = write.send(Message::Pong(payload)).await;
                    }
                    Some(Ok(Message::Close(_))) | None => {
                        emit_status(app, false);
                        return Ok(());
                    }
                    Some(Ok(_)) => {}
                    Some(Err(err)) => {
                        emit_status(app, false);
                        return Err(err.to_string());
                    }
                }
            }
        }
    }
}

fn handle_text(app: &AppHandle, text: &str) {
    let value: Value = serde_json::from_str(text).unwrap_or_else(|_| {
        json!({
            "title": "anotify",
            "message": text,
            "priority": "normal",
            "source": "relay"
        })
    });

    if let Some(state) = app.try_state::<AppState>() {
        push_history(&state, &value);
    }
    dispatch_notification(app, &value);
}
