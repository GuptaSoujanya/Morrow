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
PROGRAM="<string>$PROJECT_DIR/scripts/run_profile_update.sh</string>"
ENVIRONMENT=""

protected_folder=false
case "$PROJECT_DIR" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*) protected_folder=true ;;
esac

if [ "$protected_folder" = true ]; then
  # macOS lets a launchd job read Desktop/Documents/Downloads only when the job's own
  # binary has been granted the folder (Privacy & Security > Files and Folders). /bin/zsh
  # never gets that grant, so a shell script under the checkout dies with "can't open
  # input file" (exit 127) and a wrapper in ~/Library that execs it dies the same way.
  # The Python behind venv/bin/python can be granted (macOS asks the first time), so the
  # job runs that binary directly, with the venv on PYTHONPATH because the venv's own
  # python symlink also sits under the protected folder, and with the environment that
  # scripts/run_profile_update.sh would otherwise set.
  PYTHON="$PROJECT_DIR/venv/bin/python"
  [ -x "$PYTHON" ] || PYTHON="$(command -v python3)"
  PY_REAL="$("$PYTHON" -c 'import sys; print(sys._base_executable or sys.executable)')"
  PY_SITE="$("$PYTHON" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
  PROGRAM="<string>$PY_REAL</string><string>-m</string><string>naukri_bot.update_profile</string><string>--if-due</string>"
  ENVIRONMENT="  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PYTHONPATH</key><string>$PY_SITE</string>
    <key>VIRTUAL_ENV</key><string>$PROJECT_DIR/venv</string>
    <key>MAX_START_DELAY_SECONDS</key><string>600</string>
    <key>BACKGROUND</key><string>false</string>
    <key>HEADLESS</key><string>false</string>
  </dict>"
  echo "Note: $PROJECT_DIR is under Desktop/Documents/Downloads; launchd runs $PY_REAL directly." >&2
  echo "      If macOS asks whether Python may access the folder, click Allow once." >&2
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
  <array>$PROGRAM</array>
$ENVIRONMENT
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
if grep -qiE "Operation not permitted|can't open input file|permission denied|PermissionError" "$ERR_LOG" 2>/dev/null; then
  echo "BLOCKED: macOS would not let the background job read $PROJECT_DIR." >&2
  echo "Grant the Python that venv/bin/python points at access to this folder under" >&2
  echo "System Settings > Privacy & Security > Files and Folders, or move the checkout (for" >&2
  echo "example ~/naukri/apply) and re-run this script." >&2
  exit 1
fi
echo "launchd log: $ERR_LOG"
echo "Status:    ./scripts/profile_update_status.sh"
echo "Uninstall: launchctl bootout gui/\$(id -u)/$LABEL && rm $PLIST"
