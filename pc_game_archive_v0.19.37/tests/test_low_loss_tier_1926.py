"""Per-title NAS master offload and restoration, without requiring a live NAS in CI."""
from __future__ import annotations
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

FILE = Path(__file__).resolve().parents[1]/'components/pcga-low-loss-tier'
loader = importlib.machinery.SourceFileLoader('pcga_master_tier_1926', str(FILE))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

REAL_MOUNT_DETAILS = mod.mount_details

def sha(data): return hashlib.sha256(data).hexdigest()

class TierTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)/'archive';self.root.mkdir()
        self.nas=Path(tmp.name)/'mount';self.nas.mkdir()
        self.base=self.nas/'PCGA/media/cold-archive/low-loss-masters'
        self.endpoint={'protocol':'smb','host':'nasbox','share':'movies','base_dir':'PCGA','mount_source':'//nasbox/movies'}
        self.rel='movies/Example (2000)/Example (2000).mkv'
        self.original=b'original'*100
        self.opt=b'compressed-playable'*20
        self.live,self.local,self.meta,self.record=mod.paths(self.root,self.rel)
        self.live.parent.mkdir(parents=True);self.local.parent.mkdir(parents=True)
        self.meta.parent.mkdir(parents=True)
        self.live.write_bytes(self.opt)
        self.local.write_bytes(self.original)
        self.meta.write_text(json.dumps({'schema':1,'source':self.rel,'state':'published',
                                         'source_bytes':len(self.original),'source_sha256':sha(self.original),
                                         'encoded_sha256':sha(self.opt)}))
        patch=mock.patch.object(mod,'NAS_MOUNT',self.nas);patch.start();self.addCleanup(patch.stop)
        patch=mock.patch.object(mod,'NAS_LOCK',Path(tmp.name)/'nas-storage.lock');patch.start();self.addCleanup(patch.stop)
        mounted=mock.patch.object(mod,'mount_details',return_value=(self.base,self.endpoint));mounted.start();self.addCleanup(mounted.stop)

    def remote(self):return self.base/self.rel

    def test_end_to_end(self):
        result=mod.offload(self.root,self.rel)
        self.assertEqual(result['state'],'offloaded')
        self.assertEqual(self.remote().read_bytes(),self.original)
        self.assertFalse(self.local.exists());self.assertEqual(self.live.read_bytes(),self.opt)
        listing=mod.inventory(self.root)
        self.assertEqual(listing['masters'][0]['tier_state'],'nas_only')
        result=mod.restore(self.root,self.rel)
        self.assertEqual(result['state'],'restored')
        self.assertEqual(self.local.read_bytes(),self.original)
        self.assertEqual(self.remote().read_bytes(),self.original)
        self.assertEqual(mod.inventory(self.root)['masters'][0]['tier_state'],'local_and_nas')

    def test_wrong_remote_does_not_remove_local(self):
        self.remote().parent.mkdir(parents=True)
        self.remote().write_bytes(b'other title')
        with self.assertRaisesRegex(ValueError,'different content'):
            mod.offload(self.root,self.rel)
        self.assertTrue(self.local.exists())
        self.assertEqual(self.remote().read_bytes(),b'other title')

    def test_bad_playable_blocks_transfer(self):
        self.live.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'playable copy differs'):
            mod.offload(self.root,self.rel)
        self.assertTrue(self.local.exists())

    def test_remote_corruption_prevents_restoration(self):
        mod.offload(self.root,self.rel)
        self.remote().write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError,'does not match original checksum'):
            mod.restore(self.root,self.rel)
        self.assertFalse(self.local.exists())
        self.assertEqual(self.live.read_bytes(),self.opt)

    def test_record_endpoint_change_blocked(self):
        mod.offload(self.root,self.rel)
        rec=json.loads(self.record.read_text());rec['endpoint']['host']='evil'
        self.record.write_text(json.dumps(rec))
        with self.assertRaisesRegex(ValueError,'NAS target changed'):
            mod.restore(self.root,self.rel)

    def test_mounted_requirement_and_mirror_mode(self):
        # Test the real mount preflight: no non-mounted directory fallback.
        config=self.root/'fake-config.json';config.write_text(json.dumps({'nas':{'enabled':True,'mode':'mirror',
                               'base_dir':'PCGA','host':'nasbox','share':'movies','protocol':'smb'}}))
        with mock.patch.object(mod,'CONFIG',config),mock.patch.object(mod,'mount_details',REAL_MOUNT_DETAILS):
            with mock.patch('subprocess.run',return_value=mock.Mock(returncode=1)):
                with self.assertRaisesRegex(ValueError,'not mounted'):
                    mod.mount_details()
        config.write_text(json.dumps({'nas':{'enabled':True,'mode':'offload'}}))
        with mock.patch.object(mod,'CONFIG',config),mock.patch.object(mod,'mount_details',REAL_MOUNT_DETAILS):
            with self.assertRaisesRegex(ValueError,'Mirror mode'):
                mod.mount_details()

    def test_copy_failure_keeps_local(self):
        with mock.patch.object(mod,'copy_verified',side_effect=OSError('disconnected')):
            with self.assertRaisesRegex(OSError,'disconnected'):
                mod.offload(self.root,self.rel)
        self.assertTrue(self.local.exists())
        self.assertFalse(self.record.exists())

    def test_mount_disconnect_before_unlink_keeps_original(self):
        # Simulate a NAS disconnect after the remote data was copied.
        with mock.patch.object(mod,'mount_details',side_effect=[(self.base,self.endpoint),
                             ValueError('NAS is not mounted')]):
            with self.assertRaisesRegex(ValueError,'not mounted'):
                mod.offload(self.root,self.rel)
        self.assertTrue(self.local.exists())
        self.assertEqual(self.live.read_bytes(),self.opt)

    def test_retry_after_incomplete_record(self):
        mod.offload(self.root,self.rel)
        rec=json.loads(self.record.read_text());rec['state']='verified_remote'
        self.record.write_text(json.dumps(rec))
        result=mod.offload(self.root,self.rel)
        self.assertEqual(result['state'],'offloaded')
        self.assertEqual(mod.read_json(self.record)['state'],'offloaded')

    def test_invalid_path_and_symlinks(self):
        for name in ('../foo.mkv','music/a.mkv','/etc/passwd','movies/../../oops.mkv',
                     'movies/foo.mp4','movies/a\\b.mkv'):
            with self.subTest(name=name),self.assertRaises(ValueError):mod.relative(name)
        self.local.unlink();outside=self.root/'outside';outside.write_bytes(self.original)
        self.local.symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'symlink'):
            mod.offload(self.root,self.rel)
        self.assertEqual(outside.read_bytes(),self.original)

if __name__=='__main__':unittest.main()
