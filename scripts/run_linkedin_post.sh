#!/bin/zsh
# One scheduled LinkedIn run. launchd calls this every 30 minutes and
# `linkedin_bot --if-due` decides whether today's post is actually due.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/logs
PYTHON="venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"
exec "$PYTHON" -m linkedin_bot --if-due >> data/logs/linkedin.log 2>&1
