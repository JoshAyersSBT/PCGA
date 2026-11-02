"""v0.19.23: no guessed optical ownership, authored-title inventory and reviews."""
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[1]/'components'

def load(name):
    loader=importlib.machinery.SourceFileLoader('pcga1923_'+name,str(BASE/name))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod
    loader.exec_module(mod)
    return mod

class OpticalStructureTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.state=self.root/'optical-jobs'
        self.discs=self.root/'discs'
        self.m=load('pcga-disc-structure')
        self.m.STATE=self.state
        self.m.DISCS=self.discs
        self.fingerprint='f'*64
        self.media={'fingerprint':self.fingerprint,'title_probe_status':'ok','title':'Movie A',
            'kind':'movie','metadata_status':'provisional','layout':'single-title',
            'title_table':[{'index':0,'duration_seconds':7200,'chapters':16,'source_file':'00001.mpls'},
                           {'index':1,'duration_seconds':1200,'chapters':3,'source_file':'00002.mpls'}]}
        self.discs.mkdir(parents=True)
        self.m.atomic_json(self.discs/(self.fingerprint+'.json'),self.media)
        self.stage=self.root/'media/arm/work/completed/movies'
        self.stage.mkdir(parents=True)

    def start(self,kind='dvd-video'):
        return self.m.begin(self.root,'/dev/sr0',self.fingerprint,kind,scan_dvd=False)

    def test_dvd_ifo_multiple_cells_are_one_authored_title(self):
        xml='''<?xml version="1.0"?><lsdvd><device>/dev/sr0</device>
        <track><ix>1</ix><length>7271.22</length><pgc>2</pgc>
        <chapter><ix>1</ix><length>500</length></chapter>
        <chapter><ix>2</ix><length>600</length></chapter>
        <cell><ix>1</ix><length>400</length></cell>
        <cell><ix>2</ix><length>700</length></cell></track></lsdvd>'''
        tracks=self.m.dvd_navigation(xml)
        self.assertEqual(len(tracks),1)
        self.assertEqual(len(tracks[0]['cells']),2)
        self.assertEqual(len(tracks[0]['chapters']),2)
        self.assertEqual(tracks[0]['pgc'],'2')
        self.assertEqual(len(self.m.title_inventory(self.media)),2)

    def test_new_candidate_claims_exact_disc_and_preserves_bonus(self):
        old=self.stage/'VampireHunterD-old';old.mkdir()
        (old/'old.mkv').write_bytes(b'old')
        start=self.start()
        new=self.stage/'VampireHunterD-new';new.mkdir()
        (new/'main_t00.mkv').write_bytes(b'feature')
        (new/'making_of_t01.mkv').write_bytes(b'bonus')
        done=self.m.finish(self.root,start['job_id'],0)
        self.assertEqual(done['claimed_artifacts'],[str(new)])
        self.assertFalse((old/'.pcga-media.json').exists())
        attached=json.loads((new/'.pcga-media.json').read_text())
        self.assertEqual(attached['fingerprint'],self.fingerprint)
        self.assertEqual(len(attached['pcga_disc_structure']['logical_titles']),2)
        self.assertTrue(attached['pcga_disc_structure']['requires_review'])
        self.assertTrue((new/'making_of_t01.mkv').is_file())
        self.assertEqual(self.m.finish(self.root,start['job_id'],0),done)

    def test_identical_names_from_two_discs_not_mixed(self):
        start=self.start()
        source=self.stage/'Common Name';source.mkdir()
        (source/'feature.mkv').write_bytes(b'first movie')
        self.m.finish(self.root,start['job_id'],0)
        other='a'*64
        self.m.atomic_json(self.discs/(other+'.json'),dict(self.media,fingerprint=other,title='Another Film'))
        next_job=self.m.begin(self.root,'/dev/sr0',other,'dvd-video',scan_dvd=False)
        (source/'another.mkv').write_bytes(b'different film')
        result=self.m.finish(self.root,next_job['job_id'],0)
        self.assertEqual(result['claimed_artifacts'],[])
        self.assertEqual(json.loads((source/'.pcga-media.json').read_text())['fingerprint'],self.fingerprint)

    def test_failed_rip_does_not_bind(self):
        job=self.start()
        path=self.stage/'Incomplete';path.mkdir()
        (path/'somevideo.mkv').write_bytes(b'incomplete')
        result=self.m.finish(self.root,job['job_id'],2)
        self.assertEqual(result['unclaimed_artifacts'],[str(path)])
        self.assertFalse((path/'.pcga-media.json').exists())

    def test_only_strong_source_metadata_may_claim(self):
        job=self.start()
        path=self.stage/'LooksRight';path.mkdir()
        (path/'title.mkv').write_bytes(b'whatever')
        self.m.atomic_json(self.discs/(self.fingerprint+'.json'),dict(self.media,fingerprint='b'*64))
        result=self.m.finish(self.root,job['job_id'],0)
        self.assertEqual(result['claimed_artifacts'],[])

    def test_bluray_playlist_is_source_not_assumed_segment(self):
        job=self.start('bluray-video')
        self.assertEqual(job['dvd_navigation']['status'],'not-dvd')
        self.assertEqual(job['logical_titles'][0]['bluray_playlist'],'00001.mpls')
        self.assertEqual(job['logical_titles'][0]['chapter_count'],16)

    def test_invalid_job_paths_and_discs_are_rejected(self):
        with self.assertRaises(ValueError):self.m.begin(self.root,'/dev/sr0','no-fingerprint','dvd-video')
        with self.assertRaises(ValueError):self.m.finish(self.root,'../test',0)
        with self.assertRaises(ValueError):self.m.dvd_navigation('<random/>')

    def test_sorter_rip_lock_prevents_race(self):
        sorter=(BASE/'pcga-media-sort').read_text()
        rip=(BASE/'pcga-arm-rip').read_text()
        self.assertIn('PCGA_ARM_WRITER_OWNED',sorter)
        self.assertIn('flock -n 8',sorter)
        self.assertIn('pcga-disc-structure begin',rip)
        self.assertIn('pcga-disc-structure finish',rip)
        self.assertIn('PCGA_ARM_WRITER_OWNED=1 PCGA_SORT_SETTLE_MINUTES=0',rip)
        self.assertIn('structured_optical', (BASE/'pcga-classify').read_text())


class ContentFingerprintTests(unittest.TestCase):
    def test_same_sized_discs_with_different_content_cannot_share_strong_identity(self):
        m=load('pcga-optical-identify')
        with tempfile.TemporaryDirectory() as tmp:
            disc=Path(tmp)/'dvd-image'
            with disc.open('wb') as out:
                out.truncate(8*1024*1024)
            first=m.content_fingerprint(str(disc),disc.stat().st_size)
            with disc.open('r+b') as out:
                out.seek(1024*1024)
                out.write(b'Unique disc B')
            second=m.content_fingerprint(str(disc),disc.stat().st_size)
            self.assertIsNotNone(first)
            self.assertNotEqual(first,second)
            self.assertIsNone(m.content_fingerprint(str(disc),42))

if __name__=='__main__':unittest.main()
