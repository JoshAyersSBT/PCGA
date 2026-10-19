#!/usr/bin/env python3
"""v0.19.6 Epic queue regression tests; no real Docker or store account required."""
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

JOBS = Path(__file__).resolve().parents[1] / 'components' / 'pcga-store-jobs'

class QueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        os.environ['PCGA_STORE_JOB_STATE'] = str(cls.root / 'db')
        os.environ['PCGA_STORE_JOB_LOG_ROOT'] = str(cls.root / 'logs')
        loader = importlib.machinery.SourceFileLoader('pcga_store_jobs_epic_test', str(JOBS))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.m = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.m)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_epic_and_gog_only(self):
        self.assertEqual(self.m.PROVIDERS, ('epic','gog'))
        self.assertEqual(self.m.ALLOWED_OPERATIONS, ('install', 'update', 'verify', 'uninstall'))
        for provider in ('amazon',):
            with self.assertRaises(ValueError):
                self.m.enqueue(provider, 'install', 'ABCD')
        for op in ('uninstall', 'verify', 'update'):
            job=self.m.enqueue('epic', op, f'ABCD_{op}')
            self.assertTrue(job['created'])
            self.m.cancel_job(job['job']['id'])
        with self.assertRaises(ValueError):
            self.m.enqueue('epic', 'install', '--flag')

    def test_sqlite_durable_dedupe_and_privacy(self):
        one = self.m.enqueue('epic', 'install', 'SomeEpicApp', 'Epic Test Game')
        two = self.m.enqueue('epic', 'install', 'SomeEpicApp', 'Epic Test Game')
        self.assertTrue(one['created'])
        self.assertFalse(two['created'])
        self.assertEqual(one['job']['id'], two['job']['id'])
        self.assertEqual(self.m.DB_PATH.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.m.list_jobs()['enabled_providers'], ['epic', 'gog'])
        fresh = self.m.connect()
        self.assertEqual(fresh.execute('SELECT COUNT(*) FROM jobs WHERE app_id=?', ('SomeEpicApp',)).fetchone()[0], 1)
        fresh.close()
        self.assertEqual(self.m.cancel_job(one['job']['id'])['job']['state'], 'cancelled')
        self.assertEqual(self.m.retry_job(one['job']['id'])['job']['state'], 'queued')
        self.assertEqual(self.m.cancel_job(one['job']['id'])['job']['state'], 'cancelled')
        self.assertTrue(self.m.delete_job(one['job']['id'])['ok'])

    def test_redaction_and_progress(self):
        p = self.m.parse_progress('Downloading 43.5% • 1.5 GiB / 4 GiB • 13 MiB/s')
        self.assertEqual(p['progress'], 43.5)
        self.assertEqual(p['bytes_done'], 1610612736)
        self.assertEqual(p['speed_bps'], 13631488)
        text = self.m.redact('access_token=abcd https://example.com/download?token=xyz&code=secret')
        self.assertNotIn('abcd', text)
        self.assertNotIn('xyz', text)
        self.assertNotIn('secret', text)

    def test_worker_mocked_success(self):
        enqueue = self.m.enqueue('epic', 'install', 'fixtureGame', 'Fixture game')
        job_id = enqueue['job']['id']
        class Plan:
            mutating = True
            operation = 'install'
            argv = ('-y', 'install', 'fixtureGame', '--base-path', '/pcga/library')
        class Provider:
            id = 'epic'
        class FakeModule:
            DOCKER = 'docker'
            PROVIDERS = {'epic': Provider()}
            @staticmethod
            def docker_image_ready(): return True
            @staticmethod
            def plans_for(provider, operation, app_id, title): return [Plan()]
            @staticmethod
            def host_layout(): return {'library': str(self.root)}
            @staticmethod
            def docker_argv(provider, argv): return ['docker','run','--rm','--entrypoint','legendary','fake-image',*argv]
        script = 'import sys,time;print("Downloading 28% 28 MiB / 100 MiB 4 MiB/s",flush=True);print("Downloading 100%",flush=True)'
        original_popen = subprocess.Popen
        def popen_stub(argv, **kwargs):
            self.assertEqual(argv[2:4], ['--name', self.m.container_name(job_id)])
            return original_popen([sys.executable,'-u','-c',script], **kwargs)
        with mock.patch.object(self.m, 'load_provider_module', return_value=FakeModule), \
             mock.patch.object(self.m, 'stop_managed_container') as stop_container, \
             mock.patch.object(self.m.subprocess, 'Popen', side_effect=popen_stub):
            # Preserve underlying Popen without recursive mocking in stub.
            self.m.run_job(job_id, threading.Event())
        result = self.m.get_job(job_id)['job']
        self.assertEqual(result['state'],'completed',result.get('error'))
        self.assertEqual(result['progress'],100)
        self.assertEqual(result['exit_code'],0)
        self.assertIn('Downloading',result['log_tail'])

    def test_crash_recovery_stops_orphan(self):
        one = self.m.enqueue('epic', 'install', 'resumeGame')['job']['id']
        self.m._update(one, state='running',attempt=1,cancel_requested=0)
        with mock.patch.object(self.m, 'stop_managed_container') as stop:
            recovered = self.m.recover_interrupted()
        self.assertGreaterEqual(recovered, 1)
        stop.assert_any_call(one)
        self.assertEqual(self.m.get_job(one)['job']['state'],'queued')

if __name__=='__main__': unittest.main(verbosity=2)
