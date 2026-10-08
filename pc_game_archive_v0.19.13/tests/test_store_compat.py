#!/usr/bin/env python3
"""Offline tests for PCGA v0.19.11 UMU policy and Wolf integration."""
from __future__ import annotations
import importlib.machinery,importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest import mock

def load(name,path):
    loader=importlib.machinery.SourceFileLoader(name,str(path))
    spec=importlib.util.spec_from_loader(name,loader)
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;loader.exec_module(mod);return mod

COMP=Path(__file__).resolve().parents[1]/'components'
compat=load('store_compat_test',COMP/'pcga-store-compat')
ingest=load('store_ingest_compat_test',COMP/'pcga-store-ingest')

class StoreCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)/'archive';self.root.mkdir()
        self.umu=Path(temp.name)/'umu';self.umu.mkdir()
        self.rootfile=Path(temp.name)/'root';self.rootfile.write_text(str(self.root))
        self.patches=[]
        for name,val in [('ROOT_FILE',self.rootfile),('STATE',self.umu)]:
            p=mock.patch.object(compat,name,val);p.start();self.addCleanup(p.stop)
        (self.root/'games/stores/prefixes').mkdir(parents=True)
        self.sid='store-'+'a'*24
        # Ingestion loader gets a new module, so pass isolated UMU state as env.
        env=mock.patch.dict(os.environ,{'PCGA_STORE_UMU_STATE':str(self.umu),'PCGA_ARCHIVE_ROOT_FILE':str(self.rootfile)})
        env.start();self.addCleanup(env.stop)
    def test_auto_is_wine_until_umu_is_prepared(self):
        cfg=compat.settings_for(self.sid,archive=self.root)
        self.assertEqual(cfg['effective_runner'],'wine')
        self.assertFalse(cfg['umu_prepared'])
        (self.umu/'umu-run').write_bytes(b'#!/bin/sh\n'+b'a'*13000);(self.umu/'umu-run').chmod(0o755)
        self.assertEqual(compat.settings_for(self.sid,archive=self.root)['effective_runner'],'umu')
    def test_old_wine_prefix_is_kept_when_umu_appears(self):
        path=self.root/'games/stores/prefixes'/self.sid
        (path/'drive_c').mkdir(parents=True)
        (self.umu/'umu-run').write_bytes(b'#!/bin/sh\n'+b'a'*13000);(self.umu/'umu-run').chmod(0o755)
        state=compat.settings_for(self.sid,archive=self.root)
        self.assertTrue(state['legacy_wine_prefix'])
        self.assertEqual(state['effective_runner'],'wine')
        self.assertTrue((path/'drive_c').is_dir())
    def test_proton_override_changes_wolf_mount_and_runner(self):
        (self.umu/'umu-run').write_bytes(b'#!/bin/sh\n'+b'a'*13000);(self.umu/'umu-run').chmod(0o755)
        cfg=compat.read()
        cfg['games'][self.sid]={'mode':'umu','proton':'GE-Proton','gameid':'umu-1234'}
        compat.save(cfg)
        entry={'pcga_set_id':self.sid,'provider':'epic','provider_game_id':'Demo','relative_install_path':'Epic', 'exe_relative':'', 'stream_app_title':'Demo'}
        toml=ingest.app_block(entry,self.root)
        self.assertIn('PCGA_STORE_COMPAT_RUNNER=umu',toml)
        self.assertIn('PCGA_STORE_PROTON=GE-Proton',toml)
        self.assertIn('PCGA_STORE_UMU_GAMEID=umu-1234',toml)
        self.assertIn('/opt/pcga-umu/umu-run:ro',toml)
        self.assertIn('/prefixes/proton/'+self.sid+':/pcga/prefix:rw',toml)
        self.assertTrue((self.root/'games/stores/prefixes/proton'/self.sid).is_dir())
        self.assertNotIn('Privileged": true',toml)
    def test_invalid_gameid_is_never_persisted_from_cli(self):
        p=subprocess.run([str(COMP/'pcga-store-compat'),'set-game','--game-id',self.sid,'--umu-gameid','$(touch /tmp/fail)'],capture_output=True,text=True,env=os.environ)
        self.assertNotEqual(p.returncode,0)
        self.assertFalse(compat.store_file().exists())
    def test_same_toml_generated_consistently_and_no_boot_download(self):
        entry={'pcga_set_id':self.sid,'provider':'gog','provider_game_id':'1999','relative_install_path':'gog/1999','exe_relative':'title.exe','stream_app_title':'Title'}
        one=ingest.app_block(entry,self.root)
        two=ingest.app_block(entry,self.root)
        self.assertEqual(one,two)
        self.assertIn('PCGA_STORE_COMPAT_RUNNER=wine',one)
        self.assertNotIn('/opt/pcga-umu/umu-run:ro',one)
        self.assertFalse((self.umu/'umu-run').exists())
    def test_default_validation(self):
        self.assertEqual(compat.clean({'mode':'random','proton':'evil','gameid':'bad id'}),{'mode':'auto','proton':'UMU-Proton','gameid':'umu-default'})
    def test_prepared_check_requires_nonempty_real_binary(self):
        (self.umu/'umu-run').write_bytes(b'')
        self.assertFalse(compat.prepared())

if __name__=='__main__':unittest.main()
