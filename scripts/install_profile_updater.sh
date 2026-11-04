#!/bin/zsh
# Installs a macOS LaunchAgent that runs scripts/run_profile_update.sh at each daily slot
# (09:00, 13:30, 18:30), every 15 minutes as a catch-up, and at login/wake. The run itself
# only acts when a slot is due and not yet done, so missed slots catch up once the laptop
# is awake. The job runs in the Aqua session so the Naukri browser window can open.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.naukri-bot.profile-update"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
# launchd opens these itself before the job starts; under Desktop it cannot, and the
# job dies with exit 78 and no log at all, so they live where launchd may write.
LOG_DIR="$HOME/Library/Logs/morrow"
OUT_LOG="$LOG_DIR/launchd-profile-update.out"
ERR_LOG="$LOG_DIR/launchd-profile-update.err"
RUNNER="$PROJECT_DIR/scripts/run_profile_update.sh"

protected_folder=false
case "$PROJECT_DIR" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*) protected_folder=true ;;
esac

if [ "$protected_folder" = true ]; then
  # launchd may not read Desktop/Documents/Downloads, but a script in ~/Library may, and
  # once /bin/zsh is running it inherits the user's own folder access. The wrapper only
  # cd's into the checkout and execs the real runner, so there is nothing to keep in sync.
  WRAPPER_DIR="$HOME/Library/Application Support/morrow"
  mkdir -p "$WRAPPER_DIR"
  RUNNER="$WRAPPER_DIR/run_profile_update.sh"
  cat > "$RUNNER" <<WRAPPER
#!/bin/zsh
cd "$PROJECT_DIR" || exit 127
exec "$PROJECT_DIR/scripts/run_profile_update.sh" "\$@"
WRAPPER
  chmod +x "$RUNNER"
  echo "Note: $PROJECT_DIR is under Desktop/Documents/Downloads; launching through $RUNNER." >&2
fi

mkdir -p "$PROJECT_DIR/user/logs" "$LOG_DIR"
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
  <key>StartInterval</key><integer>900</integer>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
  </array>
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

# RunAtLoad has just fired once; a permission problem shows up in the error log within seconds.
sleep 5
if grep -qE "Operation not permitted|can't open input file|permission denied" "$ERR_LOG" 2>/dev/null; then
  echo "BLOCKED: macOS would not let the background job read $PROJECT_DIR." >&2
  echo "Grant /bin/zsh and the Python that venv/bin/python points at access to this folder under" >&2
  echo "System Settings > Privacy & Security > Files and Folders, or move the checkout (for" >&2
  echo "example ~/naukri/apply) and re-run this script." >&2
  exit 1
fi
echo "launchd log: $ERR_LOG"
echo "Status:    ./scripts/profile_update_status.sh"
echo "Uninstall: launchctl bootout gui/\$(id -u)/$LABEL && rm $PLIST"
