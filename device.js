const device = {   
    'device_id': '7e61b7',
    'device_key': '03',
    'device_state': <DeviceState.ON: ('01', 'on')>,
    'device_type': <DeviceType.BREEZE: ('Switcher Breeze', '0e01', 2, <DeviceCategory.THERMOSTAT: 3>)>,
    'fan_level': <ThermostatFanLevel.HIGH: ('3', 'high')>,
    'ip_address': '10.100.102.44',
    'last_data_update': datetime.datetime(2024, 7, 22, 20, 36, 34, 832158),
    'mac_address': '2C:08:F9:E0:77:8C',
    'mode': <ThermostatMode.COOL: ('04', 'cool')>,
    'name': 'Switcher Breeze_8C01',
    'remote_id': 'YACIFBI0',
    'swing': <ThermostatSwing.OFF: ('0', 'off')>,
    'target_temperature': 21,
    'temperature': 28.7
}

// python scripts/discover_devices.py
// usage: python scripts/control_device.py get_thermostat_state -d 7e61b7 -i "10.100.102.44" -l 03 -v 
// python scripts/control_device.py control_thermostat          -d 7e61b7 -i "10.100.102.44" -r YACIFBI0 -s on -l 03 -m cool -f high -t 24
