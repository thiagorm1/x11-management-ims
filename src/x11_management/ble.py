"""Windows native Bluetooth Low Energy (BLE) GATT transport for X11 Mouse.

Communicates with the proprietary 0xFEE0 service:
- 0xFEE3: Write with response (packet payload without report ID)
- 0xFEE4: Notification characteristic (ACK 55 50 00 <cmd>)

Uses Windows native BluetoothAPIs.dll and setupapi.dll via ctypes.
"""
from __future__ import annotations

import ctypes
import queue
import struct
import time
from ctypes import wintypes

from .transport import Ack, DeviceNotFound, GUID, SP_DEVICE_INTERFACE_DATA

GUID_BLUETOOTH_GATT_DEVICE_SERVICE = "{6E3BB679-4372-40C8-9EAA-4509DF260CD8}"
DIGCF_PRESENT = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
ERROR_MORE_DATA = 0x800700EA

CLIENT_CHARACTERISTIC_CONFIGURATION = 2
CHARACTERISTIC_VALUE_CHANGED_EVENT = 0
FEE0_SERVICE_UUID = 0xFEE0
FEE3_CHARACTERISTIC_UUID = 0xFEE3
FEE4_CHARACTERISTIC_UUID = 0xFEE4

VALUE_DATA_OFFSET = 4


class BleError(OSError):
    """Failure in GATT API call or BLE link."""


class BleDeviceNotFound(DeviceNotFound):
    """X11 BLE configuration service was not found."""


class BTH_LE_UUID_UNION(ctypes.Union):
    _fields_ = [("ShortUuid", wintypes.USHORT), ("LongUuid", GUID)]


class BTH_LE_UUID(ctypes.Structure):
    _fields_ = [("IsShortUuid", wintypes.BOOLEAN), ("Value", BTH_LE_UUID_UNION)]


class BTH_LE_GATT_SERVICE(ctypes.Structure):
    _fields_ = [("ServiceUuid", BTH_LE_UUID), ("AttributeHandle", wintypes.USHORT)]


class BTH_LE_GATT_CHARACTERISTIC(ctypes.Structure):
    _fields_ = [
        ("ServiceHandle", wintypes.USHORT),
        ("CharacteristicUuid", BTH_LE_UUID),
        ("AttributeHandle", wintypes.USHORT),
        ("CharacteristicValueHandle", wintypes.USHORT),
        ("IsBroadcastable", wintypes.BOOLEAN),
        ("IsReadable", wintypes.BOOLEAN),
        ("IsWritable", wintypes.BOOLEAN),
        ("IsWritableWithoutResponse", wintypes.BOOLEAN),
        ("IsSignedWritable", wintypes.BOOLEAN),
        ("IsNotifiable", wintypes.BOOLEAN),
        ("IsIndicatable", wintypes.BOOLEAN),
        ("HasExtendedProperties", wintypes.BOOLEAN),
    ]


class BTH_LE_GATT_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("ServiceHandle", wintypes.USHORT),
        ("CharacteristicHandle", wintypes.USHORT),
        ("DescriptorType", ctypes.c_int),
        ("DescriptorUuid", BTH_LE_UUID),
        ("AttributeHandle", wintypes.USHORT),
    ]


class _CharacteristicExtendedProperties(ctypes.Structure):
    _fields_ = [
        ("IsReliableWriteEnabled", wintypes.BOOLEAN),
        ("IsAuxiliariesWritable", wintypes.BOOLEAN),
    ]


class _ClientCharacteristicConfiguration(ctypes.Structure):
    _fields_ = [
        ("IsSubscribeToNotification", wintypes.BOOLEAN),
        ("IsSubscribeToIndication", wintypes.BOOLEAN),
    ]


class _ServerCharacteristicConfiguration(ctypes.Structure):
    _fields_ = [("IsBroadcast", wintypes.BOOLEAN)]


class _CharacteristicFormat(ctypes.Structure):
    _fields_ = [
        ("Format", ctypes.c_ubyte),
        ("Exponent", ctypes.c_ubyte),
        ("Unit", BTH_LE_UUID),
        ("NameSpace", ctypes.c_ubyte),
        ("Description", BTH_LE_UUID),
    ]


