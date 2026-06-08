const { invoke } = window.__TAURI__?.core ?? {};
const { listen } = window.__TAURI__?.event ?? {};

const $ = (id) => document.getElementById(id);
const statusDot = $("status-dot");
const wsStatus = $("ws-status");
const connectionState = $("connection-state");
const stack = $("stack");
const inboxList = $("notifications");
const inboxCount = $("inbox-count");
const navInboxCount = $("nav-inbox-count");
const recentList = $("recent-list");
const metricInbox = $("metric-inbox");
const metricPending = $("metric-pending");
const metricLive = $("metric-live");
const serverSummary = $("server-summary");
const tokenSummary = $("token-summary");
const privacyState = $("privacy-state");
const settingsForm = $("settings-form");
const cfgServer = $("cfg-server");
const cfgToken = $("cfg-token");
const configCurrent = $("config-current");
const saveBtn = $("save-btn");

const ACCENT = {
  complete: "var(--k-complete)",
  error: "var(--k-error)",
  approval: "var(--k-approval)",
  message: "var(--k-message)",
  info: "var(--k-info)",
};
const ACCENT_HEX = {
  complete: "#48b079",
  error: "#ec6a6a",
  approval: "#eba33a",
  message: "#5aa6f0",
  info: "#93a6c2",
};
const ICONS = {
  complete: "assets/04_task_complete.png",
  error: "assets/06_error.png",
  approval: "assets/03_approval_required.png",
  message: "assets/02_new_message.png",
  info: "assets/01_default.png",
};
const HOSTMAP = { hpc: "H", vps: "V", local: "M", localhost: "M", mac: "M", ci: "C", github: "G" };
const DURATION = { low: 5000, medium: 5000, high: 8000, critical: 0 };
const RULES = [
  [["error", "fail", "failed", "crash", "exception", "traceback"], "error"],
  [["approval", "approve", "permission", "confirm", "authorize", "review"], "approval"],
  [["complete", "completed", "done", "success", "succeeded", "finished", "passed"], "complete"],
  [["message", "msg", "reply", "new "], "message"],
];
const SAMPLE_NOTIFICATIONS = {
  message: { title: "New notification", message: "A background agent sent a desktop notification.", priority: "medium", source: "agent@local", kind: "message" },
  approval: { title: "Approval required", message: "An agent is waiting for your decision.", priority: "high", source: "hermes@local", kind: "approval" },
  complete: { title: "Task complete", message: "The background task finished successfully.", priority: "medium", source: "agent@local", kind: "complete" },
  error: { title: "Action failed", message: "A background task reported an error.", priority: "high", source: "agent@local", kind: "error" },
};

let inbox = [];
let dnd = false;
let pos = "br";
let theme = "cream";
let maxStack = 4;
let filter = "all";
let query = "";
let layoutLeft = false;
let serverConfigured = false;
let tokenConfigured = false;

function classify(title = "", message = "", source = "", priority = "medium") {
  const text = `${source} ${title} ${message}`.toLowerCase();
  for (const [words, kind] of RULES) {
    if (words.some((word) => text.includes(word))) return kind;
  }
  return priority === "critical" ? "error" : "info";
}

function escapeHtml(text = "") {
  const div = document.createElement("div");
  div.textContent = String(text);
  return div.innerHTML;
}

function timestampMs(ts) {
  if (!ts) return Date.now();
  return ts > 100000000000 ? ts : ts * 1000;
}

