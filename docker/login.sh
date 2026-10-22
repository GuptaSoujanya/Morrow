#!/bin/sh
# Sign in once inside a site's container, in the Chrome profile its bot uses:
#
#   docker compose run --rm --service-ports hirist docker/login.sh
#
# then open the site's screen (http://localhost:6083/vnc.html for hirist, the ports are in
# docker-compose.yml), sign in, and close the window. Each site's service opens its own
# login page (LOGIN_URL); pass URLs to open others instead.
# In the all-in-one `bots` service name the site: docker/login.sh naukri [url ...]
set -eu
site="${SITE:-}"
if [ $# -gt 0 ] && [ "${1#http}" = "$1" ]; then
  site="$1"
  shift
fi
[ -n "$site" ] || { echo "usage: docker/login.sh <naukri|linkedin|board> [url ...]" >&2; exit 2; }
case "$site" in
  naukri) root="$BROWSER_PROFILE_DIR" ;;
  linkedin) root="$LINKEDIN_BROWSER_PROFILE_DIR" ;;
  *) if [ "$site" = "${SITE:-}" ]; then root="$BROWSER_PROFILE_DIR"; else root="$(dirname "$BROWSER_PROFILE_DIR")/lanes/$site"; fi ;;
esac
[ $# -eq 0 ] && [ -n "${LOGIN_URL:-}" ] && set -- "$LOGIN_URL"
profile="$root/chrome"
mkdir -p "$profile"
echo "Chromium for $site on $profile. Sign in on its screen, then close the window."
exec chromium --user-data-dir="$profile" --password-store=basic --no-first-run \
  --no-default-browser-check --no-sandbox --disable-dev-shm-usage \
  --window-position=0,0 --window-size="${CHROME_WINDOW_SIZE:-1600,1000}" "$@"
