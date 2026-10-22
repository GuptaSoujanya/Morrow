#!/bin/zsh
# One scheduled profile update. launchd runs this every 15 minutes and
# `update_profile --if-due` decides whether a daily slot is actually due.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/logs
# launchd starts jobs with only /usr/bin:/bin:/usr/sbin:/sbin; add where claude,
# tectonic and npx usually live so the scheduled run finds what a manual run does.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
# Spread the start over 0-10 minutes so the three daily updates do not land on
# the exact slot minute. A value already in the environment wins.
export MAX_START_DELAY_SECONDS="${MAX_START_DELAY_SECONDS:-600}"
PYTHON="venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"
exec "$PYTHON" -m naukri_bot.update_profile --if-due >> data/logs/profile_update.log 2>&1
