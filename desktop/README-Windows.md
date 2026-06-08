# anotify Desktop - Windows Quick Start

## For Users (No technical knowledge required)

### Step 1: Install
Double-click `install.bat` to install anotify with GUI support.

### Step 2: Configure Token
Double-click `setup-token.bat` and enter your token when prompted.

### Step 3: Run
Double-click `anotify.bat` to start anotify.

You'll see a green dot in your system tray (bottom-right corner).
- **Green dot** = Connected
- **Red dot** = Disconnected

### Using anotify
- Notifications will appear as Windows Toast notifications
- Double-click the tray icon to open settings
- Right-click the tray icon to quit

## Troubleshooting

### "Python is not installed" error
Download and install Python from: https://www.python.org/downloads/
Make sure to check "Add Python to PATH" during installation.

### No tray icon appears
1. Check if Python is in PATH: Open Command Prompt and type `python --version`
2. Try running `python -m anotify.client` manually to see error messages

### Notifications don't appear
1. Check Windows notification settings
2. Disable Focus Assist / Do Not Disturb
3. Check notification history in Windows Settings

## Files

- `install.bat` - Installs anotify with GUI support
- `setup-token.bat` - Configures your authentication token
- `anotify.bat` - Starts anotify in background with tray icon

## Server

Default server: `wss://your-server.example/ws`
Contact your server admin for a token.
