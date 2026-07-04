# Switcher AC on macOS — unified controller, modes, menu bar & daemon

Everything now runs as **one backend** (`server.py`) that serves the HTTP API
*and* runs the control loop in-process. The web dashboard, the macOS menu-bar
app, and any future mobile app are all thin clients of that one API, so they
always show the same state.

```
                 ┌──────────────────────────────────────┐
                 │  server.py  (FastAPI, :3001)          │
   webapp  ─────▶│    • HTTP API (/api/*, /control/*)     │
   menubar ─────▶│    • control loop (in-process task)   │──▶ Switcher cloud ──▶ AC
   mobile? ─────▶│    • single source of truth: data.json│
                 └──────────────────────────────────────┘
```

## Modes

One field, `mode`, in `webapp/static/data.json` drives everything. Switch it
from the dashboard, the menu bar, or the API.

| Mode         | Behaviour                                                                 | Config used                              |
|--------------|---------------------------------------------------------------------------|------------------------------------------|
| `manual`     | Loop only *reads* state (temp/on-off) for the UI & history. You drive it. | —                                        |
| `thermostat` | Smart temp-monitoring loop (the original `auto_cloud` logic).             | `too_hot_temp`, `too_cold_temp`, `cool_temp`, `poll_interval` |
| `cycle`      | Dumb timer: X min ON @ `cool_temp`, then Y min OFF, forever.              | `cycle_on_min`, `cycle_off_min`, `cool_temp` |

`cycle` mode replaces the old standalone `ac_cycle.sh`. Its phase is derived
from a wall-clock **anchor**, so it's restart-safe — relaunching resumes the
same rhythm instead of restarting the ON phase. Switching *into* cycle mode
re-anchors to "now" (starts an ON phase immediately). Commands are only sent on
a real transition (the IR blaster beeps on every command, so we never re-assert
a state the AC already holds).

## HTTP API

```
GET  /api/state          → full state incl. mode, is_on, temperature, cycle_phase, …
POST /api/config         ← partial patch, validated + clamped. Any subset of:
                           mode, too_hot_temp, too_cold_temp, cool_temp,
                           poll_interval, cycle_on_min, cycle_off_min
GET  /control/on?temp=&fan=&mode=cool ,  GET /control/off
GET  /temp               → fresh room temp straight from the cloud
GET  /history            → CSV history for the chart
GET  /                   → the dashboard
```

Examples:
```bash
curl localhost:3001/api/state
curl -X POST localhost:3001/api/config -d '{"mode":"cycle","cycle_on_min":5,"cycle_off_min":25,"cool_temp":26}'
curl -X POST localhost:3001/api/config -d '{"mode":"thermostat"}'
```

A future mobile app just calls these same endpoints (the server already binds
`0.0.0.0:3001`, so it's reachable on the LAN).

## Menu-bar app

`menubar.py` (rumps) shows the room temp + a ❄ when the AC is on, with a
dropdown to switch mode, flip on/off, and open the dashboard. It reads/writes
the same server, so it stays in sync with the webapp.

```bash
.venv/bin/pip install -r requirements-mac.txt   # fastapi/uvicorn/requests/rumps
.venv/bin/python menubar.py                      # run once, foreground
```

## Run as a daemon (autostart + caffeinated)

Two LaunchAgents: the server+loop wrapped in `caffeinate -is` (so the Mac won't
idle-sleep while it's controlling the AC), and the menu-bar UI. Both autostart
at login and restart on crash.

```bash
bash daemon/install.sh     # stops old scripts, installs & loads both agents
bash daemon/uninstall.sh   # stops & removes them (leaves AC as-is)
```

Logs land in `logs/` (`server.out.log`, `server.err.log`, `menubar.*`).

> **Cutover note:** `install.sh` first stops any old free-running
> `auto_cloud.py` / `ac_cycle.sh` / `server.py`, so you don't end up with two
> controllers fighting over the AC.