function hhmm(ts) {
  const d = new Date(timestampMs(ts));
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function parseSource(n) {
  let agent = n.agent;
  let host = n.host;
  const src = n.source || "agent";
  if (src.includes("@")) {
    const parts = src.split("@");
    agent = agent || parts[0];
    host = host || parts[1];
  }
  agent = agent || src;
  host = host || "";
  const key = (host.split(/[-.]/)[0] || "").toLowerCase();
  return { agent, host, initial: HOSTMAP[key] || (host ? host[0].toUpperCase() : "·") };
}

function oneLiner(n) {
  return n.summary || (n.message || "").split("\n")[0] || "Notification";
}

function normalizeNotification(n) {
  const kind = n.kind || classify(n.title, n.message, n.source, n.priority);
  return {
    ...n,
    id: n.id || `n${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`,
    kind,
    priority: n.priority || "medium",
    timestamp: n.timestamp || Date.now() / 1000,
    resolution: n.resolution || null,
  };
}

function updateMetrics() {
  const pending = inbox.filter((item) => (item.kind === "approval" || item.priority === "critical") && !item.resolution).length;
  metricInbox.textContent = String(inbox.length);
  metricPending.textContent = String(pending);
  metricLive.textContent = String(stack.children.length);
  navInboxCount.textContent = String(inbox.length);
  inboxCount.textContent = `${inbox.length} item${inbox.length === 1 ? "" : "s"}`;
}

function setStatus(status) {
  statusDot.className = `dot ${status === "connected" ? "connected" : status === "connecting" ? "connecting" : "disconnected"}`;
  const label = status === "connected" ? "Connected" : status === "connecting" ? "Connecting" : "Disconnected";
  wsStatus.textContent = label;
  connectionState.textContent = label;
}

function switchView(name) {
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  $("view-title").textContent = name[0].toUpperCase() + name.slice(1);
}

function addInbox(notification) {
  const item = normalizeNotification(notification);
  inbox.unshift(item);
  if (inbox.length > 200) inbox.length = 200;
  renderInbox();
  renderRecent();
  updateMetrics();
  return item;
}

function renderRecent() {
  const items = inbox.slice(0, 5);
  if (!items.length) {
    recentList.innerHTML = '<p class="empty">No notifications yet.</p>';
    return;
  }
  recentList.innerHTML = items.map(renderInboxRow).join("");
}

function renderInboxRow(item) {
  const src = parseSource(item);
  return `<article class="ix" data-id="${item.id}" style="--ac:${ACCENT_HEX[item.kind] || ACCENT_HEX.info}">
    <div class="av"><img src="${ICONS[item.kind] || ICONS.info}" alt=""></div>
    <div><div class="t">${escapeHtml(item.title || "Notification")}</div><div class="s">${escapeHtml(src.host ? `${src.host} · ` : "")}${escapeHtml(oneLiner(item))}</div></div>
    <span class="when">${hhmm(item.timestamp)}</span>
  </article>`;
}

function renderInbox() {
  const q = query.toLowerCase();
  const items = inbox.filter((item) => {
    const text = `${item.title || ""} ${item.message || ""} ${item.source || ""}`.toLowerCase();
    return (filter === "all" || item.kind === filter) && (!q || text.includes(q));
  });
  if (!items.length) {
    inboxList.innerHTML = '<p class="empty">No notifications yet.</p>';
    return;
  }
  inboxList.innerHTML = items.map(renderInboxRow).join("");
  inboxList.querySelectorAll(".ix").forEach((row) => {
    row.addEventListener("click", () => {
      const old = row.nextElementSibling;
      if (old?.classList.contains("ix-full")) {
        old.remove();
        return;
      }
      const item = inbox.find((x) => x.id === row.dataset.id);
      const full = document.createElement("div");
      full.className = "ix-full";
      full.textContent = item?.message || oneLiner(item || {});
      row.after(full);
    });
  });
}

function spawnToast(raw) {
  const item = raw._replay ? raw : addInbox(raw);
  if (dnd && item.priority !== "critical") return;
  const kind = item.kind;
  const sticky = item.priority === "critical" || kind === "approval";
  const duration = sticky ? 0 : (DURATION[item.priority] ?? 5000);
  const src = parseSource(item);
  const summary = oneLiner(item);
  const hasMore = item.message && item.message.trim() !== summary.trim();

  const toast = document.createElement("article");
  toast.className = `toast${item.priority === "critical" ? " crit" : ""}${sticky ? " sticky" : ""}${kind === "approval" ? " open" : ""}`;
  toast.classList.toggle("left", layoutLeft);
  toast.style.setProperty("--accent", ACCENT[kind] || ACCENT.info);
  toast.innerHTML = `
    <div class="avatar"><img src="${ICONS[kind] || ICONS.info}" alt=""></div>
    <div class="body">
      <div class="row1"><div class="title">${escapeHtml(item.title || "Agent notification")}</div></div>
      <div class="summary">${escapeHtml(summary)}</div>
      <div class="meta"><span class="host" title="${escapeHtml(src.host || "unknown host")}">${escapeHtml(src.initial)}</span><span class="agent">${escapeHtml(src.agent)}</span><span class="time">${hhmm(item.timestamp)}</span></div>
    </div>
    ${hasMore ? `<div class="details"><div class="details-inner"><pre class="full">${escapeHtml(item.message)}</pre></div></div>` : ""}
    ${kind === "approval" ? '<div class="actionbar"><button class="act accept" data-act="accepted">Accept</button><button class="act deny" data-act="denied">Deny</button></div>' : ""}
    ${item.priority === "critical" ? '<div class="actionbar"><button class="act ack" data-act="acknowledged">Acknowledge</button><button class="act ghost" data-act="inbox">Open Inbox</button></div>' : ""}
    <button class="close" title="Dismiss">×</button>
    ${duration > 0 ? `<div class="prog" style="animation-duration:${duration}ms"></div>` : ""}`;

  stack.appendChild(toast);
  while (stack.children.length > maxStack) hardRemove(stack.firstElementChild);
  updateMetrics();

  let timer = duration > 0 ? setTimeout(() => dismiss(toast), duration) : null;
  toast.addEventListener("mouseenter", () => {
    toast.classList.add("paused");
    if (timer) clearTimeout(timer);
    timer = null;
  });
  toast.addEventListener("mouseleave", () => {
    toast.classList.remove("paused");
    if (duration > 0 && !timer) timer = setTimeout(() => dismiss(toast), 1600);
  });
  toast.addEventListener("click", (event) => {
    if (event.target.closest(".act") || event.target.closest(".close")) return;
    if (hasMore) toast.classList.toggle("open");
  });
  toast.querySelector(".close").addEventListener("click", () => dismiss(toast));
  toast.querySelectorAll(".act").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const act = btn.dataset.act;
      if (act === "inbox") {
        switchView("inbox");
        return;
      }
      if (kind === "approval" && item.approval_id && invoke) {
        try {
          await invoke("respond_approval", {
            approvalId: item.approval_id,
            choice: act,
            callbackUrl: item.callback_url || "",
          });
        } catch (err) {
          const bar = toast.querySelector(".actionbar");
          if (bar) bar.outerHTML = `<div class="resolved">⚠ ${escapeHtml(String(err))}</div>`;
          return;
        }
      }
      item.resolution = act;
      updateMetrics();
      const bar = toast.querySelector(".actionbar");
      if (bar) bar.outerHTML = `<div class="resolved">✔ ${act}</div>`;
      setTimeout(() => dismiss(toast), 850);
    });
  });
}

