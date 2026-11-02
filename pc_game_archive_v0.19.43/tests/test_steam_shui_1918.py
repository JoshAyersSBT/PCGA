"""v0.19.18 regression checks for Steam Headless v3, no Docker required."""
from pathlib import Path
import json
import ssl
import tempfile
import types
import unittest
import urllib.error
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def load():
    m=types.ModuleType('pcga_steam_native_test')
    m.__file__=str(ROOT/'components/pcga-steam-native')
    exec(compile((ROOT/'components/pcga-steam-native').read_text(), m.__file__, 'exec'),m.__dict__)
    return m


class SteamHeadlessV3Tests(unittest.TestCase):
    def setUp(self):
        self.module=load()

    def test_https_port_is_8483_and_401_means_auth_required_not_offline(self):
        m=self.module
        self.assertEqual(m.SHUI_URL,'https://127.0.0.1:8483/')
        failure=urllib.error.HTTPError(m.SHUI_URL,401,'Unauthorized',{},None)
        with patch.object(m.urllib.request,'urlopen',side_effect=failure) as req:
            self.assertEqual(m.web_probe(m.SHUI_URL),(True,401))
        self.assertEqual(req.call_args.kwargs['context'].verify_mode,ssl.CERT_NONE)
        with patch.object(m.urllib.request,'urlopen',side_effect=ConnectionRefusedError()):
            self.assertEqual(m.web_probe(m.SHUI_URL),(False,None))

    def test_steam_status_does_not_expose_bootstrap_password_and_requires_true_streaming(self):
        m=self.module
        def checks(cmd,timeout=4):
            return 'bootstrap-password' in cmd or 'pgrep -x steam' in cmd
        patches=[
            patch.object(m,'container_state',return_value=('running',m.IMAGE)),
            patch.object(m,'scan',return_value=[]),
            patch.object(m,'diagnostics',return_value={'missing_devices':[]}),
            patch.object(m,'configured_encoder',return_value='auto'),
            patch.object(m,'verify_existing_container'),
            patch.object(m,'container_encoder',return_value='auto'),
            patch.object(m,'web_probe',return_value=(True,401)),
            patch.object(m,'container_check',side_effect=checks),
            patch.object(m,'h264_encode_capability',return_value=False),
        ]
        for p in patches:p.start()
        try: result=m.status()
        finally:
            for p in reversed(patches):p.stop()
        self.assertEqual(result['stage'],'setup-required')
        self.assertFalse(result['ready'])
        self.assertFalse(result['streaming_ready'])
        self.assertEqual(result['diagnostics']['web_ui_http_status'],401)
        self.assertFalse(result['diagnostics']['hardware_h264_encode'])
        self.assertEqual(result['steam_login'],'unverified')
        self.assertNotIn('password',json.dumps(result).lower().replace('bootstrap-password',''))

    def test_shui_and_steam_process_running_does_not_imply_sunshine_streaming(self):
        m=self.module
        with patch.object(m,'container_state',return_value=('running',m.IMAGE)),\
             patch.object(m,'scan',return_value=[]),\
             patch.object(m,'diagnostics',return_value={}),\
             patch.object(m,'configured_encoder',return_value='auto'),\
             patch.object(m,'verify_existing_container'),\
             patch.object(m,'container_encoder',return_value='auto'),\
             patch.object(m,'web_probe',return_value=(True,401)),\
             patch.object(m,'container_check',side_effect=lambda c,timeout=4: 'pgrep -x steam' in c),\
             patch.object(m,'h264_encode_capability',return_value=True):
            result=m.status()
        self.assertEqual(result['stage'],'streaming-unavailable')
        self.assertTrue(result['ready'])
        self.assertFalse(result['streaming_ready'])
        self.assertFalse(result['diagnostics']['sunshine_running'])

    def test_setting_encoder_updates_container_args_and_persists_file(self):
        m=self.module
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(m,'ENCODER_CONFIG',Path(temp)/'steam-encoder'):
                self.assertEqual(m.configured_encoder(),'auto')
                m.save_encoder('software')
                self.assertEqual(m.configured_encoder(),'software')
                self.assertEqual(m.ENCODER_CONFIG.stat().st_mode & 0o777,0o600)
                argv=m.launch_args(1000,1000,'/test/home','/test/library','/test/state','/test/journal',[])
                self.assertIn('SHUI_ENCODER=software',argv)
                self.assertIn('/test/state:/var/lib/steam-headless',argv)
                with self.assertRaises(ValueError):m.save_encoder('software; rm -rf /')

    def test_non_disruptive_encoder_migration_for_decode_only_gpu(self):
        m=self.module
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(m,'ENCODER_CONFIG',Path(temp)/'steam-encoder'),\
                 patch.object(m,'container_state',return_value=('running',m.IMAGE)),\
                 patch.object(m,'verify_existing_container'),\
                 patch.object(m,'h264_encode_capability',return_value=False),\
                 patch.object(m,'status',return_value={'ok':True}) as status,\
                 patch.object(m,'execute') as commands:
                m.reconcile_encoder()
                self.assertEqual(m.configured_encoder(),'software')
                self.assertFalse(commands.called,'migration must not stop or recreate Steam')
                self.assertEqual(status.call_count,1)

    def test_configure_apply_guards_foreign_container_before_writing(self):
        m=self.module
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(m,'ENCODER_CONFIG',Path(temp)/'steam-encoder'),\
                 patch.object(m,'container_state',return_value=('running','other/image')):
                with self.assertRaises(RuntimeError):m.configure_encoder('software',apply=True)
                self.assertFalse(m.ENCODER_CONFIG.exists())

    def test_portal_frontend_uses_https_setup_and_exposes_separate_health(self):
        code=(ROOT/'components/pcga-status-server.py').read_text()
        self.assertIn("const url='https://'+location.hostname+':8483/'",code)
        self.assertNotIn("'http://'+location.hostname+':8083/'",code)
        for hook in ('cc-steam-encoder','cc-steam-shui','cc-steam-client','cc-steam-sunshine','cc-steam-enrollment','data-steam-encoder-apply'):
            self.assertIn(hook,code)
        host=(ROOT/'components/pcga-control').read_text()
        self.assertIn('steam-native-encoder-apply',host)
        self.assertIn('steam-native-encoder-save',host)

if __name__=='__main__':unittest.main()
