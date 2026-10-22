"""Windows native HID transport for the X11 Mouse receiver.

Uses Windows native APIs (``hid.dll``, ``setupapi.dll``, ``kernel32.dll``) via ``ctypes``.
No external C dependencies or drivers required.

Validated endpoints:
- col04: Configuration feature collection (HidD_SetFeature, Report ID 134 / 0x86)
- col03: Status and ACK input collection (ReadFile overlapped, Report ID 0x03)
"""
from __future__ import annotations

import ctypes
import re
import struct
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import protocol

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
DIGCF_PRESENT = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258


class DeviceNotFound(RuntimeError):
    """Raised when the requested HID collections are not present."""


class HidError(OSError):
    """Raised when a HID/Windows call fails."""


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.c_size_t),
    ]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


_hid = ctypes.WinDLL("hid", use_last_error=True)
_setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
_hid.HidD_GetHidGuid.restype = None
_hid.HidD_SetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
_hid.HidD_SetFeature.restype = wintypes.BOOL
_hid.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
_hid.HidD_GetFeature.restype = wintypes.BOOL

_setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD
]
_setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)
]
_setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
]
_setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
_setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

_kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE
]
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.ReadFile.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)
]
_kernel32.ReadFile.restype = wintypes.BOOL
_kernel32.GetOverlappedResult.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
    ctypes.POINTER(wintypes.DWORD), wintypes.BOOL
]
_kernel32.GetOverlappedResult.restype = wintypes.BOOL
_kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)]
_kernel32.CancelIoEx.restype = wintypes.BOOL
_kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


def _last_error() -> int:
    return ctypes.get_last_error()


def _check_handle(handle: wintypes.HANDLE, what: str) -> wintypes.HANDLE:
    if not handle or handle == wintypes.HANDLE(-1).value:
        raise HidError(_last_error(), f"{what} failed")
    return handle


@dataclass
class HidPaths:
    vid: int
    pid: int
    paths: dict[int, str] = field(default_factory=dict)

    def collection(self, number: int) -> str:
        try:
            return self.paths[number]
        except KeyError as exc:
            available = ", ".join(f"col{n:02d}" for n in sorted(self.paths)) or "none"
            raise DeviceNotFound(
                f"VID_{self.vid:04X}&PID_{self.pid:04X} collection {number} not found "
                f"(available: {available})"
            ) from exc

    @property
    def config(self) -> str:
        return self.collection(4)

    @property
    def monitor(self) -> str:
        return self.collection(3)


def find_hid_paths(vid: int = 0x1D57, pid: int = 0xFA60) -> HidPaths:
    """Enumerate present HID interfaces and group them by collection number."""
    guid = GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(guid))
    device_set = _setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    )
    _check_handle(device_set, "SetupDiGetClassDevsW")
    result = HidPaths(vid=vid, pid=pid)
    try:
        index = 0
        while True:
            interface = SP_DEVICE_INTERFACE_DATA()
            interface.cbSize = ctypes.sizeof(interface)
            if not _setupapi.SetupDiEnumDeviceInterfaces(
                device_set, None, ctypes.byref(guid), index, ctypes.byref(interface)
            ):
                break
            required = wintypes.DWORD(0)
            _setupapi.SetupDiGetDeviceInterfaceDetailW(
                device_set, ctypes.byref(interface), None, 0, ctypes.byref(required), None
            )
            if required.value:
                buffer = ctypes.create_string_buffer(required.value)
                ctypes.memset(buffer, 0, required.value)
                cb_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                struct.pack_into("<I", buffer, 0, cb_size)
                if _setupapi.SetupDiGetDeviceInterfaceDetailW(
                    device_set, ctypes.byref(interface), buffer, required.value,
                    ctypes.byref(required), None
                ):
                    path = ctypes.wstring_at(ctypes.addressof(buffer) + 4)
                    lower = path.lower()
                    if f"vid_{vid:04x}&pid_{pid:04x}" in lower:
                        match = re.search(r"&col(\d+)", lower)
                        if match:
                            result.paths.setdefault(int(match.group(1)), path)
            index += 1
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(device_set)
    return result


