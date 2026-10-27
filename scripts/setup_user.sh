#!/bin/zsh
# Give this computer its user repo: the private GitHub repo that holds one
# person's inputs, resume, ledger, reports, memory and research, cloned to
# user/ (or wherever MORROW_USER_DIR points). Also clones the shared
# Morrow-database into database/ if it is not there yet.
#
#   scripts/setup_user.sh                   # create <you>/Morrow-user-<you> from the template
#   scripts/setup_user.sh owner/repo        # use a user repo that already exists
#
# Needs the GitHub CLI signed in (gh auth login). The repo is created private
# from the public template GuptaSoujanya/Morrow-user, so its layout and
# .gitignore are right from the first commit.
set -euo pipefail
cd "$(dirname "$0")/.."

template="GuptaSoujanya/Morrow-user"
database="GuptaSoujanya/Morrow-database"
user_dir="${MORROW_USER_DIR:-user}"
database_dir="${MORROW_DATABASE_DIR:-database}"

if ! command -v gh >/dev/null; then
  echo "Install the GitHub CLI (brew install gh) and run gh auth login first." >&2
  exit 1
fi
login=$(gh api user --jq .login)
repo="${1:-$login/Morrow-user-$login}"

if [ -d "$user_dir/.git" ]; then
  echo "$user_dir is already a clone of $(git -C "$user_dir" remote get-url origin)"
elif gh repo view "$repo" >/dev/null 2>&1; then
  gh repo clone "$repo" "$user_dir"
else
  gh repo create "$repo" --private --template "$template" --clone
  mv "$(basename "$repo")" "$user_dir"
fi

if [ ! -d "$database_dir/.git" ]; then
  gh repo clone "$database" "$database_dir"
fi

[ -f .env ] || cp .env.example .env
for pair in "MORROW_USER_DIR=$user_dir" "MORROW_DATABASE_DIR=$database_dir"; do
  key="${pair%%=*}"
  if grep -q "^$key=" .env; then
    sed -i '' "s#^$key=.*#$pair#" .env
  else
    printf '\n%s\n' "$pair" >> .env
  fi
done

echo
echo "Your files live in $user_dir ($repo). Next:"
echo "  python3 -m pipeline onboard     your resume and facts -> $user_dir/inputs/{profile,persona}.yaml,"
echo "                                  answers.txt and $user_dir/resume/base.tex"
echo "or enter them from the dashboard; the bots fill the rest. scripts/sync_data.sh pushes it."