class _DescriptorValueUnion(ctypes.Union):
    _fields_ = [
        ("CharacteristicExtendedProperties", _CharacteristicExtendedProperties),
        ("ClientCharacteristicConfiguration", _ClientCharacteristicConfiguration),
        ("ServerCharacteristicConfiguration", _ServerCharacteristicConfiguration),
        ("CharacteristicFormat", _CharacteristicFormat),
    ]


class BTH_LE_GATT_DESCRIPTOR_VALUE(ctypes.Structure):
    _fields_ = [
        ("DescriptorType", ctypes.c_int),
        ("DescriptorUuid", BTH_LE_UUID),
        ("Value", _DescriptorValueUnion),
        ("DataSize", wintypes.ULONG),
        ("Data", ctypes.c_ubyte * 1),
    ]


class BTH_LE_GATT_CHARACTERISTIC_VALUE(ctypes.Structure):
    _fields_ = [("DataSize", wintypes.ULONG), ("Data", ctypes.c_ubyte * 1)]


class BLUETOOTH_GATT_VALUE_CHANGED_EVENT_REGISTRATION(ctypes.Structure):
    _fields_ = [
        ("NumCharacteristics", wintypes.USHORT),
        ("Characteristics", BTH_LE_GATT_CHARACTERISTIC * 1),
    ]


class BLUETOOTH_GATT_VALUE_CHANGED_EVENT(ctypes.Structure):
    _fields_ = [
        ("ChangedAttributeHandle", wintypes.USHORT),
        ("CharacteristicValueDataSize", ctypes.c_size_t),
        ("CharacteristicValue", ctypes.POINTER(BTH_LE_GATT_CHARACTERISTIC_VALUE)),
    ]


_setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_bth = ctypes.WinDLL("BluetoothAPIs", use_last_error=True)
_ole32 = ctypes.WinDLL("ole32", use_last_error=True)

_setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD
]
_setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
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
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL

_bth.BluetoothGATTGetServices.argtypes = [
    wintypes.HANDLE, wintypes.USHORT, ctypes.POINTER(BTH_LE_GATT_SERVICE),
    ctypes.POINTER(wintypes.USHORT), wintypes.ULONG,
]
_bth.BluetoothGATTGetServices.restype = ctypes.c_long
_bth.BluetoothGATTGetCharacteristics.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(BTH_LE_GATT_SERVICE), wintypes.USHORT,
    ctypes.POINTER(BTH_LE_GATT_CHARACTERISTIC), ctypes.POINTER(wintypes.USHORT),
    wintypes.ULONG,
]
_bth.BluetoothGATTGetCharacteristics.restype = ctypes.c_long
_bth.BluetoothGATTGetDescriptors.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(BTH_LE_GATT_CHARACTERISTIC), wintypes.USHORT,
    ctypes.POINTER(BTH_LE_GATT_DESCRIPTOR), ctypes.POINTER(wintypes.USHORT),
    wintypes.ULONG,
]
_bth.BluetoothGATTGetDescriptors.restype = ctypes.c_long
_bth.BluetoothGATTSetCharacteristicValue.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(BTH_LE_GATT_CHARACTERISTIC),
    ctypes.POINTER(BTH_LE_GATT_CHARACTERISTIC_VALUE), ctypes.c_ulonglong,
    wintypes.ULONG,
]
_bth.BluetoothGATTSetCharacteristicValue.restype = ctypes.c_long
_bth.BluetoothGATTSetDescriptorValue.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(BTH_LE_GATT_DESCRIPTOR), ctypes.c_void_p,
    wintypes.ULONG,
]
_bth.BluetoothGATTSetDescriptorValue.restype = ctypes.c_long
_BLE_CALLBACK = ctypes.WINFUNCTYPE(None, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
_bth.BluetoothGATTRegisterEvent.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, _BLE_CALLBACK, ctypes.c_void_p,
    ctypes.POINTER(wintypes.HANDLE), wintypes.ULONG,
]
_bth.BluetoothGATTRegisterEvent.restype = ctypes.c_long
_bth.BluetoothGATTUnregisterEvent.argtypes = [wintypes.HANDLE, wintypes.ULONG]
_bth.BluetoothGATTUnregisterEvent.restype = ctypes.c_long


