#!/usr/bin/env python3
"""End-to-end, offline/store-fixture coverage for v0.19.10 store ingestion."""
from __future__ import annotations
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

SRC=Path(__file__).parents[1]/'components'/'pcga-store-ingest'
loader=importlib.machinery.SourceFileLoader('pcga_store_ingest_test',str(SRC))
spec=importlib.util.spec_from_loader(loader.name,loader)
ingest=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=ingest; loader.exec_module(ingest)

class StoreIngestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name); self.archive=self.base/'archive';self.archive.mkdir()
        self.provider=self.base/'provider';self.provider.mkdir()
        self.wolf=self.base/'wolf.toml'
        self.wolf.write_text('[[profiles]]\nid = "not-the-target"\n[[profiles.apps]]\ntitle = "Unrelated"\n\n[[profiles]]\nid = "moonlight-profile-id"\n\n[[profiles.apps]]\ntitle = "Unrelated PCGA game"\n')
        path=self.base/'archive-root';path.write_text(str(self.archive))
        lock_env=mock.patch.dict(os.environ,{'PCGA_GAME_STACK_LOCK':str(self.base/'game-stack.lock')});lock_env.start();self.addCleanup(lock_env.stop)
        for name,value in [('ROOT_FILE',path),('PROVIDER_STATE',self.provider),('STATE',self.base/'state'),('PUBLIC',self.base/'public.json'),('JOBS_DB',self.base/'jobs.sqlite3'),('WOLF_CONFIG',self.wolf)]:
            p=mock.patch.object(ingest,name,value);p.start();self.addCleanup(p.stop)
        lib=self.archive/'games/stores/library';lib.mkdir(parents=True)
        config=self.archive/'games/stores/config/legendary';config.mkdir(parents=True)
        epic=lib/'EpicTest';epic.mkdir();(epic/'data.bin').write_bytes(b'a')
        (config/'installed.json').write_text(json.dumps({'EpicUnique':{'app_name':'EpicUnique','install_path':'/pcga/library/EpicTest'}}))
        gog=lib/'gog/1999';gog.mkdir(parents=True)
        (gog/'GOGGame.exe').write_bytes(b'x'*200000)
        (self.provider/'gog-installed.json').write_text(json.dumps({'games':{'1999':{'install_path':str(gog)}}}))
        db=sqlite3.connect(ingest.JOBS_DB)
        db.execute('CREATE TABLE jobs (id TEXT,provider TEXT,app_id TEXT,title TEXT,finished_at REAL,state TEXT,operation TEXT)')
        db.executemany('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)',[
            ('sj-epic','epic','EpicUnique','Epic Unique Title',123,'completed','install'),
            ('sj-gog','gog','1999','GOG Unique Title',124,'completed','install')])
        db.commit();db.close()
        self.calls=[]
        def fake_run(args,timeout=45):
            self.calls.append(args)
            if args[:2]==['docker','ps']:return mock.Mock(returncode=0,stdout='')
            return mock.Mock(returncode=0,stdout='',stderr='')
        patch=mock.patch.object(ingest,'run',side_effect=fake_run);patch.start();self.addCleanup(patch.stop)
        if self._testMethodName != 'test_missing_backend_does_not_implicitly_pull':
            patch=mock.patch.object(ingest,'build_runtime',return_value=True);patch.start();self.addCleanup(patch.stop)

    def test_direct_store_ingestion_and_wolf_profile(self):
        games=ingest.discovered_games(self.archive,ingest.confirmed_jobs())
        self.assertEqual(len(games),2)
        self.assertEqual({g['title'] for g in games},{'Epic Unique Title','GOG Unique Title'})
        self.assertTrue(all(g['launchable'] for g in games))
        self.assertEqual(next(g['exe_relative'] for g in games if g['provider']=='gog'),'GOGGame.exe')
        result=ingest.reconcile()
        self.assertEqual(result['count'],2)
        self.assertEqual(result['status'],'published')
        data=json.loads(ingest.PUBLIC.read_text())
        self.assertEqual(data['count'],2)
        self.assertTrue(all(row['playable'] for row in data['items']))
        self.assertEqual([x[:2] for x in self.calls].count(['docker','restart']),1)
        import tomllib
        doc=tomllib.loads(self.wolf.read_text())
        self.assertEqual(len(doc['profiles']),2)
        self.assertEqual(len(doc['profiles'][0]['apps']),1)
        self.assertEqual(len(doc['profiles'][1]['apps']),3)
        self.assertEqual(len(set(x['title'] for x in doc['profiles'][1]['apps'])),3)
        self.calls.clear(); self.assertEqual(ingest.reconcile()['status'],'published')
        self.assertFalse(any(x[:2]==['docker','restart'] for x in self.calls))

    def test_running_stream_defers_registration(self):
        with mock.patch.object(ingest,'active_games',return_value=True):
            outcome=ingest.reconcile()
        self.assertEqual(outcome['status'],'pending-active-stream')
        self.assertFalse(any(x[:2]==['docker','restart'] for x in self.calls))
        self.assertTrue(all(not x['playable'] for x in json.loads(ingest.PUBLIC.read_text())['items']))
        self.assertEqual(ingest.reconcile()['status'],'published')

    def test_ambiguous_gog_executable_requires_setup(self):
        gog=self.archive/'games/stores/library/gog/1999';(gog/'OtherGame.exe').write_bytes(b'x'*200000)
        games=ingest.discovered_games(self.archive,ingest.confirmed_jobs())
        g=next(x for x in games if x['provider']=='gog')
        self.assertTrue(g['setup_required']);self.assertFalse(g['launchable'])
        ingest.reconcile()
        doc=__import__('tomllib').loads(self.wolf.read_text())
        apps=doc['profiles'][1]['apps']
        self.assertEqual(len(apps),2)  # existing app + Epic only
        self.assertIn('GOG Unique Title',str(json.loads(ingest.PUBLIC.read_text())))

    def test_bad_epic_location_never_registered(self):
        outside=self.base/'outside';outside.mkdir();(outside/'evil.bin').write_text('no')
        (self.archive/'games/stores/config/legendary/installed.json').write_text(json.dumps({'EpicUnique':{'install_path':str(outside)}}))
        games=ingest.discovered_games(self.archive,ingest.confirmed_jobs())
        self.assertEqual(len(games),1)
        self.assertEqual(games[0]['provider'],'gog')

    def test_disconnected_storage_keeps_previous_catalog_and_wolf(self):
        self.assertEqual(ingest.reconcile()['status'],'published')
        previous=self.wolf.read_bytes();catalog=ingest.PUBLIC.read_bytes()
        import shutil
        shutil.rmtree(self.archive/'games/stores/library')
        with self.assertRaisesRegex(RuntimeError,'library unavailable'):
            ingest.reconcile()
        self.assertEqual(previous,self.wolf.read_bytes())
        self.assertEqual(catalog,ingest.PUBLIC.read_bytes())

    def test_missing_backend_does_not_implicitly_pull(self):
        with mock.patch.object(ingest,'run',return_value=mock.Mock(returncode=1)) as called:
            self.assertFalse(ingest.build_runtime())
            self.assertEqual(called.call_args.args[0][:3],['docker','image','inspect'])
            self.assertFalse(any('pull' in str(x.args) for x in called.call_args_list))

if __name__=='__main__':unittest.main()
