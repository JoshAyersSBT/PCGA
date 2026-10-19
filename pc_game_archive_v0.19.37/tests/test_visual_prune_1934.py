"""v0.19.36 video-content fingerprint scanner tests (read-only)."""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'components/pcga-extra-prune'
loader = importlib.machinery.SourceFileLoader('pcga_visual_prune', str(FILE))
spec = importlib.util.spec_from_loader(loader.name, loader)
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
loader.exec_module(engine)

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires FFmpeg utilities')
class VisualScannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = tempfile.TemporaryDirectory()
        tmp = Path(cls.fixtures.name)
        cls.a = tmp / 'video_A.mkv'
        cls.b = tmp / 'video_B.mp4'
        cls.unrelated = tmp / 'unrelated.mp4'
        cls.flat = tmp / 'flat.mp4'
        commands = [
            ['ffmpeg', '-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=s=640x360:r=12:d=16','-c:v','libx264','-threads','1','-preset','ultrafast','-crf','7','-pix_fmt','yuv420p','-an',str(cls.a)],
            ['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(cls.a),'-c:v','mpeg4','-q:v','3','-threads','1','-an',str(cls.b)],
            ['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i','smptebars=size=640x360:rate=12:duration=16','-c:v','mpeg4','-threads','1','-q:v','3','-an',str(cls.unrelated)],
            ['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i','color=c=black:s=640x360:r=12:d=16','-c:v','mpeg4','-threads','1','-q:v','3','-an',str(cls.flat)],
        ]
        for command in commands:
            cp = subprocess.run(command,capture_output=True,text=True,timeout=45)
            if cp.returncode:
                raise RuntimeError('ffmpeg fixture creation failed: '+cp.stderr[-500:])

    @classmethod
    def tearDownClass(cls):
        cls.fixtures.cleanup()

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)/'archive'
        self.state = Path(td.name)/'state'
        self.title = self.root/'media/library/movies/Example Film (2001)'
        self.title.mkdir(parents=True)
        self.main = self.title/'Example Film (2001).mkv'
        self.extra = self.title/'behind the scenes/Other Encode.mp4'
        self.extra.parent.mkdir(parents=True)
        shutil.copyfile(self.a,self.main)
        shutil.copyfile(self.b,self.extra)
        self.old(self.main,self.extra)

    def old(self,*paths):
        for path in paths: os.utime(path,(time.time()-7200,time.time()-7200))

    def scan(self):
        with patch.object(engine,'optical_jobs_active',return_value=False):
            return engine.scan_visual(self.root,self.state,min_age=60)

    def test_differently_encoded_footage_flagged_read_only(self):
        data = self.scan()
        self.assertEqual(data['state'],'ready')
        self.assertEqual(len(data['candidates']),1)
        c = data['candidates'][0]
        self.assertEqual(c['status'],'review_only')
        self.assertFalse(c['action_allowed'])
        self.assertTrue(c['reference_is_main'])
        self.assertEqual(c['evidence']['frames_matching'],8)
        self.assertTrue(self.main.exists() and self.extra.exists())
        self.assertEqual(engine.status(self.state)['visual_scan']['candidates'],data['candidates'])
        self.assertFalse((self.state/'scan.json').exists())

    def test_unrelated_video_not_flagged(self):
        shutil.copyfile(self.unrelated,self.extra)
        self.old(self.extra)
        self.assertEqual(self.scan()['candidates'],[])

    def test_black_frames_not_considered_a_match(self):
        shutil.copyfile(self.flat,self.main)
        shutil.copyfile(self.flat,self.extra)
        # Bytes differ only because of container, yet both are monochrome.
        self.old(self.main,self.extra)
        self.assertEqual(self.scan()['candidates'],[])

    def test_different_movie_folder_is_not_compared(self):
        other = self.root/'media/library/movies/Unrelated Movie (2008)'/'behind the scenes'
        other.mkdir(parents=True)
        dest = other/'Other Encode.mp4'
        self.extra.rename(dest)
        self.old(dest)
        self.assertEqual(self.scan()['candidates'],[])

    def test_exact_bytes_covered_only_by_exact_scanner(self):
        self.extra.unlink()
        shutil.copyfile(self.main,self.extra)
        self.old(self.extra)
        self.assertEqual(self.scan()['candidates'],[])

    def test_dangerous_path_symlinks_never_scanned(self):
        self.extra.unlink()
        self.extra.symlink_to(self.main)
        self.assertEqual(self.scan()['candidates'],[])

    def test_in_progress_optical_rips_block_scan(self):
        with patch.object(engine,'optical_jobs_active',return_value=True):
            with self.assertRaisesRegex(ValueError,'optical rip active'):
                engine.scan_visual(self.root,self.state,60)

    def test_visual_only_report_cannot_quarantine(self):
        c=self.scan()['candidates'][0]
        with self.assertRaisesRegex(ValueError,'successful scan first'):
            engine.quarantine(self.root,self.state,c['id'])
        self.assertTrue(self.extra.exists())

    def test_portal_and_control_read_only_contract(self):
        ctl=(ROOT/'components/pcga-control').read_text()
        html=(ROOT/'components/pcga-status-server.py').read_text()
        up=(ROOT/'upgrade_to_v0.19.37.sh').read_text()
        for marker in ('id="cc-extra-prune-visual-scan"','id="cc-extra-prune-visual-candidates"', 'Review only · no automatic action', 'extra-prune-scan-visual'):
            self.assertIn(marker,html if marker != 'extra-prune-scan-visual' else ctl)
        self.assertIn('name == "extra-prune-scan-visual"',ctl)
        self.assertIn('def scan_visual(', (ROOT/'components/pcga-extra-prune').read_text())
        self.assertIn('Visual fingerprint scanner missing',up)

if __name__ == '__main__': unittest.main()
