#!/bin/zsh
# Installs a macOS LaunchAgent (launchd is the Mac's cron) that keeps
# scripts/apply_scheduler.sh running: at login, after a crash, and across reboots.
# The scheduler itself decides when a round is worth starting.
#
#   scripts/install_apply_scheduler.sh            install or reinstall
#   scripts/install_apply_scheduler.sh uninstall  remove it
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.morrow.apply-scheduler"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/morrow"
OUT_LOG="$LOG_DIR/launchd-apply-scheduler.out"
ERR_LOG="$LOG_DIR/launchd-apply-scheduler.err"
WRAPPER_DIR="$HOME/Library/Application Support/morrow"
RUNNER="$WRAPPER_DIR/apply_scheduler.sh"

if [ "${1:-}" = "uninstall" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $LABEL. A scheduler started by hand keeps running; stop it with scripts/apply_scheduler.sh stop."
  exit 0
fi

# launchd may not read Desktop/Documents/Downloads directly; a script in ~/Library may,
# and once zsh is running it inherits whatever folder access the user granted it.
mkdir -p "$WRAPPER_DIR" "$LOG_DIR"
cat > "$RUNNER" <<WRAPPER
#!/bin/zsh
cd "$PROJECT_DIR" || exit 127
exec "$PROJECT_DIR/scripts/apply_scheduler.sh" loop
WRAPPER
chmod +x "$RUNNER"

: > "$ERR_LOG"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$RUNNER</string></array>
  <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>300</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
  <key>StandardOutPath</key><string>$OUT_LOG</string>
  <key>StandardErrorPath</key><string>$ERR_LOG</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed $PLIST"

sleep 6
if grep -qE "Operation not permitted|can't open input file|permission denied" "$ERR_LOG" 2>/dev/null; then
  echo "BLOCKED: macOS would not let the launchd job read $PROJECT_DIR (see $ERR_LOG)." >&2
  echo "Until that is fixed the job restarts every 5 minutes and does nothing. Either:" >&2
  echo "  - System Settings > Privacy & Security > Full Disk Access: add /bin/zsh and" >&2
  echo "    $(readlink -f "$PROJECT_DIR/venv/bin/python" 2>/dev/null || echo "$PROJECT_DIR/venv/bin/python")," >&2
  echo "  - or move the checkout out of Desktop/Documents/Downloads (for example ~/apply) and re-run this script." >&2
  echo "Meanwhile start the loop from a terminal: nohup scripts/apply_scheduler.sh > /dev/null 2>&1 &" >&2
  exit 1
fi
echo "launchd log: $ERR_LOG"
echo "Status:      scripts/apply_scheduler.sh status"
echo "Uninstall:   scripts/install_apply_scheduler.sh uninstall"
