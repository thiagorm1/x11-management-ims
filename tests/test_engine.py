from __future__ import annotations

from pathlib import Path
import sys
import unittest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from x11_management.engine import build_steps, apply_profile
from x11_management.profile import Profile


class EngineTests(unittest.TestCase):
    def test_build_steps_hid_default(self) -> None:
        profile = Profile.default("EngineTest")
        steps = build_steps(profile, full=True, ble=False)
        step_names = [s.name for s in steps]
        self.assertEqual(step_names, ["0x0C", "0x04", "0x05", "0x06", "0x08"])

    def test_build_steps_ble(self) -> None:
        profile = Profile.default("EngineBLE")
        steps = build_steps(profile, full=True, ble=True)
        step_names = [s.name for s in steps]
        self.assertEqual(step_names, ["0x0C", "0x04", "0x05", "0x08"])
        self.assertNotIn("0x06", step_names)

    def test_apply_profile_dry_run(self) -> None:
        profile = Profile.default("DryRunTest")
        steps = apply_profile(profile, dry_run=True)
        self.assertEqual(len(steps), 5)
        for s in steps:
            self.assertGreater(len(s.packet), 0)


if __name__ == "__main__":
    unittest.main()