def _hresult(hr: int) -> int:
    return hr & 0xFFFFFFFF


def _check(hr: int, what: str) -> None:
    if _hresult(hr) != 0:
        raise BleError(_hresult(hr), f"{what} failed (0x{_hresult(hr):08X})")


def _interface_paths() -> list[str]:
    guid = GUID()
    _ole32.CLSIDFromString(GUID_BLUETOOTH_GATT_DEVICE_SERVICE, ctypes.byref(guid))
    device_set = _setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    )
    if not device_set or device_set == wintypes.HANDLE(-1).value:
        raise BleError(ctypes.get_last_error(), "SetupDiGetClassDevsW failed")
    paths: list[str] = []
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
                    if "vid&02045e" in lower and "pid&0055" in lower:
                        paths.append(path)
            index += 1
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(device_set)
    return paths


def find_ble_paths() -> list[str]:
    """Return GATT interface paths for X11 BLE mouse (VID 0x045E, PID 0x0055)."""
    return _interface_paths()


def _services(handle: wintypes.HANDLE) -> list[BTH_LE_GATT_SERVICE]:
    count = wintypes.USHORT()
    hr = _bth.BluetoothGATTGetServices(handle, 0, None, ctypes.byref(count), 0)
    if _hresult(hr) != ERROR_MORE_DATA:
        _check(hr, "BluetoothGATTGetServices query")
    if count.value == 0:
        raise BleError("No GATT services in cache")
    services = (BTH_LE_GATT_SERVICE * count.value)()
    _check(
        _bth.BluetoothGATTGetServices(handle, count.value, services, ctypes.byref(count), 0),
        "BluetoothGATTGetServices",
    )
    return list(services[:count.value])


def _characteristics(handle: wintypes.HANDLE, service: BTH_LE_GATT_SERVICE) -> list[BTH_LE_GATT_CHARACTERISTIC]:
    count = wintypes.USHORT()
    hr = _bth.BluetoothGATTGetCharacteristics(
        handle, ctypes.byref(service), 0, None, ctypes.byref(count), 0
    )
    if _hresult(hr) != ERROR_MORE_DATA:
        _check(hr, "BluetoothGATTGetCharacteristics query")
    if count.value == 0:
        raise BleError("Service has no characteristics")
    characteristics = (BTH_LE_GATT_CHARACTERISTIC * count.value)()
    _check(
        _bth.BluetoothGATTGetCharacteristics(
            handle, ctypes.byref(service), count.value, characteristics, ctypes.byref(count), 0
        ),
        "BluetoothGATTGetCharacteristics",
    )
    return list(characteristics[:count.value])


def _descriptors(handle: wintypes.HANDLE, characteristic: BTH_LE_GATT_CHARACTERISTIC) -> list[BTH_LE_GATT_DESCRIPTOR]:
    count = wintypes.USHORT()
    hr = _bth.BluetoothGATTGetDescriptors(
        handle, ctypes.byref(characteristic), 0, None, ctypes.byref(count), 0
    )
    if _hresult(hr) != ERROR_MORE_DATA:
        _check(hr, "BluetoothGATTGetDescriptors query")
    if count.value == 0:
        return []
    descriptors = (BTH_LE_GATT_DESCRIPTOR * count.value)()
    _check(
        _bth.BluetoothGATTGetDescriptors(
            handle, ctypes.byref(characteristic), count.value, descriptors, ctypes.byref(count), 0
        ),
        "BluetoothGATTGetDescriptors",
    )
    return list(descriptors[:count.value])


def _short_uuid(uuid: BTH_LE_UUID) -> int | None:
    if uuid.IsShortUuid:
        return int(uuid.Value.ShortUuid)
    return None


