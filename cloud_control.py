"""Direct cloud control for Switcher Breeze AC.

Sends commands through the Switcher cloud server (<SWITCHER_CLOUD_IP>:9091),
bypassing the need for local network access to the device.

Usage:
    python cloud_control.py on                    # Cool 24°C, Medium fan
    python cloud_control.py off                   # Turn off
    python cloud_control.py on --temp 22          # Cool 22°C, Medium fan
    python cloud_control.py on --temp 26 --fan high --mode cool
    python cloud_control.py on --temp 24 --fan low --mode heat

Auth credentials captured from phone app via Wireshark (rvictl).
See CLOUD-CONTROL.md for protocol details.
"""

import argparse
import asyncio
import os
import sys
import time
from binascii import hexlify, unhexlify, crc_hqx
from pathlib import Path
from struct import pack

from dotenv import load_dotenv

from aioswitcher.api.remotes import SwitcherBreezeRemoteManager
from aioswitcher.device import (
    DeviceState,
    ThermostatFanLevel,
    ThermostatMode,
    ThermostatSwing,
)

# Load .env from same directory as this script
load_dotenv(Path(__file__).parent / ".env")

# --- Cloud server ---
CLOUD_IP = os.environ["CLOUD_IP"]
CLOUD_PORT = int(os.environ["CLOUD_PORT"])

# --- Device info ---
DEVICE_ID = os.environ["DEVICE_ID"]
REMOTE_ID = os.environ["REMOTE_ID"]

# --- Captured credentials (via Wireshark rvictl) ---
# See CLOUD-CONTROL.md for details on static vs dynamic regions
PHONE_ID = os.environ["PHONE_ID"]
LOGIN_AUTH = os.environ["LOGIN_AUTH"]
CONTROL_AUTH = os.environ["CONTROL_AUTH"]

# CRC init values (different from local protocol's 0x1021)
CRC2_INIT_LOGIN = 0xB9F9    # for cmd 0232 (login)
CRC2_INIT_CONTROL = 0x4156  # for cmd 0305 (control/keepalive/devlist)

# --- Fan level mapping ---
FAN_LEVELS = {
    "low": ThermostatFanLevel.LOW,
    "medium": ThermostatFanLevel.MEDIUM,
    "high": ThermostatFanLevel.HIGH,
    "auto": ThermostatFanLevel.AUTO,
}

MODES = {
    "cool": ThermostatMode.COOL,
    "heat": ThermostatMode.HEAT,
    "fan": ThermostatMode.FAN,
    "dry": ThermostatMode.DRY,
    "auto": ThermostatMode.AUTO,
}


def ts_hex():
    """Current unix timestamp as 4-byte LE hex string."""
    return hexlify(pack("<I", int(time.time()))).decode()


def cloud_sign(hex_packet, crc2_init):
    """Sign packet with cloud CRC algorithm.

    The cloud protocol uses a two-step CRC-CCITT:
      Step 1: CRC of packet body (init=0x1021) → 2 bytes
      Step 2: CRC of (step1 + 0x30*32) with command-specific init → 2 bytes
    Result: packet + step1_bytes + step2_bytes (4 bytes total)
    """
    data = unhexlify(hex_packet)
    crc1 = pack(">I", crc_hqx(data, 0x1021))
    h1 = hexlify(crc1).decode()
    first_2 = h1[6:8] + h1[4:6]

    key = unhexlify(first_2 + "30" * 32)
    crc2 = pack(">I", crc_hqx(key, crc2_init))
    h2 = hexlify(crc2).decode()
    second_2 = h2[6:8] + h2[4:6]

    return hex_packet + first_2 + second_2


def build_login(seq):
    """Build 204-byte cloud login packet."""
    pkt = (
        "fef0cc00"          # magic + length (204)
        "02320211"          # cmd: login
        "00000000"          # session token (empty for login)
        + f"{seq:02x}00"   # sequence + padding
        + "0100"            # direction: request
        + "00"              # padding
        + PHONE_ID          # 7-byte phone ID
        + ts_hex()          # 4-byte timestamp
        + "00000000000000000000"  # 10-byte padding
        + "f0fe"            # separator
        + LOGIN_AUTH        # 160-byte auth blob
    )
    return cloud_sign(pkt, CRC2_INIT_LOGIN)


