import ast
import hashlib
import importlib.util
import contextlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_wolf_catalog_1939 import test_directory
import pcga_wolf_config

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('upgrade_catalog', ROOT / 'upgrade_catalog.py')
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


def sandbox_path(path, root):
    """Redirect production state directories, leaving test paths untouched."""
    text = str(path)
    namespaces = ('/var/backups/pc-game-archive', '/var/lib/pc-game-archive')
    if any(text == prefix or text.startswith(prefix + '/') for prefix in namespaces):
        return root / text.lstrip('/')
    return type(root)(path)


class UpgradeCatalog1943(unittest.TestCase):
    def test_state_paths_are_redirected_once_on_linux_and_windows(self):
        for root in (PurePosixPath('/tmp/pcga-test-example'), PureWindowsPath('C:/Temp/pcga-test-example')):
            with self.subTest(root=str(root)):
                state = sandbox_path('/var/lib/pc-game-archive/game-installs/game.json', root)
                self.assertEqual(state, root / 'var/lib/pc-game-archive/game-installs/game.json')
                self.assertEqual(sandbox_path(str(state), root), state)
                script = root / 'sbin/pcga-game-orchestrator'
                self.assertEqual(sandbox_path(str(script), root), script)
                backup = sandbox_path('/var/backups/pc-game-archive/v-test', root)
                self.assertEqual(sandbox_path(str(backup), root), backup)

    def test_function_patch_preserves_unrelated_local_changes(self):
        old = 'def changed():\n    return 1'
        target = 'def changed():\n    return 2'
        original = 'LOCAL_SETTING = "preserve me"\n' + old + '\n\ndef other():\n    return "local fix"\n'
        result = upgrade.patch_functions(original, target, {'changed': hashlib.sha256(old.encode()).hexdigest()})
        self.assertIn('LOCAL_SETTING = "preserve me"', result)
        self.assertIn('return "local fix"', result)
        self.assertIn('return 2', result)
        self.assertEqual(upgrade.patch_functions(result, target, {'changed': hashlib.sha256(old.encode()).hexdigest()}), result)

    def test_unknown_function_changes_fail_before_installation(self):
        with self.assertRaisesRegex(ValueError, 'locally modified'):
            upgrade.patch_functions('def changed():\n    return 3', 'def changed():\n    return 2',
                                    {'changed': hashlib.sha256(b'def changed():\n    return 1').hexdigest()})

    def test_only_supported_installed_versions_are_accepted(self):
        result = upgrade.patch_version('VERSION = "0.19.40"\nLOCAL_FIX = True\n')
        self.assertIn('VERSION = "0.19.43"', result)
        self.assertIn('VERSION = "0.19.43"', upgrade.patch_version('VERSION = "0.19.41"\n'))
        self.assertIn('LOCAL_FIX = True', result)
        with self.assertRaisesRegex(ValueError, 'requires installed'):
            upgrade.patch_version('VERSION = "0.19.37"\n')

    def test_portal_patch_accepts_both_retry_versions(self):
        for version in ('0.19.40', '0.19.41'):
            with self.subTest(version=version):
                source = f'''VERSION = "{version}"
const_value = "const PORTAL_BUILD_VERSION='{version}'"
'''
                updated = upgrade.patch_version(source, portal=True)
                self.assertIn('VERSION = "0.19.43"', updated)
                self.assertIn("const PORTAL_BUILD_VERSION='0.19.43'", updated)

    def test_control_patch_adds_netbird_service_without_removing_local_changes(self):
        source = '''VERSION = "0.19.40"
NETBIRD_PROVIDER = "netbird"
OTHER_PROVIDERS = {"netbird": "status"}
LOCAL_FIX = True
DOCKER_SERVICES = {
    "wolf": "wolf",
}
def compose_files():
    names = ["compose.yml", "compose.nas.yml"]
    return names
def action(name, payload):
    if name == "netbird-status":
        return netbird_remote("status")
'''
        result = upgrade.patch_control(source)
        self.assertIn('VERSION = "0.19.43"', result)
        self.assertIn('"netbird": "pcga-netbird"', result)
        self.assertIn('"compose.netbird.yml"', result)
        self.assertIn('LOCAL_FIX = True', result)
        self.assertEqual(upgrade.patch_control(result), result)

    def test_upgrade_uses_standard_entrypoint_and_checksum_manifest(self):
        wrapper = (ROOT / 'upgrade.sh').read_text()
        script = (ROOT / 'upgrade_to_v0.19.43.sh').read_text()
        self.assertIn('TARGET="$HERE/upgrade_to_v0.19.43.sh"', wrapper)
        self.assertIn('sha256sum --check --quiet MANIFEST.sha256', script)
        self.assertIn('python3 "$HERE/upgrade_catalog.py"', script)

    def simulate_install(self, fail_validation=False):
        with test_directory() as directory:
            root = Path(directory)
            sbin = root / 'sbin'; sbin.mkdir()
            stack = root / 'stack'; (stack / 'status').mkdir(parents=True)
            # Reconstruct the installed v0.19.39 functions from guarded fixtures.
            for name in ('pcga-game-orchestrator', 'pcga-heroic-sync'):
                # Tests also run inside a standalone release on the server.
                # Baseline function text is carried as a test fixture.
                (sbin / name).write_bytes((ROOT / 'tests/fixtures' / (name + '-1938.txt')).read_bytes())
            control = sbin / 'pcga-control'; control.write_text('''VERSION = "0.19.40"
NETBIRD_PROVIDER = "netbird"
OTHER_PROVIDERS = {"netbird": "status"}
LOCAL_FIX = True
DOCKER_SERVICES = {
    "wolf": "wolf",
}
def compose_files():
    names = ["compose.yml", "compose.nas.yml"]
    return names
''')
            portal = stack / 'status/server.py'
            portal_text = (ROOT / 'components/pcga-status-server.py').read_text(encoding='utf8')
            portal.write_text(portal_text.replace('0.19.43', '0.19.40'), encoding='utf8')
            wolf = root / 'wolf.toml'; wolf.write_bytes(b'original config\n')
            state_dir = root / 'var/lib/pc-game-archive/game-installs'; state_dir.mkdir(parents=True)
            state = state_dir / 'game.json'; state.write_bytes(b'{"stream_state":"failed"}')
            original = {p: p.read_bytes() for p in [control, portal, wolf, state, sbin/'pcga-game-orchestrator', sbin/'pcga-heroic-sync']}
            commands = []
            def runner(args, **kwargs):
                commands.append(args)
                stdout = 'active' if args[:2] == ['systemctl', 'is-active'] and args[-1].endswith('.timer') else 'inactive'
                return SimpleNamespace(returncode=0, stdout=stdout, stderr='')
            calls = []
            def reconcile(recover=False):
                calls.append(recover)
                if recover:
                    wolf.write_bytes(b'reconciled config\n')
                    state.write_bytes(b'{"stream_state":"ready"}')
            def mapped_path(path):
                return sandbox_path(path, root)
            native_mkdir = Path.mkdir
            def portable_mkdir(path, mode=0o777, parents=False, exist_ok=False):
                return native_mkdir(path, mode=0o755 if os.name == 'nt' and mode == 0o700 else mode,
                                    parents=parents, exist_ok=exist_ok)
            with contextlib.ExitStack() as contexts:
                for name, item in {'SBIN': sbin, 'STACK': stack, 'WOLF_CONFIG': wolf, 'Path': mapped_path,
                                   'run': runner, 'reconcile_catalog': reconcile, 'pool_ready': lambda: None,
                                   'wolf_started': lambda: 'same-start-time', 'refresh_portal': lambda: None,
                                   'validate_portal': lambda: None, 'log': lambda *a: None}.items():
                    contexts.enter_context(patch.object(upgrade, name, item))
                contexts.enter_context(patch.object(upgrade.os, 'geteuid', return_value=0, create=True))
                contexts.enter_context(patch.object(pcga_wolf_config, 'stack_lock', lambda **kw: contextlib.nullcontext()))
                contexts.enter_context(patch.object(Path, 'mkdir', portable_mkdir))
                contexts.enter_context(patch.object(upgrade.sys, 'path', list(upgrade.sys.path)))
                if fail_validation:
                    contexts.enter_context(patch.object(upgrade, 'validate_live_apps', side_effect=RuntimeError('lane check failed')))
                    with self.assertRaisesRegex(RuntimeError, 'lane check failed'):
                        upgrade.main()
                    self.assertTrue(all(path.read_bytes() == data for path, data in original.items()))
                    self.assertFalse((sbin / 'pcga_wolf_config.py').exists())
                    self.assertFalse((sbin / 'pcga-netbird-remote').exists())
                    self.assertFalse((sbin / 'pcga-netbird-container-entrypoint').exists())
                    self.assertFalse((sbin / 'pcga-thin-client-bootstrap').exists())
                    self.assertFalse((stack / 'compose.netbird.yml').exists())
                else:
                    contexts.enter_context(patch.object(upgrade, 'validate_live_apps', lambda: None))
                    upgrade.main()
                    self.assertEqual(calls, [True, False])
                    self.assertIn(b'VERSION = "0.19.43"', control.read_bytes())
                    self.assertIn(b'"netbird": "pcga-netbird"', control.read_bytes())
                    self.assertIn(b'"compose.netbird.yml"', control.read_bytes())
                    self.assertTrue((sbin / 'pcga_wolf_config.py').is_file())
                    self.assertTrue((sbin / 'pcga-netbird-remote').is_file())
                    self.assertTrue((sbin / 'pcga-netbird-container-entrypoint').is_file())
                    self.assertTrue((sbin / 'pcga-thin-client-bootstrap').is_file())
                    self.assertTrue((stack / 'compose.netbird.yml').is_file())
            self.assertIn(['systemctl', 'stop'] + upgrade.TIMERS, commands)
            self.assertIn(['systemctl', 'start'] + upgrade.TIMERS, commands)

    def test_install_restores_timers_after_success(self):
        self.simulate_install()

    def test_failed_lane_validation_restores_files_states_config_and_timers(self):
        self.simulate_install(fail_validation=True)


if __name__ == '__main__':
    unittest.main()
