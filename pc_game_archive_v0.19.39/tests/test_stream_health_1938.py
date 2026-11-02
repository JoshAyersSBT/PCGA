import copy
import json
import importlib.machinery
import importlib.util
from pathlib import Path
import ssl
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


health = load('stream_health', ROOT / 'components/pcga-stream-health')
try:
    import fcntl
except ImportError:
    with patch.dict(sys.modules, {'fcntl': types.ModuleType('fcntl')}):
        installer = load('stream_installer', ROOT / 'upgrade_runtime.py')
else:
    installer = load('stream_installer', ROOT / 'upgrade_runtime.py')

ADDRESS = '192.168.4.45'


def pool():
    return {'state': 'ready', 'lanes': [
        {'lane': lane, 'state': 'ready', 'paired': True, 'network_mode': 'host',
         'wolf_address': ADDRESS, 'host_id': lane * 100, 'web_port': 8100 + lane}
        for lane in range(1, 5)
    ]}


def fetch(port, path, context):
    if path == '/api/authenticate':
        return {'id': 1}
    if path.startswith('/api/host?'):
        return {'host': {'address': ADDRESS}}
    return {'apps': [{'title': 'PCGA Game', 'app_id': 3}]}


class HealthChecks(unittest.TestCase):
    def test_live_protocol_empty_200_auth_and_json_host_apps_pass_all_lanes(self):
        def respond(req, **kwargs):
            path = health.urllib.parse.urlsplit(req.full_url).path
            response = MagicMock()
            response.status = 200
            response.read.return_value = b'' if path == '/api/authenticate' else json.dumps(
                {'host': {'address': ADDRESS}} if path == '/api/host' else {'apps': []}).encode()
            response.__enter__.return_value = response
            return response
        with patch.object(health.urllib.request, 'urlopen', side_effect=respond) as opener:
            result = health.check_pool(pool(), ADDRESS, None)
        self.assertTrue(result['ready'], result)
        self.assertEqual(opener.call_count, 12)

    def test_empty_host_or_apps_response_is_still_rejected(self):
        for path in ('/api/host?host_id=100', '/api/apps?host_id=100'):
            with self.subTest(path=path):
                response = MagicMock()
                response.status = 200
                response.read.return_value = b''
                response.__enter__.return_value = response
                with patch.object(health.urllib.request, 'urlopen', return_value=response):
                    with self.assertRaisesRegex(ValueError, 'empty or invalid JSON'):
                        health.request_json(8101, path, None)

    def test_empty_auth_response_does_not_override_http_failure(self):
        response = MagicMock()
        response.status = 401
        response.read.return_value = b''
        response.__enter__.return_value = response
        with patch.object(health.urllib.request, 'urlopen', return_value=response):
            with self.assertRaisesRegex(ValueError, '/api/authenticate: HTTP 401'):
                health.request_json(8101, '/api/authenticate', None)

    def test_healthy_pool_checks_every_live_lane(self):
        calls = []
        def recorder(port, path, context):
            calls.append((port, path))
            return fetch(port, path, context)
        result = health.check_pool(pool(), ADDRESS, None, recorder)
        self.assertTrue(result['ready'])
        self.assertEqual({port for port, _ in calls}, {8101, 8102, 8103, 8104})
        self.assertEqual(len(calls), 12)

    def test_cached_ready_does_not_hide_changed_dhcp_address(self):
        result = health.check_pool(pool(), '192.168.4.99', None,
                                   lambda *args: self.fail('stale identity must fail before network access'))
        self.assertFalse(result['ready'])
        self.assertTrue(all('LAN address' in row['detail'] for row in result['lanes']))

    def test_only_one_broken_lane_makes_pool_unhealthy(self):
        def unavailable(port, path, context):
            if port == 8103:
                raise TimeoutError('connection timed out')
            return fetch(port, path, context)
        result = health.check_pool(pool(), ADDRESS, None, unavailable)
        self.assertFalse(result['ready'])
        self.assertEqual([x['lane'] for x in result['lanes'] if not x['ready']], [3])

    def test_saved_host_can_be_current_but_live_registration_stale(self):
        def wrong_host(port, path, context):
            if path.startswith('/api/host?'):
                return {'address': '192.168.4.26'}
            return fetch(port, path, context)
        result = health.check_pool(pool(), ADDRESS, None, wrong_host)
        self.assertFalse(result['ready'])

    def test_tls_failure_is_not_treated_as_pairing_success(self):
        def bad_tls(*args):
            raise ssl.SSLCertVerificationError('untrusted server')
        result = health.check_pool(pool(), ADDRESS, None, bad_tls)
        self.assertFalse(result['ready'])

    def test_http_200_error_body_is_not_an_app_list(self):
        def error_apps(port, path, context):
            return {'error': 'not paired'} if path.startswith('/api/apps?') else fetch(port, path, context)
        self.assertFalse(health.check_pool(pool(), ADDRESS, None, error_apps)['ready'])

    def test_explicit_default_user_authentication_failure(self):
        def unauth(port, path, context):
            return {'authenticated': False} if path == '/api/authenticate' else fetch(port, path, context)
        self.assertFalse(health.check_pool(pool(), ADDRESS, None, unauth)['ready'])

    def test_duplicate_and_missing_lane_records_are_rejected(self):
        for rows in (pool()['lanes'][:3], [pool()['lanes'][0]] * 4, [None] * 4):
            with self.subTest(rows=rows):
                self.assertFalse(health.check_pool({'lanes': rows}, ADDRESS, None, fetch)['ready'])

    def test_invalid_host_id_does_not_reach_network(self):
        data = pool()
        data['lanes'][0]['host_id'] = True
        self.assertFalse(health.check_pool(data, ADDRESS, None, fetch)['ready'])


