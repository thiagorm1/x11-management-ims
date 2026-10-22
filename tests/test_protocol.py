from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from x11_management import protocol
from x11_management.profile import ProFile

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATA = ROOT / "data" / "default_pro.data"
EXAMPLES_JSON = ROOT / "assets" / "example-packets.json"


class ProtocolTests(unittest.TestCase):
    def test_sample_packets_against_hardware_reference(self) -> None:
        pro = ProFile.load(SAMPLE_DATA)
        p0 = pro.profile(0)
        packets = p0.make_packets()
        spec = json.loads(EXAMPLES_JSON.read_text(encoding="utf-8"))["packets"]

        # Validate DPI (0x04)
        self.assertEqual(
            packets["0x04"].hex(" ").lower(),
            spec["04_dpi"]["hex"].lower(),
        )
        # Validate Lighting (0x05)
        self.assertEqual(
            packets["0x05"].hex(" ").lower(),
            spec["05_lighting"]["hex"].lower(),
        )
        # Validate Polling (0x06)
        self.assertEqual(
            packets["0x06"].hex(" ").lower(),
            spec["06_polling"]["hex"].lower(),
        )
        # Validate Buttons (0x08)
        self.assertEqual(
            packets["0x08"].hex(" ").lower(),
            spec["08_buttons"]["hex"].lower(),
        )

    def test_decode_input_reports(self) -> None:
        rep_power = bytes([0x03, 0x55, 0x40, 0x01, 0x55])
        dec_power = protocol.decode_input(rep_power)
        self.assertEqual(dec_power["kind"], "power")
        self.assertEqual(dec_power["status"], 1)
        self.assertEqual(dec_power["percent"], 85)

        rep_ack = bytes([0x03, 0x55, 0x50, 0x00, 0x04])
        dec_ack = protocol.decode_input(rep_ack)
        self.assertEqual(dec_ack["kind"], "ack")
        self.assertTrue(dec_ack["accepted"])

        with self.assertRaises(ValueError):
            protocol.decode_input(bytes([0x01, 0x02, 0x03, 0x04, 0x05]))


if __name__ == "__main__":
    unittest.main()
