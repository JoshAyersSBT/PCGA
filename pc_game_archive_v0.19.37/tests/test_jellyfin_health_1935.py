"""Jellyfin must be a managed service and never vanish from diagnostics."""
import io
import json
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
ROOT = Path(__file__).resolve().parents[1]

def load(name):
    module=types.ModuleType('pcga_1935_'+name)
    module.__file__=str(ROOT/'components'/name)
    exec(compile((ROOT/'components'/name).read_text(),module.__file__,'exec'),module.__dict__)
    return module

class JellyfinRecovery1935(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control=load('pcga-control')
        cls.portal=load('pcga-status-server.py')

    def test_missing_jellyfin_is_shown_in_media_diagnostics(self):
        c=self.control
        c._LOG_CATALOG_CACHE.update({'data': None, 'at': 0})
        with patch.object(c,'_systemd_log_candidates',return_value=[]), \
            patch.object(c,'_docker_log_candidates',return_value=[]), \
            patch.object(c,'_setup_session_log_candidates',return_value=[]):
            catalog=c.log_catalog(force=True)
        self.assertIn('docker:jellyfin',catalog['profiles']['media']['services'])
        entry=next(x for x in catalog['services'] if x['id']=='docker:jellyfin')
        self.assertEqual(entry['state'],'missing')
        self.assertFalse(entry['active'])

    def test_present_jellyfin_has_no_synthetic_duplicate(self):
        c=self.control
        with patch.object(c,'_systemd_log_candidates',return_value=[]), \
            patch.object(c,'_docker_log_candidates',return_value=[('jellyfin','jellyfin/jellyfin','Up','')]), \
            patch.object(c,'docker_state',return_value={'state':'running','active':True,'health':'healthy'}), \
            patch.object(c,'_setup_session_log_candidates',return_value=[]):
            catalog=c.log_catalog(force=True)
        self.assertEqual(sum(x['id']=='docker:jellyfin' for x in catalog['services']),1)

    def test_reachable_health_without_token(self):
        m=self.portal
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch.object(m.urllib.request,'urlopen',return_value=Response()),patch.object(m,'jellyfin_token',return_value=None):
            result=m.jellyfin_health_status()
        self.assertTrue(result['reachable'])
        self.assertFalse(result['token_configured'])

    def test_network_failure_is_a_readable_health_result(self):
        m=self.portal
        with patch.object(m.urllib.request,'urlopen',side_effect=URLError('connection refused')),patch.object(m,'jellyfin_token',return_value='example'):
            result=m.jellyfin_health_status()
        self.assertFalse(result['reachable'])
        self.assertIn('unreachable',result['detail'])

    def test_upgrade_refuses_silent_missing_service(self):
        text=(ROOT/'upgrade_to_v0.19.37.sh').read_text()
        self.assertIn('JELLYFIN_COMPOSE_DEFINED',text)
        self.assertIn('compose_up_retry -d --no-deps jellyfin',text)
        self.assertIn('JELLYFIN_APP_ENABLED',text)
        self.assertIn('PCGA_TOOL_HOST',text)
        self.assertIn('PCGA_JELLYFIN_PORT',text)
        self.assertIn('http://127.0.0.1:${JELLYFIN_CURRENT}/health',text)
        self.assertIn('/api/jellyfin/health',text)
        self.assertIn('docker:jellyfin',text)
        self.assertNotIn('compose_up_retry -d --no-deps --force-recreate jellyfin',text)

    def test_player_recovery_link(self):
        src=(ROOT/'components/pcga-status-server.py').read_text()
        self.assertIn('data-library-retry',src)
        self.assertIn('data-library-diagnostics',src)
        self.assertIn("p.value='media'",src)

if __name__=='__main__':unittest.main()
