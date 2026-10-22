"""X11 hardware packet encoders and decoders.

Implementation of the X11 Mouse hardware protocol.
Provides packet generation for:
- 0x04: DPI configuration (stages, values, colors)
- 0x05: Lighting configuration (mode, speed, brightness, RGB color)
- 0x06: Polling rate (125, 250, 500, 1000 Hz)
- 0x08: Button mapping and shortcuts
- 0x09: Macro records and wireless fragmenter
- 0x0C: Full initialization sequence prefix
- 0x03: Input report decoder (battery, charging, link status, ACK)
"""
from __future__ import annotations

import json
from pathlib import Path
import struct

_TABLES_PATH = Path(__file__).resolve().parent / "tables.json"
if not _TABLES_PATH.exists():
    _TABLES_PATH = Path(__file__).resolve().parents[2] / "assets" / "tables.json"

if _TABLES_PATH.exists():
    TABLES = json.loads(_TABLES_PATH.read_text(encoding="utf-8"))
else:
    raise FileNotFoundError(f"Could not locate tables.json at {_TABLES_PATH}")


def uint(data: bytes | bytearray, offset: int) -> int:
    """Read a 32-bit unsigned little-endian integer."""
    return struct.unpack_from("<I", data, offset)[0]


def checksum(packet: bytearray, end: int) -> bytes:
    """Calculate and append 16-bit big-endian sum checksum."""
    packet[end:end + 2] = (sum(packet[3:end]) & 0xFFFF).to_bytes(2, "big")
    return bytes(packet)


def dpi_packet(profile: bytes | bytearray) -> bytes:
    """Generate the 56-byte report for DPI stages and colors (Command 0x04)."""
    p = bytearray(56)
    p[:3] = bytes([4, 56, 1])
    p[3:5] = bytes([profile[0x944], profile[0x940]])
    for i in range(8):
        if uint(profile, 0x904 + i * 4) == 1:
            p[5] |= 1 << i
        n = profile[0x8C4 + i * 4]  # Low byte of DPI stage setting
        if n <= 100:
            index = n * 2 - 1
        elif n <= 120:
            index = n + 99
        elif n <= 200:
            index = n - 1
        else:
            index = (n - 200) // 2 + 199
        if n > 120:
            p[6] |= 1 << i
            p[7] |= 1 << i
        if index >= 0:
            p[8 + i] = TABLES["dpi_lookup"][index] & 255
            p[16 + i] = int(101 <= n <= 120 or n >= 201)
        p[25 + i * 3:28 + i * 3] = profile[0x960 + i * 4:0x963 + i * 4]
    p[24] = (profile[0x934] + 1) & 255
    p[49] = 2
    return checksum(p, 50)


def lighting_packet(profile: bytes | bytearray) -> bytes:
    """Generate the 15-byte report for lighting parameters (Command 0x05)."""
    p = bytearray(15)
    mode, speed, sleep = (uint(profile, o) for o in (0x94C, 0x928, 0x92C))
    brightness = profile[0x924] if mode in (1, 5) else 8
    p[:3] = bytes([5, 15, 1])
    p[3] = (mode << 4) & 255
    p[4] = ((sleep & 0xF0) | (9 - speed)) & 255
    p[5] = ((sleep << 4) | brightness) & 255
    p[6:9] = profile[0x95C:0x95F]
    p[9] = profile[0x930]
    p[10] = profile[0x958]
    return checksum(p, 11)


def polling_packet(profile: bytes | bytearray) -> bytes:
    """Generate the 9-byte report for polling rate (Command 0x06)."""
    index = uint(profile, 0x938)
    value = {0: 8, 1: 4, 2: 2, 3: 1}.get(index, 2)
    return bytes([6, 9, 1, value, value ^ 255, 0, 0, 0, 0])


def button_packet(profile: bytes | bytearray) -> bytes:
    """Generate the 59-byte report for button mappings and shortcuts (Command 0x08)."""
    p = bytearray(59)
    p[:3] = bytes([8, 59, 1])
    rows = {r[0]: bytes(v & 255 for v in r[1:4]) for r in TABLES["action_rows_u32"]}
    for i in range(18):
        offset = 0x9A0 + i * 0x4F8
        action = profile[offset + 1]
        triple = bytearray(rows.get(action, b"\0\0\0"))
        if action == 0x10:  # Keyboard shortcut
            triple[1:] = bytes([profile[offset + 7], profile[offset + 3]])
        elif action == 0x11:  # Macro
            triple[1:] = bytes([0, i + 1])
        p[3 + i * 3:6 + i * 3] = triple
    return checksum(p, 57)


def macro_packet(record: bytes | bytearray, slot: int) -> bytes:
    """Generate the 131-byte macro payload for a button slot (Command 0x09)."""
    if len(record) != 0x4F8 or not 1 <= slot <= 18:
        raise ValueError("Expected a button record of 0x4F8 bytes and slot 1..18")
    count = struct.unpack_from("<H", record, 0x44)[0]
    if count > 46:
        raise ValueError("More than 46 source events")
    p = bytearray(131)
    p[:3] = bytes([9, 131, slot])
    p[3] = record[0xC]
    p[4:7] = bytes([record[0x43C]]) * 3
    p[7] = record[0x40] or 1
    events = bytearray()
    extensions = 0
    for i in range(count):
        code, state, delay = struct.unpack_from("<BBH", record, 0x440 + i * 4)

        def event(d: int) -> bytes:
            return bytes([((max(d, 1) + 5) // 10 | (1 if state == 1 else 0x81)) & 255, code])

        if delay >= 1271:
            events += event(delay % 200)
            if extensions < 10:
                events += bytes([(delay // 200) & 255, 3])
                extensions += 1
            else:
                events += event(delay % 200)
        else:
            events += event(delay)

    if len(events) > 100:
        raise ValueError("Expanded events overlap the checksum area")
    p[28] = (count + extensions) & 255
    p[29:29 + len(events)] = events
    return checksum(p, 129)


def fragment_macro(packet: bytes | bytearray, wireless: bool = False) -> list[bytes]:
    """Split a 131-byte logical macro packet into 3 transmission chunks."""
    if len(packet) != 131 or packet[0] != 9:
        raise ValueError("Expected macro logical packet of length 131")
    payload = packet[3:] + bytes(52)
    return [
        bytes([9, 12 if wireless and i == 2 else 64, packet[2], i]) + payload[i * 60:(i + 1) * 60]
        for i in range(3)
    ]


def decode_input(report: bytes | bytearray) -> dict:
    """Decode a 5-byte input report (0x03 0x55 <event> <value LE16>)."""
    if len(report) != 5 or report[:2] != b"\x03\x55":
        raise ValueError("Expected 03 55 <event> <value LE16>")
    value = int.from_bytes(report[3:], "little")
    event = report[2]
    result: dict = {"event": event, "value": value}
    if event == 0x10:
        result.update(kind="dpi", slot_one_based=value)
    elif event == 0x20:
        result.update(kind="polling", raw_index=value)
    elif event == 0x40:
        result.update(kind="power", status=value & 255, percent=value >> 8)
    elif event == 0x50:
        result.update(kind="ack", accepted=(value & 255) == 0)
    elif event == 0x60:
        result.update(kind="power_level", level=value)
    elif event == 0x70:
        result.update(kind="lighting", mode=(value >> 4) & 15)
    elif event == 0x80:
        result.update(kind="device_state", value=value)
    else:
        result["kind"] = "unresolved"
    return result
