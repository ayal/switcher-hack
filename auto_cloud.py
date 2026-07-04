"""Cloud variant of auto.py — runs the same thermostat automation, but:

  * reads the live AC state + room temperature from the Switcher CLOUD
    (cloud_get_state), falling back to the LAN UDP broadcast only if the cloud
    is unreachable, and
  * controls the AC via the Switcher CLOUD (cloud_control), not the dead LAN API.

Same threshold / force-state logic as auto.py. Because both reads and writes go
through the cloud, this can run anywhere with internet — no LAN access needed.

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
from aioswitcher.device import DeviceState

# Importing cloud_control loads .env (it calls load_dotenv at import time)
from cloud_control import cloud_control, cloud_get_state

CSV_FILE_PATH = "webapp/static/data.csv"
DATA_JSON_PATH = "webapp/static/data.json"
DECISIONS_PATH = "webapp/static/decisions.json"
DEVICE_ID = os.environ.get("DEVICE_ID", "")  # from .env (gitignored)

last_force_time = None
force_cooldown_time = timedelta(minutes=5)

# Operating modes the whole system understands (webapp, menubar, mobile all
# just flip this one field in data.json):
#   manual      — the loop only reads/records state; you drive the AC by hand
#   thermostat  — the smart temp-monitoring loop (control_cycle) runs
#   cycle        — dumb timer: X min ON then Y min OFF, forever
VALID_MODES = ("manual", "thermostat", "cycle")

# Cap the cycle-mode sleep so room-temp readings + the UI heartbeat stay fresh
# even in the middle of a long OFF phase, and so a boundary is never missed by
# more than this many seconds.
CYCLE_REFRESH_CAP = 30


# ---- shared data.json / CSV helpers ----
def load_data():
    """Read data.json, tolerating a missing/corrupt file."""
    try:
        with open(DATA_JSON_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_data(d):
    try:
        with open(DATA_JSON_PATH, "w") as f:
            json.dump(d, f)
    except Exception as e:
        print("could not write data.json:", e)


def append_csv(temp, state):
    """Append one history row (the dashboard chart + trend logic read this)."""
    try:
        with open(CSV_FILE_PATH, "a") as f:
            f.write(f"{datetime.now()}, {state == DeviceState.ON}, {temp}\n")
    except Exception as e:
        print("could not append CSV:", e)


def parse_dt(s):
    """Parse an ISO timestamp we wrote earlier; None on failure."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def resolve_mode(d):
    """The active mode, migrating the legacy `auto` boolean when `mode` is unset."""
    m = d.get("mode")
    if m in VALID_MODES:
        return m
    return "thermostat" if d.get("auto") else "manual"


