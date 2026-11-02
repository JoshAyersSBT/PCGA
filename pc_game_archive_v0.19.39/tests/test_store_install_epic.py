#!/usr/bin/env python3
"""v0.19.6 guarded native Epic install preflight, no live store credentials."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

CONTROL=Path(__file__).resolve().parents[1]/'components'/'pcga-control'
loader=importlib.machinery.SourceFileLoader('pcga_control_install_fixture',str(CONTROL))
spec=importlib.util.spec_from_loader(loader.name,loader)
mod=importlib.util.module_from_spec(spec)
loader.exec_module(mod)

class StoreInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.archive=root/'archive'
        self.archive.mkdir()
        archive_file=root/'archive-root'
        archive_file.write_text(str(self.archive))
        self.root_patch=mock.patch.object(mod,'ROOT_FILE',archive_file)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.account=True
        self.installed=False
        self.owned=True
        self.installable=True
        self.active=False
        self.completed=False
        self.calls=[]
        self.provider_patch=mock.patch.object(mod,'_store_provider_call',side_effect=self.fake_provider)
        self.provider_patch.start();self.addCleanup(self.provider_patch.stop)
        self.jobs_patch=mock.patch.object(mod,'store_jobs',side_effect=self.fake_jobs)
        self.jobs_patch.start();self.addCleanup(self.jobs_patch.stop)

    def fake_provider(self,args,timeout):
        self.calls.append(list(args))
        if args[0]=='accounts':
            return {'ok':True,'providers':[{'id':'epic','connected':self.account}]}
        if args[0]=='library':
            return {'ok':True,'providers':[{'provider':'epic','available':True}], 'items':[
                {'provider':'epic','provider_game_id':'OwnedGame','title':'Trusted Library Title',
                 'owned':self.owned,'installed':self.installed,'installable':self.installable}]}
        raise AssertionError(args)

    def fake_jobs(self,limit):
        rows=[]
        if self.active:rows.append({'id':'active','provider':'epic','app_id':'OwnedGame','state':'running'})
        if self.completed:rows.append({'id':'complete','provider':'epic','app_id':'OwnedGame','state':'completed'})
        return {'ok':True,'jobs':rows}

    def payload(self):return {'provider':'epic','operation':'install','app_id':'OwnedGame','title':'Attacker-provided title'}

    def test_valid_preflight_nonmutating(self):
        x=mod.store_install_preflight(self.payload())
        self.assertTrue(x['can_enqueue']);self.assertEqual(x['title'],'Trusted Library Title')
        self.assertGreater(x['free_bytes'],0)
        self.assertEqual(self.calls[0][0],'accounts')
        self.assertEqual(self.calls[1][0],'library')
        self.assertNotIn('install',[x[0] for x in self.calls])

    def test_rejects_unowned_and_installed(self):
        self.owned=False
        with self.assertRaisesRegex(ValueError,'not found'):mod.store_install_preflight(self.payload())
        self.owned=True;self.installed=True
        with self.assertRaisesRegex(ValueError,'already installed'):mod.store_install_preflight(self.payload())

    def test_rejects_disconnected_and_other_stores(self):
        self.account=False
        with self.assertRaisesRegex(ValueError,'Connect'):mod.store_install_preflight(self.payload())
        with self.assertRaisesRegex(ValueError,'Epic Games and GOG only'):mod.store_install_preflight({'provider':'amazon','app_id':'OwnedGame'})
        with self.assertRaises(ValueError):mod.store_install_preflight({'provider':'epic','app_id':'--option'})

    def test_existing_jobs_and_completed(self):
        self.active=True
        self.assertFalse(mod.store_install_preflight(self.payload())['can_enqueue'])
        self.active=False;self.completed=True
        self.assertFalse(mod.store_install_preflight(self.payload())['can_enqueue'])
        with self.assertRaisesRegex(ValueError,'completed'):
            mod.store_job_enqueue(self.payload())

    def test_canonical_title_and_dedupe(self):
        self.active=True
        response=mod.store_job_enqueue(self.payload())
        self.assertFalse(response['created']);self.assertEqual(response['job']['id'],'active')
        self.active=False
        with mock.patch.object(mod,'_store_jobs_call',return_value={'ok':True,'created':True,'job':{'id':'queued'}}) as queue, mock.patch.object(mod,'run'):
            response=mod.store_job_enqueue(self.payload())
            self.assertTrue(response['created'])
            self.assertEqual(queue.call_args[0][0][-1],'Trusted Library Title')

    def test_requires_storage_and_reserve(self):
        with mock.patch.object(mod.os,'statvfs') as vfs:
            vfs.return_value=type('Stat',(),{'f_bavail':1,'f_frsize':1})()
            with self.assertRaisesRegex(ValueError,'2 GiB'):mod.store_install_preflight(self.payload())

if __name__=='__main__':unittest.main(verbosity=2)
