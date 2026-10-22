"""Apply a profile with ACK/retry handling and optional dry-run."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import protocol
from .profile import CONFIGURABLE_BUTTONS, Profile
from .transport import Ack, X11Transport

NORMAL_COMMANDS = ("0x0C", "0x04", "0x05", "0x06", "0x08")
# BLE firmware does not receive 0x06 (polling); the rest maintains original order.
NORMAL_COMMANDS_BLE = ("0x0C", "0x04", "0x05", "0x08")


@dataclass
class ApplyStep:
    name: str
    packet: bytes
    macro: bool = False
    fragments: list[bytes] = field(default_factory=list)
    ack: Ack | None = None
    attempts: int = 0

    @property
    def command(self) -> int:
        return self.packet[0]

    def to_dict(self) -> dict:
        result = {
            "name": self.name,
            "command": f"0x{self.command:02X}",
            "packet": self.packet.hex(" ").upper(),
            "length": len(self.packet),
            "macro": self.macro,
            "attempts": self.attempts,
        }
        if self.fragments:
            result["fragments"] = [f.hex(" ").upper() for f in self.fragments]
        if self.ack is not None:
            result["ack"] = self.ack.to_dict()
        return result


def _normalize_command(command: str | int) -> str:
    text = str(command).strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    try:
        value = int(text, 16)
    except ValueError as exc:
        raise ValueError(f"invalid command {command!r}; use e.g. 0x04") from exc
    if not 0 <= value <= 0xFF:
        raise ValueError(f"command out of range: {command!r}")
    return f"0x{value:02X}"


def build_steps(
    profile: Profile,
    *,
    full: bool = True,
    commands: Iterable[str] | None = None,
    include_macros: bool = True,
    ble: bool = False,
) -> list[ApplyStep]:
    """Build the packets in the exact hardware sequence.

    full=True matches the full initialization sequence:
    0x0C, 0x04, 0x05, 0x06, 0x08 and macros.
    With ble=True, 0x06 is omitted and 0x09 is sent whole.
    """
    profile.validate()
    sequence = NORMAL_COMMANDS_BLE if ble else NORMAL_COMMANDS
    normalized = None if commands is None else {_normalize_command(c) for c in commands}
    if ble and normalized is not None and "0x06" in normalized:
        raise ValueError("0x06 (polling rate) cannot be sent over BLE")
    if full:
        selected = set(sequence)
    elif normalized is None:
        selected = set(sequence) - {"0x0C"}
    else:
        selected = normalized
    if "0x0C" in selected:
        selected.update(sequence)
    packets = profile.make_packets()
    steps: list[ApplyStep] = []
    for command in sequence:
        if command not in selected:
            continue
        steps.append(ApplyStep(name=command, packet=packets[command]))
    if include_macros:
        for slot in range(1, CONFIGURABLE_BUTTONS + 1):
            key = f"0x09:{slot}"
            if key not in packets:
                continue
            logical = packets[key]
            fragments = [] if ble else protocol.fragment_macro(logical, wireless=True)
            steps.append(
                ApplyStep(
                    name=f"0x09 slot {slot} (macro)",
                    packet=logical,
                    macro=True,
                    fragments=fragments,
                )
            )
    return steps


def apply_profile(
    profile: Profile,
    transport: X11Transport | None = None,
    *,
    full: bool = True,
    commands: Iterable[str] | None = None,
    include_macros: bool = True,
    retries: int = 10,
    wireless: bool = True,
    dry_run: bool = False,
    ble: bool = False,
    on_step: Callable[[ApplyStep], None] | None = None,
) -> list[ApplyStep]:
    """Apply profile to device and return the executed steps with ACKs."""
    steps = build_steps(
        profile,
        full=full,
        commands=commands,
        include_macros=include_macros,
        ble=ble,
    )
    if dry_run:
        return steps
    owned = transport is None
    if transport is None:
        if ble:
            from .ble import BleTransport
            transport = BleTransport()
        else:
            transport = X11Transport(wireless=wireless)
    try:
        for step in steps:
            if step.macro:
                ack = transport.send_macro(step.packet, wireless=wireless, retries=retries)
            else:
                ack = transport.send(step.packet, command=step.command, retries=retries)
            step.ack = ack
            step.attempts = int(getattr(transport, "last_attempts", 0))
            if on_step is not None:
                on_step(step)
        return steps
    finally:
        if owned:
            transport.close()
