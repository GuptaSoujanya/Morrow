#!/bin/zsh
# Serve the PrepForge study site (COURSE_DIR in .env) at http://localhost:8000.
# The daily report names one module of its plan a day. Usage: serve_course.sh [port]
set -euo pipefail
cd "$(dirname "$0")/.."

COURSE="$(grep -E '^COURSE_DIR=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)"
COURSE="${COURSE:-../system degine/course}"
[[ "$COURSE" = /* ]] || COURSE="$PWD/$COURSE"
if [ ! -f "$COURSE/serve.py" ]; then
  echo "No course found at $COURSE (set COURSE_DIR in .env)."
  exit 1
fi
cd "$COURSE"
exec python3 serve.py "${1:-8000}"
