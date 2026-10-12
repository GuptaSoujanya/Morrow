#!/bin/zsh
# Sign in to your Google account once inside the bot's own browser profile, so
# "Sign in with Google" on company career sites can reuse that session.
#
# This opens ordinary Chrome (not the automated one, which Google refuses to
# sign in) on the bot's profile folder, with the same keychain flags ChromeDriver
# uses; without them the bot could not read the cookies saved here.
set -euo pipefail
cd "$(dirname "$0")/.."

PROFILE_ROOT="$(grep -E '^BROWSER_PROFILE_DIR=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)"
PROFILE_ROOT="${PROFILE_ROOT:-data/browser/naukri}"
[[ "$PROFILE_ROOT" = /* ]] || PROFILE_ROOT="$PWD/$PROFILE_ROOT"
PROFILE="$PROFILE_ROOT/chrome"

if [ -e "$PROFILE/SingletonLock" ] || [ -L "$PROFILE/SingletonLock" ]; then
  echo "The bot's browser profile is in use (a bot run or another window has it open)."
  echo "Wait for the run to finish or quit that Chrome window, then try again."
  exit 1
fi
mkdir -p "$PROFILE"

echo "Opening Chrome on $PROFILE"
echo "1. Sign in to your Google account in that window."
echo "2. Sign in with Google on any other tab it opened (job sites given as arguments)."
echo "3. Quit that Chrome window with Cmd+Q when you are done; the bot needs the profile free."
open -na "Google Chrome" --args \
  --user-data-dir="$PROFILE" \
  --use-mock-keychain \
  --password-store=basic \
  --no-first-run \
  --no-default-browser-check \
  "https://accounts.google.com/" "$@"
