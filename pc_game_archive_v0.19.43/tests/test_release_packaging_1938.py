import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_builder', ROOT / 'tools/build_release.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class LinuxReleasePackaging1938(unittest.TestCase):
    def test_bash_crlf_is_rejected_before_packaging(self):
        with self.assertRaisesRegex(ValueError, 'Windows/CR'):
            builder.validate_payload('upgrade_to_v0.19.38.sh', b'#!/bin/bash\r\nset -Eeuo pipefail\r\n')

    def test_extensionless_component_crlf_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Windows/CR'):
            builder.validate_payload('components/pcga-service-auth', b'#!/bin/bash\r\nset -u\r\n')

    def test_bom_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'BOM'):
            builder.validate_payload('upgrade.sh', b'\xef\xbb\xbf#!/bin/bash\n')

    def test_linux_script_is_accepted(self):
        builder.validate_payload('upgrade.sh', b'#!/bin/bash\nset -Eeuo pipefail\n')

    def test_actual_release_sources_are_linux_safe(self):
        for path in builder.release_files(ROOT):
            with self.subTest(file=path.relative_to(ROOT).as_posix()):
                builder.validate_payload(path.relative_to(ROOT).as_posix(), path.read_bytes())


if __name__ == '__main__':
    unittest.main()
