

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
    DeviceType,
    DeviceState,
    ThermostatFanLevel,
    ThermostatMode,
    ThermostatSwing,
)
import aiohttp
import traceback
import math
import os
import csv

# Fixed file path
CSV_FILE_PATH = 'webapp/static/data.csv'
last_force_time = None
force_cooldown_time = timedelta(minutes=5)

def read_last_n_rows(n=5):
    """Reads the last n rows from a fixed CSV file path."""
    if not os.path.exists(CSV_FILE_PATH):
        # File doesn't exist, return None
        return None

    try:
        with open(CSV_FILE_PATH, 'r') as f:
            reader = list(csv.reader(f))
            if len(reader) < n:
                # Not enough rows in the file yet
                return None
            return reader[-n:]
    except Exception as e:
        # Catch any error that may occur during reading (e.g. file format issues)
        print(f"Error reading file: {e}")
        return None

def has_state_changed(states):
    """Checks if there has been a state change in the given list of states."""
    # If there is more than one unique state, a state change occurred
    return len(set(states)) > 1

def determine_temp_trend(temps):
    """Determines if the temperature is rising, falling, or stable based on general trend."""
    deltas = [temps[i] - temps[i-1] for i in range(1, len(temps))]

    rising_count = sum(delta > 0 for delta in deltas)
    falling_count = sum(delta < 0 for delta in deltas)

    # Determine trend based on the majority of changes
    if rising_count > falling_count:
        return "rising"
    elif falling_count > rising_count:
        return "falling"
    else:
        return "stable"

def get_force_change(current_state, current_temp, last_force_time=None):
    """Checks if the current state of the AC is inconsistent with the temperature trend."""
    # Step 1: Read the last 5 entries from the file
    data = read_last_n_rows(5)
    if not data:
        # Not enough data to determine trends or file doesn't exist
        return None

     # Step 2: Check if there's enough data (at least 5 rows)
    if not data or len(data) < 5:
        # Not enough data to determine trends or file doesn't exist
        return None

    # Step 2: Extract the state and temperature from the last 5 data points
    temperatures = [float(row[2]) for row in data]  # Assuming temp is the 3rd column
    states = [row[1].strip() == 'True' for row in data]  # Convert the 'True/False' string to boolean

    # Step 3: Check if there was a state change
    if has_state_changed(states):
        # If there was a state change, we can't reliably calculate the trend
        return None


    if last_force_time and datetime.now() - last_force_time < force_cooldown_time:
        return None

    # Step 4: Determine the temperature trend
    temp_trend = determine_temp_trend(temperatures)

    print(f"Temperature trend: {temp_trend}", current_state, current_temp)

    # Step 5: Check the current state of the AC and compare with the trend
    if current_state == DeviceState.OFF:
        # AC is off, temperature should be stable or rising
        if temp_trend == "falling":
            return DeviceState.OFF  # Force it off, since the AC is likely still on
    elif current_state == DeviceState.ON:
        # AC is on, temperature should be stable or falling
        if temp_trend == "rising":
            return DeviceState.ON  # Force it on, since the AC is likely still off

    # No need to force a state change
    return None


async def read_temp_from_esp32(url):
    try:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        try:
                            temp = float(data.get("temp"))
                            hum = float(data.get("hum"))
                            return {"temp": temp, "hum": hum}
                        except (ValueError, TypeError):
                            return {"error": "Invalid temperature or humidity data"}
                    else:
                        return {"error": f"Failed to retrieve data, status code: {response.status}"}
            except asyncio.TimeoutError:
                return {"error": "Request timed out"}
            except aiohttp.ClientError as e:
                return {"error": f"Connection error: {str(e)}"}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}


async def control_breeze_x(device_ip, device_id, device_key, remote_manager, remote_id) :
    # print("Connecting to device", device_id, "at", device_ip, "with key", device_key)
    # for connecting to a device we need its id, login key and ip address