class InstallerTransforms(unittest.TestCase):
    def test_version_upgrade_preserves_installed_local_logic(self):
        source = 'VERSION = "0.19.37"\nlocal_setting = 42\n'
        result = installer.patch_version(source)
        self.assertIn('VERSION = "0.19.38"', result)
        self.assertIn('local_setting = 42', result)
        self.assertEqual(installer.patch_version(result), result)

    def test_outdated_source_requires_previous_upgrade_first(self):
        with self.assertRaises(ValueError):
            installer.patch_version('VERSION = "0.19.13"\n')

    def test_vendor_startup_keeps_relay_raw_and_sets_uri_for_dotnet_only(self):
        source = '''#!/bin/bash
WOLF_SOCKET_PATH=/var/run/wolf/wolf.sock
socat UNIX-LISTEN:/app/wolf.sock,mode=600 UNIX-CONNECT:"${WOLF_SOCKET_PATH}" &
exec gosu "${APP_UID}" dotnet WolfLeash.dll &
wait $!
'''
        result = installer.patch_den_entrypoint(source)
        self.assertIn('UNIX-CONNECT:"${WOLF_SOCKET_PATH}"', result)
        self.assertIn('UNIX-LISTEN:/app/wolf.sock,unlink-early,', result)
        self.assertIn('--unix-socket /app/wolf.sock', result)
        self.assertLess(result.index('socat '), result.index('export WOLF_SOCKET_PATH=unix:///app/wolf.sock'))
        self.assertLess(result.index('export WOLF_SOCKET_PATH=unix:///app/wolf.sock'), result.index('exec gosu '))
        self.assertEqual(installer.patch_den_entrypoint(result), result)

    def test_unknown_vendor_entrypoint_is_rejected_before_install(self):
        with self.assertRaises(ValueError):
            installer.patch_den_entrypoint('#!/bin/sh\nexec dotnet Unknown.dll\n')

    def test_compose_mount_is_scoped_to_den_and_idempotent(self):
        source = '''services:
  wolf:
    image: wolf
    volumes:
      - /dev:/dev
  wolf-den:
    image: wolf-den
    volumes:
      - /var/run/wolf:/var/run/wolf
  another:
    image: other
'''
        result = installer.patch_compose(source)
        self.assertEqual(result.split('  wolf-den:')[0], source.split('  wolf-den:')[0])
        self.assertEqual(result.split('  another:')[1], source.split('  another:')[1])
        self.assertEqual(result.count(installer.DEN_MOUNT), 1)
        self.assertEqual(installer.patch_compose(result), result)

    def test_existing_custom_entrypoint_is_not_overwritten(self):
        source = 'services:\n  wolf-den:\n    volumes:\n      - /custom/script:/entrypoint.sh:ro\n'
        with self.assertRaises(ValueError):
            installer.patch_compose(source)

    def test_background_reconciliation_checks_live_connection_even_when_cached_ready(self):
        source = '''if [[ "$moon_state" != ready ]]; then
    /usr/local/sbin/pcga-moonlight-web-bootstrap || { log 'Moonlight Web reconciliation failed; timer will retry'; failed=1; }
  fi'''
        result = installer.patch_auth(source)
        self.assertNotIn('if [[ "$moon_state" != ready ]]', result)
        self.assertIn('if /usr/local/sbin/pcga-stream-health', result)
        self.assertIn('still unhealthy after reconciliation', result)
        self.assertEqual(installer.patch_auth(result), result)


class RepairDeferral(unittest.TestCase):
    def setUp(self):
        self.sessions = MagicMock(spec=Path)
        self.sessions.exists.return_value = False
        self.path_patch = patch.object(health, 'SESSIONS', self.sessions)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def test_active_game_blocks_repair(self):
        with patch.object(health.subprocess, 'run', return_value=SimpleNamespace(stdout='PCGA-Game-123\n')):
            self.assertFalse(health.safe_to_repair()['safe_to_repair'])

    def test_control_session_blocks_repair_without_pcga_container(self):
        with patch.object(health.subprocess, 'run', side_effect=[SimpleNamespace(stdout='wolf\n'), SimpleNamespace(stdout='0 0 192.168.4.45:48010 192.168.4.36:53000\n')]):
            self.assertFalse(health.safe_to_repair()['safe_to_repair'])

    def test_pending_browser_launch_blocks_repair(self):
        self.sessions.exists.return_value = True
        self.sessions.read_text.return_value = '{"reservations":{"a":{"reserved_at":9999999999}}}'
        with patch.object(health.subprocess, 'run', return_value=SimpleNamespace(stdout='')):
            self.assertFalse(health.safe_to_repair()['safe_to_repair'])

    def test_idle_and_expired_reservation_allow_repair(self):
        self.sessions.exists.return_value = True
        self.sessions.read_text.return_value = '{"reservations":{"a":{"reserved_at":1}}}'
        with patch.object(health.subprocess, 'run', return_value=SimpleNamespace(stdout='')):
            self.assertTrue(health.safe_to_repair()['safe_to_repair'])

    def test_failed_inspection_never_permits_restart(self):
        with patch.object(health.subprocess, 'run', side_effect=OSError('docker unavailable')):
            self.assertFalse(health.safe_to_repair()['safe_to_repair'])


if __name__ == '__main__':
    unittest.main()
