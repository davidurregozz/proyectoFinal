#!/bin/sh
# Runs the Tkinter dashboard on a virtual X display and serves it via noVNC.
set -e

Xvfb "$DISPLAY" -screen 0 "$SCREEN_RESOLUTION" -nolisten tcp &

# Wait for the X socket before starting clients.
display_number="${DISPLAY#:}"
for _ in $(seq 1 50); do
    [ -S "/tmp/.X11-unix/X${display_number}" ] && break
    sleep 0.1
done

openbox &

# With VNC_PASSWORD set, noVNC asks for it; needed when port 6080 is open to the network.
# VNC only uses the first 8 characters.
if [ -n "$VNC_PASSWORD" ]; then
    mkdir -p "$HOME/.vnc"
    x11vnc -storepasswd "$VNC_PASSWORD" "$HOME/.vnc/passwd" >/dev/null 2>&1
    vnc_auth="-rfbauth $HOME/.vnc/passwd"
else
    vnc_auth="-nopw"
fi
# shellcheck disable=SC2086  # vnc_auth holds two words on purpose
x11vnc -display "$DISPLAY" -forever -shared $vnc_auth -localhost -rfbport 5900 -quiet &
websockify --web /usr/share/novnc "$NOVNC_PORT" localhost:5900 &

# When the dashboard window is closed the container stops and compose restarts it.
exec python -m frontend.run
