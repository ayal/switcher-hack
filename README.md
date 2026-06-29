# Switcher Smart AC Climate Control

A DIY smart climate control system built on top of [aioswitcher](https://github.com/TomerFi/aioswitcher) — an async Python library for controlling Switcher smart home devices.

This project adds automated temperature-based AC control using a **Switcher Breeze** (IR blaster), an **ESP32 temperature sensor**, and a **web dashboard** — originally running on a Raspberry Pi.

## Architecture

```
┌────────────┐        HTTP /data         ┌───────────────┐
│   ESP32    │ ◄──────────────────────── │               │
│  DHT11     │   (temp + humidity)       │   auto.py     │
│  sensor    │                           │  (control     │
└────────────┘                           │   loop)       │
                                         │               │
┌────────────┐     TCP (port 10000)      │  every 60s:   │
│  Switcher  │ ◄──────────────────────── │  read temp    │
│  Breeze    │   (IR commands via        │  check limits │
│  (AC IR)   │    aioswitcher API)       │  turn on/off  │
└────────────┘                           └───────────────┘

┌────────────┐                           ┌───────────────┐
│  iPhone    │ ──── Siri Shortcuts ────► │  server.py    │
│  Shortcut  │   GET /control/on|off     │  (FastAPI)    │
└────────────┘                           │  port 3001    │
                                         │               │
┌────────────┐        tunnel             │  /control/on  │
│  Browser   │ ◄──── cloudflared ──────► │  /control/off │
│  anywhere  │   (remote access)         │  /data        │
└────────────┘                           │  / (dashboard)│
                                         └───────────────┘
```

## Components

### `auto.py` — Automated Climate Control Loop

The core automation. Runs in an infinite loop (every 60 seconds):

1. Reads room temperature from the ESP32 sensor (`http://<ESP_IP>/data`)
2. Reads the current AC state from the Switcher Breeze device
3. Compares temperature against configurable upper/lower limits (from `data.json`)
4. Turns AC on if room is too hot, off if too cold
5. Adjusts fan level (LOW / MEDIUM / HIGH) based on how far the temperature exceeds the limit
6. Detects inconsistent state (e.g. AC says "on" but temp is rising) and forces a correction
7. Logs temperature + state to CSV for the dashboard chart

### `server.py` — FastAPI Web Server

A web server on port 3001 serving:

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Web dashboard (temperature chart + controls) |
| `/control/on` | GET | Turn AC on (cool, 24°C, medium fan) |
| `/control/off` | GET | Turn AC off |
| `/data` | GET | Current state JSON |
| `/data` | POST | Update config (temp limits, auto mode) |
| `/history` | GET | CSV history data |
| `/autolog` | GET | View auto.py log |

### `webapp/` — Web Dashboard

A single-page dashboard built with Alpine.js, Tailwind CSS, and Chart.js:

- **Scatter chart**: temperature over time, color-coded (green = AC on, red = AC off)
- **Controls**: auto mode toggle, upper/lower temperature limit adjusters
- **Status**: current on/off state, room temperature, AC target temp
- Auto-refreshes every 5 seconds (state) and 30 seconds (chart)

### `esp32/esp-dht.ino` — Temperature Sensor

Arduino sketch for an ESP32 with a DHT11 sensor:

- Connects to WiFi and serves a tiny HTTP server on port 80
- `GET /` — HTML page showing temperature and humidity
- `GET /data` — JSON response: `{"temp": "25.00", "hum": "50.00"}`
- Used by `auto.py` to get accurate room temperature readings

### `src/aioswitcher/` — Switcher Device Library

A fork of the [aioswitcher](https://github.com/TomerFi/aioswitcher) Python library with modifications for:

- TCP-based API for controlling Switcher devices (Breeze, Runner, water heaters, plugs)
- UDP bridge for device discovery via broadcast messages
- Breeze-specific features: thermostat state, IR remote commands, fan/swing/mode control
- Schedule management, device naming, auto-shutdown configuration

### Shell Scripts

| Script | Purpose |
|---|---|
| `run-all.sh` | Start `auto.py`, `server.py`, and cloudflared tunnel in background |
| `kill-all.sh` | Kill all running processes (auto, server, cloudflared) |
| `check-all.sh` | Check if processes are running |
| `restart.sh` | Git pull + kill + restart |
| `one.sh` | Alternative launcher with timestamped logs to `./logs/` |
| `two.sh` | SSH reverse tunnel via `tunnl.icu` (older tunnel method) |

### `run-all.service` — Systemd Service

Auto-starts everything on RPi boot via systemd (`/home/ayalg/switcher-hack`).

## Device Configuration

Device identity is read from `.env` (gitignored) — see `.env.example`. Discover your
values with `python scripts/discover_devices.py`.

| Property | Env var |
|---|---|
| Device IP | `DEVICE_IP` |
| Device ID | `DEVICE_ID` |
| Device Key | `DEVICE_KEY` |
| Remote ID | `REMOTE_ID` |
| ESP32 sensor URL | `ESP_URL` |

## Quick Start

```bash
# Install the library
pip install -e .

# Run the automation loop
python auto.py

# Run the web server (port 3001)
python server.py

# Or run everything together
source run-all.sh
```

## Remote Access (iPhone Siri Shortcuts)

The system was exposed externally via a Cloudflare tunnel (`cloudflared`), allowing Siri Shortcuts to call:

- **Turn on**: `GET https://<tunnel-url>/control/on`
- **Turn off**: `GET https://<tunnel-url>/control/off`

Create a Shortcut with the "Get Contents of URL" action pointing to the tunnel URL.

## Utility Scripts

```bash
# Discover Switcher devices on the network
python scripts/discover_devices.py

# Get a device's login key
python scripts/get_device_login_key.py -i "<DEVICE_IP>" -p 10002
```

## Based On

This project is a fork of [aioswitcher](https://github.com/TomerFi/aioswitcher) by Tomer Figenblat, originally licensed under Apache 2.0.