class HidDevice:
    """A single HID collection handle."""

    def __init__(self, path: str, *, overlapped: bool = False, read_write: bool = True):
        self.path = path
        access = (GENERIC_READ | GENERIC_WRITE) if read_write else GENERIC_READ
        flags = FILE_FLAG_OVERLAPPED if overlapped else 0
        self.handle = _kernel32.CreateFileW(
            path, access, FILE_SHARE_READ | FILE_SHARE_WRITE, None,
            OPEN_EXISTING, flags, None
        )
        if not self.handle or self.handle == wintypes.HANDLE(-1).value:
            raise HidError(_last_error(), f"CreateFileW({path}) failed")
        self.overlapped = overlapped

    def set_feature(self, data: bytes) -> None:
        if not data:
            raise ValueError("empty feature report")
        buffer = ctypes.create_string_buffer(data, len(data))
        if not _hid.HidD_SetFeature(self.handle, buffer, len(data)):
            raise HidError(_last_error(), f"HidD_SetFeature({len(data)} bytes) failed")

    def get_feature(self, length: int) -> bytes:
        if length <= 0:
            raise ValueError("length must be positive")
        buffer = ctypes.create_string_buffer(length)
        if not _hid.HidD_GetFeature(self.handle, buffer, length):
            raise HidError(_last_error(), f"HidD_GetFeature({length} bytes) failed")
        return buffer.raw[:length]

    def read(self, timeout: float = 0.5) -> bytes | None:
        """Read one input report; return None on timeout."""
        if not self.overlapped:
            raise RuntimeError("read() requires overlapped=True")
        event = _kernel32.CreateEventW(None, True, False, None)
        if not event:
            raise HidError(_last_error(), "CreateEventW failed")
        overlapped = OVERLAPPED()
        overlapped.hEvent = event
        buffer = ctypes.create_string_buffer(64)
        read_bytes = wintypes.DWORD(0)
        try:
            ok = _kernel32.ReadFile(
                self.handle, buffer, 64, ctypes.byref(read_bytes), ctypes.byref(overlapped)
            )
            if not ok:
                error = _last_error()
                if error != ERROR_IO_PENDING:
                    raise HidError(error, "ReadFile failed")
                wait = _kernel32.WaitForSingleObject(event, max(1, int(timeout * 1000)))
                if wait == WAIT_TIMEOUT:
                    _kernel32.CancelIoEx(self.handle, ctypes.byref(overlapped))
                    _kernel32.GetOverlappedResult(
                        self.handle, ctypes.byref(overlapped), ctypes.byref(read_bytes), True
                    )
                    return None
                if wait != WAIT_OBJECT_0:
                    raise HidError(_last_error(), "WaitForSingleObject failed")
                if not _kernel32.GetOverlappedResult(
                    self.handle, ctypes.byref(overlapped), ctypes.byref(read_bytes), False
                ):
                    raise HidError(_last_error(), "GetOverlappedResult failed")
            return bytes(buffer.raw[:read_bytes.value])
        finally:
            _kernel32.CloseHandle(event)

    def close(self) -> None:
        if getattr(self, "handle", None):
            _kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "HidDevice":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


@dataclass
class Ack:
    raw: bytes
    accepted: bool
    status: int
    command: int

    @classmethod
    def from_report(cls, report: bytes) -> "Ack | None":
        if len(report) == 5 and report[:2] == b"\x03\x55" and report[2] == 0x50:
            return cls(raw=report, accepted=report[3] == 0, status=report[3], command=report[4])
        if len(report) == 4 and report[:2] == b"\x55\x50":
            return cls(raw=report, accepted=report[2] == 0, status=report[2], command=report[3])
        return None

    def to_dict(self) -> dict:
        return {
            "raw": self.raw.hex(" ").upper(),
            "accepted": self.accepted,
            "status": self.status,
            "command": self.command,
        }


