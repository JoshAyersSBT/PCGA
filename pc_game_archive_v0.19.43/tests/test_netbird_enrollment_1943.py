import importlib.util
import importlib.machinery
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_component(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


remote = load_component('pcga_netbird_remote_1943', ROOT / 'components' / 'pcga-netbird-remote')
upgrade = load_component('pcga_upgrade_catalog_1943', ROOT / 'upgrade_catalog.py')


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return json.dumps(self.payload).encode()


class NetBirdEnrollment1943(unittest.TestCase):
    def test_client_key_is_created_as_one_off_ephemeral_and_never_returned_from_status(self):
        token_path = Path('test-management-api-token')
        url_path = Path('test-management-url')
        original = Path.read_text
        def read_text(path, *args, **kwargs):
            if path == token_path:
                return 'pat-secret'
            if path == url_path:
                return 'https://netbird.example.test'
            return original(path, *args, **kwargs)
        with patch.object(remote, 'MANAGEMENT_API_TOKEN', token_path), \
             patch.object(remote, 'MANAGEMENT_URL', url_path), \
             patch.object(Path, 'read_text', read_text), \
             patch.object(remote.urllib.request, 'urlopen', return_value=Response({'key': 'one-use-key'})) as request:
            result = remote.issue_client_key({'client_id': 'living-room'})
        self.assertTrue(result['ok'])
        self.assertEqual(result['setup_key'], 'one-use-key')
        args, kwargs = request.call_args
        self.assertEqual(args[0].full_url, 'https://netbird.example.test/api/setup-keys')
        self.assertEqual(args[0].get_header('Authorization'), 'Token pat-secret')
        body = json.loads(args[0].data)
        self.assertEqual(body['type'], 'one-off')
        self.assertEqual(body['usage_limit'], 1)
        self.assertTrue(body['ephemeral'])
        self.assertEqual(body['expires_in'], 86400)
        self.assertEqual(body['auto_groups'], [])
        self.assertEqual(kwargs['timeout'], 12)

    def test_bootstrap_only_requests_ephemeral_key_when_client_asks(self):
        source = (ROOT / 'components' / 'pcga-thin-client-bootstrap').read_text()
        self.assertIn('request.get("request_netbird_setup_key") is True', source)
        self.assertIn('request.get("auto_enroll") is True', source)
        self.assertIn('"issue-client-key"', source)
        self.assertIn('"setup_key": str(candidate["setup_key"])', source)

    def test_portal_patch_adds_secret_entry_and_configuration_action_idempotently(self):
        source = (ROOT / 'components' / 'pcga-status-server.py').read_text(encoding='utf8')
        patched = upgrade.patch_portal(source)
        self.assertIn('cc-nb-api-token', patched)
        self.assertIn('netbird-configure-api', patched)
        self.assertEqual(upgrade.patch_portal(patched), patched)


if __name__ == '__main__':
    unittest.main()