def _uuid_text(uuid: BTH_LE_UUID) -> str:
    if uuid.IsShortUuid:
        return f"0x{int(uuid.Value.ShortUuid):04X}"
    value = uuid.Value.LongUuid
    data4 = bytes(value.Data4)
    return (
        f"{value.Data1:08X}-{value.Data2:04X}-{value.Data3:04X}-"
        f"{data4[:2].hex().upper()}-{data4[2:].hex().upper()}"
    )


class BleTransport:
    """GATT transport with writes to 0xFEE3 and ACKs on 0xFEE4."""

    def __init__(self, *, timeout: float = 2.0):
        self.timeout = timeout
        self.path = ""
        self.service: BTH_LE_GATT_SERVICE | None = None
        self.fee3: BTH_LE_GATT_CHARACTERISTIC | None = None
        self.fee4: BTH_LE_GATT_CHARACTERISTIC | None = None
        self.cccd: BTH_LE_GATT_DESCRIPTOR | None = None
        self.handle = None
        self._event_handle = None
        self._callback = None
        self._notifications: queue.Queue[bytes] = queue.Queue()
        self.last_attempts = 0
        self._open()

    def _open(self) -> None:
        paths = _interface_paths()
        if not paths:
            raise BleDeviceNotFound(
                "X11 GATT service not found. Pair mouse and ensure 'Connected' in Windows (VID_045E&PID_0055)."
            )
        preferred = [p for p in paths if "0000fee0-" in p.lower()]
        candidates = preferred + [p for p in paths if p not in preferred]
        for path in candidates:
            handle = _kernel32.CreateFileW(
                path, GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None
            )
            if not handle or handle == wintypes.HANDLE(-1).value:
                continue
            try:
                for service in _services(handle):
                    try:
                        characteristics = _characteristics(handle, service)
                    except BleError:
                        continue
                    by_uuid = {_short_uuid(c.CharacteristicUuid): c for c in characteristics}
                    fee3 = by_uuid.get(FEE3_CHARACTERISTIC_UUID)
                    fee4 = by_uuid.get(FEE4_CHARACTERISTIC_UUID)
                    if fee3 is None or fee4 is None:
                        continue
                    cccd = next(
                        (
                            d for d in _descriptors(handle, fee4)
                            if d.DescriptorType == CLIENT_CHARACTERISTIC_CONFIGURATION
                            or _short_uuid(d.DescriptorUuid) == 0x2902
                        ),
                        None,
                    )
                    if cccd is None:
                        continue
                    self.path = path
                    self.service = service
                    self.fee3 = fee3
                    self.fee4 = fee4
                    self.cccd = cccd
                    self.handle = handle
                    self._subscribe()
                    return
            except Exception:
                _kernel32.CloseHandle(handle)
                raise
            _kernel32.CloseHandle(handle)
        raise BleDeviceNotFound(
            "Service FEE0 with FEE3/FEE4 not found. Ensure mouse is connected via BLE."
        )

    def _set_notifications(self, enabled: bool) -> None:
        if self.handle is None or self.cccd is None:
            return
        value = BTH_LE_GATT_DESCRIPTOR_VALUE()
        value.DescriptorType = CLIENT_CHARACTERISTIC_CONFIGURATION
        value.Value.ClientCharacteristicConfiguration.IsSubscribeToNotification = int(enabled)
        _check(
            _bth.BluetoothGATTSetDescriptorValue(
                self.handle, ctypes.byref(self.cccd), ctypes.byref(value), 0
            ),
            "BluetoothGATTSetDescriptorValue(CCCD)",
        )

    def _on_notify(self, _event_type: int, event_ptr: int, _context: int) -> None:
        if not event_ptr:
            return
        try:
            event = ctypes.cast(
                event_ptr, ctypes.POINTER(BLUETOOTH_GATT_VALUE_CHANGED_EVENT)
            ).contents
            value = event.CharacteristicValue
            if not value:
                return
            raw = ctypes.string_at(
                ctypes.addressof(value.contents) + VALUE_DATA_OFFSET,
                min(int(value.contents.DataSize), 512),
            )
            self._notifications.put(raw)
        except Exception:
            pass

    def _subscribe(self) -> None:
        self._set_notifications(True)
        registration = BLUETOOTH_GATT_VALUE_CHANGED_EVENT_REGISTRATION()
        registration.NumCharacteristics = 1
        assert self.fee4 is not None
        registration.Characteristics[0] = self.fee4
        event_handle = wintypes.HANDLE()
        callback = _BLE_CALLBACK(self._on_notify)
        _check(
            _bth.BluetoothGATTRegisterEvent(
                self.handle, CHARACTERISTIC_VALUE_CHANGED_EVENT,
                ctypes.byref(registration), callback, None,
                ctypes.byref(event_handle), 0,
            ),
            "BluetoothGATTRegisterEvent",
        )
        self._callback = callback
        self._event_handle = event_handle

    def _value_buffer(self, packet: bytes):
        size = VALUE_DATA_OFFSET + len(packet)
        buffer = ctypes.create_string_buffer(size)
        ctypes.memmove(buffer, struct.pack("<I", len(packet)), VALUE_DATA_OFFSET)
        ctypes.memmove(ctypes.addressof(buffer) + VALUE_DATA_OFFSET, packet, len(packet))
        return ctypes.cast(buffer, ctypes.POINTER(BTH_LE_GATT_CHARACTERISTIC_VALUE)), buffer

    def _write(self, packet: bytes) -> None:
        if self.handle is None or self.fee3 is None:
            raise BleError("BLE transport closed")
        if not packet:
            raise ValueError("empty packet")
        value, _buffer = self._value_buffer(packet)
        _check(
            _bth.BluetoothGATTSetCharacteristicValue(
                self.handle, ctypes.byref(self.fee3), value, 0, 0
            ),
            f"BluetoothGATTSetCharacteristicValue(0x{packet[0]:02X})",
        )

    def _wait_ack(self, command: int, timeout: float, accept_any: bool) -> Ack | None:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                data = self._notifications.get(timeout=remaining)
            except queue.Empty:
                return None
            ack = Ack.from_report(data)
            if ack is None:
                continue
            if accept_any or command is None or ack.command == command:
                return ack

    def _drain(self) -> None:
        while True:
            try:
                self._notifications.get_nowait()
            except queue.Empty:
                return

    def send(
        self,
        packet: bytes,
        command: int | None = None,
        *,
        timeout: float | None = None,
        retries: int = 10,
        accept_any: bool = False,
    ) -> Ack:
        if not packet:
            raise ValueError("empty packet")
        command = packet[0] if command is None else command
        timeout = self.timeout if timeout is None else timeout
        last_error: Exception | None = None
        for attempt in range(1, max(1, retries) + 1):
            self.last_attempts = attempt
            self._drain()
            try:
                self._write(packet)
            except (BleError, OSError) as exc:
                last_error = exc
                time.sleep(0.5)
                continue
            ack = self._wait_ack(command, timeout, accept_any)
            if ack is not None:
                return ack
            time.sleep(0.5)
        raise TimeoutError(
            f"No BLE ACK for 0x{command:02X} after {retries} attempt(s)"
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
            raise ValueError("send_macro expects a 0x09 packet")
        ack = self.send(packet, command=0x09, timeout=timeout, retries=retries)
        time.sleep(0.5)
        return ack

    def describe(self) -> dict:
        return {
            "path": self.path,
            "service": _uuid_text(self.service.ServiceUuid) if self.service else None,
            "fee3": _uuid_text(self.fee3.CharacteristicUuid) if self.fee3 else None,
            "fee4": _uuid_text(self.fee4.CharacteristicUuid) if self.fee4 else None,
            "cccd_handle": int(self.cccd.AttributeHandle) if self.cccd else None,
        }

    def close(self) -> None:
        if self._event_handle:
            try:
                _bth.BluetoothGATTUnregisterEvent(self._event_handle, 0)
            except Exception:
                pass
            self._event_handle = None
        if self.handle is not None:
            try:
                self._set_notifications(False)
            except Exception:
                pass
            _kernel32.CloseHandle(self.handle)
            self.handle = None
        self._callback = None

    def __enter__(self) -> "BleTransport":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
