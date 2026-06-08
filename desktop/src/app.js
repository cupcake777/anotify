// ═══════════════════════════════════════════════════
// anotify — desktop frontend
// ═══════════════════════════════════════════════════

const { invoke } = window.__TAURI__?.core ?? {};
const { listen } = window.__TAURI__?.event ?? {};

// Debug: show Tauri API status
console.log("[anotify] __TAURI__:", window.__TAURI__ ? "OK" : "MISSING");
console.log("[anotify] invoke:", typeof invoke);
console.log("[anotify] listen:", typeof listen);

// Show debug banner if Tauri API is missing
if (!window.__TAURI__) {
  document.addEventListener("DOMContentLoaded", () => {
    const d = document.createElement("div");
    d.style.cssText = "position:fixed;top:0;left:0;right:0;background:#e05555;color:white;padding:6px 12px;font-size:12px;z-index:9999;font-family:monospace";
    d.textContent = "⚠ Tauri API not loaded — settings won't work. Check console (F12).";
    document.body.prepend(d);
  });
}

// ═══════ DOM refs ═══════
const $statusDot = document.getElementById("status-dot");
const $wsStatus = document.getElementById("ws-status");
const $notifications = document.getElementById("notifications");
const $tabBtns = document.querySelectorAll(".tab");
const $tabContents = document.querySelectorAll(".tab-content");
const $settingsForm = document.getElementById("settings-form");
const $cfgServer = document.getElementById("cfg-server");
const $cfgToken = document.getElementById("cfg-token");
const $clearBtn = document.getElementById("clear-btn");

// ═══════ Priority emoji ═══════
const PRIORITY_ICONS = {
  low: "🐦",
  medium: "💌",
  high: "⚠️",
  critical: "🚨",
};

// ═══════ Tab switching ═══════
$tabBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab;
    $tabBtns.forEach((b) => b.classList.remove("active"));
    $tabContents.forEach((c) => c.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${tab}`).classList.add("active");
  });
});

// ═══════ Load notifications ═══════
async function loadNotifications() {
  if (!invoke) return;
  try {
    const list = await invoke("get_notifications");
    renderNotifications(list);
  } catch (e) {
    console.error("Failed to load notifications:", e);
  }
}

function renderNotifications(list) {
  if (!list || list.length === 0) {
    $notifications.innerHTML =
      '<p class="empty">No notifications yet. Waiting for messages...</p>';
    return;
  }

  $notifications.innerHTML = list
    .slice()
    .reverse()
    .map(
      (n) => `
    <div class="notif-item priority-${n.priority}">
      <span class="notif-priority">${PRIORITY_ICONS[n.priority] || "📨"}</span>
      <div class="notif-body">
        <div class="notif-title">${escapeHtml(n.title)}</div>
        <div class="notif-msg">${escapeHtml(n.message)}</div>
        <div class="notif-meta">
          <span>${escapeHtml(n.source)}</span>
          <span>${formatTime(n.timestamp)}</span>
          <span>${n.priority}</span>
        </div>
      </div>
    </div>`
    )
    .join("");
}

function addNotification(notif) {
  const el = document.createElement("div");
  el.className = `notif-item priority-${notif.priority} highlight`;
  el.innerHTML = `
    <span class="notif-priority">${PRIORITY_ICONS[notif.priority] || "📨"}</span>
    <div class="notif-body">
      <div class="notif-title">${escapeHtml(notif.title)}</div>
      <div class="notif-msg">${escapeHtml(notif.message)}</div>
      <div class="notif-meta">
        <span>${escapeHtml(notif.source)}</span>
        <span>${formatTime(notif.timestamp)}</span>
        <span>${notif.priority}</span>
      </div>
    </div>`;

  // Remove empty state
  const empty = $notifications.querySelector(".empty");
  if (empty) empty.remove();

  $notifications.prepend(el);

  // Remove highlight after animation
  setTimeout(() => el.classList.remove("highlight"), 2000);

  // Limit displayed items
  while ($notifications.children.length > 100) {
    $notifications.lastChild?.remove();
  }
}

// ═══════ Clear notifications ═══════
$clearBtn?.addEventListener("click", async () => {
  if (!invoke) return;
  try {
    await invoke("clear_notifications");
    $notifications.innerHTML =
      '<p class="empty">No notifications yet. Waiting for messages...</p>';
  } catch (e) {
    console.error("Failed to clear notifications:", e);
  }
});

// ═══════ Settings ═══════
async function loadConfig() {
  if (!invoke) return;
  try {
    const [server, token] = await invoke("get_config");
    $cfgServer.value = server || "";
    $cfgToken.value = token || "";
  } catch (e) {
    console.error("Failed to load config:", e);
  }
}

$settingsForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!invoke) return;
  try {
    await invoke("update_config", {
      server: $cfgServer.value.trim(),
      token: $cfgToken.value.trim(),
    });
    // Reconnect WebSocket with new config
    try {
      await invoke("reconnect");
    } catch (re) {
      console.error("Reconnect failed:", re);
    }
    // Show success feedback inline instead of alert
    const btn = $settingsForm.querySelector('button[type="submit"]');
    const original = btn.textContent;
    btn.textContent = "✅ Saved!";
    btn.disabled = true;
    setTimeout(() => {
      btn.textContent = original;
      btn.disabled = false;
    }, 2000);
  } catch (err) {
    console.error("Failed to save settings:", err);
    alert("Failed to save settings.");
  }
});

// ═══════ Listen to Rust backend events ═══════
async function setupListeners() {
  if (!listen) return;

  // New notification from WebSocket
  await listen("notification", (event) => {
    addNotification(event.payload);
  });

  // WebSocket status
  await listen("ws-status", (event) => {
    const status = event.payload;
    $wsStatus.textContent =
      status === "connected" ? "● Connected" : "○ Disconnected";
    $statusDot.className = `dot ${status === "connected" ? "connected" : "disconnected"}`;
  });

  // Navigate to tab (from tray menu)
  await listen("navigate", (event) => {
    const tab = event.payload;
    $tabBtns.forEach((b) => {
      if (b.dataset.tab === tab) b.click();
    });
  });
}

// ═══════ Helpers ═══════
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function formatTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// ═══════ Init ═══════
setupListeners();
loadNotifications();
loadConfig();
