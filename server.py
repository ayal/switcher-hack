import json
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Any, Dict
from pathlib import Path
from fastapi.responses import HTMLResponse
from fastapi import Request
import asyncio
import json
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from datetime import timedelta
from pprint import PrettyPrinter
from typing import Any, Dict, List, Union
from binascii import hexlify, unhexlify
from datetime import datetime
from aioswitcher.api import Command, SwitcherType1Api, SwitcherType2Api
from aioswitcher.api.remotes import SwitcherBreezeRemoteManager
from aioswitcher.device import (
    DeviceState,
    ThermostatFanLevel,
    ThermostatMode,
    ThermostatSwing,
)

remote_manager = SwitcherBreezeRemoteManager()

async def control_breeze_on(device_ip, device_id, device_key, remote_manager, remote_id) :
    async with SwitcherType2Api(device_ip, device_id, device_key) as api:
        remote = remote_manager.get_remote(remote_id)

        await api.control_breeze_device(
                    remote,
                    DeviceState.ON,
                    ThermostatMode.COOL,
                    24,
                    ThermostatFanLevel.MEDIUM,
                    ThermostatSwing.OFF,
                )

async def control_breeze_off(device_ip, device_id, device_key, remote_manager, remote_id) :
    async with SwitcherType2Api(device_ip, device_id, device_key) as api:
        remote = remote_manager.get_remote(remote_id)

        await api.control_breeze_device(
                    remote,
                    DeviceState.OFF,
                    ThermostatMode.COOL,
                    25,
                    ThermostatFanLevel.LOW,
                    ThermostatSwing.OFF,
                )


app = FastAPI()

# Middleware to set no-cache headers
@app.middleware("http")
async def add_cache_control_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Path to the JSON file
DATA_FILE = Path("webapp/static/data.json")

HISTORY_CSV = Path("webapp/static/data.csv")

def read_data_file():
    if DATA_FILE.exists():
        with DATA_FILE.open("r") as file:
            return json.load(file)
    return {}

def read_history_file():
    if HISTORY_CSV.exists():
        with HISTORY_CSV.open("r") as file:
            return file.read()
    return ""

def write_data_file(data: Dict[str, Any]):
    with DATA_FILE.open("w") as file:
        json.dump(data, file, indent=4)

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("webapp/index.html") as file:
        return file.read()

@app.get("/autolog", response_class=HTMLResponse)
async def read_root():
    with open("auto-log.log") as file:
        log_content = file.read()
        return f"<pre>{log_content}</pre>"

@app.get("/data")
async def read_data():
    return read_data_file()

@app.get("/history")
async def read_data():
    return read_history_file()

@app.get("/control/on")
async def turn_on():
    await control_breeze_on("<DEVICE_IP>", "<DEVICE_ID>", "03", remote_manager, "YACIFBI0")
    return "ac is now on"

@app.get("/control/off")
async def turn_on():
    await control_breeze_off("<DEVICE_IP>", "<DEVICE_ID>", "03", remote_manager, "YACIFBI0")
    return "ac is now off"


@app.post("/data")
async def replace_data(new_data: Dict[str, Any]):
    print("saving new data", new_data)
    write_data_file(new_data)
    return new_data

# Serve static files from the current directory
app.mount("/static", StaticFiles(directory="./webapp/static"), name="static")

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)
