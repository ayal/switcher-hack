"""FastAPI server for AC cloud control.

Exposes HTTP endpoints that trigger Switcher cloud commands.
Same endpoints the RPi had, but using cloud control (no LAN needed).

Usage:
    python server.py                    # Start on port 3001
    curl localhost:3001/control/on      # Turn AC on
    curl localhost:3001/control/off     # Turn AC off
    curl "localhost:3001/control/on?temp=22&fan=high"
"""

import json
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi import Request
from pathlib import Path
from typing import Any, Dict, Optional

from cloud_control import cloud_control

app = FastAPI(title="Switcher AC Cloud Control")


@app.middleware("http")
async def add_cache_control_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# --- AC Control (cloud) ---

@app.get("/control/on")
async def turn_on(temp: int = 24, fan: str = "medium", mode: str = "cool"):
    """Turn AC on. Optional: ?temp=22&fan=high&mode=cool"""
    success = await cloud_control("on", temp=temp, fan=fan, mode=mode)
    if success:
        _patch_data({"is_on": True, "ac_temp": temp})
        return {"status": "ok", "action": "on", "temp": temp, "fan": fan, "mode": mode}
    return {"status": "error", "message": "cloud command failed"}


@app.get("/control/off")
async def turn_off():
    """Turn AC off."""
    success = await cloud_control("off")
    if success:
        _patch_data({"is_on": False})
        return {"status": "ok", "action": "off"}
    return {"status": "error", "message": "cloud command failed"}


# --- Data/dashboard (legacy, kept for compatibility) ---

DATA_FILE = Path("webapp/static/data.json")
HISTORY_CSV = Path("webapp/static/data.csv")


def _patch_data(patch: Dict[str, Any]) -> None:
    """Merge a partial update into data.json so the dashboard reflects manual
    control immediately (the auto loop re-syncs from the broadcast next cycle)."""
    try:
        d = json.loads(DATA_FILE.read_text()) if DATA_FILE.exists() else {}
    except Exception:
        d = {}
    d.update(patch)
    DATA_FILE.write_text(json.dumps(d, indent=4))


@app.get("/", response_class=HTMLResponse)
async def read_root():
    index = Path("webapp/index.html")
    if index.exists():
        return index.read_text()
    return "<h1>Switcher AC Control</h1><p><a href='/control/on'>ON</a> | <a href='/control/off'>OFF</a></p>"


@app.get("/data")
async def read_data():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {}


@app.get("/history")
async def read_history():
    if HISTORY_CSV.exists():
        return PlainTextResponse(HISTORY_CSV.read_text())
    return PlainTextResponse("")


@app.post("/data")
async def replace_data(new_data: Dict[str, Any]):
    DATA_FILE.write_text(json.dumps(new_data, indent=4))
    return new_data


# Serve static files
static_dir = Path("webapp/static")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)
