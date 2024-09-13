

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

FORCE_CHANGE_DELTA = 1

async def read_temp_from_esp32():
    url = "http://<ESP_IP>/data"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            # Ensure the response is successful
            if response.status == 200:
                data = await response.json()
                # Extract temperature and humidity from the response
                temp = float(data.get("temp"))
                hum = float(data.get("hum"))
                return {"temp": temp, "hum": hum}
            else:
                return {"error": f"Failed to retrieve data, status code: {response.status}"}


async def control_breeze_x(device_ip, device_id, device_key, remote_manager, remote_id) :
    print("Connecting to device", device_id, "at", device_ip, "with key", device_key)
    # for connecting to a device we need its id, login key and ip address
#    async with SwitcherType2Api(DeviceType.BREEZE, device_ip, device_id, device_key) as api:
    async with SwitcherType2Api(device_ip, device_id, device_key) as api:
        print("Connected to device", device_id, "at", device_ip, "with key", device_key)
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

        esp_data = await read_temp_from_esp32()
        # print("esp data", esp_data)
        esp_temp = esp_data["temp"]
        # print("esp temp", esp_temp)

        # esp is more accurate?
        the_temp = esp_temp


        remote = remote_manager.get_remote(remote_id)

        turn_on_ac_temp =  round(data_json["too_cold_temp"])
        if turn_on_ac_temp > 25:
            turn_on_ac_temp = 25

        hot_temp_delta = the_temp - data_json["too_hot_temp"]
        cold_temp_delta = data_json["too_cold_temp"] - the_temp

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
        # so we need to force the device to turn on or off if temperature is way too hot or cold
        force_state = None
        # force state on or off according to an irregular hot_temp_delta or cold_temp_delta (more than FORCE_CHANGE_DELTA)
        if data_json.get("auto", False) == True:
            if room_too_hot and hot_temp_delta > FORCE_CHANGE_DELTA and device_is_on:
                force_state = DeviceState.ON
            if room_too_cold and cold_temp_delta > FORCE_CHANGE_DELTA and device_is_off:
                force_state = DeviceState.OFF

        if force_state is not None:
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

        if force_state is not None:
            print("*** FORCING DEVICE STATE", force_state, "***")
            new_state = force_state

        fan_level_change = fan_level != state.fan_level
        ac_temp_change = turn_on_ac_temp != state.target_temperature
        state_change = new_state != state.state
        off_to_off = state.state == DeviceState.OFF and new_state == DeviceState.OFF

        should_change = ((fan_level_change or ac_temp_change or state_change) and not off_to_off)
        change_reason = "fan-level" if fan_level_change else "temp" if ac_temp_change else "state" if state_change else "none"

        print("Time: ", datetime.now())
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
        print("\n---\n")

        state = await api.get_breeze_state()
        thedatetime = datetime.now()

        with open('webapp/static/data.csv', 'a') as f:
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

        if should_change:
            try:
                await api.control_breeze_device(
                    remote,
                    new_state,
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
        with open('webapp/static/data.csv', 'a') as f:
            # append one row to the csv file
            f.write(f'{thedatetime}, {state.state == DeviceState.ON}, {the_temp}\n')

        # write to data.json the current state:
        data_json["is_on"] = state.state == DeviceState.ON
        data_json["temperature"] = the_temp
        with open('webapp/static/data.json', 'w') as f:
            json.dump(data_json, f)



# create the remote manager outside the context for re-using
remote_manager = SwitcherBreezeRemoteManager()
# python scripts/control_device.py control_thermostat          -d <DEVICE_ID> -i "<DEVICE_IP>" -r YACIFBI0 -s on -l 03 -m cool -f high -t 24

key = "05"
deviceID = "<DEVICE_ID>"
remoteID = "YACIFBI0"
IP = "<DEVICE_IP>"

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
