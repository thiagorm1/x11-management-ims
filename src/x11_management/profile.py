"""Profile and ``pro.data`` model for the X11 Mouse hardware protocol.

The binary layout corresponds to the X11 Mouse hardware profile format:
- Header size: 0x28464 bytes (preserved verbatim for perfect firmware/driver compatibility)
- Profile size: 0x80E0 bytes per profile (N profiles supported)
- Button records: 24 buttons * 0x4F8 bytes (18 configurable slots)
"""
from __future__ import annotations

import json
from pathlib import Path
import struct
from typing import Iterable, Sequence

from . import protocol

PROFILE_SIZE = 0x80E0
HEADER_SIZE = 0x28464
BUTTON_SIZE = 0x4F8
BUTTON_COUNT = 24
CONFIGURABLE_BUTTONS = 18
MACRO_EVENT_MAX = 46
POLLING_LABELS = ("125 Hz", "250 Hz", "500 Hz", "1000 Hz")
LIGHT_MODE_LABELS = (
    "LED Off", "Static", "Breathing", "Neon", "Colorful", "Wave",
    "Reactive", "Rainbow", "Ripple", "Laser", "Custom", "Unknown",
)
COLORREF_MAX = 0xFFFFFF


def _u8(data: bytearray, offset: int) -> int:
    return data[offset]


def _set_u8(data: bytearray, offset: int, value: int) -> None:
    data[offset] = value & 0xFF


