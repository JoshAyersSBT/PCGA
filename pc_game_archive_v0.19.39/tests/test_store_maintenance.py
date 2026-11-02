"""v0.19.12 maintenance guardrails; no store accounts or installed Docker needed."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

COMP = Path(__file__).resolve().parents[1] / 'components'

def load(path, name):
    loader=importlib.machinery.SourceFileLoader(name, str(path))
    spec=importlib.util.spec_from_loader(name,loader)
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    loader.exec_module(obj)
    return obj

provider=load(COMP/'pcga-store-provider','pcga_store_provider_maint_test')
control=load(COMP/'pcga-control','pcga_control_maint_test')

class MaintenanceQueue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        cls.env=mock.patch.dict(os.environ,{'PCGA_STORE_JOB_STATE':str(cls.root/'queue'), 'PCGA_STORE_JOB_LOG_ROOT':str(cls.root/'logs')})
        cls.env.start()
        cls.jobs=load(COMP/'pcga-store-jobs','pcga_store_jobs_maint_test')

    @classmethod
    def tearDownClass(cls):
        cls.env.stop();cls.temp.cleanup()

    def test_operations_and_cross_action_dedupe(self):
        self.assertEqual(self.jobs.ALLOWED_OPERATIONS, ('install','update','verify','uninstall'))
        a=self.jobs.enqueue('epic','update','MaintCheck1')['job']
        b=self.jobs.enqueue('epic','uninstall','MaintCheck1')
        self.assertFalse(b['created'])
        self.assertEqual(a['id'],b['job']['id'])
        old=self.jobs.enqueue('epic','verify','Retry123')['job']
        self.jobs.cancel_job(old['id'])
        new=self.jobs.enqueue('epic','install','Retry123')['job']
        with self.assertRaisesRegex(ValueError, 'active job'):
            self.jobs.retry_job(old['id'])
        self.jobs.cancel_job(new['id'])
        self.jobs.cancel_job(a['id'])

    def test_cancel_inflight_uninstall_blocked(self):
        row=self.jobs.enqueue('gog','uninstall','testCancellation')['job']
        self.jobs._update(row['id'],state='running')
        with self.assertRaisesRegex(ValueError,'cannot be interrupted'):
            self.jobs.cancel_job(row['id'])
        self.jobs._update(row['id'],state='completed')

    def test_gog_uninstall_only_owned_folder(self):
        root=self.root/'storage';library=root/'library';library.mkdir(parents=True,exist_ok=True)
        (library/'gog').mkdir(exist_ok=True)
        state=root/'providers';state.mkdir(parents=True,exist_ok=True)
        target=library/'gog'/'1423049311';target.mkdir(exist_ok=True)
        (target/'Game.exe').write_bytes(b'fake')
        prefix=root/'external-prefix';prefix.mkdir(exist_ok=True)
        (prefix/'user.reg').write_text('preserve')
        (target/'prefix-link').symlink_to(prefix,target_is_directory=True)
        manifest=state/'gog-installed.json'
        manifest.write_text(json.dumps({'schema':1,'games':{'1423049311':{'install_path':str(target)}}}))
        class M:
            STATE_ROOT=state
            @staticmethod
            def host_layout(): return {'library':library}
        self.jobs.gog_uninstall_managed(M,'1423049311')
        self.assertFalse(target.exists())
        self.assertTrue((prefix/'user.reg').exists())
        self.assertFalse(json.loads(manifest.read_text())['games'])

    def test_gog_uninstall_rejects_symlinks_or_wrong_manifest(self):
        root=self.root/'reject';library=root/'library';gog=library/'gog';gog.mkdir(parents=True,exist_ok=True)
        state=root/'state';state.mkdir(exist_ok=True)
        outside=root/'outside';outside.mkdir(exist_ok=True);(outside/'keep').write_text('keep')
        (gog/'someGOG').symlink_to(outside,target_is_directory=True)
        (state/'gog-installed.json').write_text(json.dumps({'games':{'someGOG':{'install_path':str(outside)}}}))
        class M:
            STATE_ROOT=state
            @staticmethod
            def host_layout(): return {'library':library}
        with self.assertRaisesRegex(RuntimeError,'unsafe'):
            self.jobs.gog_uninstall_managed(M,'someGOG')
        self.assertEqual((outside/'keep').read_text(),'keep')
        other=gog/'otherGame';other.mkdir()
        (state/'gog-installed.json').write_text(json.dumps({'games':{'otherGame':{'install_path':str(outside)}}}))
        with self.assertRaisesRegex(RuntimeError,'does not match'):
            self.jobs.gog_uninstall_managed(M,'otherGame')

    def test_launch_reservation_blocks_maintenance(self):
        game='ReservationGOG'
        sid='store-'+__import__('hashlib').sha256(('gog\x00'+game).encode()).hexdigest()[:24]
        reservation=self.root/'pending.json'
        reservation.write_text(json.dumps({'reservations':{'abcd':{'game_set_id':sid,'reserved_at':self.jobs.now(),'container_id':None}}}))
        with mock.patch.dict(os.environ,{'PCGA_GAME_RESERVATIONS_PATH':str(reservation)}):
            self.assertTrue(self.jobs._active_game_runtime('gog',game))
        reservation.write_text('{broken json')
        with mock.patch.dict(os.environ,{'PCGA_GAME_RESERVATIONS_PATH':str(reservation)}):
            with self.assertRaisesRegex(RuntimeError,'Cannot verify'):
                self.jobs._active_game_runtime('gog',game)

class ProviderStatus(unittest.TestCase):
    def test_catalog_error_actionable_and_no_traceback(self):
        error=RuntimeError('''[cli] INFO: Logging in...\nTraceback (most recent call last):\n File "/some/internal/core.py", line 44, in login\n RuntimeError: auth expired''')
        msg=provider._catalog_failure_detail('epic',error)
        self.assertIn('Epic',msg)
        self.assertIn('Control Center',msg)
        self.assertNotIn('Traceback',msg)
        self.assertNotIn('core.py',msg)
        self.assertIn('Amazon',provider._catalog_failure_detail('amazon',RuntimeError('ERROR [CLI]: User not logged in')))
        self.assertIn('GOG',provider._catalog_failure_detail('gog',RuntimeError('null')))

    def test_gog_cached_installed_state_revoked_after_uninstall(self):
        fake={'provider':'gog','provider_game_id':'missing_game','installed':True,'status':'installed','installed_source':'pcga-gog'}
        with mock.patch.object(provider,'_gog_managed_installs',return_value={}),mock.patch.object(provider,'_legacy_heroic_installed_map',return_value={}):
            row=provider._overlay_legacy_installed([fake])[0]
        self.assertFalse(row['installed'])
        self.assertEqual(row['status'],'owned')

if __name__=='__main__':unittest.main()
