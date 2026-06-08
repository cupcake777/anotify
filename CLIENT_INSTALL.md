# anotify 客户端安装指南

## 通用安装 (Python)

```bash
pip install anotify
anotify config --server https://your-server.example --token YOUR_TOKEN
```

## macOS 菜单栏应用 (推荐)

```bash
pip install -e ".[mac]"
anotify config --server https://your-server.example --token YOUR_TOKEN
anotify-mac
```

### 开机自启

```bash
# 运行设置脚本
bash scripts/setup_mac.sh
```

或手动创建 `~/Library/LaunchAgents/com.anotify.client.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.anotify.client</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>anotify.mac_app</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

## Windows

### 方式 1: Python 安装

```powershell
pip install anotify
anotify config --server https://your-server.example --token YOUR_TOKEN
anotify-client --silent
```

### 方式 2: 独立 exe (无需 Python)

```bash
# 在有 Python 的机器上构建
cd ~/ops/agent-notify
python build_exe.py
# 生成 dist/anotify.exe
```

### 开机自启

创建 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\anotify.bat`:

```batch
pythonw anotify-client --silent --no-tray
```

## Linux

```bash
pip install anotify
anotify config --server https://your-server.example --token YOUR_TOKEN
anotify-client --no-tray
```

## 测试

```bash
anotify test
anotify send "测试消息" -t "测试" -p high
```

## 静默运行

```bash
# Windows (隐藏控制台窗口)
anotify-client --silent

# Linux/macOS (后台运行)
anotify-client --no-tray &
```