def build_control(seq, session_token, breeze_cmd):
    """Build cloud breeze control packet.

    Args:
        seq: packet sequence number
        session_token: 8-char hex session token from login response
        breeze_cmd: SwitcherBreezeCommand from remote manager
    """
    payload = (
        DEVICE_ID + "00"    # 3-byte device ID + padding
        + CONTROL_AUTH      # 38-byte auth
        + "3701"            # command marker
        + breeze_cmd.length # length field (e.g. "b300")
        + breeze_cmd.command  # 00000000 + hex-encoded IR string
    )

    body = (
        "03050102"          # cmd: control
        + session_token     # 4-byte session token
        + f"{seq:02x}00"   # sequence + padding
        + "0100"            # direction: request
        + "0000"            # padding
        + DEVICE_ID         # 3-byte device ID
        + "000000"          # padding
        + ts_hex()          # 4-byte timestamp
        + "00000000000000000000"  # 10-byte padding
        + "f0fe"            # separator
        + payload
    )

    total_len = 2 + 2 + len(unhexlify(body)) + 4  # magic + len + body + crc
    length_hex = hexlify(pack("<H", total_len)).decode()
    pkt = "fef0" + length_hex + body
    return cloud_sign(pkt, CRC2_INIT_CONTROL)


def generate_ir_command(state, mode, temp, fan, current_state):
    """Generate IR command using aioswitcher remote database."""
    mgr = SwitcherBreezeRemoteManager()
    remote = mgr.get_remote(REMOTE_ID)
    return remote.build_command(
        state, mode, temp, fan, ThermostatSwing.OFF, current_state
    )


def build_get_state(seq, session_token):
    """Build the cloud 'get device state' request (cmd 03050103)."""
    body = (
        "03050103"          # cmd: get state
        + session_token     # 4-byte session token
        + f"{seq:02x}00"   # sequence + padding
        + "0100"            # direction: request
        + "0000"            # padding
        + DEVICE_ID         # 3-byte device ID
        + "000000"          # padding
        + ts_hex()          # 4-byte timestamp
        + "00000000000000000000"  # 10-byte padding
        + "f0fe"            # separator
        + DEVICE_ID         # payload: device ID
        + "00"
    )
    total_len = 2 + 2 + len(unhexlify(body)) + 4
    length_hex = hexlify(pack("<H", total_len)).decode()
    return cloud_sign("fef0" + length_hex + body, CRC2_INIT_CONTROL)


# Field encodings inside the cloud state response (reverse-engineered, offsets
# relative to the byte after the 'f0fe' separator in the inner 0103 message).
_MODE_BY_HEX = {0x04: ThermostatMode.COOL, 0x01: ThermostatMode.AUTO,
                0x02: ThermostatMode.DRY, 0x03: ThermostatMode.FAN,
                0x05: ThermostatMode.HEAT}
_FAN_BY_BYTE = {0x30: ThermostatFanLevel.AUTO, 0x31: ThermostatFanLevel.LOW,
                0x32: ThermostatFanLevel.MEDIUM, 0x33: ThermostatFanLevel.HIGH}


