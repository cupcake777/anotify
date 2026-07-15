<p align="center">
  <img src="desktop/src/assets/brand/07_app_icon.png" alt="🐧 anotify" width="136"/>
</p>

<h1 align="center">🐧 anotify</h1>

<p align="center">
  <strong>🤖 AI 帮你搭好中继 · 🧑 你只要贴个 Token</strong><br/>
  <sub><em>AI sets up the relay. You just paste a token.</em></sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-v0.2.1_beta-E59A63?style=flat-square" alt="v0.2.1 beta"/>
  <img src="https://img.shields.io/badge/Windows%20%7C%20macOS%20%7C%20Linux-24446F?style=flat-square" alt="Windows, macOS, and Linux"/>
  <img src="https://img.shields.io/badge/Python%203.9%2B%20%2B%20Tauri%202-3776AB?style=flat-square" alt="Python 3.9+ and Tauri 2"/>
  <img src="https://img.shields.io/badge/relay-self--hosted-48B079?style=flat-square" alt="Self-hosted relay"/>
</p>

<p align="center">
  <img src=".github/readme-flow.svg" alt="⬇️ anotify event flow: agent → relay → desktop" width="920"/>
</p>

> [!NOTE]
> **📦 Public beta.** Unsigned desktop installers are available from [GitHub Releases](https://github.com/cupcake777/anotify/releases/latest). The project named `anotify` on PyPI is unrelated; install the Python CLI from this repository.

---

## 🎯 到底是什么

**anotify** 是一个通知中继，让 AI agent 能直接通知你的桌面。

当你的编程助手、HPC 任务或 CI 跑完需要告诉你一声——或者需要你拍个板——它发一个信号，经过轻量中继，落到你桌面上弹一条原生通知。

> **🧠 核心设计哲学：AI 干重活，你干轻活。**
>
> 中继服务器 -> AI 自动安装配置<br/>
> 你只需要 -> 下载客户端 → 粘贴 Token → 收通知

---

## 🤖 AI 自助：一键部署中继

如果你是 AI agent（Codex、Claude Code、Hermes、Cline…），在给用户搭通知通道时，照这个流程走：

```bash
# 📦 获取源码（PyPI 上的 anotify 不是本项目）
git clone https://github.com/cupcake777/anotify.git /opt/anotify
cd /opt/anotify
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[server]"

# 🔑 生成安全 Token
ANOTIFY_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(36))")
sudo install -d -m 700 /etc/anotify
echo "$ANOTIFY_TOKEN" | sudo tee /etc/anotify/token >/dev/null
sudo chmod 600 /etc/anotify/token

# 🚀 启动中继
python server/server.py --host 127.0.0.1 --port 7799 --token-file /etc/anotify/token
```

中继就是一个 Python 进程——**没有数据库、没有托管服务、没有消息队列**。收 HTTP POST，走 WebSocket 广播给所有桌面客户端。

### ✅ AI 部署 checklist

| 步骤 | 说明 |
|------|------|
| ☐ 选一台有公网域名或 Cloudflare Tunnel 的机器 | 中继需要能被客户端访问 |
| ☐ 生成随机 Token，`chmod 600` 存好 | 安全第一 |
| ☐ 用 `--token-file` 启动 | Token 不会出现在 `ps aux` 里 |
| ☐ 套上 systemd 或进程管理器 | 崩溃自动重启 |
| ☐ 把中继地址 + Token 给用户 | 用户贴到桌面客户端就行 |

### 📝 给用户的信息

Agent 应该直接给用户一个可以粘贴的配置：

```
✅ 中继已就绪！在桌面客户端里填入以下信息：

  Server: https://notify.yourdomain.com
  Token:  your-token-here
```

如果 Agent 能直接写配置文件，也可以一步到位：

```json
{"server":"https://notify.yourdomain.com","token":"your-token-here"}
```

---

## 🧑 用户：下载 + 粘贴 Token

**这是你唯一需要手动做的事。** 👇

从 [GitHub Releases](https://github.com/cupcake777/anotify/releases/latest) 下载当前 unsigned beta 安装包；安装后粘贴 Agent 给你的 Server 和 Token。

| 平台 | 安装方式 |
|------|----------|
| 🪟 **Windows** | 下载 `.msi` 安装包 → 双击装 → 粘贴 Token → 完事 |
| 🍎 **macOS** | 下载 `.dmg` → 拖到 Applications → 粘贴 Token → 完事 |
| 🐧 **Linux** | 下载 `.deb` 或 `.AppImage` → 安装 → 粘贴 Token → 完事 |

装好后，app 藏在系统托盘里。自动连中继、收通知、弹原生 Toast、记录历史。

> 如果你是开发者想从源码跑，往下翻 👉 看 [Quick start](#quick-start)

### 🔔 你会看到什么

| 通知类型 | 意思 |
|----------|------|
| ✅ **Complete** | 任务跑完了，一切正常 |
| ❌ **Error** | 出事了，需要你瞅一眼 |
| 💬 **Message** | Agent 给你留了个言 |
| 🔐 **Approval** | Agent 等你拍板呢 |

通知以**原生 OS 弹窗**出现（Windows Toast 🪟、macOS 通知中心 🍎、Linux notify-send 🐧）。托盘图标一眼告诉你连接状态。

### ✋ 审批请求

有些通知可以当场回复。Agent 问你"要不要部署？"或者"删不删这个旧备份？"，你直接在通知或收件箱里点 **Accept** 或 **Deny**，Agent 收到答复继续干活。

---

## 💡 使用场景

### 🤖 AI 编程助手

你的编程 agent（Claude Code、Codex、Hermes、Cline）遇到问题、跑完任务或需要你批准时，直接弹桌面通知。不用盯着终端，不用开着聊天窗口。

```bash
# Agent 自动跑这行
anotify send "✅ 编译完成" --title "Codex" --priority high
anotify approve "🚀 部署到生产？" --agent codex --timeout 300
```

### 🖥️ HPC / 批处理任务

集群上跑了几小时的作业，跑完自动通知你——不用轮询、不用等邮件、不用 SSH 上去看。

```bash
# Slurm epilogue 或 CI 脚本里加一行
anotify send "🧬 Job $SLURM_JOB_ID done" --title "RNA-seq" --priority high
```

### 🔄 CI / CD 流水线

GitHub Actions、GitLab CI、Jenkins 跑完直接弹你桌面。

```yaml
# GitHub Actions workflow 里
- run: anotify send "🔧 CI: ${{ job.status }}" --title "${{ github.repository }}"
```

---

## 🏗️ 架构

```
                          🔒 HTTPS                    🔗 WebSocket
 Remote host           ──────────►      Relay       ──────────►   Your desktop
 ┌──────────────────┐               ┌──────────────────┐          ┌──────────────────┐
 │ 🖥️ HPC / VPS     │  POST /api/   │  anotify-server  │  ws://   │  🐧 Tauri app    │
 │ 🤖 AI agent      │  ───────────► │  FastAPI relay   │  ───────►│  toast + inbox   │
 │ 🔧 CI runner     │               │  token auth      │          │  native notify   │
 └──────────────────┘               └──────────────────┘          └──────────────────┘
          ▲                                   │                             │
          └──────── outbound poll ────────────┴─── approval result ─────────┘
```

三个组件：

| 组件 | 干什么的 |
|------|----------|
| `anotify` 🐍 | Python CLI，agent/脚本/CI/cron 用来发通知或等人审批 |
| `anotify-server` ⚡ | 自托管 FastAPI 中继，REST 收 → WebSocket 发，Token 鉴权，内存缓冲 |
| 桌面 app 🐧 | Tauri 托盘应用，实时收件箱、原生通知、连接状态、一键审批 |

> 远程机器只做出站 HTTP 请求。**不需要开入站端口、不需要聊天工作区、不需要远程 Shell。**

---

## 🚀 Quick start（源码跑）

在本地跑通完整链路。需要 Python 3.9+、Rust stable、Node.js 22+、pnpm 10。

### 1️⃣ 安装 CLI 和中继

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[server]"
```

### 2️⃣ 启动本地中继

```bash
ANOTIFY_TOKEN=local-dev-token \
  python server/server.py --host 127.0.0.1 --port 7799
```

### 3️⃣ 配置 + 打开桌面 app

```bash
. .venv/bin/activate
anotify config \
  --server http://127.0.0.1:7799 \
  --token local-dev-token

cd desktop
pnpm install
pnpm tauri dev
```

### 4️⃣ 发送第一条通知 🎉

```bash
. .venv/bin/activate
anotify send "Training finished" \
  --title "HPC" \
  --priority high \
  --agent codex \
  --script train.py
```

通知会以弹窗出现，同时收件箱里能看到。

---

## ⚙️ 配置

优先级：`CLI 参数 > 环境变量 > ~/.anotify.json`

| 配置项 | CLI | 环境变量 | 配置键 |
|--------|-----|----------|--------|
| 📡 中继地址 | `--server` | `ANOTIFY_SERVER` | `server` |
| 🔑 Token | `--token` | `ANOTIFY_TOKEN` | `token` |
| 📄 配置路径 | — | `ANOTIFY_CONFIG` | — |

一次性保存：

```bash
anotify config --server https://notify.example.com --token your-secret-token
```

Python CLI 和桌面 app 共用同一个配置文件。Unix 上权限 `0600`。Tauri 后端返回设置到 WebView 时会自动掩码已有 Token。

---

## 🏠 自托管中继

```bash
git clone https://github.com/cupcake777/anotify.git
cd anotify
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[server]"
ANOTIFY_TOKEN='替换成你的随机长密码' \
  python server/server.py --host 127.0.0.1 --port 7799
```

验证：

```bash
curl http://127.0.0.1:7799/api/health
```

然后在前面套 TLS（nginx、Caddy 或 Cloudflare Tunnel）。详见 [`server/README.md`](server/README.md)。

---

## 🔒 安全

- **🔐 Token 鉴权** — 每次请求都需要 `Authorization` header；URL 参数 Token 仅作兼容回退
- **🔒 必须走 TLS** — 部署在 HTTPS 后面，否则 Token 和通知内容明文传输
- **📄 Token 文件** — 用 `--token-file` 避免 Token 出现在 `ps aux` 和进程日志里
- **🧠 内存级历史** — 中继重启后记录消失。中继和桌面两端历史都有上限
- **⚠️ 审批 ≠ 沙箱** — 调用脚本自己负责校验、授权和执行，中继只传递决策

---

## 📂 项目结构

```
anotify/
├── src/anotify/       🐍 Python 发送 CLI + 兼容桌面客户端
├── server/            ⚡ FastAPI 中继 + 部署文档
├── desktop/           🐧 Tauri 2 桌面 app
├── tests/             🧪 Python/中继/安全/UI 集成测试
└── .github/workflows/ 🔄 桌面包构建 + Python CI
```

---

## 📊 项目状态

发送 CLI、中继、Tauri 桌面 app、审批流程、跨平台构建都已实现并通过测试。`v0.2.1` 是第一个公开桌面 beta；Python CLI 的包名和分发仍待最终确定。

Beta 期间：
- 📦 从 GitHub Releases 下载 unsigned 桌面安装包
- 🐍 Python CLI 从本仓库安装，不要从 PyPI
- ⚠️ 配置和 UI 细节还在演进
- 🧠 中继历史是内存级的，不是持久存储
- 🔍 用于生产审批前先审查 beta 版本

---

## 📜 License

MIT。详见 [`LICENSE`](LICENSE)。

<p align="center">
  <sub>🐧 AI sets up the relay. You just paste a token.</sub>
</p>