function dismiss(toast) {
  if (!toast || toast.classList.contains("out")) return;
  toast.classList.add("out");
  toast.addEventListener("animationend", () => hardRemove(toast), { once: true });
  setTimeout(() => hardRemove(toast), 420);
}

function hardRemove(toast) {
  if (!toast || toast._gone) return;
  toast._gone = true;
  toast.remove();
  updateMetrics();
}

function applyLayout() {
  stack.classList.remove("pos-bl", "pos-tr", "pos-tl");
  if (pos === "bl") stack.classList.add("pos-bl");
  if (pos === "tr") stack.classList.add("pos-tr");
  if (pos === "tl") stack.classList.add("pos-tl");
  layoutLeft = pos === "bl" || pos === "tl";
}
function applyTheme() {
  document.body.className = theme === "cream" ? "" : `theme-${theme}`;
}

async function loadConfig() {
  if (!invoke) return;
  try {
    const config = await invoke("get_config");
    cfgServer.value = "";
    cfgToken.value = "";
    serverConfigured = Boolean(config.server_configured);
    tokenConfigured = Boolean(config.token_configured);
    serverSummary.textContent = serverConfigured ? "Server configured" : "Server not configured";
    tokenSummary.textContent = tokenConfigured ? "Token configured" : "Token not configured";
    configCurrent.textContent = `Current config: ${serverConfigured && tokenConfigured ? "ready" : "setup required"}`;
    privacyState.textContent = serverConfigured || tokenConfigured ? "Values hidden" : "Setup required";
  } catch (err) {
    console.error("Failed to load config:", err);
  }
}

