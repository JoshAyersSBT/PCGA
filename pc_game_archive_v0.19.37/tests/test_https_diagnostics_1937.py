"""v0.19.37 regression for TLS-only Diagnostics and truthful upgrade errors."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
SCRIPT = (BASE / 'upgrade_to_v0.19.37.sh').read_text()
CHECKER = BASE / 'components/pcga-upgrade-diagnostics-check'

loader = importlib.machinery.SourceFileLoader('upgrade_diag_1937', str(CHECKER))
spec = importlib.util.spec_from_loader(loader.name, loader)
checker = importlib.util.module_from_spec(spec)
loader.exec_module(checker)


def catalog(*, media=True):
    return {
        'ok': True,
        'services': [{'id': 'docker:pcga-status'}, {'id': 'docker:jellyfin'}],
        'profiles': {'streaming': {'services': ['docker:pcga-status']},
                     'media': {'services': ['docker:jellyfin'] if media else []}},
    }


class HttpsDiagnostics1937(unittest.TestCase):
    def test_secure_endpoint_unchanged(self):
        portal = (BASE / 'components/pcga-status-server.py').read_text()
        self.assertIn('if not isinstance(self.connection, ssl.SSLSocket):', portal)
        self.assertIn('HTTPStatus.UPGRADE_REQUIRED', portal)

    def test_jellyfin_requires_media_membership_not_merely_presence(self):
        self.assertTrue(checker.verify(catalog(), True))
        with self.assertRaisesRegex(ValueError, 'absent from the secure Media'):
            checker.verify(catalog(media=False), True)
        self.assertTrue(checker.verify(catalog(media=False), False))

    def test_invalid_json_and_catalog_are_clean_errors(self):
        with self.assertRaisesRegex(ValueError, 'invalid types'):
            checker.verify({'ok': True, 'services': {}, 'profiles': {}}, True)
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / 'broken.json'
            f.write_text('not json')
            result = subprocess.run(['python3', str(CHECKER), str(f), 'true'], text=True, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Diagnostics verification failed:', result.stderr)
            self.assertNotIn('Traceback', result.stderr)

    def test_one_secure_catalog_and_no_http_diagnostics(self):
        self.assertEqual(SCRIPT.count('https://127.0.0.1:8443/api/diagnostics/catalog'), 1)
        self.assertNotIn('http://127.0.0.1:8098/api/diagnostics/catalog', SCRIPT)
        self.assertIn('--cacert /etc/pc-game-archive/tls/pcga-ca.crt', SCRIPT)
        self.assertIn('"$COMP/pcga-upgrade-diagnostics-check"', SCRIPT)
        self.assertIn('http://127.0.0.1:8098/api/jellyfin/health', SCRIPT)

    def run_shell_validation(self, status, response, enabled='true'):
        # Exercise the *real upgrade Bash segment* without needing Docker or TLS.
        a = SCRIPT.index('diagnostics_response="$(mktemp)"')
        b = SCRIPT.index('log "HTTPS Diagnostics catalog and Media profile validated"', a)
        segment = SCRIPT[a:b + len('log "HTTPS Diagnostics catalog and Media profile validated"')]
        with tempfile.TemporaryDirectory() as t:
            body = Path(t) / 'reply'
            body.write_text(response)
            mock = '''
set -Eeuo pipefail
COMP=''' + "'" + str(BASE / 'components') + "'" + '''
JELLYFIN_APP_ENABLED=''' + "'" + enabled + "'" + '''
log(){ echo "LOG:$*"; }
die(){ echo "ERROR:$*" >&2; exit 20; }
curl(){
  local dest=''
  while (($#)); do
    if [[ "$1" == '-o' ]]; then dest="$2"; shift 2; else shift; fi
  done
  cp "${MOCK_REPLY}" "$dest"
  printf '%s' "${MOCK_STATUS}"
}
''' + segment + '\n'
            result = subprocess.run(['bash', '-c', mock], text=True, capture_output=True,
                                    env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'MOCK_REPLY': str(body), 'MOCK_STATUS': str(status)})
            return result

    def test_actual_bash_rejects_426_without_json_traceback(self):
        result = self.run_shell_validation('426', '{"ok":false,"error":"secure-context-required","detail":"Open HTTPS PCGA portal"}')
        self.assertEqual(result.returncode, 20)
        self.assertIn('HTTPS Diagnostics catalog returned HTTP 426', result.stderr)
        self.assertIn('Open HTTPS PCGA portal', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertNotIn('missing from the Media', result.stderr)

    def test_actual_bash_accepts_valid_secure_media_catalog(self):
        result = self.run_shell_validation('200', json.dumps(catalog()))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Media profile validated', result.stdout)

    def test_actual_bash_rejects_missing_media(self):
        result = self.run_shell_validation('200', json.dumps(catalog(media=False)))
        self.assertEqual(result.returncode, 20)
        self.assertIn('absent from the secure Media', result.stderr)
        self.assertNotIn('JSONDecodeError', result.stderr)

    def test_actual_bash_accepts_jellyfin_disabled(self):
        result = self.run_shell_validation('200', json.dumps(catalog(media=False)), enabled='false')
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
