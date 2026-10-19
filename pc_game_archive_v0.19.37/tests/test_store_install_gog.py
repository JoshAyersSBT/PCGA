#!/usr/bin/env python3
"""GOG native install fixtures, no accounts or downloads required."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

COMP=Path(__file__).resolve().parents[1] / 'components'
def load(path,name):
    loader=importlib.machinery.SourceFileLoader(name,str(path))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    loader.exec_module(module)
    return module
control=load(COMP/'pcga-control','pcga_control_gog_test')
provider=load(COMP/'pcga-store-provider','pcga_store_provider_gog_test')

class GogControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);archive=root/'archive';archive.mkdir()
        archive_file=root/'archive-root';archive_file.write_text(str(archive))
        patch=mock.patch.object(control,'ROOT_FILE',archive_file);patch.start();self.addCleanup(patch.stop)
        self.connected=True;self.owned=True;self.installed=False;self.active=False
        self.calls=[]
        def provider_stub(args,timeout):
            self.calls.append(args)
            if args[0]=='accounts':return {'ok':True,'providers':[{'id':'gog','connected':self.connected}]}
            if args[0]=='library':return {'ok':True,'providers':[{'provider':'gog','available':True}], 'items':[{'provider':'gog','provider_game_id':'1423049311','title':'Cyberpunk 2077', 'owned':self.owned,'installed':self.installed,'installable':True}]}
            raise AssertionError(args)
        def job_stub(limit):return {'ok':True,'jobs':[{'id':'job-1','provider':'gog','app_id':'1423049311','state':'running'}] if self.active else []}
        for name,fn in [('_store_provider_call',provider_stub),('store_jobs',job_stub)]:
            patch=mock.patch.object(control,name,side_effect=fn);patch.start();self.addCleanup(patch.stop)

    def payload(self): return {'provider':'gog','app_id':'1423049311','title':'UNTRUSTED'}
    def test_gog_owned_install_preflight(self):
        info=control.store_install_preflight(self.payload())
        self.assertEqual(info['title'],'Cyberpunk 2077')
        self.assertEqual(info['provider'],'gog')
        self.assertTrue(info['can_enqueue'])
        self.assertNotIn('install',[args[0] for args in self.calls])
        with mock.patch.object(control,'_store_jobs_call',return_value={'ok':True,'created':True,'job':{'id':'sj-demo'}}) as jobs, mock.patch.object(control,'run'):
            self.assertTrue(control.store_job_enqueue(self.payload())['created'])
            self.assertEqual(jobs.call_args.args[0],['enqueue','--provider','gog','--operation','install','--app-id','1423049311','--title','Cyberpunk 2077'])

    def test_gog_guardrails(self):
        self.connected=False
        with self.assertRaisesRegex(ValueError,'Connect'):control.store_install_preflight(self.payload())
        self.connected=True;self.owned=False
        with self.assertRaisesRegex(ValueError,'not found'):control.store_install_preflight(self.payload())
        self.owned=True;self.installed=True
        with self.assertRaisesRegex(ValueError,'already installed'):control.store_install_preflight(self.payload())
        self.installed=False;self.active=True
        self.assertFalse(control.store_install_preflight(self.payload())['can_enqueue'])
        with self.assertRaisesRegex(ValueError,'Amazon'):
            control.store_job_enqueue({'provider':'amazon','app_id':'123'})
        with self.assertRaisesRegex(ValueError,'not registered as installed'):
            control.store_job_enqueue({'provider':'gog','app_id':'1423049311','operation':'uninstall'})

class GogQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        os.environ['PCGA_STORE_JOB_STATE']=str(cls.root/'queue')
        os.environ['PCGA_STORE_JOB_LOG_ROOT']=str(cls.root/'logs')
        cls.jobs=load(COMP/'pcga-store-jobs','pcga_store_jobs_gog_test')
    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_gog_command_plan(self):
        p=provider.PROVIDERS['gog'].install_plan('1423049311','Cyberpunk 2077')[0]
        self.assertEqual(p.operation,'install')
        self.assertTrue(p.mutating)
        self.assertEqual(p.argv[2:4],('download','1423049311'))
        self.assertIn('--support',p.argv)
        self.assertEqual(p.argv[p.argv.index('--path')+1],'/pcga/library/gog/1423049311')
        self.assertNotIn('UNTRUSTED',p.argv)
        with self.assertRaises(ValueError):provider.PROVIDERS['gog'].install_plan('--mount','Title')

    def test_gog_progress_and_separate_queue(self):
        parsed=self.jobs.parse_progress('Progress: 1423049311 1.11/89.08 MiB/00:06:02')
        self.assertAlmostEqual(parsed['progress'],1.246,places=1)
        self.assertEqual(parsed['bytes_total'],int(89.08*1024**2))
        e=self.jobs.enqueue('epic','install','SharedName','Epic title')
        g=self.jobs.enqueue('gog','install','SharedName','GOG title')
        self.assertNotEqual(e['job']['id'],g['job']['id'])
        self.assertEqual(self.jobs.container_name(e['job']['id']),f"pcga-epic-{e['job']['id']}")
        self.assertEqual(self.jobs.container_name(g['job']['id'],'gog'),f"pcga-gog-{g['job']['id']}")
        self.jobs.cancel_job(e['job']['id']);self.jobs.cancel_job(g['job']['id'])

    def test_gog_success_manifest_and_overlay(self):
        app='1423049311'
        job=self.jobs.enqueue('gog','install',app,'Cyberpunk 2077')['job']
        root=self.root/'library';target=root/'gog'/app
        target.mkdir(parents=True,exist_ok=True)
        (target/'Game.exe').write_bytes(b'fixture')
        state=self.root/'provider-state'
        class Plan:
            mutating=True;operation='install';argv=('--auth-config-path','/pcga/config/gog/auth.json','download',app,'--path','/pcga/library/gog/'+app)
        class Store:
            id='gog'
        class FakeModule:
            DOCKER='docker';PROVIDERS={'gog':Store()};STATE_ROOT=state
            @staticmethod
            def docker_image_ready():return True
            @staticmethod
            def plans_for(pid,op,aid,title):return [Plan()]
            @staticmethod
            def host_layout():return {'library':root}
            @staticmethod
            def docker_argv(pid,argv):return ['docker','run','--rm','fake-image',*argv]
        original_popen=subprocess.Popen
        def popen_stub(argv,**kwargs):
            self.assertEqual(argv[2:4],['--name',self.jobs.container_name(job['id'],'gog')])
            return original_popen([sys.executable,'-u','-c','print("Progress: 1423049311 89.08/89.08 MiB/00:00:00")'],**kwargs)
        with mock.patch.object(self.jobs,'load_provider_module',return_value=FakeModule),mock.patch.object(self.jobs,'stop_managed_container'),mock.patch.object(self.jobs.subprocess,'Popen',side_effect=popen_stub):
            self.jobs.run_job(job['id'],threading.Event())
        result=self.jobs.get_job(job['id'])['job']
        self.assertEqual(result['state'],'completed',result['error'])
        manifest=json.loads((state/'gog-installed.json').read_text())
        self.assertEqual(manifest['games'][app]['install_path'],str(target))
        self.assertEqual((state/'gog-installed.json').stat().st_mode&0o777,0o600)
        with mock.patch.object(provider,'STATE_ROOT',state),mock.patch.object(provider,'host_layout',return_value={'library':root}):
            rows=provider._overlay_legacy_installed([{'provider':'gog','provider_game_id':app,'installed':False}])
        self.assertTrue(rows[0]['installed'])
        self.assertEqual(rows[0]['installed_source'],'pcga-gog')
        (target/'Game.exe').unlink()
        with mock.patch.object(provider,'STATE_ROOT',state),mock.patch.object(provider,'host_layout',return_value={'library':root}):
            rows=provider._overlay_legacy_installed([{'provider':'gog','provider_game_id':app,'installed':False}])
        self.assertFalse(rows[0]['installed'])

    def test_gog_empty_success_not_installed(self):
        row={'app_id':'123456','title':'No Files','id':'sj-20261008000000-1234567890'}
        fake=type('Provider',(),{'host_layout':lambda _:{'library':GogQueueTests.root/'library'},'STATE_ROOT':self.root/'state'})()
        with self.assertRaisesRegex(RuntimeError,'directory is missing'):
            self.jobs.record_gog_install(fake,row)

if __name__=='__main__':unittest.main(verbosity=2)
