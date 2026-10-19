"""Regression: in-place upgrade scripts must survive ZIP extraction as executables."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class UpgradeEntryPoint1929(unittest.TestCase):
    def test_both_entrypoints_exist_and_are_executable(self):
        for name in ("upgrade.sh", "upgrade_to_v0.19.37.sh"):
            with self.subTest(script=name):
                path = ROOT / name
                self.assertTrue(path.is_file())
                self.assertTrue(os.access(path, os.X_OK))
                subprocess.run(["bash", "-n", str(path)], check=True)

    def test_wrapper_delegates_and_upgrade_is_current_release(self):
        wrapper = (ROOT / "upgrade.sh").read_text()
        upgrader = (ROOT / "upgrade_to_v0.19.37.sh").read_text()
        self.assertIn('TARGET="$HERE/upgrade_to_v0.19.37.sh"', wrapper)
        self.assertIn('exec bash "$TARGET" "$@"', wrapper)
        self.assertIn('VERSION="0.19.37"', upgrader)
        self.assertIn('Existing PCGA stack not found', upgrader)

if __name__ == "__main__":
    unittest.main()
