"""X11 Management IMS (Integrated Management System).

Complete hardware management and control suite for the X11 Mouse.
Supports 2.4GHz Wireless (FA60), Wired, and BLE (FEE0/FEE3/FEE4).
"""
__version__ = "1.0.0"
__author__ = "IMS Hardware Engineering (Integrated Management System)"

from .protocol import (
    dpi_packet,
    lighting_packet,
    polling_packet,
    button_packet,
    macro_packet,
    fragment_macro,
    decode_input,
)
from .profile import Profile, ProFile, MacroEvent, Button
from .transport import X11Transport, Monitor, Ack, DeviceNotFound, HidError
from .ble import BleTransport, BleDeviceNotFound, BleError
from .engine import apply_profile, build_steps, ApplyStep

__all__ = [
    "dpi_packet",
    "lighting_packet",
    "polling_packet",
    "button_packet",
    "macro_packet",
    "fragment_macro",
    "decode_input",
    "Profile",
    "ProFile",
    "MacroEvent",
    "Button",
    "X11Transport",
    "Monitor",
    "Ack",
    "DeviceNotFound",
    "HidError",
    "BleTransport",
    "BleDeviceNotFound",
    "BleError",
    "apply_profile",
    "build_steps",
    "ApplyStep",
]
