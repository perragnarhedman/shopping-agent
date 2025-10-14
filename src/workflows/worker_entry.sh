#!/usr/bin/env bash
set -euo pipefail

# Start X virtual framebuffer for a desktop at 1440x900x24 and prep Xauthority
export DISPLAY=:99
# Clear any stale X lock/socket from previous runs
rm -f /tmp/.X99-lock 2>/dev/null || true
rm -f /tmp/.X11-unix/X99 2>/dev/null || true
Xvfb :99 -screen 0 1440x900x24 -ac +extension RANDR &
# Wait for Xvfb UNIX socket to be ready (:99)
python - <<'PY'
import os, socket, time
sock_path = "/tmp/.X11-unix/X99"
for _ in range(120):  # up to ~30s
    if os.path.exists(sock_path):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.25)
            s.connect(sock_path)
            s.close()
            break
        except Exception:
            pass
    time.sleep(0.25)
PY
touch /root/.Xauthority || true

# Start x11vnc bound to the Xvfb display (no auth needed since Xvfb started with -ac)
x11vnc -display :99 -nopw -forever -shared -rfbport 5900 -listen 0.0.0.0 -wait 5 -o /tmp/x11vnc.log &

# Wait for VNC port to be ready to avoid noVNC race
python - <<'PY'
import socket, time
s = socket.socket()
for _ in range(240):  # up to ~60s
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
for _ in range(240):  # up to ~60s
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


