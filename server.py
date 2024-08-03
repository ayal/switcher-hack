import json
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Any, Dict
from pathlib import Path
from fastapi.responses import HTMLResponse
from fastapi import Request

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

def read_data_file():
    if DATA_FILE.exists():
        with DATA_FILE.open("r") as file:
            return json.load(file)
    return {}

def write_data_file(data: Dict[str, Any]):
    with DATA_FILE.open("w") as file:
        json.dump(data, file, indent=4)

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("webapp/index.html") as file:
        return file.read()

@app.get("/data")
async def read_data():
    return read_data_file()

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
