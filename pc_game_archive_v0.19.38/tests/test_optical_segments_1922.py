"""v0.19.22 optical segments: explicit ordering, non-destructive assembly and review."""
import importlib.machinery
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / 'components'
loader = importlib.machinery.SourceFileLoader('pcga_segments_review', str(BASE/'pcga-manual-review'))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
loader.exec_module(mod)


class SegmentedMovieTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=self.root/'media'/'metadata-pending'/'dvd-two-part-feature'
        self.source.mkdir(parents=True)

    @staticmethod
    def make_video(path, color, codec='mpeg4'):
        subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-f','lavfi','-i',f'color=c={color}:s=96x64:r=24',
                        '-t','1.5','-c:v',codec,'-q:v','6','-an',str(path)],check=True,timeout=35)

    def test_explicit_order_preserves_sources_and_requires_review(self):
        self.make_video(self.source/'part02.mkv','blue')
        self.make_video(self.source/'part01.mkv','red')
        source_id=mod.item_id(self.root,self.source)
        job='c'*32
        mod._atomic_job_write(self.root,job,{'status':'queued','job':job,'item':source_id,'tracks':['part01.mkv','part02.mkv']})
        result=mod.assemble_segment_job(self.root,job)
        self.assertEqual(result['status'],'complete')
        out=Path(result['result_path'])
        self.assertTrue((out/'assembled.mkv').exists())
        self.assertTrue((self.source/'part01.mkv').exists())
        self.assertTrue((self.source/'part02.mkv').exists())
        meta=json.loads((out/'.pcga-segment-assembly.json').read_text())
        self.assertEqual(meta['segment_keys'],['part01.mkv','part02.mkv'])
        self.assertTrue(meta['review_required'])
        self.assertEqual(json.loads((out/'.pcga-classification.json').read_text())['action'],'review')
        self.assertAlmostEqual(result['runtime_seconds'],3.0,delta=.5)

    def test_rejects_duplicate_and_escaped_inputs(self):
        self.make_video(self.source/'part01.mkv','red')
        self.make_video(self.source/'part02.mkv','blue')
        sid=mod.item_id(self.root,self.source)
        for bad in [['part01.mkv','part01.mkv'],['../outside.mkv','part02.mkv'],['part01.mkv','nope.mkv']]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                mod._segment_sources(self.root,sid,bad)

    def test_rejects_incompatible_video_and_does_not_write_candidate(self):
        self.make_video(self.source/'part01.mkv','red')
        self.make_video(self.source/'part02.mkv','blue',codec='ffv1')
        job='d'*32
        mod._atomic_job_write(self.root,job,{'status':'queued','job':job,
                     'item':mod.item_id(self.root,self.source), 'tracks':['part01.mkv','part02.mkv']})
        with self.assertRaisesRegex(ValueError,'incompatible stream formats'):
            mod.assemble_segment_job(self.root,job)
        self.assertEqual(json.loads(mod._segment_job_file(self.root,job).read_text())['status'],'failed')
        self.assertTrue((self.source/'part01.mkv').exists())
        self.assertTrue((self.source/'part02.mkv').exists())
        self.assertEqual([x for x in (self.root/'media'/'metadata-pending').glob('*assembled*')],[])

    def test_review_listing_ignores_hidden_workspaces(self):
        hidden=self.root/'media'/'metadata-pending'/'.pcga-segment-build-abcd'
        hidden.mkdir(parents=True)
        self.make_video(hidden/'partial.mkv','yellow')
        self.make_video(self.source/'part01.mkv','red')
        self.assertFalse(any('.pcga-segment-build' in str(i.path) for i in mod.scan_items(self.root)))

if __name__=='__main__': unittest.main()
