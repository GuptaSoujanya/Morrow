#!/bin/zsh
# Health check for the scheduled profile updater: agent loaded?, today's slots, last log lines.
cd "$(dirname "$0")/.."
LABEL="com.naukri-bot.profile-update"
STATE="${PROFILE_UPDATE_STATE_PATH:-user/logs/profile_update.json}"
PYTHON="venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

echo "== Schedule"
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  launchctl print "gui/$(id -u)/$LABEL" \
    | grep -E "^[[:space:]]+(state|runs|last exit code) =" | sed 's/^[[:space:]]*/  /'
  ERR_LOG="$HOME/Library/Logs/morrow/launchd-profile-update.err"
  [ -f "$ERR_LOG" ] || ERR_LOG="user/logs/launchd-profile-update.err"
  if grep -qiE "can't open input file|Operation not permitted|permission denied" "$ERR_LOG" 2>/dev/null; then
    echo "  BLOCKED: macOS would not let the background job read $(pwd)"
    echo "  (see $ERR_LOG). Grant /bin/zsh and python access to the folder under"
    echo "  System Settings > Privacy & Security > Files and Folders, or move the checkout out of"
    echo "  Desktop/Documents/Downloads and rerun ./scripts/install_profile_updater.sh."
  fi
  if launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -q "last exit code = 78"; then
    echo "  launchd could not start the job at all (exit 78): its log files or the script are"
    echo "  unreadable to it. Rerun ./scripts/install_profile_updater.sh."
  fi
else
  echo "  NOT INSTALLED - run ./scripts/install_profile_updater.sh"
fi

echo "== Today's slots ($STATE)"
if [ -f "$STATE" ]; then
  "$PYTHON" - "$STATE" "$(date +%F)" <<'PY'
import json
import sys

state = json.load(open(sys.argv[1]))
today = [(key, entry) for key, entry in sorted(state.items()) if key.startswith(sys.argv[2])]
for key, entry in today:
    print("  %s  done=%s  attempts=%s  last=%s" % (
        key, entry.get("done", False), entry.get("attempts", 0), entry.get("last", "-")))
if not today:
    print("  none yet")
PY
else
  echo "  none yet"
fi

echo "== Last 8 log lines (user/logs/profile_update.log)"
tail -8 user/logs/profile_update.log 2>/dev/null | cut -c1-150 | sed 's/^/  /' || true
