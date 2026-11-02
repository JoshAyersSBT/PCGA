import importlib.util
import importlib.machinery
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader(
    'pcga_netbird_remote', str(ROOT / 'components' / 'pcga-netbird-remote')
)
spec = importlib.util.spec_from_loader(loader.name, loader)
remote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote)


def result(code=0, stdout='', stderr=''):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


class NetBirdContainer1941(unittest.TestCase):
    def test_compose_uses_host_network_and_persistent_peer_state(self):
        compose = (ROOT / 'components' / 'compose.netbird.yml').read_text()
        for expected in (
            'image: netbirdio/netbird:0.81.3',
            'network_mode: host',
            '- NET_ADMIN',
            '- SYS_ADMIN',
            '- SYS_RESOURCE',
            '/dev/net/tun:/dev/net/tun',
            '/var/lib/pc-game-archive/netbird:/var/lib/netbird',
            '/etc/pc-game-archive/netbird:/run/pcga-netbird:ro',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, compose)
        self.assertNotIn('NB_SETUP_KEY', compose)
        self.assertNotIn('setup-key:', compose)

    def test_status_requires_management_and_startup_health(self):
        management = result(stdout='{"management":{"connected":true}}')
        startup = result()
        address = result(stdout='100.64.0.9/16\n')
        with patch.object(remote.shutil, 'which', return_value='docker'), \
             patch.object(remote, '_container_running', return_value=True), \
             patch.object(remote, '_netbird', side_effect=[management, startup, address]):
            state = remote.status()
        self.assertTrue(state['configured'])
        self.assertEqual(state['state'], 'ready')
        self.assertEqual(state['ip'], '100.64.0.9')

        for json_output, startup_result in (
            ('{"management":{}}', result()),
            ('{"management":{"connected":true}}', result(code=1, stderr='relay down')),
        ):
            with self.subTest(json_output=json_output, startup=startup_result.returncode), \
                 patch.object(remote.shutil, 'which', return_value='docker'), \
                 patch.object(remote, '_container_running', return_value=True), \
                 patch.object(remote, '_netbird', side_effect=[result(stdout=json_output), startup_result]), \
                 patch.object(remote, 'run', return_value=result(stdout='container diagnostics')):
                state = remote.status()
            self.assertFalse(state['configured'])
            self.assertEqual(state['state'], 'disconnected')

    def test_connect_writes_key_to_secret_file_and_never_to_process_arguments(self):
        key = 'one-time-secret-value'
        secret_dir = ROOT / 'netbird-secret-test-absent'
        with patch.object(remote, 'SETUP_DIR', secret_dir), \
             patch.object(remote, 'SETUP_KEY', secret_dir / 'setup-key'), \
             patch.object(remote, 'MANAGEMENT_URL', secret_dir / 'management-url'), \
             patch.object(remote, '_container_running', return_value=True), \
             patch.object(remote, 'read_payload', return_value={'setup_key': key}), \
             patch.object(remote, '_write_secret') as write_secret, \
             patch.object(remote, 'status', return_value={'ok': True, 'configured': True}), \
             patch.object(remote, 'run') as command:
            state = remote.connect()
        self.assertTrue(state['configured'])
        write_secret.assert_called_once_with(secret_dir / 'setup-key', key)
        self.assertNotIn(key, ' '.join(str(arg) for call in command.call_args_list for arg in call.args))
        entrypoint = (ROOT / 'components' / 'pcga-netbird-container-entrypoint').read_text()
        self.assertIn('--setup-key-file "$SETUP_KEY"', entrypoint)
        self.assertNotIn('--setup-key "$', entrypoint)


if __name__ == '__main__':
    unittest.main()
