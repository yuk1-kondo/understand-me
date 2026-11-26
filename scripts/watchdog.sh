#!/bin/bash
# Understand Me watchdog: restart backend / Discord receiver only if DOWN.
# Never touches healthy processes. Logs to /tmp/um-watchdog.log.
ROOT="$HOME/understand-me"
LOG=/tmp/um-watchdog.log
STAMP_DIR=/tmp/um-watchdog-stamps
mkdir -p "$STAMP_DIR"

now=$(date +%s)
ts() { date '+%Y-%m-%d %H:%M:%S'; }

cooldown_ok() {
  local f="$STAMP_DIR/$1"
  if [ -f "$f" ]; then
    local last
    last=$(cat "$f")
    if [ $((now - last)) -lt 180 ]; then return 1; fi
  fi
  echo "$now" > "$f"
  return 0
}

# --- backend (uvicorn on :8000) ---
if ! curl -s -m 3 http://localhost:8000/captions > /dev/null 2>&1; then
  if cooldown_ok backend; then
    echo "[$(ts)] backend DOWN -> restarting" >> "$LOG"
    pkill -f "uvicorn main:app" 2>/dev/null
    sleep 2
    cd "$ROOT/backend/core" && set -a && . ../../.env && set +a && \
      nohup ./.venv/bin/uvicorn main:app --port 8000 > /tmp/backend.log 2>&1 &
    echo "[$(ts)] backend restart issued" >> "$LOG"
  fi
fi

# --- discord receiver ---
if ! pgrep -f "receiver.py" > /dev/null 2>&1; then
  if cooldown_ok receiver; then
    echo "[$(ts)] receiver DOWN -> restarting" >> "$LOG"
    cd "$ROOT/backend/discord_bot" && set -a && . ../../.env && set +a && \
      STT_PROVIDER=whisper UM_DEBUG_DUMP=1 nohup .venv/bin/python receiver.py > /tmp/receiver.log 2>&1 &
    echo "[$(ts)] receiver restart issued" >> "$LOG"
  fi
fi
