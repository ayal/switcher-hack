const device = {   
    'device_id': '<DEVICE_ID>',
    'device_key': '03',
    'device_state': <DeviceState.ON: ('01', 'on')>,
    'device_type': <DeviceType.BREEZE: ('Switcher Breeze', '0e01', 2, <DeviceCategory.THERMOSTAT: 3>)>,
    'fan_level': <ThermostatFanLevel.HIGH: ('3', 'high')>,
    'ip_address': '<DEVICE_IP>',
    'last_data_update': datetime.datetime(2024, 7, 22, 20, 36, 34, 832158),
    'mac_address': '<DEVICE_MAC>',
    'mode': <ThermostatMode.COOL: ('04', 'cool')>,
    'name': 'Switcher Breeze_8C01',
    'remote_id': 'YACIFBI0',
    'swing': <ThermostatSwing.OFF: ('0', 'off')>,
    'target_temperature': 21,
    'temperature': 28.7
}

// device ip: <DEVICE_IP>

// python scripts/discover_devices.py
// usage: python scripts/control_device.py get_thermostat_state -d <DEVICE_ID> -i "<DEVICE_IP>" -l 03 -v 
// python scripts/control_device.py control_thermostat          -d <DEVICE_ID> -i "<DEVICE_IP>" -r YACIFBI0 -s on -l 03 -m cool -f high -t 24


// wireshark filter:
// anything that comes out of iphone:
// find out phone ip in network, for example 10.100.102.18
// ip.src == 10.100.102.18 or ip.dst == 10.100.102.18

// anything from iphone to switcher:
// ip.src == 10.100.102.18 and ip.dst == <DEVICE_IP>

// switcher server:
// <SWITCHER_CLOUD_IP> port=9091
// filter:
// ip.src == <SWITCHER_CLOUD_IP> or ip.dst == <SWITCHER_CLOUD_IP>
// payload fef0 2c 000305 030144ee 1b36 a7a70 2 000000 000000000000 4499 c06600000000000000000000f0fe d72141ee
// payload fef0 2c 000305 1715ebef 1b36 37050 1 000000 000000000000 4d9a c06600000000000000000000f0fe 1c571e87
// payload fef0 2c 000305 03011bf1 1b36 78ba0 2 000000 000000000000 cd9a c06600000000000000000000f0fe 43eb9ad6
// payload fef0 2c 000305 01037292 1c36 61020 2 000000 <DEVICE_ID>000000 07dd c06600000000000000000000f0fe 6514ace2

// from server to device:
// payload fef0 78 000305 03011bf1 1b36 78ba0 1 000000<DEVICE_ID>000000 cd9ac 06600000000000000000000f0fe 01039805 cd9ac066004100537769746368657220427265657a655f38433031000000000000000000000000011e0002f6000104153000075941434946424930000000000000000000000000020b4472ea


// get phone id:
// idevice_id -l
// start remote virtual interface:
// rvictl -s phone_id

// change ip address macosx:
// sudo ifconfig en0 inet 10.100.102.18 netmask 255.255.255.0