def _u16(data: bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _set_u16(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<H", data, offset, value & 0xFFFF)


def _u32(data: bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _set_u32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value & 0xFFFFFFFF)


def _i32(data: bytearray, offset: int) -> int:
    return struct.unpack_from("<i", data, offset)[0]


def _set_i32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<i", data, offset, value)


def _wstr(data: bytearray, offset: int, chars: int) -> str:
    raw = bytes(data[offset:offset + chars * 2])
    return raw.decode("utf-16le", errors="replace").split("\x00", 1)[0]


def _set_wstr(data: bytearray, offset: int, chars: int, value: str) -> None:
    encoded = value.encode("utf-16le")[: max(0, chars - 1) * 2]
    data[offset:offset + chars * 2] = encoded + b"\x00" * (chars * 2 - len(encoded))
    data[offset + (chars - 1) * 2:offset + chars * 2] = b"\x00\x00"


class MacroEvent:
    """Represents a single macro event (keyboard scan code, state down/up, delay ms)."""

    def __init__(self, code: int, state: int, delay: int):
        if not 0 <= code <= 0xFF:
            raise ValueError("macro event code must be 0..255")
        if state not in (0, 1):
            raise ValueError("macro event state must be 0 (down) or 1 (up)")
        if not 0 <= delay <= 0xFFFF:
            raise ValueError("macro event delay must be 0..65535 ms")
        self.code = code
        self.state = state
        self.delay = delay

    def to_dict(self) -> dict:
        return {"code": self.code, "state": self.state, "delay": self.delay}

    def __repr__(self) -> str:
        return f"MacroEvent(code=0x{self.code:02X}, state={'UP' if self.state == 1 else 'DOWN'}, delay={self.delay}ms)"


class Button:
    """A view over one 0x4F8-byte hardware button record."""

    def __init__(self, data: bytearray, offset: int, slot: int):
        if len(data) < offset + BUTTON_SIZE:
            raise ValueError("button record outside profile boundary")
        self._data = data
        self._offset = offset
        self.slot = slot

    @property
    def index(self) -> int:
        return _u8(self._data, self._offset + 0x00)

    @index.setter
    def index(self, value: int) -> None:
        _set_u8(self._data, self._offset + 0x00, value)

    @property
    def action(self) -> int:
        return _u8(self._data, self._offset + 0x01)

    @action.setter
    def action(self, value: int) -> None:
        _set_u8(self._data, self._offset + 0x01, value)

    @property
    def parameter(self) -> int:
        return _u8(self._data, self._offset + 0x02)

    @parameter.setter
    def parameter(self, value: int) -> None:
        _set_u8(self._data, self._offset + 0x02, value)

    @property
    def shortcut_modifier(self) -> int:
        return _u8(self._data, self._offset + 0x03)

    @shortcut_modifier.setter
    def shortcut_modifier(self, value: int) -> None:
        _set_u8(self._data, self._offset + 0x03, value)

    @property
    def shortcut_key(self) -> int:
        return _u8(self._data, self._offset + 0x07)

    @shortcut_key.setter
    def shortcut_key(self, value: int) -> None:
        _set_u8(self._data, self._offset + 0x07, value)

    @property
    def constant(self) -> int:
        return _u16(self._data, self._offset + 0x008)

    @constant.setter
    def constant(self, value: int) -> None:
        _set_u16(self._data, self._offset + 0x008, value)

    @property
    def opaque_0c(self) -> int:
        return _u8(self._data, self._offset + 0x00C)

    @opaque_0c.setter
    def opaque_0c(self, value: int) -> None:
        _set_u8(self._data, self._offset + 0x00C, value)

    @property
    def macro_name(self) -> str:
        return _wstr(self._data, self._offset + 0x010, 24)

    @macro_name.setter
    def macro_name(self, value: str) -> None:
        _set_wstr(self._data, self._offset + 0x010, 24, value)

    @property
    def repetitions(self) -> int:
        return _u32(self._data, self._offset + 0x040)

    @repetitions.setter
    def repetitions(self, value: int) -> None:
        _set_u32(self._data, self._offset + 0x040, value)

    @property
    def macro_count(self) -> int:
        return _u32(self._data, self._offset + 0x044)

    @macro_count.setter
    def macro_count(self, value: int) -> None:
        _set_u32(self._data, self._offset + 0x044, value)

    @property
    def macro_index(self) -> int:
        return _i32(self._data, self._offset + 0x430)

    @macro_index.setter
    def macro_index(self, value: int) -> None:
        _set_i32(self._data, self._offset + 0x430, value)

    @property
    def reserved_434(self) -> int:
        return _i32(self._data, self._offset + 0x434)

    @reserved_434.setter
    def reserved_434(self, value: int) -> None:
        _set_i32(self._data, self._offset + 0x434, value)

    @property
    def opaque_43c(self) -> int:
        return _u8(self._data, self._offset + 0x43C)

    @opaque_43c.setter
    def opaque_43c(self, value: int) -> None:
        _set_u8(self._data, self._offset + 0x43C, value)

    @property
    def events(self) -> list[MacroEvent]:
        count = self.macro_count
        if count > MACRO_EVENT_MAX:
            raise ValueError(f"button {self.slot}: macro_count={count} > {MACRO_EVENT_MAX}")
        result = []
        for i in range(count):
            base = self._offset + 0x440 + i * 4
            result.append(MacroEvent(_u8(self._data, base), _u8(self._data, base + 1),
                                     _u16(self._data, base + 2)))
        return result

    def set_events(self, events: Iterable[MacroEvent], repetitions: int = 1) -> None:
        event_list = list(events)
        if len(event_list) > MACRO_EVENT_MAX:
            raise ValueError(f"button {self.slot}: {len(event_list)} events > {MACRO_EVENT_MAX}")
        if not 0 <= repetitions <= 0xFFFFFFFF:
            raise ValueError("repetitions must be an unsigned 32-bit value")
        base = self._offset + 0x440
        self._data[base:base + MACRO_EVENT_MAX * 4] = b"\x00" * (MACRO_EVENT_MAX * 4)
        for i, event in enumerate(event_list):
            off = base + i * 4
            _set_u8(self._data, off, event.code)
            _set_u8(self._data, off + 1, event.state)
            _set_u16(self._data, off + 2, event.delay)
        self.macro_count = len(event_list)
        self.repetitions = repetitions

    def clear_macro(self) -> None:
        self.macro_name = ""
        self.repetitions = 0
        self.macro_count = 0
        base = self._offset + 0x440
        self._data[base:base + MACRO_EVENT_MAX * 4] = b"\x00" * (MACRO_EVENT_MAX * 4)
        self.macro_index = -1

    def to_bytes(self) -> bytes:
        return bytes(self._data[self._offset:self._offset + BUTTON_SIZE])

    def to_dict(self) -> dict:
        return {
            "slot": self.slot,
            "index": self.index,
            "action": self.action,
            "parameter": self.parameter,
            "shortcut_modifier": self.shortcut_modifier,
            "shortcut_key": self.shortcut_key,
            "macro_name": self.macro_name,
            "repetitions": self.repetitions,
            "events": [e.to_dict() for e in self.events],
            "opaque_0c": self.opaque_0c,
            "opaque_43c": self.opaque_43c,
            "macro_index": self.macro_index,
            "reserved_434": self.reserved_434,
        }


class Profile:
    """One 0x80E0-byte hardware profile representation."""

    def __init__(self, data: bytes | bytearray | None = None):
        if data is None:
            self._data = bytearray(PROFILE_SIZE)
        else:
            if len(data) != PROFILE_SIZE:
                raise ValueError(f"profile must be {PROFILE_SIZE} bytes, got {len(data)}")
            self._data = bytearray(data)
        self._buttons = [
            Button(self._data, 0x9A0 + i * BUTTON_SIZE, i + 1)
            for i in range(BUTTON_COUNT)
        ]

    @property
    def data(self) -> bytearray:
        return self._data

    def to_bytes(self) -> bytes:
        return bytes(self._data)

    @property
    def name(self) -> str:
        return _wstr(self._data, 0x000, 100)

    @name.setter
    def name(self, value: str) -> None:
        _set_wstr(self._data, 0x000, 100, value)

    @property
    def buttons(self) -> list[Button]:
        return self._buttons

    @property
    def configurable_buttons(self) -> list[Button]:
        return self._buttons[:CONFIGURABLE_BUTTONS]

    def _get_u32(self, offset: int) -> int:
        return _u32(self._data, offset)

    def _set_u32(self, offset: int, value: int) -> None:
        _set_u32(self._data, offset, value)

    @property
    def brightness(self) -> int:
        return self._get_u32(0x924)

    @brightness.setter
    def brightness(self, value: int) -> None:
        self._set_u32(0x924, value)

    @property
    def effect_speed(self) -> int:
        return self._get_u32(0x928)

    @effect_speed.setter
    def effect_speed(self, value: int) -> None:
        self._set_u32(0x928, value)

    @property
    def sleep_timer_minutes(self) -> int:
        return self._get_u32(0x92C)

    @sleep_timer_minutes.setter
    def sleep_timer_minutes(self, value: int) -> None:
        self._set_u32(0x92C, value)

    @property
    def light_off_minutes(self) -> int:
        return self._get_u32(0x930)

    @light_off_minutes.setter
    def light_off_minutes(self, value: int) -> None:
        self._set_u32(0x930, value)

    @property
    def selected_dpi_index(self) -> int:
        return self._get_u32(0x934)

    @selected_dpi_index.setter
    def selected_dpi_index(self, value: int) -> None:
        self._set_u32(0x934, value)

    @property
    def polling_index(self) -> int:
        return self._get_u32(0x938)

    @polling_index.setter
    def polling_index(self, value: int) -> None:
        self._set_u32(0x938, value)

    @property
    def move_wake(self) -> int:
        return self._get_u32(0x93C)

    @move_wake.setter
    def move_wake(self, value: int) -> None:
        self._set_u32(0x93C, value)

    @property
    def ripple_control(self) -> int:
        return self._get_u32(0x940)

    @ripple_control.setter
    def ripple_control(self, value: int) -> None:
        self._set_u32(0x940, value)

    @property
    def angle_snap(self) -> int:
        return self._get_u32(0x944)

    @angle_snap.setter
    def angle_snap(self, value: int) -> None:
        self._set_u32(0x944, value)

    @property
    def light_mode(self) -> int:
        return self._get_u32(0x94C)

    @light_mode.setter
    def light_mode(self, value: int) -> None:
        self._set_u32(0x94C, value)

    @property
    def ble_light_mode(self) -> int:
        return self._get_u32(0x950)

    @ble_light_mode.setter
    def ble_light_mode(self, value: int) -> None:
        self._set_u32(0x950, value)

    @property
    def key_response_time(self) -> int:
        return self._get_u32(0x958)

    @key_response_time.setter
    def key_response_time(self, value: int) -> None:
        self._set_u32(0x958, value)

    @property
    def light_color(self) -> int:
        return self._get_u32(0x95C)

    @light_color.setter
    def light_color(self, value: int) -> None:
        self._set_u32(0x95C, value & COLORREF_MAX)

    @property
    def lift_off_distance(self) -> int:
        return self._get_u32(0x8B4)

    @lift_off_distance.setter
    def lift_off_distance(self, value: int) -> None:
        self._set_u32(0x8B4, value)

    @property
    def reserved_898(self) -> int:
        return self._get_u32(0x898)

    @reserved_898.setter
    def reserved_898(self, value: int) -> None:
        self._set_u32(0x898, value)

    @property
    def reserved_89c(self) -> int:
        return self._get_u32(0x89C)

    @reserved_89c.setter
    def reserved_89c(self, value: int) -> None:
        self._set_u32(0x89C, value)

    @property
    def reserved_8a0(self) -> int:
        return _u8(self._data, 0x8A0)

    @reserved_8a0.setter
    def reserved_8a0(self, value: int) -> None:
        _set_u8(self._data, 0x8A0, value)

    @property
    def reserved_8a4(self) -> int:
        return self._get_u32(0x8A4)

    @reserved_8a4.setter
    def reserved_8a4(self, value: int) -> None:
        self._set_u32(0x8A4, value)

    @property
    def reserved_8b0(self) -> int:
        return self._get_u32(0x8B0)

    @reserved_8b0.setter
    def reserved_8b0(self, value: int) -> None:
        self._set_u32(0x8B0, value)

    @property
    def reserved_8b8(self) -> int:
        return self._get_u32(0x8B8)

    @reserved_8b8.setter
    def reserved_8b8(self, value: int) -> None:
        self._set_u32(0x8B8, value)

    @property
    def reserved_954(self) -> int:
        return _u8(self._data, 0x954)

    @reserved_954.setter
    def reserved_954(self, value: int) -> None:
        _set_u8(self._data, 0x954, value)

    @staticmethod
    def _array8(data: bytearray, offset: int) -> list[int]:
        return list(struct.unpack_from("<8I", data, offset))

    @staticmethod
    def _set_array8(data: bytearray, offset: int, values: Sequence[int]) -> None:
        vals = list(values)
        if len(vals) != 8:
            raise ValueError("expected exactly 8 values")
        struct.pack_into("<8I", data, offset, *[int(v) & 0xFFFFFFFF for v in vals])

    @property
    def dpi_x(self) -> list[int]:
        return self._array8(self._data, 0x8C4)

    @dpi_x.setter
    def dpi_x(self, values: Sequence[int]) -> None:
        self._set_array8(self._data, 0x8C4, values)

    @property
    def dpi_y(self) -> list[int]:
        return self._array8(self._data, 0x8E4)

    @dpi_y.setter
    def dpi_y(self, values: Sequence[int]) -> None:
        self._set_array8(self._data, 0x8E4, values)

    @property
    def dpi_enabled(self) -> list[int]:
        return self._array8(self._data, 0x904)

    @dpi_enabled.setter
    def dpi_enabled(self, values: Sequence[int]) -> None:
        self._set_array8(self._data, 0x904, values)

    @property
    def dpi_colors(self) -> list[int]:
        return self._array8(self._data, 0x960)

    @dpi_colors.setter
    def dpi_colors(self, values: Sequence[int]) -> None:
        self._set_array8(self._data, 0x960, values)

    @property
    def extra_colors(self) -> list[int]:
        return self._array8(self._data, 0x980)

    @extra_colors.setter
    def extra_colors(self, values: Sequence[int]) -> None:
        self._set_array8(self._data, 0x980, values)

    def dpi_stages(self) -> list[dict]:
        return [
            {
                "index": i,
                "x": self.dpi_x[i],
                "y": self.dpi_y[i],
                "enabled": self.dpi_enabled[i] != 0,
                "color": self.dpi_colors[i],
            }
            for i in range(8)
        ]

    def set_dpi_stage(
        self,
        index: int,
        *,
        x: int | None = None,
        y: int | None = None,
        enabled: bool | None = None,
        color: int | None = None,
    ) -> None:
        if not 0 <= index <= 7:
            raise ValueError("DPI stage index must be 0..7")
        if x is not None:
            values = self.dpi_x
            values[index] = x
            self.dpi_x = values
        if y is not None:
            values = self.dpi_y
            values[index] = y
            self.dpi_y = values
        if enabled is not None:
            values = self.dpi_enabled
            values[index] = 1 if enabled else 0
            self.dpi_enabled = values
        if color is not None:
            values = self.dpi_colors
            values[index] = color & COLORREF_MAX
            self.dpi_colors = values

    @classmethod
    def default(cls, name: str = "Profile1") -> "Profile":
        p = cls()
        p.name = name
        p.reserved_898 = 0x1A4
        p.reserved_89c = 3
        p.reserved_8a0 = 0
        p.reserved_8a4 = 6
        p.reserved_8b0 = 0
        p.lift_off_distance = 0
        p.reserved_8b8 = 0
        p.reserved_954 = 1
        p.selected_dpi_index = 1
        p.polling_index = 3
        p.dpi_x = [8, 0x10, 0x18, 0x20, 0x32, 0xDC, 0, 0]
        p.dpi_y = [8, 0x10, 0x18, 0x20, 0x32, 0xDC, 0, 0]
        p.dpi_enabled = [1, 1, 1, 1, 1, 1, 0, 0]
        p.dpi_colors = [0xFF, 0xFF00, 0xFF0000, 0xFFFF, 0xFFFF00, 0xFF00FF, 0x40FF, 0xFFFFFF]
        p.extra_colors = [0xFF, 0xFF00, 0xFF0000, 0xFF00FF, 0xFFFF, 0xFFFFFF, 0xFFFFFF, 0x80FF]
        p.light_mode = 0
        p.ble_light_mode = 3
        p.brightness = 8
        p.effect_speed = 6
        p.sleep_timer_minutes = 10
        p.light_off_minutes = 1
        p.key_response_time = 4
        p.light_color = 0xFF0000
        p.move_wake = 0
        p.ripple_control = 0
        p.angle_snap = 0

        types = protocol.TABLES["default_button_types"]
        params = protocol.TABLES["default_button_parameters"]
        for i in range(CONFIGURABLE_BUTTONS):
            button = p.buttons[i]
            button.index = i
            button.action = int(types[i]) & 0xFF
            button.parameter = int(params[i]) & 0xFF
            button.constant = 0x232
            button.macro_index = -1
            button.reserved_434 = -1
        return p

    def make_packets(self) -> dict[str, bytes]:
        """Return the logical packets for a full apply, including macros."""
        packets: dict[str, bytes] = {
            "0x0C": bytes([0x0C, 0x0A, 0x01, 0xFE, 0x01, 0xFE, 0, 0, 0, 0]),
            "0x04": protocol.dpi_packet(self._data),
            "0x05": protocol.lighting_packet(self._data),
            "0x06": protocol.polling_packet(self._data),
            "0x08": protocol.button_packet(self._data),
        }
        for i, button in enumerate(self.configurable_buttons):
            if button.action == 0x11:
                packets[f"0x09:{i + 1}"] = protocol.macro_packet(button.to_bytes(), i + 1)
        return packets

    def macro_fragments(self, slot: int, wireless: bool = True) -> list[bytes]:
        if not 1 <= slot <= CONFIGURABLE_BUTTONS:
            raise ValueError("slot must be 1..18")
        packet = protocol.macro_packet(self.buttons[slot - 1].to_bytes(), slot)
        return protocol.fragment_macro(packet, wireless=wireless)

    def validate(self) -> None:
        if int(self.brightness) not in range(1, 9):
            raise ValueError("brightness must be 1..8")
        if int(self.effect_speed) not in range(4, 9):
            raise ValueError("effect_speed must be 4..8")
        if not 1 <= int(self.sleep_timer_minutes) <= 60:
            raise ValueError("sleep_timer_minutes must be 1..60")
        if not 1 <= int(self.light_off_minutes) <= 60:
            raise ValueError("light_off_minutes must be 1..60")
        if not 0 <= int(self.selected_dpi_index) <= 7:
            raise ValueError("selected_dpi_index must be 0..7")
        if not 0 <= int(self.polling_index) <= 3:
            raise ValueError("polling_index must be 0..3")
        if not 0 <= int(self.light_mode) <= 11:
            raise ValueError("light_mode must be 0..11")
        if not 2 <= int(self.key_response_time) <= 25:
            raise ValueError("key_response_time must be 2..25")
        enabled = self.dpi_enabled
        for i, x in enumerate(self.dpi_x):
            if enabled[i] and not 1 <= x <= 220:
                raise ValueError(f"dpi_x[{i}] must be 1..220 (units of 100), got {x}")
            if not 0 <= x <= 220:
                raise ValueError(f"dpi_x[{i}] must be 0..220, got {x}")
        for i, y in enumerate(self.dpi_y):
            if enabled[i] and not 1 <= y <= 220:
                raise ValueError(f"dpi_y[{i}] must be 1..220 (units of 100), got {y}")
            if not 0 <= y <= 220:
                raise ValueError(f"dpi_y[{i}] must be 0..220, got {y}")
        for button in self.configurable_buttons:
            if button.macro_count > MACRO_EVENT_MAX:
                raise ValueError(f"button {button.slot}: macro has too many events")
            if button.action == 0x11:
                protocol.macro_packet(button.to_bytes(), button.slot)
        protocol.dpi_packet(self._data)
        protocol.lighting_packet(self._data)
        protocol.polling_packet(self._data)
        protocol.button_packet(self._data)

    def to_dict(self, include_raw: bool = True) -> dict:
        result = {
            "name": self.name,
            "fields": {
                "brightness": self.brightness,
                "effect_speed": self.effect_speed,
                "sleep_timer_minutes": self.sleep_timer_minutes,
                "light_off_minutes": self.light_off_minutes,
                "selected_dpi_index": self.selected_dpi_index,
                "polling_index": self.polling_index,
                "move_wake": self.move_wake,
                "ripple_control": self.ripple_control,
                "angle_snap": self.angle_snap,
                "light_mode": self.light_mode,
                "ble_light_mode": self.ble_light_mode,
                "key_response_time": self.key_response_time,
                "light_color_colorref": self.light_color,
                "lift_off_distance": self.lift_off_distance,
                "reserved_898": self.reserved_898,
                "reserved_89c": self.reserved_89c,
                "reserved_8a0": self.reserved_8a0,
                "reserved_8a4": self.reserved_8a4,
                "reserved_8b0": self.reserved_8b0,
                "reserved_8b8": self.reserved_8b8,
                "reserved_954": self.reserved_954,
            },
            "dpi": self.dpi_stages(),
            "extra_colors": self.extra_colors,
            "buttons": [b.to_dict() for b in self.buttons],
        }
        if include_raw:
            result["raw_hex"] = self.to_bytes().hex()
        return result

    @classmethod
    def from_dict(cls, value: dict) -> "Profile":
        if value.get("raw_hex"):
            p = cls(bytes.fromhex(value["raw_hex"]))
        else:
            p = cls.default(str(value.get("name") or "Profile1"))
        if value.get("name") is not None:
            p.name = str(value["name"])
        fields = value.get("fields", {})
        for key in (
            "brightness", "effect_speed", "sleep_timer_minutes", "light_off_minutes",
            "selected_dpi_index", "polling_index", "move_wake", "ripple_control",
            "angle_snap", "light_mode", "ble_light_mode", "key_response_time",
            "lift_off_distance", "reserved_898", "reserved_89c", "reserved_8a0",
            "reserved_8a4", "reserved_8b0", "reserved_8b8", "reserved_954",
        ):
            if key in fields:
                setattr(p, key, int(fields[key]))
        if "light_color_colorref" in fields:
            p.light_color = int(fields["light_color_colorref"])
        if value.get("dpi"):
            for stage in value["dpi"]:
                p.set_dpi_stage(
                    int(stage["index"]),
                    x=stage.get("x"),
                    y=stage.get("y"),
                    enabled=stage.get("enabled"),
                    color=stage.get("color"),
                )
        if value.get("extra_colors"):
            p.extra_colors = [int(v) for v in value["extra_colors"]]
        if value.get("buttons"):
            for b in value["buttons"]:
                slot = int(b.get("slot", 0))
                if not 1 <= slot <= BUTTON_COUNT:
                    raise ValueError(f"invalid button slot {slot}")
                button = p.buttons[slot - 1]
                if "action" in b:
                    button.action = int(b["action"])
                if "parameter" in b:
                    button.parameter = int(b["parameter"])
                if "shortcut_modifier" in b:
                    button.shortcut_modifier = int(b["shortcut_modifier"])
                if "shortcut_key" in b:
                    button.shortcut_key = int(b["shortcut_key"])
                if "opaque_0c" in b:
                    button.opaque_0c = int(b["opaque_0c"])
                if "opaque_43c" in b:
                    button.opaque_43c = int(b["opaque_43c"])
                if "macro_index" in b:
                    button.macro_index = int(b["macro_index"])
                if "reserved_434" in b:
                    button.reserved_434 = int(b["reserved_434"])
                if "macro_name" in b:
                    button.macro_name = str(b["macro_name"])
                if "events" in b:
                    events = [
                        MacroEvent(int(e["code"]), int(e["state"]), int(e["delay"]))
                        for e in b["events"]
                    ]
                    button.set_events(events, int(b.get("repetitions", 1)))
        return p


class ProFile:
    """A ``pro.data`` container: opaque header + N profiles."""

    def __init__(
        self,
        profiles: Sequence[Profile] | None = None,
        header: bytes | bytearray | None = None,
    ):
        self.header = bytearray(header if header is not None else b"\x00" * HEADER_SIZE)
        if len(self.header) != HEADER_SIZE:
            raise ValueError(f"header must be {HEADER_SIZE} bytes, got {len(self.header)}")
        self.profiles = list(profiles or [])

    @classmethod
    def default(cls, name: str = "Profile1") -> "ProFile":
        return cls([Profile.default(name)])

    @classmethod
    def load(cls, path: str | Path) -> "ProFile":
        data = Path(path).read_bytes()
        if len(data) < HEADER_SIZE or (len(data) - HEADER_SIZE) % PROFILE_SIZE:
            raise ValueError(
                f"invalid pro.data size {len(data)}; expected {HEADER_SIZE} + N*{PROFILE_SIZE}"
            )
        header = data[:HEADER_SIZE]
        profiles = [
            Profile(data[o:o + PROFILE_SIZE])
            for o in range(HEADER_SIZE, len(data), PROFILE_SIZE)
        ]
        return cls(profiles, header)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = bytearray(self.header)
        for profile in self.profiles:
            payload += profile.to_bytes()
        path.write_bytes(payload)

    @property
    def profile_count(self) -> int:
        return len(self.profiles)

    def profile(self, index: int) -> Profile:
        if not 0 <= index < len(self.profiles):
            raise IndexError(f"profile index {index} out of range 0..{len(self.profiles) - 1}")
        return self.profiles[index]

    def add(self, profile: Profile) -> Profile:
        if len(self.profiles) >= 0xFFFFFFFF:
            raise ValueError("too many profiles")
        self.profiles.append(profile)
        return profile

    def remove(self, index: int) -> Profile:
        if not 0 <= index < len(self.profiles):
            raise IndexError(f"profile index {index} out of range")
        return self.profiles.pop(index)

    def to_dict(self) -> dict:
        return {
            "header_hex": bytes(self.header).hex(),
            "profiles": [p.to_dict() for p in self.profiles],
        }

    @classmethod
    def from_dict(cls, value: dict) -> "ProFile":
        header = bytes.fromhex(value["header_hex"]) if value.get("header_hex") else None
        profiles = [Profile.from_dict(p) for p in value.get("profiles", [])]
        return cls(profiles, header)

    def save_json(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load_json(cls, path: str | Path) -> "ProFile":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