def record_decision(action, reason, temp=None, state=None, target=None):
    """Append one decision to a rolling log (last 40) the dashboard displays.

    action: on | off | none | skip | auto-off | offline
    """
    rec = {
        "t": datetime.now().isoformat(),
        "action": action,
        "reason": reason,
        "temp": temp,
        "on": (state == DeviceState.ON) if state is not None else None,
        "target": target,
    }
    items = []
    try:
        with open(DECISIONS_PATH) as f:
            items = json.load(f)
    except Exception:
        items = []
    items.append(rec)
    try:
        with open(DECISIONS_PATH, "w") as f:
            json.dump(items[-40:], f)
    except Exception as e:
        print("could not write decisions:", e)



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

    data_json = {"auto": True, "too_hot_temp": 25, "too_cold_temp": 25,
                 "cool_temp": 26, "poll_interval": 60}
    try:
        with open(DATA_JSON_PATH, "r") as f:
            data_json = json.load(f)
    except Exception as e:
        print("error reading data file", e, "\n\nRESETTING DATA FILE")
        with open(DATA_JSON_PATH, "w") as f:
            json.dump(data_json, f)
    # cooling setpoint the AC is set to when turned on (configurable via the UI)
    data_json.setdefault("cool_temp", 26)

    # Get current state from the CLOUD (works off-LAN). Fall back to the LAN
    # UDP broadcast only if the cloud is unreachable.
    st = await cloud_get_state()
    source = "cloud"
    if st is None:
        dev = await read_breeze_state()
        if dev is None:
            print("Could not read device state (cloud + LAN both failed); skipping.")
            record_decision("offline", "no state from cloud or LAN")
            return
        st = {"temperature": dev.temperature, "state": dev.device_state,
              "target_temperature": dev.target_temperature}
        source = "lan-broadcast"

    state = st["state"]
    the_temp = st["temperature"]
    cur_target = st["target_temperature"]

    turn_on_ac_temp = int(data_json.get("cool_temp", 26))
    hot_temp_delta = round(the_temp - data_json["too_hot_temp"], 3)
    cold_temp_delta = round(data_json["too_cold_temp"] - the_temp, 3)

    # Fan is always LOW: changing fan is a separate IR command (a beep), and the
    # cloud's fan reading is unreliable, so we never touch it. Still nudge the
    # target setpoint down when the room is well above the limit (cool harder).
    if hot_temp_delta > 1:
        turn_on_ac_temp -= 1
    if hot_temp_delta > 2:
        turn_on_ac_temp -= 1

    room_too_hot = the_temp > data_json["too_hot_temp"]
    room_too_cold = the_temp < data_json["too_cold_temp"]

    if room_too_hot:
        reason = f"{the_temp}° above upper limit {data_json['too_hot_temp']}°"
    elif room_too_cold:
        reason = f"{the_temp}° below lower limit {data_json['too_cold_temp']}°"
    else:
        reason = f"{the_temp}° within {data_json['too_cold_temp']}–{data_json['too_hot_temp']}°"

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

    # Fan is NOT used as a change trigger: the cloud's fan view is unreliable
    # for this open-loop IR device, so comparing it would cause phantom re-sends.
    ac_temp_change = turn_on_ac_temp != cur_target
    state_change = new_state != state
    off_to_off = state == DeviceState.OFF and new_state == DeviceState.OFF

    should_change = (ac_temp_change or state_change) and not off_to_off
    should_force = force_state is not None

    print("\n--- cycle", datetime.now(), "---")
    print("AUTO MODE:", data_json.get("auto", False))
    print(f"[{source}] State: {state}  RoomTemp: {the_temp}  AC target: {cur_target}")
    print(f"limits  hot>{data_json['too_hot_temp']}  cold<{data_json['too_cold_temp']}  "
          f"(too_hot={room_too_hot} too_cold={room_too_cold})")
    print(f"decide -> new_state={new_state}  ac_temp={turn_on_ac_temp}  fan=low")
    print(f"should_change={should_change} should_force={should_force} force_state={force_state}")

    # log to CSV + data.json (drives the dashboard + the trend logic)
    with open(CSV_FILE_PATH, "a") as f:
        f.write(f"{datetime.now()}, {state == DeviceState.ON}, {the_temp}\n")
    data_json["is_on"] = state == DeviceState.ON
    data_json["temperature"] = the_temp
    data_json["ac_temp"] = cur_target
    with open(DATA_JSON_PATH, "w") as f:
        json.dump(data_json, f)

    if resolve_mode(data_json) != "thermostat":
        print("Thermostat mode not active — not changing anything.")
        record_decision("auto-off", "thermostat off", the_temp, state, cur_target)
        return

    if not (should_change or should_force):
        print("No change needed.")
        record_decision("none", reason, the_temp, state, cur_target)
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
        and cur_target == turn_on_ac_temp
    )
    if already_off or already_on_same:
        print("Device already in desired state — skipping command (no beep).")
        record_decision("skip", "already " + ("on" if device_is_on else "off"),
                        the_temp, state, cur_target)
        return

    if dry:
        print(f"[DRY] would send: {'ON ' + str(turn_on_ac_temp) + 'C low' if target == DeviceState.ON else 'OFF'}")
        return

    forced = " (forced)" if (should_force and not should_change) else ""
    try:
        if target == DeviceState.ON:
            await cloud_control("on", temp=turn_on_ac_temp, fan="low", mode="cool")
            record_decision("on", reason + forced, the_temp, DeviceState.ON, turn_on_ac_temp)
        else:
            await cloud_control("off")
            record_decision("off", reason + forced, the_temp, DeviceState.OFF, cur_target)
    except Exception as e:
        print("Error controlling via cloud:", e)
        traceback.print_exc()
        record_decision("error", str(e)[:80], the_temp, state, cur_target)


