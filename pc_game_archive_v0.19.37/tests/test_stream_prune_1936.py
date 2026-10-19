"""v0.19.36 Ghost in the Shell regression and preservation tests."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
PATH = BASE / 'components/pcga-stream-prune'
loader = importlib.machinery.SourceFileLoader('pcga_stream_prune_1936', str(PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

VIDEO = [('video_hash', 'h264', 'eng', '', False)]
AUDIO = [(f'audio{i}', 'ac3', 'eng', '', False) for i in range(7)]
SUBA = [(f'sub-a{i}', 'hdmv_pgs_subtitle', 'eng', '', False) for i in range(6)]
SUBB = [(f'sub-b{i}', 'hdmv_pgs_subtitle', 'jpn', '', False) for i in range(6)]
CHAPTERS = [(0.0, 100.0, '', ''), (100.0, 200.0, '', '')]


class StreamPrune1936(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'archive'
        self.state = Path(self.tmp.name) / 'state'
        self.title = self.root / 'media/library/movies/Ghost in the Shell (1995)'
        self.extra = self.title / 'extras'
        self.extra.mkdir(parents=True)
        self.main = self.title / 'Ghost in the Shell (1995).mkv'
        self.rich = self.extra / 'None.mkv'
        self.t00 = self.extra / 'Ghost in the Shell_t00.mkv'
        for f, data in [(self.main,b'a'),(self.rich,b'b'),(self.t00,b'c')]:
            f.write_bytes(data * 1_100_000)
            os.utime(f, (time.time()-3600, time.time()-3600))
        self.rich_inode = self.rich.stat().st_ino
        self.main_inode = self.main.stat().st_ino
        self.t00_inode = self.t00.stat().st_ino
        self.chapters_added = False
        self.other = False
        self.patches = [
            patch.object(mod.base, 'optical_jobs_active', return_value=False),
            patch.object(mod.shutil, 'which', side_effect=lambda name: '/usr/bin/'+name),
            patch.object(mod, 'probe', side_effect=self.fake_probe),
            patch.object(mod, 'execute', side_effect=self.fake_execute),
        ]
        for p in self.patches: p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def fake_probe(self, file):
        inode = Path(file).stat().st_ino
        is_rich = inode == self.rich_inode
        is_alt = inode == self.t00_inode
        return {'duration': 200.0,
                'tracks': {'video': VIDEO if not (self.other and is_alt) else [('wrong', 'h264', 'eng','',False)],
                           'audio': AUDIO,
                           'subtitle': sorted(SUBA+SUBB) if is_rich else SUBB if is_alt else SUBA},
                'chapters': CHAPTERS if (not is_rich or self.chapters_added) else []}

    def fake_execute(self, args, timeout=3600):
        if args[0] == 'mkvextract':
            Path(args[-1]).write_text('<Chapters>safe</Chapters>')
        elif args[0] == 'mkvpropedit':
            self.chapters_added = True
        return ''

    def candidates(self):
        return mod.scan(self.root, self.state, 'Ghost in the Shell', 60)['candidates']

    def test_ghost_subtitle_union_and_chapter_copy(self):
        results = self.candidates()
        self.assertEqual(len(results), 1)
        c = results[0]
        self.assertEqual(c['files_consolidated'],3)
        self.assertEqual(c['chapters'],'copy-from-main')
        self.assertEqual(c['subtitle_tracks'],12)
        self.assertEqual(c['audio_tracks'],7)
        self.assertTrue(c['keeper']['path'].endswith('extras/None.mkv'))
        self.assertGreater(c['estimated_reclaim'],2_000_000)

    def test_stage_and_restore_keep_all_data(self):
        c = self.candidates()[0]
        res = mod.stage(self.root,self.state,c['id'])
        self.assertEqual(res['state'],'staged')
        self.assertEqual(self.main.stat().st_ino,self.rich_inode)
        self.assertFalse(self.rich.exists())
        self.assertFalse(self.t00.exists())
        self.assertTrue(self.chapters_added)
        status = mod.status(self.state)
        self.assertEqual(len(status['staged']),1)
        mod.restore(self.root,self.state,c['id'])
        self.assertEqual(self.main.stat().st_ino,self.main_inode)
        self.assertEqual(self.rich.stat().st_ino,self.rich_inode)
        self.assertEqual(self.t00.stat().st_ino,self.t00_inode)

    def test_never_merge_different_video(self):
        self.other = True
        results = self.candidates()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['files_consolidated'],2)
        self.assertFalse(any(x['path'].endswith('_t00.mkv') for x in results[0]['members']))

    def test_reject_changed_file_after_scan(self):
        c = self.candidates()[0]
        self.rich.write_bytes(b'x'*1_100_000)
        with self.assertRaisesRegex(ValueError, 'changed'):
            mod.stage(self.root,self.state,c['id'])
        self.assertTrue(self.main.exists())

    def test_stage_requires_no_symlink_and_approval(self):
        self.rich.unlink()
        self.rich.symlink_to(self.main)
        self.assertEqual(self.candidates(), [])

    def test_purge_requires_seven_days(self):
        c=self.candidates()[0]
        mod.stage(self.root,self.state,c['id'])
        with self.assertRaisesRegex(ValueError,'Seven-day'):
            mod.purge(self.root,self.state,c['id'])
        self.assertTrue(self.main.is_file())

    def test_purge_removes_only_held_after_wait(self):
        c=self.candidates()[0]
        mod.stage(self.root,self.state,c['id'])
        with patch.object(mod,'PURGE_AGE',0):
            result=mod.purge(self.root,self.state,c['id'])
        self.assertEqual(result['state'],'purged')
        self.assertEqual(self.main.stat().st_ino,self.rich_inode)
        self.assertFalse((self.root/'recovery-hold/stream-prune'/c['id']/'original-0.mkv').exists())

    def test_purge_refuses_modified_keeper_streams(self):
        c=self.candidates()[0]
        mod.stage(self.root,self.state,c['id'])
        self.other = True  # unrelated t00 is held, but retained stream probe should remain stable
        with patch.object(mod, 'PURGE_AGE', 0), patch.object(mod, 'probe', return_value={'tracks': {'video': [('wrong', 'h264','','',False)],'audio': AUDIO,'subtitle': sorted(SUBA+SUBB)}, 'chapters': CHAPTERS}):
            with self.assertRaisesRegex(ValueError, 'Keeper streams or chapters changed'):
                mod.purge(self.root,self.state,c['id'])

    def test_filesystem_pressure_signals_and_upgrade_hook(self):
        control=(BASE/'components/pcga-control').read_text()
        portal=(BASE/'components/pcga-status-server.py').read_text()
        up=(BASE/'upgrade_to_v0.19.37.sh').read_text()
        self.assertIn('"storage_pressure"',control)
        self.assertIn('cc-stream-scan',portal)
        self.assertIn('stream-prune-stage',control)
        self.assertIn('install -m 0755 "$COMP/pcga-stream-prune"',up)


if __name__ == '__main__': unittest.main()
