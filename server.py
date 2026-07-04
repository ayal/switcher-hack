"""FastAPI server for AC cloud control — the single backend for every client.

This one process now runs BOTH the HTTP API and the control loop (as a
background task), so the webapp, the macOS menubar app, and any future mobile
app are all thin clients of the same API and always see the same state.

Endpoints
    Clean API (use these from new clients):
        GET  /api/state              -> full state {mode, is_on, temperature, ...}
        POST /api/config             <- partial config patch (validated/clamped)
        GET  /control/on?temp&fan&mode , GET /control/off
        GET  /temp                   -> fresh room temp straight from the cloud

    Legacy (kept for the existing dashboard):
        GET/POST /data , GET /history , GET /

Usage:
    python server.py                    # API + control loop on :3001
    curl localhost:3001/api/state
    curl -X POST localhost:3001/api/config -d '{"mode":"cycle","cycle_on_min":5}'
"""

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

# aioswitcher lives under ./src (mirrors the PYTHONPATH=src the CLIs use).
_SRC = Path(__file__).parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from aioswitcher.device import DeviceState
from cloud_control import cloud_control, cloud_get_state
from auto_cloud import (
    VALID_MODES,
    load_data,
    resolve_mode,
    run_loop,
    save_data,
)

DATA_FILE = Path("webapp/static/data.json")
HISTORY_CSV = Path("webapp/static/data.csv")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Spawn the control loop alongside the API, and cancel it on shutdown."""
    task = asyncio.create_task(run_loop())
    print("control loop started (in-process)")
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Switcher AC Cloud Control", lifespan=lifespan)


@app.middleware("http")
async def add_cache_control_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ---------------------------------------------------------------------------
# Clean JSON API (webapp / menubar / future mobile all use this)
# ---------------------------------------------------------------------------

def _current_state() -> Dict[str, Any]:
    """The full stored state with `mode` normalized (migrates legacy `auto`)."""
    d = load_data()
    d["mode"] = resolve_mode(d)
    d["auto"] = d["mode"] == "thermostat"  # keep the legacy mirror in sync
    return d


@app.get("/api/state")
async def api_state():
    """Everything a client needs to render, kept fresh by the control loop."""
    return _current_state()


# Validation/clamps for each configurable field. Anything not listed is ignored.
def _clamp_int(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def _clamp_num(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


@app.post("/api/config")
async def api_config(patch: Dict[str, Any]):
    """Merge a partial, validated config patch into the stored state.

    Accepts any subset of: mode, too_hot_temp, too_cold_temp, cool_temp,
    poll_interval, cycle_on_min, cycle_off_min. Switching *into* cycle mode
    re-anchors the timer to now, so it starts a fresh ON phase immediately.
    """
    d = load_data()
    prev_mode = resolve_mode(d)

    if "mode" in patch:
        m = patch["mode"]
        if m in VALID_MODES:
            d["mode"] = m
            d["auto"] = m == "thermostat"
            if m == "cycle" and prev_mode != "cycle":
                d["cycle_anchor"] = _now_iso()  # start cycling from ON, now
    if "too_hot_temp" in patch:
        d["too_hot_temp"] = _clamp_num(patch["too_hot_temp"], 10, 40, d.get("too_hot_temp", 27))
    if "too_cold_temp" in patch:
        d["too_cold_temp"] = _clamp_num(patch["too_cold_temp"], 10, 40, d.get("too_cold_temp", 26))
    if "cool_temp" in patch:
        d["cool_temp"] = _clamp_int(patch["cool_temp"], 16, 30, d.get("cool_temp", 26))
    if "poll_interval" in patch:
        d["poll_interval"] = _clamp_int(patch["poll_interval"], 10, 3600, d.get("poll_interval", 60))
    if "cycle_on_min" in patch:
        d["cycle_on_min"] = _clamp_num(patch["cycle_on_min"], 1, 240, d.get("cycle_on_min", 5))
    if "cycle_off_min" in patch:
        d["cycle_off_min"] = _clamp_num(patch["cycle_off_min"], 1, 240, d.get("cycle_off_min", 25))

    save_data(d)
    d["mode"] = resolve_mode(d)
    return d


def _now_iso() -> str:
    # Local import keeps datetime out of the module top (and mirrors auto_cloud's
    # naive-local timestamps used everywhere else in the app).
    from datetime import datetime
    return datetime.now().isoformat()


# ---------------------------------------------------------------------------
# Live reading (fresh from the cloud, independent of the control loop)
# ---------------------------------------------------------------------------

@app.get("/temp")
async def live_temp():
    st = await cloud_get_state()
    if not st:
        return {"status": "error"}
    return {
        "status": "ok",
        "temperature": st["temperature"],
        "is_on": st["state"] == DeviceState.ON,
        "ac_temp": st["target_temperature"],
    }


# ---------------------------------------------------------------------------
# AC control (cloud)
# ---------------------------------------------------------------------------

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
    success = await cloud_control("off")
    if success:
        _patch_data({"is_on": False})
        return {"status": "ok", "action": "off"}
    return {"status": "error", "message": "cloud command failed"}


# ---------------------------------------------------------------------------
# Legacy data/dashboard endpoints
# ---------------------------------------------------------------------------

def _patch_data(patch: Dict[str, Any]) -> None:
    """Merge a partial update into data.json so the dashboard reflects manual
    control immediately (the loop re-syncs from the cloud next tick)."""
    d = load_data()
    d.update(patch)
    save_data(d)


@app.get("/", response_class=HTMLResponse)
async def read_root():
    index = Path("webapp/index.html")
    if index.exists():
        return index.read_text()
    return "<h1>Switcher AC Control</h1><p><a href='/control/on'>ON</a> | <a href='/control/off'>OFF</a></p>"


@app.get("/data")
async def read_data():
    return _current_state()


@app.get("/history")
async def read_history():
    if HISTORY_CSV.exists():
        return PlainTextResponse(HISTORY_CSV.read_text())
    return PlainTextResponse("")


@app.post("/data")
async def replace_data(new_data: Dict[str, Any]):
    """Legacy full-state write. New clients should use POST /api/config."""
    DATA_FILE.write_text(json.dumps(new_data, indent=4))
    return new_data


static_dir = Path("webapp/static")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)