#    async with SwitcherType2Api(DeviceType.BREEZE, device_ip, device_id, device_key) as api:
    async with SwitcherType2Api(device_ip, device_id, device_key) as api:
        print("Connected to device", device_id, "at", device_ip)
        # read current data from json:
        data_json = {"auto": True, "too_hot_temp": 25, "too_cold_temp": 25}

        try:
            with open('webapp/static/data.json', 'r') as f:
                data_json = json.load(f)
        except Exception as e:
            print('error reading data file', e, '\n\nRESETTING DATA FILE')
            with open('webapp/static/data.json', 'w') as f:
                json.dump(data_json, f)

        state = await api.get_breeze_state()
        switcher_temp = state.temperature
        # print("switcher temp", switcher_temp)

        # The ESP32 DHT11 sensor is optional. Set ESP_URL in .env (e.g.
        # http://<ESP_IP>/data) to use it. With no ESP hardware, leave it
        # unset and the temperature comes straight from the Switcher.
        esp_temp = 0
        esp_url = os.environ.get("ESP_URL")
        if esp_url:
            esp_data = await read_temp_from_esp32(esp_url)
            if "error" in esp_data:
                print("Error reading data from ESP32:", esp_data["error"])
            else:
                esp_temp = esp_data["temp"]

        # Use the ESP temp only when present and sane (10-40C); otherwise fall
        # back to the Switcher's own temperature reading.
        if esp_temp < 10 or esp_temp > 40:
            the_temp = switcher_temp
            print("Using Switcher temp:", switcher_temp)
        else:
            the_temp = esp_temp


        remote = remote_manager.get_remote(remote_id)

        # avg between the two limits, rounded up to full number
        # turn_on_ac_temp =  math.ceil((data_json["too_hot_temp"] + data_json["too_cold_temp"]) / 2)
        # if turn_on_ac_temp > 25:
        #    turn_on_ac_temp = 25
        turn_on_ac_temp = 25

        # round 2nd decimal place
        hot_temp_delta = the_temp - data_json["too_hot_temp"]
        hot_temp_delta = round(hot_temp_delta, 3)

        cold_temp_delta = data_json["too_cold_temp"] - the_temp
        cold_temp_delta = round(cold_temp_delta, 3)

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

        print("\n---\n")

        device_is_on = state.state == DeviceState.ON
        device_is_off = state.state == DeviceState.OFF


        # sometimes the device state is WRONG (i.e it says it's on but it's not really on)
        # so we need to force the device to turn on or off if temperature trend is not consistent with the state
        global last_force_time
        force_state = get_force_change(state.state, the_temp, last_force_time)

        if force_state is not None:
            last_force_time = datetime.now()
            print("*** Forcing state change - room is >>>", "TOO HOT" if room_too_hot else "TOO COLD", "<<< ***")


        new_state = state.state
        if room_too_hot:
            print("Room too hot. upper limit is: ", data_json["too_hot_temp"], "current temp:", the_temp)
            if device_is_off:
                print("device is off, should turn on")
                new_state = DeviceState.ON
            else:
                print("device is on, should leave on?")
        if room_too_cold:
            print("Room too cold. lower limit is:", data_json["too_cold_temp"], "current temp:", the_temp)
            if device_is_on:
                print("device is on, should turn off")
                new_state = DeviceState.OFF
            else:
                print("device is off, should leave off?")
        if room_too_hot == False and room_too_cold == False:
            print("Room temp is within limits. current temp:", the_temp)


        fan_level_change = fan_level != state.fan_level
        ac_temp_change = turn_on_ac_temp != state.target_temperature
        state_change = new_state != state.state
        off_to_off = state.state == DeviceState.OFF and new_state == DeviceState.OFF

        should_change = ((fan_level_change or ac_temp_change or state_change) and not off_to_off)
        should_force = force_state is not None
        change_reason = "fan-level" if fan_level_change else "temp" if ac_temp_change else "state" if state_change else "none"

        print("Time: ", datetime.now())
        print("AUTO MODE: ", data_json.get("auto", False))
        print(f"Current state: {state.state}")
        print(f"Current fan level: {state.fan_level}")
        print(f"Current switcher temp: {switcher_temp}")
        print(f"Current ESP32 temp: {esp_temp}")
        print(f"Using temp: {the_temp}")
        print(f"UPPER LIMIT: {data_json['too_hot_temp']}", f"LOWER LIMIT: {data_json['too_cold_temp']}")
        print(f"Hot temp delta: {hot_temp_delta}", f"Cold temp delta: {cold_temp_delta}")
        print(f"Turn on AC with temp: {turn_on_ac_temp}", f"Temp change: {ac_temp_change}", f"from AC temp {state.target_temperature} to AC temp {turn_on_ac_temp}" if ac_temp_change else "")
        print(f"Fan level: {fan_level}", f"Fan level change: {fan_level_change}")
        print(f"New state: {new_state}", f"State change: {state_change}")
        print(f"Off to off: {off_to_off}")
        print(f"Should change: {should_change}", "change reason: ", "none" if not should_change else change_reason)
        print(f"Should force change: {should_force}", "force state: ", force_state)
        print("\n---\n")

        state = await api.get_breeze_state()
        thedatetime = datetime.now()

        with open(CSV_FILE_PATH, 'a') as f:
            # append one row to the csv file
            f.write(f'{thedatetime}, {state.state == DeviceState.ON}, {the_temp}\n')

        # write to data.json the current state:
        data_json["is_on"] = state.state == DeviceState.ON
        data_json["temperature"] = the_temp
        data_json["ac_temp"] = state.target_temperature
        with open('webapp/static/data.json', 'w') as f:
            json.dump(data_json, f)

        if data_json.get("auto", False) == False:
            print("\n\n----- Auto mode is off. Not changing anything. -----\n\n")
            return

        if should_change or should_force:
            try:
                await api.control_breeze_device(
                    remote,
                    force_state if force_state is not None else new_state,
                    ThermostatMode.COOL,
                    turn_on_ac_temp,
                    fan_level,
                    ThermostatSwing.OFF,
                )
            except Exception as e:
                print(f"Error controlling breeze: {str(e)}")
                print(f"Type of exception: {type(e)}")
                traceback.print_exc()

        # sleep for 5 seconds to allow the device to process the command
        await asyncio.sleep(5)

        state = await api.get_breeze_state()

        thedatetime = datetime.now()
        with open(CSV_FILE_PATH, 'a') as f:
            # append one row to the csv file
            f.write(f'{thedatetime}, {state.state == DeviceState.ON}, {the_temp}\n')

        # write to data.json the current state:
        data_json["is_on"] = state.state == DeviceState.ON
        data_json["temperature"] = the_temp
        with open('webapp/static/data.json', 'w') as f:
            json.dump(data_json, f)



# create the remote manager outside the context for re-using
remote_manager = SwitcherBreezeRemoteManager()

# Device params come from .env (gitignored) — see .env.example.
from dotenv import load_dotenv  # noqa: E402
load_dotenv()
key = os.environ.get("DEVICE_KEY", "")
deviceID = os.environ.get("DEVICE_ID", "")
remoteID = os.environ.get("REMOTE_ID", "")
IP = os.environ.get("DEVICE_IP", "")

index = 0
async def main():
    print("running main...")
    while True:
        try:
            await control_breeze_x(IP, deviceID, key, remote_manager, remoteID)
        except Exception as e:
            print(f"General Error: {str(e)}")
        await asyncio.sleep(60)


print("starting climate control...")

if __name__ == "__main__":
    asyncio.run(main())