async def cloud_get_state():
    """Fetch current device state from the Switcher cloud — no LAN access needed.

    Returns a dict {temperature, state, target_temperature, mode, fan} or None.
    Note: fan is best-effort (the cloud's view of fan is unreliable for this
    open-loop IR device); don't use it for control decisions.
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(CLOUD_IP, CLOUD_PORT), timeout=10)
    except Exception as e:
        print("cloud_get_state: connect failed:", e)
        return None
    try:
        writer.write(unhexlify(build_login(1)))
        await writer.drain()
        login = await asyncio.wait_for(reader.read(4096), timeout=5)
        token = hexlify(login).decode()[16:24]
        if len(token) < 8:
            return None
        writer.write(unhexlify(build_get_state(2, token)))
        await writer.drain()
        data = b""
        for _ in range(6):
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=3)
            except asyncio.TimeoutError:
                break
            if not chunk:
                break
            data += chunk
        h = hexlify(data).decode()
        i = h.find("f0fe")
        while i >= 0:
            p = h[i + 4:]
            if p[:4] == "0103":            # device-state response
                b = bytes.fromhex(p)
                if len(b) >= 53:
                    return {
                        "temperature": int.from_bytes(b[47:49], "little") / 10,
                        "state": DeviceState.ON if b[49] == 1 else DeviceState.OFF,
                        "mode": _MODE_BY_HEX.get(b[50]),
                        "target_temperature": b[51],
                        "fan": _FAN_BY_BYTE.get(b[52]),
                    }
            i = h.find("f0fe", i + 4)
        return None
    finally:
        writer.close()
        await writer.wait_closed()


async def cloud_control(action, temp=24, fan="medium", mode="cool"):
    """Send AC control command via Switcher cloud.

    Args:
        action: "on" or "off"
        temp: target temperature (16-30)
        fan: fan level (low/medium/high/auto)
        mode: thermostat mode (cool/heat/fan/dry/auto)
    """
    # Generate IR command
    state = DeviceState.ON if action == "on" else DeviceState.OFF
    current = DeviceState.OFF if action == "on" else DeviceState.ON
    fan_level = FAN_LEVELS.get(fan, ThermostatFanLevel.MEDIUM)
    thermo_mode = MODES.get(mode, ThermostatMode.COOL)
    breeze_cmd = generate_ir_command(state, thermo_mode, temp, fan_level, current)

    print(f"Connecting to {CLOUD_IP}:{CLOUD_PORT}...")
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(CLOUD_IP, CLOUD_PORT), timeout=10
    )
    print("Connected!")

    try:
        seq = 0x01

        # --- Login ---
        print("Logging in...")
        writer.write(unhexlify(build_login(seq)))
        await writer.drain()

        resp = b""
        try:
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5)
                if not chunk:
                    break
                resp += chunk
                if len(resp) >= 4:
                    expected = int.from_bytes(resp[2:4], "little")
                    if len(resp) >= expected:
                        break
        except asyncio.TimeoutError:
            pass

        if len(resp) < 32:
            print(f"Login failed: short response ({len(resp)} bytes)")
            print(f"  Hex: {hexlify(resp).decode()}")
            return False

        resp_hex = hexlify(resp).decode()
        session_token = resp_hex[16:24]
        status = resp_hex[30:32]

        if status != "00":
            print(f"Login failed: error code {status}")
            print(f"  (credentials may have expired, recapture with Wireshark)")
            return False

        print(f"Login OK (session: {session_token})")
        seq += 1
        await asyncio.sleep(0.2)

        # --- Control ---
        desc = f"{action.upper()}"
        if action == "on":
            desc += f" {mode} {temp}°C fan={fan}"
        print(f"Sending: {desc}...")

        writer.write(unhexlify(build_control(seq, session_token, breeze_cmd)))
        await writer.drain()

        ctrl_resp = b""
        try:
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=10)
                if not chunk:
                    break
                ctrl_resp += chunk
                if len(ctrl_resp) >= 4:
                    expected = int.from_bytes(ctrl_resp[2:4], "little")
                    if len(ctrl_resp) >= expected:
                        break
        except asyncio.TimeoutError:
            pass

        if not ctrl_resp:
            print("No response (timeout)")
            return False

        ctrl_hex = hexlify(ctrl_resp).decode()
        ctrl_status = ctrl_hex[30:32] if len(ctrl_resp) >= 16 else "??"

        if ctrl_status == "00":
            print(f">>> AC {desc} — SUCCESS <<<")
            return True
        else:
            print(f"Command failed: error {ctrl_status}")
            return False

    finally:
        writer.close()
        await writer.wait_closed()


def main():
    parser = argparse.ArgumentParser(
        description="Control Switcher Breeze AC via cloud"
    )
    parser.add_argument("action", choices=["on", "off"], help="Turn AC on or off")
    parser.add_argument("--temp", type=int, default=24, help="Temperature (16-30, default: 24)")
    parser.add_argument("--fan", choices=["low", "medium", "high", "auto"], default="medium")
    parser.add_argument("--mode", choices=["cool", "heat", "fan", "dry", "auto"], default="cool")
    args = parser.parse_args()

    if args.temp < 16 or args.temp > 30:
        print("Temperature must be 16-30")
        sys.exit(1)

    success = asyncio.run(cloud_control(args.action, args.temp, args.fan, args.mode))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
