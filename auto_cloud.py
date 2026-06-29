"""Cloud variant of auto.py — runs the same thermostat automation, but:

  * reads the live AC state + room temperature from the device's UDP BROADCAST
    (the LAN TCP control API is dead on this unit's firmware), and
  * controls the AC via the Switcher CLOUD (cloud_control.py), not the LAN API.

Same threshold / fan / force-state logic as auto.py. Designed to run on any
machine on the same Wi-Fi as the Switcher (for reading temp); control works
from anywhere since it goes through the cloud.

Usage:
    python auto_cloud.py            # run the loop forever (controls the AC)
    python auto_cloud.py --once     # run a single cycle then exit
    python auto_cloud.py --dry      # decide + log but DON'T send any AC command
"""

import argparse
import asyncio
import csv
import json
import os
import traceback
from datetime import datetime, timedelta

from aioswitcher.bridge import (
    SwitcherBridge,
    SWITCHER_UDP_PORT_TYPE2,
    SWITCHER_UDP_PORT_TYPE2_NEW_VERSION,
)
from aioswitcher.device import DeviceState, ThermostatFanLevel, ThermostatMode

# Importing cloud_control loads .env (it calls load_dotenv at import time)
from cloud_control import cloud_control

CSV_FILE_PATH = "webapp/static/data.csv"
DATA_JSON_PATH = "webapp/static/data.json"
DEVICE_ID = os.environ.get("DEVICE_ID", "")  # from .env (gitignored)

last_force_time = None
force_cooldown_time = timedelta(minutes=5)

FAN_TO_STR = {
    ThermostatFanLevel.LOW: "low",
    ThermostatFanLevel.MEDIUM: "medium",
    ThermostatFanLevel.HIGH: "high",
    ThermostatFanLevel.AUTO: "auto",
}


# ---- trend / force-state helpers (unchanged from auto.py) ----
def read_last_n_rows(n=5):
    if not os.path.exists(CSV_FILE_PATH):
        return None
    try:
        with open(CSV_FILE_PATH, "r") as f:
            reader = list(csv.reader(f))
            if len(reader) < n:
                return None
            return reader[-n:]
    except Exception as e:
        print(f"Error reading file: {e}")
        return None


def has_state_changed(states):
    return len(set(states)) > 1


def determine_temp_trend(temps):
    deltas = [temps[i] - temps[i - 1] for i in range(1, len(temps))]
    rising_count = sum(d > 0 for d in deltas)
    falling_count = sum(d < 0 for d in deltas)
    if rising_count > falling_count:
        return "rising"
    elif falling_count > rising_count:
        return "falling"
    return "stable"


def get_force_change(current_state, current_temp, last_force_time=None):
    data = read_last_n_rows(5)
    if not data or len(data) < 5:
        return None
    temperatures = [float(row[2]) for row in data]
    states = [row[1].strip() == "True" for row in data]
    if has_state_changed(states):
        return None
    if last_force_time and datetime.now() - last_force_time < force_cooldown_time:
        return None
    temp_trend = determine_temp_trend(temperatures)
    print(f"Temperature trend: {temp_trend}", current_state, current_temp)
    if current_state == DeviceState.OFF and temp_trend == "falling":
        return DeviceState.OFF
    if current_state == DeviceState.ON and temp_trend == "rising":
        return DeviceState.ON
    return None


# ---- read live state from the UDP broadcast (replaces the dead LAN API) ----
async def read_breeze_state(timeout=8):
    """Listen briefly for our device's broadcast and return its state object."""
    holder = {}
    found = asyncio.Event()

    def cb(device):
        if getattr(device, "device_id", None) == DEVICE_ID and not found.is_set():
            holder["device"] = device
            found.set()

    ports = [SWITCHER_UDP_PORT_TYPE2, SWITCHER_UDP_PORT_TYPE2_NEW_VERSION]
    async with SwitcherBridge(cb, broadcast_ports=ports):
        try:
            await asyncio.wait_for(found.wait(), timeout)
        except asyncio.TimeoutError:
            pass
    return holder.get("device")