def update_poll_meta():
    """Record this poll's time and return the (clamped) poll interval in seconds.

    Reads `poll_interval` from data.json (configurable from the dashboard,
    default 60s, clamped 10s-1h) and stamps `last_poll` so the UI can show the
    heartbeat and count down to the next run.
    """
    data = {}
    try:
        with open(DATA_JSON_PATH) as f:
            data = json.load(f)
    except Exception:
        pass
    try:
        interval = int(data.get("poll_interval", 60))
    except (TypeError, ValueError):
        interval = 60
    interval = max(10, min(3600, interval))
    data["poll_interval"] = interval
    data["last_poll"] = datetime.now().isoformat()
    try:
        with open(DATA_JSON_PATH, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print("could not write poll meta:", e)
    return interval


# ---- cycle mode (the dumb timer, folded in from ac_cycle.sh) ----
async def cycle_cycle(dry=False):
    """One tick of the on/off timer. Returns the seconds to sleep before the
    next tick (short, so boundaries are hit promptly and readings stay fresh).

    The phase is derived from a wall-clock anchor, so it's restart-safe: killing
    and relaunching the loop resumes the same on/off rhythm instead of jumping
    back to the start of an ON phase.
    """
    d = load_data()
    on_min = float(d.get("cycle_on_min", 5))
    off_min = float(d.get("cycle_off_min", 25))
    cool = int(d.get("cool_temp", 26))
    on_sec = max(60, int(on_min * 60))       # floor at 1 min per phase
    off_sec = max(60, int(off_min * 60))
    period = on_sec + off_sec

    now = datetime.now()
    anchor = parse_dt(d.get("cycle_anchor"))
    if anchor is None:
        anchor = now
        d["cycle_anchor"] = anchor.isoformat()

    elapsed = max(0.0, (now - anchor).total_seconds())
    pos = elapsed % period
    if pos < on_sec:
        desired, phase, secs_left = DeviceState.ON, "on", on_sec - pos
    else:
        desired, phase, secs_left = DeviceState.OFF, "off", period - pos

    st = await cloud_get_state()
    state = st["state"] if st else None
    the_temp = st["temperature"] if st else None
    cur_target = st["target_temperature"] if st else None

    # record readings + history so the chart/UI stay alive in cycle mode too
    if state is not None:
        append_csv(the_temp, state)
        d["is_on"] = state == DeviceState.ON
        d["temperature"] = the_temp
        d["ac_temp"] = cur_target
    d["cycle_phase"] = phase
    d["cycle_phase_until"] = (now + timedelta(seconds=secs_left)).isoformat()
    d["last_poll"] = now.isoformat()
    save_data(d)

    print(f"\n--- cycle-mode tick {now} ---")
    print(f"phase={phase} desired={desired} state={state} target={cur_target} "
          f"cool={cool} secs_left={int(secs_left)}")

    if st is None:
        record_decision("offline", "no cloud state (cycle)")
        return CYCLE_REFRESH_CAP

    if not dry:
        # Idempotency: only send on a real transition (the IR blaster beeps on
        # every command, so never re-assert a state the device already holds).
        if desired == DeviceState.ON and (state != DeviceState.ON or cur_target != cool):
            await cloud_control("on", temp=cool, fan="low", mode="cool")
            record_decision("on", f"cycle: {int(on_min)}m on @ {cool}°",
                            the_temp, DeviceState.ON, cool)
        elif desired == DeviceState.OFF and state != DeviceState.OFF:
            await cloud_control("off")
            record_decision("off", f"cycle: {int(off_min)}m off",
                            the_temp, DeviceState.OFF, cur_target)

    # Sleep to the phase boundary, but never longer than the refresh cap.
    return max(1, min(CYCLE_REFRESH_CAP, int(secs_left)))


# ---- manual mode: only observe (record readings, never control) ----
async def refresh_readings():
    d = load_data()
    st = await cloud_get_state()
    now = datetime.now()
    if st:
        append_csv(st["temperature"], st["state"])
        d["is_on"] = st["state"] == DeviceState.ON
        d["temperature"] = st["temperature"]
        d["ac_temp"] = st["target_temperature"]
    d["last_poll"] = now.isoformat()
    d.pop("cycle_phase", None)
    d.pop("cycle_phase_until", None)
    save_data(d)


# ---- one dispatched tick: routes to the active mode ----
async def tick(dry=False):
    """Run one control tick for the current mode. Returns the seconds to sleep
    before the next tick, or None to fall back to the configured poll interval."""
    mode = resolve_mode(load_data())
    if mode == "cycle":
        return await cycle_cycle(dry=dry)
    if mode == "thermostat":
        await control_cycle(dry=dry)
        return None
    await refresh_readings()  # manual
    return None


async def run_loop(dry=False):
    """The single long-running controller loop (also spawned in-process by the
    FastAPI server). Reads the mode fresh every tick, so switching modes from
    any client takes effect on the next cycle."""
    print("starting unified AC controller...", "(dry run)" if dry else "")
    while True:
        sleep_s = None
        try:
            sleep_s = await tick(dry=dry)
        except Exception as e:
            print(f"General Error: {e}")
            traceback.print_exc()
        if sleep_s is None:
            sleep_s = update_poll_meta()  # thermostat/manual: stamp + poll_interval
        print(f"next tick in {sleep_s}s")
        await asyncio.sleep(sleep_s)


async def main():
    parser = argparse.ArgumentParser(description="Unified cloud AC controller")
    parser.add_argument("--once", action="store_true", help="run one tick then exit")
    parser.add_argument("--dry", action="store_true", help="don't actually send AC commands")
    args = parser.parse_args()

    if args.once:
        await tick(dry=args.dry)
        return
    await run_loop(dry=args.dry)


if __name__ == "__main__":
    asyncio.run(main())
