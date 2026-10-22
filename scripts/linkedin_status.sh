#!/bin/zsh
# Health check for the LinkedIn poster: agent loaded?, today's entry, last log lines.
cd "$(dirname "$0")/.."
LABEL="com.naukri-bot.linkedin-post"
STATE="${LINKEDIN_STATE_PATH:-data/linkedin/state.json}"
PYTHON="venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

echo "== Schedule"
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  launchctl print "gui/$(id -u)/$LABEL" \
    | grep -E "^[[:space:]]+(state|runs|last exit code) =" | sed 's/^[[:space:]]*/  /'
else
  echo "  NOT INSTALLED - run ./scripts/install_linkedin_poster.sh"
fi

echo "== Today ($STATE)"
if [ -f "$STATE" ]; then
  "$PYTHON" - "$STATE" "$(date +%F)" <<'PY'
import json
import sys

state = json.load(open(sys.argv[1]))
entry = state.get("days", {}).get(sys.argv[2])
if entry:
    print("  done=%s  attempts=%s  last=%s" % (
        entry.get("done", False), entry.get("attempts", 0), entry.get("last", "-")))
else:
    print("  nothing yet")
posted = state.get("posted", [])
if posted:
    last = posted[-1]
    print("  last post: %s  %s" % (last.get("date", "-"), last.get("url", "-")))
PY
else
  echo "  nothing yet"
fi

echo "== Last 8 log lines (data/logs/linkedin.log)"
tail -8 data/logs/linkedin.log 2>/dev/null | cut -c1-150 | sed 's/^/  /' || true
