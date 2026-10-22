from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from x11_management import protocol
from x11_management.profile import (
    HEADER_SIZE,
    PROFILE_SIZE,
    Button,
    MacroEvent,
    Profile,
    ProFile,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATA = ROOT / "data" / "default_pro.data"


class ProfileTests(unittest.TestCase):
    def test_load_sample_file(self) -> None:
        pro = ProFile.load(SAMPLE_DATA)
        self.assertEqual(pro.profile_count, 1)
        self.assertEqual(len(pro.header), HEADER_SIZE)
        self.assertEqual(pro.profile(0).name, "Profile1")
        self.assertEqual(len(pro.profile(0).to_bytes()), PROFILE_SIZE)

    def test_roundtrip_bytes(self) -> None:
        pro = ProFile.load(SAMPLE_DATA)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pro.data"
            pro.save(path)
            self.assertEqual(path.read_bytes(), SAMPLE_DATA.read_bytes())
            again = ProFile.load(path)
            self.assertEqual(again.to_dict(), pro.to_dict())

    def test_default_profile(self) -> None:
        profile = Profile.default("TestIMS")
        profile.validate()
        self.assertEqual(profile.name, "TestIMS")
        self.assertEqual(len(profile.to_bytes()), PROFILE_SIZE)
        self.assertEqual(profile.polling_index, 3)
        self.assertEqual(len(profile.buttons), 24)
        self.assertEqual(profile.buttons[0].action, 0x01)
        self.assertEqual(profile.buttons[17].action, 0x0C)
        self.assertEqual(
            set(profile.make_packets()),
            {"0x0C", "0x04", "0x05", "0x06", "0x08"},
        )

    def test_default_json_roundtrip(self) -> None:
        profile = Profile.default("TestJson")
        self.assertEqual(
            Profile.from_dict(profile.to_dict()).to_bytes(),
            profile.to_bytes(),
        )

    def test_macro_packet_and_fragments(self) -> None:
        profile = Profile.default("MacroTest")
        button = profile.buttons[17]
        button.action = 0x11
        button.macro_name = "IMS_MACRO"
        button.set_events([MacroEvent(0x04, 0, 10), MacroEvent(0x04, 1, 10)], 1)
        packet = protocol.macro_packet(button.to_bytes(), 18)
        self.assertEqual(len(packet), 131)
        self.assertEqual(packet[:4], bytes([0x09, 0x83, 0x12, 0x00]))
        fragments = protocol.fragment_macro(packet, wireless=True)
        self.assertEqual(len(fragments), 3)
        self.assertEqual(
            [f[:4] for f in fragments],
            [
                bytes([9, 0x40, 18, 0]),
                bytes([9, 0x40, 18, 1]),
                bytes([9, 0x0C, 18, 2]),
            ],
        )

    def test_multi_profile(self) -> None:
        pro = ProFile([Profile.default("P1"), Profile.default("P2")])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pro.data"
            pro.save(path)
            self.assertEqual(path.stat().st_size, HEADER_SIZE + 2 * PROFILE_SIZE)
            loaded = ProFile.load(path)
            self.assertEqual([p.name for p in loaded.profiles], ["P1", "P2"])


if __name__ == "__main__":
    unittest.main()