async function verifyConnection() {
  if (!invoke) {
    spawnToast({ title: "Desktop bridge unavailable", message: "Open this panel from the installed desktop app.", priority: "high", source: "anotify@local", kind: "error" });
    return;
  }
  try {
    const result = await invoke("verify_connection");
    spawnToast({ title: "Connection verified", message: result, priority: "medium", source: "anotify@local", kind: "complete" });
  } catch (err) {
    spawnToast({ title: "Connection failed", message: String(err), priority: "high", source: "anotify@local", kind: "error" });
  }
}

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!invoke) return;
  const original = saveBtn.textContent;
  saveBtn.textContent = "Saving...";
  saveBtn.disabled = true;
  try {
    await invoke("update_config", { server: cfgServer.value.trim(), token: cfgToken.value.trim() });
    await invoke("reconnect");
    saveBtn.textContent = "Saved";
    cfgToken.value = "";
    await loadConfig();
    spawnToast({ title: "Settings saved", message: "Connection settings were updated.", priority: "medium", source: "anotify@local", kind: "complete" });
  } catch (err) {
    saveBtn.textContent = "Failed";
    spawnToast({ title: "Save failed", message: String(err), priority: "high", source: "anotify@local", kind: "error" });
  } finally {
    setTimeout(() => {
      saveBtn.textContent = original;
      saveBtn.disabled = false;
    }, 1600);
  }
});

async function setupListeners() {
  if (!listen) {
    setStatus("disconnected");
    return;
  }
  await listen("notification", (event) => spawnToast(event.payload));
  await listen("ws-status", (event) => setStatus(event.payload));
  await listen("navigate", (event) => switchView(event.payload === "settings" ? "settings" : "inbox"));
}

$("clear-btn").addEventListener("click", async () => {
  inbox = [];
  renderInbox();
  renderRecent();
  stack.innerHTML = "";
  updateMetrics();
  if (invoke) await invoke("clear_notifications").catch(console.error);
});
$("verify-btn").addEventListener("click", verifyConnection);
$("settings-verify-btn").addEventListener("click", verifyConnection);
$("settings-shortcut").addEventListener("click", () => switchView("settings"));
$("dnd-btn").addEventListener("click", () => {
  dnd = !dnd;
  $("dnd-btn").dataset.on = String(dnd);
  $("dnd-btn").textContent = dnd ? "DND on" : "DND off";
  $("set-dnd").dataset.on = String(dnd);
});
$("set-dnd").addEventListener("click", () => {
  dnd = !dnd;
  $("set-dnd").dataset.on = String(dnd);
  $("dnd-btn").dataset.on = String(dnd);
  $("dnd-btn").textContent = dnd ? "DND on" : "DND off";
});
$("search").addEventListener("input", (event) => { query = event.target.value; renderInbox(); });
document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
document.querySelectorAll("[data-view-jump]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.viewJump)));

function wireSeg(id, callback) {
  const group = $(id);
  group.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      group.querySelectorAll("button").forEach((b) => { b.dataset.on = String(b === button); });
      callback(button.dataset.v);
    });
  });
}
wireSeg("set-pos", (value) => { pos = value; applyLayout(); });
wireSeg("set-max", (value) => { maxStack = Number(value); });
wireSeg("set-theme", (value) => { theme = value; applyTheme(); });

const chips = ["all", "message", "approval", "complete", "error", "info"];
$("chips").innerHTML = chips.map((chip) => `<button class="chip" data-k="${chip}" data-on="${chip === "all"}">${chip}</button>`).join("");
$("chips").querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    filter = chip.dataset.k;
    $("chips").querySelectorAll(".chip").forEach((c) => { c.dataset.on = String(c === chip); });
    renderInbox();
  });
});

document.querySelectorAll("[data-sample]").forEach((button) => {
  button.addEventListener("click", () => spawnToast(SAMPLE_NOTIFICATIONS[button.dataset.sample]));
});

setStatus("connecting");
renderInbox();
renderRecent();
updateMetrics();
setupListeners();
loadConfig();
