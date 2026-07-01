# Switcher Breeze Cloud Control

Direct control of Switcher Breeze AC via the Switcher cloud server — no local network access, no RPi, no tunnel required.

## Quick Start

```bash
python cloud_control.py on                         # Cool 24°C, medium fan
python cloud_control.py off                        # Turn off
python cloud_control.py on --temp 22               # Cool 22°C
python cloud_control.py on --temp 26 --fan high    # Cool 26°C, high fan
python cloud_control.py on --mode heat --temp 24   # Heat 24°C
```

## How It Works

The official Switcher phone app controls the AC through a cloud relay server. We reverse-engineered the protocol by capturing traffic from the iPhone app using Wireshark (`rvictl`).

### Architecture

```
Phone App ──TCP──> Switcher Cloud (<SWITCHER_CLOUD_IP>:9091) ──TCP──> AC Device
                          ^
Our Script ──TCP──┘       (same protocol, same server)
```

The cloud server acts as a relay — the phone (or our script) connects to it, authenticates, and sends IR commands that get forwarded to the device.

### Protocol Flow

1. **TCP Connect** to `<SWITCHER_CLOUD_IP>:9091`
2. **Login** (204-byte packet) — encrypted credentials → server returns 4-byte session token
3. **Control** (266-byte packet) — session token + device ID + IR command → server relays to device
4. **Response** (44-byte packet) — success/error status

### Packet Format

All packets share a common header:

```
Offset  Size  Field
0       2     Magic: 0xFEF0
2       2     Length (little-endian, includes magic+length+body+crc)
4       2     Command prefix (0x0232 for login, 0x0305 for control)
6       2     Sub-command
8       4     Session token (0x00000000 for login request, assigned by server in response)
12      1     Sequence number (increments per packet)
13      1     Padding (0x00)
14      2     Direction: 0x0100 = request, 0x0200 = response
...           Command-specific fields
N-2     2     Separator: 0xF0FE
...           Payload
Last 4  4     CRC (two-step CRC-CCITT)
```

### CRC Algorithm

The cloud protocol uses a modified two-step CRC-CCITT, different from the local protocol:

```python
def cloud_sign(hex_packet, crc2_init):
    # Step 1: Standard CRC-CCITT of packet body (init=0x1021)
    crc1 = crc_hqx(packet_bytes, 0x1021)  # → 2 bytes (byte-swapped)

    # Step 2: CRC-CCITT of (crc1 + 0x30*32) with COMMAND-SPECIFIC init
    crc2 = crc_hqx(crc1_bytes + b'\x30'*32, crc2_init)  # → 2 bytes

    # Result: packet + crc1 + crc2 (4 bytes appended)
```

**CRC init values by command type:**
| Command | Init Value | Used For |
|---------|-----------|----------|
| 0x0232  | 0xB9F9    | Login packets |
| 0x0305  | 0x4156    | Control, keepalive, device list |

The local `aioswitcher` protocol uses `0x1021` for both steps.

### Login Packet (204 bytes)

```
Header (40 bytes):
  fef0cc00          Magic + length
  02320211          Command: login
  00000000          Session token (empty)
  {seq}00           Sequence + padding
  0100              Direction: request
  00                Padding
  {phone_id}        7-byte phone/session identifier
  {timestamp}       4-byte LE unix timestamp
  0000...           10-byte padding
  f0fe              Separator

Payload (160 bytes):
  {login_auth}      Encrypted credentials

CRC (4 bytes)
```

The 160-byte login auth blob has three regions:
- **Bytes 0–111** (112 bytes): Static — derived from account credentials
- **Bytes 112–127** (16 bytes): **Dynamic** — changes per session (likely encrypted timestamp/nonce)
- **Bytes 128–159** (32 bytes): Static

**The dynamic 16 bytes are the key limitation.** They must be captured fresh from the phone app via Wireshark. Their expiration period is unknown (could be days to months).

### Control Packet (266 bytes)

```
Header (40 bytes):
  fef00a01          Magic + length (266)
  03050102          Command: control
  {session}         4-byte session token (from login response)
  {seq}00           Sequence + padding
  0100              Direction: request
  0000              Padding
  {device_id}       3-byte device ID (e.g. <DEVICE_ID>)
  000000            Padding
  {timestamp}       4-byte LE unix timestamp
  0000...           10-byte padding
  f0fe              Separator

Payload:
  {device_id}00     3-byte device ID + padding
  {control_auth}    38-byte control auth (fully static)
  3701              Command marker
  {length}          IR command length field (e.g. b300)
  {command}         00000000 + hex-encoded IR string (NECX|...)

CRC (4 bytes)
```

