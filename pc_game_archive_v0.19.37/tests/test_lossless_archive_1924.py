"""Cold-archive byte identity and fail-closed safety checks."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

FILE=Path(__file__).resolve().parents[1]/'components/pcga-lossless-archive'
loader=importlib.machinery.SourceFileLoader('pcga_lossless_1924',str(FILE))
spec=importlib.util.spec_from_loader(loader.name,loader)
mod=importlib.util.module_from_spec(spec)
loader.exec_module(mod)


class LosslessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'media/library/movies/Test (2001)').mkdir(parents=True)
        self.rel='movies/Test (2001)/Test (2001).mkv'
        self.src=self.root/'media/library'/self.rel

    def test_exact_archive_restore_and_offline(self):
        payload=b'Faux bluray block'*(1024*320)
        self.src.write_bytes(payload)
        with mock.patch.object(mod,'MIN_AGE',0):
            result=mod.archive(self.root,self.rel,offline=True)
        self.assertEqual(result['state'],'archived')
        self.assertFalse(self.src.exists())
        inv=mod.inventory(self.root)
        self.assertEqual(inv['offline_count'],1)
        self.assertEqual(inv['offline_archives'][0]['source'],self.rel)
        restored=mod.restore(self.root,self.rel)
        self.assertEqual(restored['state'],'restored')
        self.assertEqual(self.src.read_bytes(),payload)
        self.assertEqual(mod.inventory(self.root)['offline_count'],0)

    def test_incompressible_skipped_and_playable(self):
        self.src.write_bytes(os.urandom(2*1024*1024))
        with mock.patch.object(mod,'MIN_AGE',0):
            result=mod.archive(self.root,self.rel,offline=True,min_savings=2)
        self.assertEqual(result['state'],'skipped')
        self.assertTrue(self.src.is_file())
        self.assertFalse(mod.paths(self.root,Path(self.rel))[0].exists())

    def test_explicit_offline_required(self):
        self.src.write_bytes(b'abc'*10000)
        with self.assertRaisesRegex(ValueError,'explicit --offline'):
            mod.archive(self.root,self.rel)
        self.assertTrue(self.src.exists())

    def test_traversal_and_outside_library_rejected(self):
        for value in ('../etc/passwd','movies/../../etc/foo.mkv','tv/../../foo.mkv','/tmp/foo.mkv','music/track.mp3'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):mod.safe_rel(value)

    def test_symlink_source_refused(self):
        outside=self.root/'outside.mkv';outside.write_bytes(b'not your movie')
        self.src.symlink_to(outside)
        with mock.patch.object(mod,'MIN_AGE',0):
            with self.assertRaisesRegex(ValueError,'symlink'):
                mod.archive(self.root,self.rel,offline=True)
        self.assertEqual(outside.read_bytes(),b'not your movie')

    def test_archive_tamper_blocks_restore(self):
        self.src.write_bytes(b'X'*3000000)
        with mock.patch.object(mod,'MIN_AGE',0):mod.archive(self.root,self.rel,offline=True)
        packed,_=mod.paths(self.root,Path(self.rel))
        with packed.open('ab') as f:f.write(b'bad')
        with self.assertRaisesRegex(ValueError,'checksum mismatch'):
            mod.restore(self.root,self.rel)
        self.assertFalse(self.src.exists())

    def test_restore_refuses_overwrite(self):
        self.src.write_bytes(b'Z'*3000000)
        with mock.patch.object(mod,'MIN_AGE',0):mod.archive(self.root,self.rel,offline=True)
        self.src.write_bytes(b'new movie content')
        with self.assertRaisesRegex(ValueError,'refusing overwrite'):
            mod.restore(self.root,self.rel)
        self.assertEqual(self.src.read_bytes(),b'new movie content')

    def test_recent_file_guard(self):
        self.src.write_bytes(b'Z'*3000000)
        with mock.patch.object(mod,'MIN_AGE',600):
            with self.assertRaisesRegex(ValueError,'recently modified'):
                mod.archive(self.root,self.rel,offline=True)


if __name__=='__main__':unittest.main()
