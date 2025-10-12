#!/usr/bin/env bash
set -euo pipefail

# Start X virtual framebuffer for a desktop at 1440x900x24 and prep Xauthority
export DISPLAY=:99
Xvfb :99 -screen 0 1440x900x24 -ac +extension RANDR &
sleep 0.5
touch /root/.Xauthority || true

# Start x11vnc bound to the Xvfb display (no auth needed since Xvfb started with -ac)
x11vnc -display :99 -nopw -forever -shared -rfbport 5900 -listen 0.0.0.0 -o /tmp/x11vnc.log &

# Wait for VNC port to be ready to avoid noVNC race
python - <<'PY'
import socket, time
s = socket.socket()
for _ in range(40):
    try:
        s.connect(("127.0.0.1", 5900))
        s.close()
        break
    except Exception:
        time.sleep(0.25)
PY

# Start websockify/noVNC to serve VNC in browser on :6080
NOVNC_DIR=/usr/share/novnc
if [ -d "$NOVNC_DIR" ]; then
  websockify --verbose --web "$NOVNC_DIR" --log-file /tmp/websockify.log 6080 localhost:5900 &
  # Wait for 6080 to be ready
  python - <<'PY'
import socket, time
s = socket.socket()
for _ in range(40):
    try:
        s.connect(("127.0.0.1", 6080))
        s.close()
        break
    except Exception:
        time.sleep(0.25)
PY
fi

# (WebRTC removed) no FFmpeg streaming

# Run the Temporal worker
exec python -m src.workflows.worker


