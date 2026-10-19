"""Safety and feature tests for v0.19.33 extras pruning."""
from __future__ import annotations
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'components/pcga-extra-prune'
loader = importlib.machinery.SourceFileLoader('pcga_extra_prune',str(FILE))
spec = importlib.util.spec_from_loader(loader.name, loader)
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
loader.exec_module(engine)

class ExtraPruneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'archive'
        self.state = Path(self.temp.name) / 'state'
        self.root.mkdir()
        self.title = self.root/'media/library/movies/Example Film (2001)'
        self.title.mkdir(parents=True)
        self.feature = self.title/'Example Film (2001).mkv'
        self.dup = self.title/'behind the scenes/Copy.mkv'
        self.dup.parent.mkdir()
        self.feature.write_bytes(b'1'*1100000)
        self.dup.write_bytes(b'1'*1100000)
        self.old(self.feature,self.dup)
    def old(self,*paths):
        for p in paths: os.utime(p,(time.time()-7200,time.time()-7200))
    def scan(self):
        return engine.scan(self.root,self.state,60)
    def test_main_feature_kept_and_duplicate_quarantined_and_restored(self):
        c = self.scan()['candidates']
        self.assertEqual(len(c),1)
        self.assertTrue(c[0]['keeper_is_main'])
        self.assertTrue(c[0]['duplicate'].endswith('Copy.mkv'))
        result=engine.quarantine(self.root,self.state,c[0]['id'])
        self.assertFalse(self.dup.exists())
        self.assertTrue(self.feature.exists())
        self.assertEqual(len(engine.quarantined_items(self.state)),1)
        self.assertTrue((self.root/result['item']['quarantine']).exists())
        engine.restore(self.root,self.state,c[0]['id'])
        self.assertEqual(self.dup.read_bytes(),self.feature.read_bytes())
    def test_different_content_same_size_never_pruned(self):
        self.dup.write_bytes(b'2'*1100000);self.old(self.dup)
        self.assertEqual(self.scan()['candidates'],[])
    def test_unrelated_movie_never_compared(self):
        self.dup.unlink()
        other=self.root/'media/library/movies/Other Film (2004)/behind the scenes/copy.mkv'
        other.parent.mkdir(parents=True);other.write_bytes(self.feature.read_bytes());self.old(other)
        self.assertEqual(self.scan()['candidates'],[])
    def test_duplicate_extra_within_same_title_keeps_one(self):
        self.feature.write_bytes(b'Z'*1100000);self.old(self.feature)
        extra=self.title/'interviews/Other.mp4';extra.parent.mkdir();extra.write_bytes(self.dup.read_bytes());self.old(extra)
        data=self.scan()['candidates']
        self.assertEqual(len(data),1)
        self.assertTrue(data[0]['duplicate'].endswith('Other.mp4') or data[0]['duplicate'].endswith('Copy.mkv'))
        self.assertIn('behind the scenes',data[0]['keep'])
    def test_modified_candidate_fails_revalidation(self):
        candidate=self.scan()['candidates'][0]
        self.dup.write_bytes(b'3'*1100000);self.old(self.dup)
        with self.assertRaisesRegex(ValueError,'changed'):
            engine.quarantine(self.root,self.state,candidate['id'])
        self.assertTrue(self.dup.exists())
    def test_symlinked_extra_not_scanned(self):
        self.dup.unlink();self.dup.symlink_to(self.feature)
        self.assertEqual(self.scan()['candidates'],[])
    def test_unrelated_non_extra_main_is_untouched(self):
        self.dup.unlink()
        other=self.title/'Other main.mkv';other.write_bytes(self.feature.read_bytes());self.old(other)
        self.assertEqual(self.scan()['candidates'],[])
    def test_old_scan_blocked(self):
        c=self.scan()['candidates'][0]
        state=json.loads((self.state/'scan.json').read_text());state['finished_at']=1
        engine.state_write(self.state/'scan.json',state)
        with self.assertRaisesRegex(ValueError,'old'):
            engine.quarantine(self.root,self.state,c['id'])
    def test_purge_grace_and_immutability(self):
        c=self.scan()['candidates'][0]
        q=engine.quarantine(self.root,self.state,c['id'])
        with self.assertRaisesRegex(ValueError,'seven-day'):
            engine.purge(self.root,self.state,c['id'])
        manifest=self.state/'quarantined'/f"{c['id']}.json"
        item=json.loads(manifest.read_text());item['created_at']=int(time.time())-engine.MIN_PURGE_AGE-1
        engine.state_write(manifest,item)
        result=engine.purge(self.root,self.state,c['id'])
        self.assertEqual(result['state'],'purged')
        self.assertFalse((self.root/q['item']['quarantine']).exists())
        self.assertTrue(self.feature.exists())
    def test_cli_confirmation_required(self):
        c=self.scan()['candidates'][0]
        cp=subprocess.run([sys.executable,str(FILE),'quarantine','--root',str(self.root),'--state-dir',str(self.state),'--id',c['id']],capture_output=True,text=True)
        self.assertNotEqual(cp.returncode,0)
        self.assertTrue(self.dup.exists())
    def test_changed_destination_restore_refused(self):
        c=self.scan()['candidates'][0]
        engine.quarantine(self.root,self.state,c['id'])
        self.dup.write_bytes(b'new file')
        with self.assertRaisesRegex(ValueError,'already exists'):
            engine.restore(self.root,self.state,c['id'])
        self.assertEqual(self.dup.read_bytes(),b'new file')
    def test_portal_integration_contract(self):
        html=(ROOT/'components/pcga-status-server.py').read_text()
        ctl=(ROOT/'components/pcga-control').read_text()
        up=(ROOT/'upgrade_to_v0.19.37.sh').read_text()
        for marker in ('id="cc-extra-prune-scan"','id="cc-extra-prune-candidates"','data-open-extras-prune',"extra-prune-quarantine", "extra-prune-restore", "extra-prune-purge"):
            self.assertIn(marker,html)
        self.assertIn('name == "extra-prune-scan"',ctl)
        self.assertIn('install -m 0755 "$COMP/pcga-extra-prune"',up)
if __name__ == '__main__': unittest.main()
