#!/usr/bin/env bash
# PlayDate — single entry point for Linux and macOS.
# Run this directly or pin it to your dock/taskbar.
# On first run (or when the venv is missing), setup runs automatically.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$DIR/.venv/bin/python"
OS="$(uname)"

# ── Register/update desktop integration (self-healing if folder moves) ─────────

if [ "$OS" = "Linux" ]; then
    DESKTOP_DIR="$HOME/.local/share/applications"
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP_DIR/playdate.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=PlayDate
Comment=Your personal Steam library manager
Exec=$DIR/launch.sh
Icon=$DIR/static/img/favicon.png
Terminal=false
Categories=Game;
StartupWMClass=main.py
EOF
    chmod +x "$DESKTOP_DIR/playdate.desktop"
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

elif [ "$OS" = "Darwin" ]; then
    APP="$HOME/Applications/PlayDate.app"
    mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
    cat > "$APP/Contents/MacOS/PlayDate" << EOF
#!/usr/bin/env bash
exec "$DIR/launch.sh"
EOF
    chmod +x "$APP/Contents/MacOS/PlayDate"
    if [ ! -f "$APP/Contents/Info.plist" ]; then
        cat > "$APP/Contents/Info.plist" << 'PLISTEOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>CFBundleName</key>        <string>PlayDate</string>
    <key>CFBundleDisplayName</key> <string>PlayDate</string>
    <key>CFBundleIdentifier</key>  <string>com.playdate.app</string>
    <key>CFBundleVersion</key>     <string>1.0</string>
    <key>CFBundleExecutable</key>  <string>PlayDate</string>
    <key>CFBundlePackageType</key> <string>APPL</string>
    <key>CFBundleIconFile</key>    <string>favicon</string>
    <key>LSUIElement</key>         <false/>
</dict></plist>
PLISTEOF
    fi
    [ -f "$DIR/static/img/favicon.png" ] && \
        cp "$DIR/static/img/favicon.png" "$APP/Contents/Resources/favicon.png" 2>/dev/null || true
    mdimport "$APP" 2>/dev/null || true
fi

# ── Run setup if venv is missing ───────────────────────────────────────────────

if [ ! -f "$VENV_PYTHON" ]; then
    python3 "$DIR/install.py"
    if [ ! -f "$VENV_PYTHON" ]; then
        echo "Setup did not complete. Re-run launch.sh to try again."
        exit 1
    fi
fi

# ── Launch ─────────────────────────────────────────────────────────────────────

exec "$VENV_PYTHON" "$DIR/main.py" "$@"
