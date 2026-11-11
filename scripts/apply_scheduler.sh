#!/bin/zsh
# Keeps applying until the goals are met, then stops.
#
#   scripts/apply_scheduler.sh            run the loop in the foreground
#   nohup scripts/apply_scheduler.sh &    run it in the background from a terminal
#   scripts/apply_scheduler.sh status     goals, Naukri slots, what the loop is doing
#   scripts/apply_scheduler.sh stop       stop the loop and the round it is running
#   scripts/apply_scheduler.sh once       one check right now, no loop
#
# Every check: a Naukri round when Naukri's allowance has APPLY_MIN_SLOTS free again
# (python -m naukri_bot.quota) and Naukri's last "daily quota exceeded" refusal is older
# than APPLY_QUOTA_COOLDOWN_H hours (its allowance has refused ~30 applies a day lately,
# so the ledger's 50-slot count alone starts rounds too early), the boards and startups
# once a day after APPLY_BOARDS_AFTER.
# Goals, counted from APPLY_GOAL_SINCE: APPLY_GOAL_NAUKRI (Naukri + company sites reached
# from Naukri), APPLY_GOAL_BOARDS (Hirist/Instahyre/Cutshort/Wellfound), APPLY_GOAL_STARTUPS.
# Settings come from .env; the environment overrides it (TARGET_APPLICATIONS, PLATFORM_LIMIT ...).
set -u
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
# A local Anthropic proxy in the shell (headroom) answers the claude CLI with 421s.
unset ANTHROPIC_BASE_URL HEADROOM_BACKEND CLAUDE_PROXY_PORT
# Naukri answers headless Chrome with an access-denied page.
export BACKGROUND=false HEADLESS=false
export LLM_TIMEOUT_S="${LLM_TIMEOUT_S:-180}"
export TARGET_APPLICATIONS="${TARGET_APPLICATIONS:-100}"
export PLATFORM_LIMIT="${PLATFORM_LIMIT:-75}"

GOAL_NAUKRI=${APPLY_GOAL_NAUKRI:-100}
GOAL_BOARDS=${APPLY_GOAL_BOARDS:-300}
GOAL_STARTUPS=${APPLY_GOAL_STARTUPS:-3}
GOAL_SINCE=${APPLY_GOAL_SINCE:-2026-11-05}
MIN_SLOTS=${APPLY_MIN_SLOTS:-10}
CHECK_EVERY=${APPLY_CHECK_EVERY_S:-1800}
BOARDS_AFTER=${APPLY_BOARDS_AFTER:-10:00}
STARTUP_LIMIT=${APPLY_STARTUP_LIMIT:-10}
QUOTA_COOLDOWN_H=${APPLY_QUOTA_COOLDOWN_H:-12}

PY=venv/bin/python
[ -x "$PY" ] || PY=python3
RUNS=.runtime/runs
LOG=$RUNS/scheduler.log
LOCK=.runtime/apply-scheduler.pid
mkdir -p "$RUNS" .runtime

log() { print -r -- "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

progress() {
  "$PY" - "$GOAL_SINCE" <<'PYEOF'
import sqlite3, sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from common import config
settings = config.load_settings()
zone = ZoneInfo(settings.run_timezone or "Asia/Kolkata")
since = datetime.fromisoformat(sys.argv[1]).replace(tzinfo=zone).astimezone(ZoneInfo("UTC")).isoformat()
con = sqlite3.connect(settings.db_path)
naukri = con.execute("""SELECT COUNT(*) FROM applications WHERE at >= ? AND url LIKE '%naukri.com%'
                        AND status IN ('applied', 'applied_external')""", (since,)).fetchone()[0]
board = con.execute("SELECT COUNT(*) FROM applications WHERE at >= ? AND status = 'applied_platform'", (since,)).fetchone()[0]
con.close()
startups = 0
try:
    agent = sqlite3.connect("%s/application-agent.sqlite" % settings.data_dir)
    startups = agent.execute("""SELECT COUNT(*) FROM attempts WHERE state = 'confirmed' AND updated_at >= ?
                                AND (job_id LIKE 'yc:%' OR job_id LIKE 'hn:%')""", (since[:19],)).fetchone()[0]
    agent.close()
except sqlite3.Error:
    pass
print(naukri, board, startups)
PYEOF
}

quota_json() { "$PY" -m naukri_bot.quota --json --slots "$MIN_SLOTS" 2>/dev/null; }

refusal_cooldown_ends() {
  "$PY" - "$QUOTA_COOLDOWN_H" <<'PYEOF'
import sqlite3, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from common import config
settings = config.load_settings()
con = sqlite3.connect(settings.db_path)
last = con.execute("SELECT MAX(at) FROM applications WHERE status = 'quota_expired'").fetchone()[0]
con.close()
if last:
    ends = datetime.fromisoformat(last) + timedelta(hours=float(sys.argv[1]))
    if ends > datetime.now(timezone.utc):
        print(ends.astimezone(ZoneInfo(settings.run_timezone or "Asia/Kolkata")).strftime("%Y-%m-%d %H:%M %Z"))
PYEOF
}
json_field() { "$PY" -c 'import json,sys; v=json.load(sys.stdin).get(sys.argv[1]); print("" if v is None else v)' "$1"; }

alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }

kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$child"; done
  kill -TERM "$pid" 2>/dev/null
}

run_round() {
  local name=$1; shift
  local stamp; stamp=$(date '+%m%d-%H%M')
  local out=$RUNS/sched-$stamp-$name.log
  log "round $name starts: $* (log $out)"
  "$@" > "$out" 2>&1
  local code=$?
  local tally
  tally=$(grep -E "applied \(verified\)|applied, company site|applied +:|funnel" "$out" | tail -n 4 | tr -s ' ' | tr '\n' ';')
  log "round $name ended (exit $code) ${tally:-no summary line}"
}

cycle() {
  local counts naukri_done boards_done startups_done
  counts=$(progress) || { log "could not read progress from the ledger"; return 1; }
  read -r naukri_done boards_done startups_done <<< "$counts"
  log "progress since $GOAL_SINCE: naukri $naukri_done/$GOAL_NAUKRI, boards $boards_done/$GOAL_BOARDS, startups $startups_done/$GOAL_STARTUPS"
  if [ "$naukri_done" -ge "$GOAL_NAUKRI" ] && [ "$boards_done" -ge "$GOAL_BOARDS" ] && [ "$startups_done" -ge "$GOAL_STARTUPS" ]; then
    log "every goal is met; nothing to do"
    return 2
  fi

  local today; today=$(date '+%Y-%m-%d')
  local boards_stamp=.runtime/boards-$today.done
  if [ ! -e "$boards_stamp" ] && [[ "$(date '+%H:%M')" > "$BOARDS_AFTER" || "$(date '+%H:%M')" == "$BOARDS_AFTER" ]]; then
    if [ "$boards_done" -lt "$GOAL_BOARDS" ]; then
      run_round boards "$PY" -m pipeline run --only apply --skip apply:naukri --skip apply:startups --redo --ignore-window
    fi
    if [ "$startups_done" -lt "$GOAL_STARTUPS" ]; then
      run_round startups "$PY" -m startup_bot --limit "$STARTUP_LIMIT" --ignore-window --no-replies
    fi
    touch "$boards_stamp"
  fi

  if [ "$naukri_done" -lt "$GOAL_NAUKRI" ]; then
    local q remaining frees_local
    q=$(quota_json) || q=""
    remaining=$(print -r -- "$q" | json_field remaining 2>/dev/null)
    frees_local=$(print -r -- "$q" | json_field frees_at_local 2>/dev/null)
    if [ -z "$remaining" ]; then
      log "could not read Naukri's slots; running the Naukri round anyway"
      remaining=$MIN_SLOTS
    fi
    local cooldown_ends; cooldown_ends=$(refusal_cooldown_ends 2>/dev/null)
    if [ -n "$cooldown_ends" ]; then
      log "waiting for Naukri: it refused applies (daily quota exceeded); next Naukri round after $cooldown_ends"
    elif [ "$remaining" -ge "$MIN_SLOTS" ]; then
      run_round naukri "$PY" -m pipeline run --only apply:naukri --redo --ignore-window
    else
      log "waiting for Naukri: $remaining slot(s) free, $MIN_SLOTS free at ${frees_local:-?}"
    fi
  fi
  return 0
}

status() {
  local pid; pid=$(cat "$LOCK" 2>/dev/null)
  if alive "$pid"; then print "scheduler: running (pid $pid)"; else print "scheduler: not running"; fi
  local counts; counts=$(progress) && print "progress since $GOAL_SINCE (naukri boards startups): $counts  goals: $GOAL_NAUKRI $GOAL_BOARDS $GOAL_STARTUPS"
  "$PY" -m naukri_bot.quota --slots "$MIN_SLOTS"
  [ -f "$LOG" ] && { print "last log lines:"; tail -n 8 "$LOG"; }
  pgrep -fil "python -m (pipeline|startup_bot|naukri_bot|[a-z]+_bot)" 2>/dev/null | sed 's/^/running: /'
}

stop() {
  local pid; pid=$(cat "$LOCK" 2>/dev/null)
  if alive "$pid"; then kill_tree "$pid"; log "stopped by request (pid $pid)"; rm -f "$LOCK"; else print "scheduler: not running"; fi
}

case "${1:-loop}" in
  status) status; exit 0 ;;
  stop) stop; exit 0 ;;
  once) cycle; exit $? ;;
  loop) ;;
  *) print -u2 "usage: $0 [loop|once|status|stop]"; exit 64 ;;
esac

if alive "$(cat "$LOCK" 2>/dev/null)"; then
  log "another scheduler (pid $(cat "$LOCK")) is running; standing by"
  while alive "$(cat "$LOCK" 2>/dev/null)"; do sleep "$CHECK_EVERY"; done
fi
print $$ > "$LOCK"
trap 'rm -f "$LOCK"; exit 0' INT TERM
log "scheduler starts (pid $$): check every ${CHECK_EVERY}s, Naukri rounds at >= $MIN_SLOTS free slots, boards after $BOARDS_AFTER"
while true; do
  cycle
  case $? in
    2) rm -f "$LOCK"; exit 0 ;;
  esac
  sleep "$CHECK_EVERY"
done
