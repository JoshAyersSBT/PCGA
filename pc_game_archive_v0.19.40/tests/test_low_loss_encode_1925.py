"""Safety, quality-profile, preservation, and real FFmpeg conversion tests."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

FILE=Path(__file__).resolve().parents[1]/'components/pcga-low-loss-encode'
loader=importlib.machinery.SourceFileLoader('pcga_low_loss_1925',str(FILE))
spec=importlib.util.spec_from_loader(loader.name,loader)
mod=importlib.util.module_from_spec(spec)
loader.exec_module(mod)


class LowLossTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.rel='movies/Example (2000)/Example (2000).mkv'
        self.src=self.root/'media/library'/self.rel
        self.src.parent.mkdir(parents=True)
        self.patch=mock.patch.object(mod,'MIN_AGE',0);self.patch.start();self.addCleanup(self.patch.stop)

    def generate(self):
        # Deliberately simple highly compressible video for fast integration tests.
        args=['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=96x64:rate=12',
              '-f','lavfi','-i','sine=frequency=440:sample_rate=22050','-t','16','-threads','1',
              '-c:v','mpeg4','-q:v','1','-c:a','pcm_s16le',str(self.src)]
        subprocess.run(args,check=True,timeout=25)

    def test_input_validation(self):
        for value in ('../foo.mkv','/home/foo.mkv','movies/../../escape.mkv','music/a.mkv','tv/video.mp4','movies/a\\b.mkv'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):mod.relative_file(value)

    def test_hdr_and_multiple_video_block(self):
        v={'codec_type':'video','pix_fmt':'yuv420p10le','color_transfer':'smpte2084'}
        with self.assertRaisesRegex(ValueError,'HDR'):
            mod.eligibility({'streams':[v]})
        with self.assertRaisesRegex(ValueError,'exactly one'):
            mod.eligibility({'streams':[{'codec_type':'video'},{'codec_type':'video'}]})

    def test_real_encode_publish_and_rollback(self):
        if not mod.encoder_available('hevc'): self.skipTest('Host FFmpeg does not include libx265')
        self.generate()
        original_hash=mod.checksum(self.src)
        original_size=self.src.stat().st_size
        # Hard-coded codec input leaves DVD-sized audio copied, video recompressed.
        result=mod.encode(self.root,self.rel,'hevc','balanced',min_savings=0)
        self.assertEqual(result['state'],'encoded')
        self.assertEqual(mod.checksum(self.src),original_hash)
        src,staged,record,master=mod.locations(self.root,self.rel)
        self.assertTrue(staged.exists())
        self.assertTrue(record.exists())
        m=json.loads(record.read_text())
        self.assertEqual(m['source_sha256'],original_hash)
        self.assertTrue(m['audio_tracks'])
        self.assertEqual(m['source_bytes'],original_size)
        self.assertEqual(mod.probe(staged)['streams'][0]['codec_name'],'hevc')
        publish=mod.publish(self.root,self.rel)
        self.assertEqual(publish['state'],'published')
        self.assertEqual(mod.checksum(master),original_hash)
        self.assertEqual(mod.checksum(src),m['encoded_sha256'])
        with self.assertRaises(ValueError):mod.publish(self.root,self.rel)
        restored=mod.rollback(self.root,self.rel)
        self.assertEqual(restored['state'],'encoded')
        self.assertEqual(mod.checksum(src),original_hash)
        self.assertTrue(staged.exists())
        self.assertFalse(master.exists())

    def test_external_edit_blocks_publish_and_preserves_source(self):
        self.generate()
        before=mod.checksum(self.src)
        src,staged,record,master=mod.locations(self.root,self.rel)
        staged.parent.mkdir(parents=True,exist_ok=True)
        staged.write_bytes(b'optimized')
        mod.save_record(record,{'schema':1,'source':self.rel,'state':'encoded',
                              'source_bytes':src.stat().st_size,'source_mtime_ns':src.stat().st_mtime_ns,
                              'source_sha256':before,'encoded_sha256':mod.checksum(staged)})
        src.write_bytes(b'edited after conversion')
        with self.assertRaisesRegex(ValueError,'changed'):
            mod.publish(self.root,self.rel)
        self.assertFalse(master.exists())
        self.assertEqual(src.read_bytes(),b'edited after conversion')

    def test_tamper_blocks_publish(self):
        self.generate()
        src,staged,record,master=mod.locations(self.root,self.rel)
        staged.parent.mkdir(parents=True,exist_ok=True)
        staged.write_bytes(b'optimized')
        mod.save_record(record,{'schema':1,'source':self.rel,'state':'encoded',
                              'source_bytes':src.stat().st_size,'source_mtime_ns':src.stat().st_mtime_ns,
                              'source_sha256':mod.checksum(src),'encoded_sha256':'0'*64})
        with self.assertRaisesRegex(ValueError,'checksum mismatch'):
            mod.publish(self.root,self.rel)
        self.assertEqual(src.stat().st_size,mod.regular(src).st_size)
        self.assertFalse(master.exists())

    def test_failed_transcode_does_not_touch_original(self):
        self.src.write_bytes(b'not-a-video'*100000)
        before=self.src.read_bytes()
        with self.assertRaises(ValueError):mod.encode(self.root,self.rel,'hevc','balanced')
        self.assertEqual(self.src.read_bytes(),before)

    def test_existing_symlink_refused(self):
        original=self.root/'elsewhere.mkv';original.write_bytes(b'important')
        self.src.symlink_to(original)
        with self.assertRaisesRegex(ValueError,'symlink'):
            mod.library_source(self.root,self.rel)


if __name__=='__main__':unittest.main()
