#!/bin/zsh
# Installs a macOS LaunchAgent that runs scripts/run_profile_update.sh every 15 minutes
# and at login/wake. The run itself only acts when a daily slot (09:00, 13:30, 18:30)
# is due and not yet done, so missed slots catch up once the laptop is awake.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.naukri-bot.profile-update"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

case "$PROJECT_DIR" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*)
    echo "WARNING: $PROJECT_DIR is under Desktop, Documents or Downloads." >&2
    echo "macOS privacy rules block background launchd jobs from reading those folders," >&2
    echo "so the agent fails with 'Operation not permitted' in data/logs/launchd-profile-update.err." >&2
    echo "Either move the checkout (for example ~/naukri/apply) and re-run this script, or" >&2
    echo "grant the Python binary that venv/bin/python points at access to this folder under" >&2
    echo "System Settings > Privacy & Security > Files and Folders." >&2
    ;;
esac

mkdir -p "$PROJECT_DIR/data/logs"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PROJECT_DIR/scripts/run_profile_update.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>900</integer>
  <key>StandardOutPath</key><string>$PROJECT_DIR/data/logs/launchd-profile-update.out</string>
  <key>StandardErrorPath</key><string>$PROJECT_DIR/data/logs/launchd-profile-update.err</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed $PLIST"
echo "Status:    ./scripts/profile_update_status.sh"
echo "Uninstall: launchctl bootout gui/\$(id -u)/$LABEL && rm $PLIST"