# ---- one control cycle ----
async def control_cycle(dry=False):
    global last_force_time

    data_json = {"auto": True, "too_hot_temp": 25, "too_cold_temp": 25}
    try:
        with open(DATA_JSON_PATH, "r") as f:
            data_json = json.load(f)
    except Exception as e:
        print("error reading data file", e, "\n\nRESETTING DATA FILE")
        with open(DATA_JSON_PATH, "w") as f:
            json.dump(data_json, f)

    device = await read_breeze_state()
    if device is None:
        print("Could not read device state from broadcast this cycle; skipping.")
        return

    state = device.device_state
    switcher_temp = device.temperature

    # ESP32 sensor optional (see auto.py); default: use the Switcher's own temp
    the_temp = switcher_temp

    turn_on_ac_temp = 25
    hot_temp_delta = round(the_temp - data_json["too_hot_temp"], 3)
    cold_temp_delta = round(data_json["too_cold_temp"] - the_temp, 3)

    fan_level = ThermostatFanLevel.LOW
    if hot_temp_delta > 1:
        fan_level = ThermostatFanLevel.MEDIUM
        turn_on_ac_temp -= 1
    if hot_temp_delta > 2:
        fan_level = ThermostatFanLevel.HIGH
        turn_on_ac_temp -= 1
    if hot_temp_delta < 0:
        fan_level = ThermostatFanLevel.LOW

    room_too_hot = the_temp > data_json["too_hot_temp"]
    room_too_cold = the_temp < data_json["too_cold_temp"]

    device_is_on = state == DeviceState.ON
    device_is_off = state == DeviceState.OFF

    force_state = get_force_change(state, the_temp, last_force_time)
    if force_state is not None:
        last_force_time = datetime.now()
        print("*** Forcing state change - room is >>>",
              "TOO HOT" if room_too_hot else "TOO COLD", "<<< ***")

    new_state = state
    if room_too_hot and device_is_off:
        new_state = DeviceState.ON
    if room_too_cold and device_is_on:
        new_state = DeviceState.OFF

    fan_level_change = fan_level != device.fan_level
    ac_temp_change = turn_on_ac_temp != device.target_temperature
    state_change = new_state != state
    off_to_off = state == DeviceState.OFF and new_state == DeviceState.OFF

    should_change = (fan_level_change or ac_temp_change or state_change) and not off_to_off
    should_force = force_state is not None

    print("\n--- cycle", datetime.now(), "---")
    print("AUTO MODE:", data_json.get("auto", False))
    print(f"State: {state}  RoomTemp: {the_temp}  AC target: {device.target_temperature}  fan: {device.fan_level}")
    print(f"limits  hot>{data_json['too_hot_temp']}  cold<{data_json['too_cold_temp']}  "
          f"(too_hot={room_too_hot} too_cold={room_too_cold})")
    print(f"decide -> new_state={new_state}  ac_temp={turn_on_ac_temp}  fan={fan_level}")
    print(f"should_change={should_change} should_force={should_force} force_state={force_state}")

    # log to CSV + data.json (drives the dashboard + the trend logic)
    with open(CSV_FILE_PATH, "a") as f:
        f.write(f"{datetime.now()}, {state == DeviceState.ON}, {the_temp}\n")
    data_json["is_on"] = state == DeviceState.ON
    data_json["temperature"] = the_temp
    data_json["ac_temp"] = device.target_temperature
    with open(DATA_JSON_PATH, "w") as f:
        json.dump(data_json, f)

    if not data_json.get("auto", False):
        print("Auto mode OFF — not changing anything.")
        return

    if not (should_change or should_force):
        print("No change needed.")
        return

    target = force_state if force_state is not None else new_state

    # Idempotency guard: never re-send a command the device already satisfies.
    # The Switcher is an IR blaster, so a redundant command just makes the AC
    # beep with no visible effect. (The force-state re-assert always echoes the
    # current reported state, so without this guard it fires phantom on/off
    # commands every time the temperature merely drifts up/down.)
    already_off = target == DeviceState.OFF and state == DeviceState.OFF
    already_on_same = (
        target == DeviceState.ON
        and state == DeviceState.ON
        and device.target_temperature == turn_on_ac_temp
        and device.fan_level == fan_level
    )
    if already_off or already_on_same:
        print("Device already in desired state — skipping command (no beep).")
        return

    if dry:
        print(f"[DRY] would send: {'ON ' + str(turn_on_ac_temp) + 'C ' + FAN_TO_STR.get(fan_level, 'medium') if target == DeviceState.ON else 'OFF'}")
        return

    try:
        if target == DeviceState.ON:
            await cloud_control("on", temp=turn_on_ac_temp,
                                fan=FAN_TO_STR.get(fan_level, "medium"), mode="cool")
        else:
            await cloud_control("off")
    except Exception as e:
        print("Error controlling via cloud:", e)
        traceback.print_exc()


async def main():
    parser = argparse.ArgumentParser(description="Cloud-based AC thermostat loop")
    parser.add_argument("--once", action="store_true", help="run one cycle then exit")
    parser.add_argument("--dry", action="store_true", help="don't actually send AC commands")
    args = parser.parse_args()

    print("starting cloud climate control...", "(dry run)" if args.dry else "")
    if args.once:
        await control_cycle(dry=args.dry)
        return
    while True:
        try:
            await control_cycle(dry=args.dry)
        except Exception as e:
            print(f"General Error: {e}")
            traceback.print_exc()
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
