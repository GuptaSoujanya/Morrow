#!/bin/zsh
# Commit and push what the bots wrote into data/ (Morrow-data) and .memory/
# (Morrow-memory). Each push runs that repo's "Bump Morrow" workflow, which
# moves Morrow's submodule pointers on GitHub; afterwards `git pull` here.
#
# Browser sessions and SQLite scratch files are never committed (see each
# submodule's .gitignore). Safe to run from launchd or by hand at any time.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

stamp=$(date "+%Y-%m-%d %H:%M")

# Fold the write-ahead log into the database so the committed .db is complete.
if [ -f data/db/naukri_bot.db ] && command -v sqlite3 >/dev/null; then
  sqlite3 data/db/naukri_bot.db "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null
fi

for repo in data .memory; do
  git -C "$repo" add -A
  if git -C "$repo" diff --cached --quiet; then
    echo "$repo: nothing new"
  else
    git -C "$repo" commit -q -m "Record the bots' $repo as of $stamp"
    echo "$repo: committed $(git -C "$repo" log -1 --format=%h)"
  fi
  git -C "$repo" pull -q --rebase origin main
  git -C "$repo" push -q origin main
done