class Monitor:
    """Input-report reader for the col03 status and ACK collection."""

    def __init__(self, path: str):
        self.device = HidDevice(path, overlapped=True, read_write=False)

    def wait_for_ack(
        self,
        command: int | None = None,
        timeout: float = 2.0,
        *,
        accept_any: bool = False,
        event_callback: Callable[[dict], None] | None = None,
    ) -> Ack | None:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            report = self.device.read(min(0.5, remaining))
            if report is None:
                continue
            if event_callback is not None and not (
                len(report) == 5 and report[:2] == b"\x03\x55" and report[2] == 0x50
            ):
                try:
                    event_callback(protocol.decode_input(report))
                except ValueError:
                    event_callback({"kind": "unknown", "raw": report.hex(" ")})
            ack = Ack.from_report(report)
            if ack is None:
                continue
            if accept_any or command is None or ack.command == command:
                return ack

    def read_for(self, seconds: float, callback: Callable[[dict], None]) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            report = self.device.read(min(0.5, remaining))
            if report is None:
                continue
            try:
                callback(protocol.decode_input(report))
            except ValueError:
                callback({"kind": "unknown", "raw": report.hex(" ")})

    def close(self) -> None:
        self.device.close()

    def __enter__(self) -> "Monitor":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class X11Transport:
    """Wireless FA60 transport (col04 configuration + col03 monitor)."""

    def __init__(
        self,
        vid: int = 0x1D57,
        pid: int = 0xFA60,
        config_collection: int = 4,
        monitor_collection: int = 3,
        wireless: bool = True,
    ):
        paths = find_hid_paths(vid, pid)
        self.paths = paths
        self.wireless = wireless
        self.config = HidDevice(paths.collection(config_collection), read_write=True)
        try:
            self.monitor = Monitor(paths.collection(monitor_collection))
        except Exception:
            self.config.close()
            raise
        self.last_events: list[dict] = []
        self.last_attempts = 0

    def _record_event(self, event: dict) -> None:
        self.last_events.append(event)

    def send(
        self,
        packet: bytes,
        command: int | None = None,
        *,
        timeout: float = 2.0,
        retries: int = 10,
        accept_any: bool = False,
    ) -> Ack:
        if not packet:
            raise ValueError("empty packet")
        command = packet[0] if command is None else command
        last_error: Exception | None = None
        for attempt in range(1, max(1, retries) + 1):
            self.last_attempts = attempt
            try:
                self.config.set_feature(packet)
            except HidError as exc:
                last_error = exc
                time.sleep(0.5)
                continue
            ack = self.monitor.wait_for_ack(
                command, timeout, accept_any=accept_any, event_callback=self._record_event
            )
            if ack is not None:
                return ack
            time.sleep(0.5)
        raise TimeoutError(
            f"no ACK for command 0x{command:02X} after {retries} attempts"
            + (f": {last_error}" if last_error else "")
        )

    def send_macro(
        self,
        packet: bytes,
        *,
        wireless: bool | None = None,
        retries: int = 10,
        timeout: float = 3.0,
    ) -> Ack:
        if not packet or packet[0] != 0x09:
            raise ValueError("send_macro expects a logical 0x09 packet")
        wireless = self.wireless if wireless is None else wireless
        fragments = protocol.fragment_macro(packet, wireless=wireless)
        delay = 1.0 if wireless else 0.2
        last_error: Exception | None = None
        for attempt in range(1, max(1, retries) + 1):
            self.last_attempts = attempt
            try:
                for index, fragment in enumerate(fragments):
                    self.config.set_feature(fragment)
                    if index < len(fragments) - 1:
                        time.sleep(delay)
            except HidError as exc:
                last_error = exc
                time.sleep(delay)
                continue
            ack = self.monitor.wait_for_ack(0x09, timeout, event_callback=self._record_event)
            if ack is not None:
                return ack
            time.sleep(delay)
        raise TimeoutError(
            f"no ACK for 0x09 after {retries} attempts"
            + (f": {last_error}" if last_error else "")
        )

    def close(self) -> None:
        self.config.close()
        self.monitor.close()

    def __enter__(self) -> "X11Transport":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
