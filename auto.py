

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

last_force_on = None
last_force_off = None

async def control_breeze_x(device_ip, device_id, device_key, remote_manager, remote_id) :
    # for connecting to a device we need its id, login key and ip address
    async with SwitcherType2Api(device_ip, device_id, device_key) as api:
        # read current data from json:
        data_json = {}
        with open('webapp/static/data.json', 'r') as f:
            data_json = json.load(f)

        state = await api.get_breeze_state()
        remote = remote_manager.get_remote(remote_id)

        # sometimes the device state is wrong so we need to force the device to turn on or off if temperature is too high or too low
        # only force if last force was more than 15 minutes ago
        # force_on = data_json["too_hot_temp"] + 1 < state.temperature
        # force_off = state.temperature < data_json["too_cold_temp"] - 1
        turn_on_temp =  data_json["too_cold_temp"]
        if turn_on_temp > 25:
            turn_on_temp = 25

        very_hot_delta = state.temperature - data_json["too_hot_temp"]
        fan_level = ThermostatFanLevel.LOW
        if very_hot_delta > 1:
            fan_level = ThermostatFanLevel.MEDIUM
            turn_on_temp -= 1
        if very_hot_delta > 2:
            fan_level = ThermostatFanLevel.HIGH
            turn_on_temp -= 1
        if very_hot_delta < 0:
            fan_level = ThermostatFanLevel.LOW


        print("\n---\n")

        new_state = state.state
        if data_json["too_hot_temp"] < state.temperature:
            print("Too hot", data_json["too_hot_temp"], "is hotter than", state.temperature)
            if state.state != DeviceState.ON:
                print("Turning on!")
                new_state = DeviceState.ON
        if data_json["too_cold_temp"] > state.temperature:
            print("Too cold", data_json["too_cold_temp"], "is colder than", state.temperature)
            if state.state != DeviceState.OFF:
                print("Turning off!")
                new_state = DeviceState.OFF


        fan_level_change = fan_level != state.fan_level
        temp_change = turn_on_temp != state.target_temperature
        state_change = new_state != state.state
        off_to_off = state.state == DeviceState.OFF and new_state == DeviceState.OFF

        should_change = ((fan_level_change or temp_change or state_change) and not off_to_off)
        change_reason = "fan level" if fan_level_change else "temp" if temp_change else "state" if state_change else "none"

        print("Time: ", datetime.now())
        print(f"Current state: {state.state}")
        print(f"Current fan level: {state.fan_level}")
        print(f"Current temp: {state.temperature}")
        print(f"Too hot temp: {data_json['too_hot_temp']}", f"Too cold temp: {data_json['too_cold_temp']}")
        print(f"Temp delta: {very_hot_delta}")
        print(f"Turn on temp: {turn_on_temp}", f"Temp change: {temp_change}", f"from {state.target_temperature} to {turn_on_temp}" if temp_change else "")
        print(f"Fan level: {fan_level}", f"Fan level change: {fan_level_change}")
        print(f"New state: {new_state}", f"State change: {state_change}")
        print(f"Off to off: {off_to_off}")
        print(f"Should change: {should_change}", "change reason: ", "none" if not should_change else change_reason)
        print("\n---\n")

        state = await api.get_breeze_state()
        thedatetime = datetime.now()

        with open('webapp/static/data.csv', 'a') as f:
            # append one row to the csv file
            f.write(f'{thedatetime}, {state.state == DeviceState.ON}, {state.temperature}\n')

        # write to data.json the current state:
        data_json["is_on"] = state.state == DeviceState.ON
        data_json["temperature"] = state.temperature
        with open('webapp/static/data.json', 'w') as f:
            json.dump(data_json, f)

        if data_json.get("auto", False) == False:
            print("\n\nAuto mode is off\n\n")
            return

        if should_change:
            try:
                await api.control_breeze_device(
                    remote,
                    new_state,
                    ThermostatMode.COOL,
                    turn_on_temp,
                    fan_level,
                    ThermostatSwing.OFF,
                )
            except Exception as e:
                print(f"Error: {e}")

        # sleep for 5 seconds to allow the device to process the command
        await asyncio.sleep(5)

        state = await api.get_breeze_state()

        thedatetime = datetime.now()
        with open('webapp/static/data.csv', 'a') as f:
            # append one row to the csv file
            f.write(f'{thedatetime}, {state.state == DeviceState.ON}, {state.temperature}\n')

        # write to data.json the current state:
        data_json["is_on"] = state.state == DeviceState.ON
        data_json["temperature"] = state.temperature
        with open('webapp/static/data.json', 'w') as f:
            json.dump(data_json, f)



# create the remote manager outside the context for re-using
remote_manager = SwitcherBreezeRemoteManager()
# python scripts/control_device.py control_thermostat          -d 7e61b7 -i "10.100.102.44" -r YACIFBI0 -s on -l 03 -m cool -f high -t 24

index = 0
async def main():
    while True:
        await control_breeze_x("10.100.102.44", "7e61b7", "03", remote_manager, "YACIFBI0")
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
