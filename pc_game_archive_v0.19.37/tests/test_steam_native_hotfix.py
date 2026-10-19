"""Offline tests for first-run Steam Headless startup and safe repair."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'components' / 'pcga-steam-native'
loader = importlib.machinery.SourceFileLoader('pcga_steam_native', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
steam = importlib.util.module_from_spec(spec)
loader.exec_module(steam)


def ok(stdout=''):
    return SimpleNamespace(returncode=0, stdout=stdout, stderr='')


class SteamHotfixTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'archive').mkdir()
        self.config = self.root / 'archive-root'
        self.config.write_text(str(self.root / 'archive'))
        self.env = self.root / '.env'
        self.env.write_text('PUID=1234\nPGID=4321\n')
        self.patcher = patch.multiple(steam, ROOT_CONFIG=self.config, STACK_ENV=self.env)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_identity_prefers_appliance_over_sudo_and_is_initialized_first(self):
        with patch.dict(os.environ, {'SUDO_UID': '9999', 'SUDO_GID': '9999'}):
            self.assertEqual(steam.runtime_identity(), (1234, 4321))
        seen = []
        def fake_chown(path, uid, gid):
            seen.append((path, uid, gid))
        with patch.object(steam.os, 'chown', fake_chown):
            identity = steam.prepare_directories()
        self.assertEqual(identity[:2], (1234, 4321))
        self.assertEqual(len(seen), 2)
        self.assertEqual([i[1:] for i in seen], [(1234, 4321), (1234, 4321)])

    def test_first_launch_passes_upstream_required_mounts_and_gpu(self):
        calls = []
        def fake_execute(argv, timeout=25):
            calls.append(argv)
            return ok('created')
        with patch.object(steam, 'execute', fake_execute), \
             patch.object(steam, 'container_state', side_effect=[('not-installed', ''), ('running', steam.IMAGE)]), \
             patch.object(steam, 'device_nodes', return_value=['/dev/dri/card0', '/dev/dri/renderD128', '/dev/uinput', '/dev/fuse']), \
             patch.object(steam.os, 'chown'), \
             patch.object(steam.shutil, 'which', return_value='/usr/bin/docker'):
            result = steam.start()
        self.assertEqual(result['status'], 'running')
        argv = calls[0]
        self.assertEqual(argv[:3], ['docker', 'run', '-d'])
        for flag in ('--cgroupns', '--device-cgroup-rule', '--tmpfs', '--stop-signal'):
            self.assertIn(flag, argv)
        self.assertIn('PUID=1234', argv)
        self.assertIn('PGID=4321', argv)
        self.assertIn('/dev/dri/card0', argv)
        self.assertIn('/dev/dri/renderD128', argv)
        self.assertIn('writable-cgroups=true', argv)
        self.assertTrue(any(str(self.root/'archive'/'games'/'steam'/'home') in str(x) for x in argv))

    def test_scan_custom_and_default_library_deduplicated(self):
        _,home,library,_,_ = steam.steam_paths()
        for base in (library/'steamapps', home/'.local/share/Steam/steamapps'):
            base.mkdir(parents=True)
            (base/'appmanifest_440.acf').write_text('"AppState"\n{\n"appid" "440"\n"name" "Team Fortress 2"\n"StateFlags" "4"\n}')
        (library/'steamapps'/'appmanifest_500.acf').write_text('"AppState"\n{\n"name" "Incomplete"\n"StateFlags" "2"\n}')
        result = steam.scan()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['title'], 'Team Fortress 2')

    def test_libraryfolders_vdf_scans_only_managed_locations(self):
        _, home, library, _, _ = steam.steam_paths()
        config_dir = home / '.local/share/Steam/steamapps'
        extra = library / 'additional/steamapps'
        extra.mkdir(parents=True)
        config_dir.mkdir(parents=True)
        (config_dir / 'libraryfolders.vdf').write_text('"libraryfolders"\n{\n"1" { "path" "/mnt/games/additional" }\n"2" { "path" "/etc" }\n}')
        (extra / 'appmanifest_570.acf').write_text('"name" "Dota 2"\n"StateFlags" "4"\n')
        # Real libraryfolders formats place path on its own line.
        (config_dir / 'libraryfolders.vdf').write_text('"libraryfolders"\n{\n"1"\n{\n"path" "/mnt/games/additional"\n}\n"2"\n{\n"path" "/etc"\n}\n}')
        self.assertEqual([g['appid'] for g in steam.scan()], ['570'])
        self.assertFalse(any(str(path).startswith('/etc') for path in steam.steam_manifest_dirs()))

    def test_existing_container_start_refuses_wrong_mount(self):
        with patch.object(steam, 'container_state', return_value=('exited', steam.IMAGE)), \
             patch.object(steam, 'device_nodes', return_value=['/dev/dri/card0']), \
             patch.object(steam, 'container_mounts', return_value=[]), \
             patch.object(steam.os, 'chown'), \
             patch.object(steam.shutil, 'which', return_value='/usr/bin/docker'), \
             patch.object(steam, 'execute') as docker:
            with self.assertRaisesRegex(RuntimeError, 'non-PCGA storage'):
                steam.start()
            docker.assert_not_called()

    def test_repair_refuses_external_mounts_and_wrong_image(self):
        with patch.object(steam, 'container_state', return_value=('exited','not-pcga/image')):
            with self.assertRaisesRegex(RuntimeError, 'unexpected image'):
                steam.repair()
        with patch.object(steam, 'container_state', return_value=('exited',steam.IMAGE)), \
             patch.object(steam, 'container_mounts', return_value=[{'Type':'bind','Destination':'/mnt/games','Source':'/tmp/unrelated'}]):
            with self.assertRaisesRegex(RuntimeError, 'non-PCGA storage'):
                steam.repair()

    def test_repair_recreates_container_without_removing_volumes(self):
        calls = []
        def fake_execute(argv, timeout=25):
            calls.append(argv)
            return ok('ok')
        paths = steam.steam_paths()
        mounts = [{'Type':'bind','Destination':dest,'Source':str(src)} for dest,src in zip(
            ('/home/steamheadless','/mnt/games','/var/lib/steam-headless','/var/log/journal'), paths[1:])]
        with patch.object(steam, 'container_state', side_effect=[('exited',steam.IMAGE), ('not-installed',''), ('running',steam.IMAGE)]), \
             patch.object(steam, 'container_mounts', return_value=mounts), \
             patch.object(steam, 'device_nodes', return_value=['/dev/dri/card0','/dev/dri/renderD128','/dev/uinput','/dev/fuse']), \
             patch.object(steam, 'execute', fake_execute), \
             patch.object(steam.os, 'chown'), \
             patch.object(steam.shutil, 'which', return_value='/usr/bin/docker'):
            result = steam.repair()
        self.assertFalse(result['ready'])  # Docker running is not SHUI / login readiness
        self.assertEqual(result['status'], 'running')
        self.assertIn(['docker', 'rm', steam.NAME], calls)
        self.assertTrue(any(x[:3] == ['docker', 'run', '-d'] for x in calls))
        self.assertFalse(any('rm' in x and '-v' in x for x in calls))


if __name__ == '__main__':
    unittest.main()
