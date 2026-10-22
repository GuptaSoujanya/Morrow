#!/bin/sh
# Start the virtual screen the bot's Chrome draws on (headless Chrome is flagged far
# more often), a VNC server on it, and noVNC, which shows that screen in a web page on
# port 6080 (docker-compose.yml publishes it on the site's own port, e.g. 6083 for hirist).
# With VNC_PASSWORD set the screen asks for it, and port 5900 also takes a VNC client.
set -e
rm -f /tmp/.X99-lock
Xvfb :99 -screen 0 "${SCREEN_SIZE:-1600x1000}x24" -nolisten tcp >/tmp/xvfb.log 2>&1 &
i=0
while [ ! -e /tmp/.X11-unix/X99 ]; do
  i=$((i + 1))
  [ "$i" -gt 50 ] && { echo "Xvfb did not start:" >&2; cat /tmp/xvfb.log >&2; exit 1; }
  sleep 0.1
done
if [ -n "${VNC_PASSWORD:-}" ]; then
  x11vnc -display :99 -forever -shared -rfbport 5900 -passwd "$VNC_PASSWORD" -quiet >/tmp/x11vnc.log 2>&1 &
else
  x11vnc -display :99 -forever -shared -rfbport 5900 -localhost -nopw -quiet >/tmp/x11vnc.log 2>&1 &
fi
websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/novnc.log 2>&1 &
exec "$@"
