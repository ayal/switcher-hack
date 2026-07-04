#!/usr/bin/env bash
# Cycle the Switcher Breeze AC: every 30 minutes, run 5 min ON then 25 min OFF.
# ON = 26°C, low fan, cool mode. Control goes via the cloud relay (cloud_control.py),
# since this unit's local LAN control is dead. Starts immediately.
#
# Single-instance: on startup this kills any previous ac_cycle.sh, so you can never
# stack overlapping loops. Sleeps are interruptible, so `kill` stops it (and turns
# the AC off) within a second instead of waiting out the current sleep.
#
# Usage:  ./ac_cycle.sh
# Stop:   kill "$(cat /tmp/ac_cycle.pid)"   (turns AC OFF on exit), or Ctrl-C.

set -euo pipefail

cd "$(dirname "$0")"

PY=".venv/bin/python"
export PYTHONPATH=src

PIDFILE="/tmp/ac_cycle.pid"
SELF=$$

ON_SECONDS=300     # 5 minutes on
OFF_SECONDS=1500   # 25 minutes off  (300 + 1500 = 1800s = 30 min cycle)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# --- Single-instance guard: kill any previously running loop before we start. ---
kill_previous() {
  # Kill by recorded PID first (graceful, so its trap turns the AC off), then force.
  if [ -f "$PIDFILE" ]; then
    local old; old="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [ -n "$old" ] && [ "$old" != "$SELF" ] && kill -0 "$old" 2>/dev/null; then
      log "Killing previous instance (PID $old)."
      pkill -P "$old" 2>/dev/null || true   # its child sleep, so it wakes immediately
      kill "$old" 2>/dev/null || true
      for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$old" 2>/dev/null || break; sleep 0.5; done
      kill -9 "$old" 2>/dev/null || true
    fi
  fi
  # Catch any strays not in the PID file (excluding ourselves).
  for p in $(pgrep -f '[a]c_cycle.sh' || true); do
    [ "$p" = "$SELF" ] && continue
    kill -9 "$p" 2>/dev/null || true
  done
}

kill_previous
echo "$SELF" > "$PIDFILE"

# Interruptible sleep: run in background and `wait`, so a trapped signal fires at once.
SLEEP_PID=""
nap() {
  sleep "$1" &
  SLEEP_PID=$!
  wait "$SLEEP_PID"
}

# Always try to leave the AC off when the script stops.
cleanup() {
  log "Stopping — turning AC OFF."
  [ -n "$SLEEP_PID" ] && kill "$SLEEP_PID" 2>/dev/null || true
  "$PY" cloud_control.py off || true
  [ "$(cat "$PIDFILE" 2>/dev/null || true)" = "$SELF" ] && rm -f "$PIDFILE"
  exit 0
}
trap cleanup INT TERM

cycle=1
while true; do
  log "Cycle #$cycle: turning AC ON (26°C, low fan, cool) for 5 min."
  "$PY" cloud_control.py on --temp 26 --fan low --mode cool
  nap "$ON_SECONDS"

  log "Cycle #$cycle: turning AC OFF for 25 min."
  "$PY" cloud_control.py off
  nap "$OFF_SECONDS"

  cycle=$((cycle + 1))
done