The IR command string (`NECX|26|32|...`) is the same format used by `aioswitcher` for local control. It's generated from the remote database based on device type, temperature, mode, fan level, etc.

### Login Response (332 bytes)

```
Header (40 bytes):
  Same structure as request
  Session token at bytes 8-11 — USE THIS for subsequent packets
  Status at byte 15: 0x00 = success, other = error

Payload (288 bytes):
  Encrypted session data
```

### Device List Response (618 bytes)

After login, the app periodically requests device lists (cmd `0x0543`). The response contains JSON:

```json
{
  "VersionNo": 6,
  "DevList": [{
    "DeviceType": "0E01",
    "DID": 12018046,
    "DeviceName": "Switcher Breeze_8C01",
    "OnlineStatus": 1,
    "WorkStatus": "base64-encoded-state",
    "FirmwareMark": "S209-IR0",
    "FirmwareVersion": "0214"
  }]
}
```

## Credentials

### Static (never change)
- **Phone ID**: `<PHONE_ID>` — identifies the phone/app installation
- **Control auth** (38 bytes): Used in every control packet, identical across sessions
- **Login auth static regions** (144 bytes): Account-derived, persist across sessions

### Dynamic (require refresh)
- **Login auth dynamic bytes** (16 bytes at offset 112–127): Rotate per session
- **Session token** (4 bytes): Assigned by server on each login, used for that connection only

## Refreshing Credentials

When the dynamic login bytes expire, recapture from the phone:

```bash
# 1. Get iPhone UDID
idevice_id -l

# 2. Create virtual interface (iPhone must be connected via USB)
rvictl -s <UDID>

# 3. Capture traffic to Switcher cloud
tshark -i rvi0 -f "host <SWITCHER_CLOUD_IP>" -w /tmp/capture.pcapng -a duration:120

# 4. Force-close Switcher app, reopen it, toggle AC

# 5. Find the 204-byte login packet (first data packet from phone)
tshark -r /tmp/capture.pcapng -T fields -e data.data -Y "tcp.len == 204"

# 6. Extract bytes 120-151 (hex positions 240-303) from the login payload
#    (16 bytes starting at auth blob offset 112, which is packet offset 152)

# 7. Update LOGIN_AUTH in cloud_control.py with the new 16 dynamic bytes

# 8. Clean up
rvictl -x <UDID>
```

## Reverse Engineering Notes

### Discovery Process

1. **mitmproxy** — captured HTTP traffic to `il-papi.ogemray-server.com` (metadata API with Token/UID), but control commands bypassed HTTP proxy (raw TCP)
2. **Wireshark via rvictl** — captured raw TCP to `<SWITCHER_CLOUD_IP>:9091`, revealing the full binary protocol
3. **Two captures** — diffing two sessions revealed which bytes are static vs dynamic
4. **CRC brute-force** — discovered the cloud uses different CRC init values than the local protocol by brute-forcing the init parameter

### Key Differences: Cloud vs Local Protocol

| Feature | Local (aioswitcher) | Cloud |
|---------|-------------------|-------|
| Server | Device IP on LAN | <SWITCHER_CLOUD_IP>:9091 |
| Login cmd | 0x0305/a600 (48 bytes) | 0x0232/0211 (204 bytes) |
| Control cmd | 0x0305/0102 | 0x0305/0102 (same!) |
| Auth | device_key + phone_id + password | 160-byte encrypted blob |
| CRC step 2 init | 0x1021 | 0xB9F9 (login) / 0x4156 (control) |
| Session token | Not used | Assigned by server on login |
| IR commands | Same NECX format | Same NECX format |

### Ogemray Cloud Infrastructure

Switcher devices are manufactured by a Chinese OEM. The cloud infrastructure is:
- **Control server**: `<SWITCHER_CLOUD_IP>:9091` — raw TCP, binary protocol
- **Metadata API**: `il-papi.ogemray-server.com` — HTTP REST, JSON with Token/UID
- **Device connection**: Devices maintain persistent TCP to the same cloud server
