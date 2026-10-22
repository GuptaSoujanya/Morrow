#!/bin/zsh
# One scheduled LinkedIn run. launchd calls this every 30 minutes and
# `linkedin_bot --if-due` decides whether today's post is actually due.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/logs
# launchd starts jobs with only /usr/bin:/bin:/usr/sbin:/sbin; add where claude,
# tectonic and npx usually live so the scheduled run finds what a manual run does.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
PYTHON="venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"
exec "$PYTHON" -m linkedin_bot --if-due >> data/logs/linkedin.log 2>&1
