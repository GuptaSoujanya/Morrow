#!/bin/zsh
# Commit and push what the bots wrote into the user's private repo (user/, or
# MORROW_USER_DIR). Everything personal lives there: inputs, resume, ledger,
# reports, the pipeline's memory and the day's research. Morrow itself is
# public and never holds any of it.
#
# Browser sessions and SQLite scratch files are never committed (see the user
# repo's .gitignore). Safe to run from launchd or by hand at any time.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

user_dir=""
if [ -f .env ]; then
  user_dir=$(grep -E '^MORROW_USER_DIR=' .env | tail -1 | cut -d= -f2- | tr -d '"' || true)
fi
repo="${MORROW_USER_DIR:-${user_dir:-user}}"
case "$repo" in
  /*) ;;
  *) repo="$PWD/$repo" ;;
esac

if [ ! -d "$repo/.git" ]; then
  echo "$repo is not a git clone; run scripts/setup_user.sh first." >&2
  exit 1
fi

stamp=$(date "+%Y-%m-%d %H:%M")

# Fold the write-ahead log into the database so the committed .db is complete.
if [ -f "$repo/db/naukri_bot.db" ] && command -v sqlite3 >/dev/null; then
  sqlite3 "$repo/db/naukri_bot.db" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null
fi

git -C "$repo" add -A
if git -C "$repo" diff --cached --quiet; then
  echo "user: nothing new"
else
  git -C "$repo" commit -q -m "Record the bots' work as of $stamp"
  echo "user: committed $(git -C "$repo" log -1 --format=%h)"
fi
git -C "$repo" pull -q --rebase origin main
git -C "$repo" push -q origin main
