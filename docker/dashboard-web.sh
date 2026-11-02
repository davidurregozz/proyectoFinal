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
x11vnc -display "$DISPLAY" -forever -shared -nopw -localhost -rfbport 5900 -quiet &
websockify --web /usr/share/novnc "$NOVNC_PORT" localhost:5900 &

# When the dashboard window is closed the container stops and compose restarts it.
exec python -m frontend.run
