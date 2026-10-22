from __future__ import annotations

from pathlib import Path
import sys
import unittest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from x11_management.cli import _action, _format_color, _parse_macro_events
from x11_management.gui import _parse_action, _parse_hex_byte


class CliParsingTests(unittest.TestCase):
    def test_action_parsing(self) -> None:
        self.assertEqual(_action("0x11"), 0x11)
        self.assertEqual(_action("0x11 — Macro"), 0x11)
        self.assertEqual(_action("Macro"), 0x11)
        self.assertEqual(_parse_action("0x11 — Macro"), 0x11)

    def test_shortcut_hex_byte(self) -> None:
        self.assertEqual(_parse_hex_byte("02", "modificador"), 2)
        self.assertEqual(_parse_hex_byte("0x04", "tecla"), 4)
        self.assertEqual(_parse_hex_byte("", "tecla"), 0)
        with self.assertRaises(ValueError):
            _parse_hex_byte("invalid_hex", "modificador")

    def test_format_color(self) -> None:
        self.assertEqual(_format_color(0x0000FF), "#FF0000")
        self.assertEqual(_format_color(0x00FF00), "#00FF00")
        self.assertEqual(_format_color(0xFF0000), "#0000FF")

    def test_parse_macro_events_json(self) -> None:
        raw_json = '[{"code": 4, "state": 0, "delay": 10}, {"code": 4, "state": 1, "delay": 15}]'
        events = _parse_macro_events(raw_json)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].code, 4)
        self.assertEqual(events[0].state, 0)
        self.assertEqual(events[0].delay, 10)
        self.assertEqual(events[1].delay, 15)


if __name__ == "__main__":
    unittest.main()
