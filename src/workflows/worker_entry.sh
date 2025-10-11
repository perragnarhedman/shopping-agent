#!/usr/bin/env bash
set -euo pipefail

# Start X virtual framebuffer for a desktop at 1440x900x24
export DISPLAY=:99
Xvfb :99 -screen 0 1440x900x24 -ac +extension RANDR &

# Start x11vnc bound to the Xvfb display
x11vnc -display :99 -nopw -forever -shared -rfbport 5900 -quiet &

# Start websockify/noVNC to serve VNC in browser on :6080
NOVNC_DIR=/usr/share/novnc
if [ -d "$NOVNC_DIR" ]; then
  websockify --web "$NOVNC_DIR" 6080 localhost:5900 &
fi

# Run the Temporal worker
exec python -m src.workflows.worker


