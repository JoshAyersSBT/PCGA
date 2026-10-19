"""Regression tests: two-drive identity and movie feature preservation."""
from __future__ import annotations
import importlib.machinery
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

COMP = Path(__file__).resolve().parents[1] / 'components'

def mod(name: str):
    loader=importlib.machinery.SourceFileLoader(name,str(COMP/name))
    spec=importlib.util.spec_from_loader(name,loader)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

class ConcurrentMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.intake=mod('pcga-media-intake')
        self.intake.STATE=self.root/'state'; self.intake.DISCS=self.intake.STATE/'discs'; self.intake.ITEMS=self.intake.STATE/'items'
        self.intake.COLLECTIONS=self.intake.STATE/'collections'
        self.intake.DISCS.mkdir(parents=True)
        now=datetime.now(timezone.utc).isoformat()
        for fp,title,drive in [('aaa111','First Movie','sr0'),('bbb222','Second Movie','sr1')]:
            self.intake.save(self.intake.DISCS/f'{fp}.json',{
                'fingerprint':fp,'title':title,'volume_label':title,
                'rip_status':'complete','rip_drive':drive,'rip_completed_at':now,
                'metadata_status':'provisional',
            })

    def test_two_simultaneous_titles_never_cross_associate(self):
        a=self.root/'20261010-000000-First Movie';a.mkdir()
        b=self.root/'20261010-000000-Second Movie';b.mkdir()
        aa=self.intake.attach_artifact(a,'aaa111')
        bb=self.intake.attach_artifact(b,'bbb222')
        self.assertEqual(aa['fingerprint'],'aaa111')
        self.assertEqual(bb['fingerprint'],'bbb222')
        self.assertEqual(self.intake.load(a/'.pcga-media.json')['title'],'First Movie')
        self.assertEqual(self.intake.load(b/'.pcga-media.json')['title'],'Second Movie')

    def test_no_time_only_association_and_no_overwrite(self):
        unknown=self.root/'20261010-000000-Unknown';unknown.mkdir()
        with self.assertRaises(SystemExit):self.intake.attach_artifact(unknown)
        self.assertFalse((unknown/'.pcga-media.json').exists())
        a=self.root/'First Movie';a.mkdir()
        self.intake.attach_artifact(a,'aaa111')
        with self.assertRaises(SystemExit):self.intake.attach_artifact(a,'bbb222')
        self.assertEqual(self.intake.load(a/'.pcga-media.json')['fingerprint'],'aaa111')

    def test_identical_disc_labels_are_ambiguous(self):
        other=self.intake.load(self.intake.DISCS/'bbb222.json')
        other['title']='First Movie';other['volume_label']='First Movie'
        self.intake.save(self.intake.DISCS/'bbb222.json',other)
        source=self.root/'First Movie';source.mkdir()
        with self.assertRaises(SystemExit):self.intake.attach_artifact(source)
        self.assertFalse((source/'.pcga-media.json').exists())

    def test_generic_title_not_matched(self):
        row=self.intake.load(self.intake.DISCS/'aaa111.json')
        row['title']='DVD VIDEO';row['volume_label']='DVD VIDEO'
        self.intake.save(self.intake.DISCS/'aaa111.json',row)
        source=self.root/'DVD VIDEO';source.mkdir()
        with self.assertRaises(SystemExit):self.intake.attach_artifact(source)

class MovieRoleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.review=mod('pcga-manual-review')
        self.classifier=mod('pcga-classify')
        self.source=self.root/'metadata-pending'/'First Movie'
        self.source.mkdir(parents=True)
        (self.source/'title00.mkv').write_bytes(b'0'*2048)
        (self.source/'title01.mkv').write_bytes(b'1'*1024)

    def test_optical_role_rows_available_without_metadata(self):
        class Stub:
            path=self.source
        rows=self.review.optical_review_title_rows(Stub())
        self.assertEqual(len(rows),2)
        self.assertEqual({row['key'] for row in rows},{'title00.mkv','title01.mkv'})
        self.assertFalse(any(row['role']=='main-feature' for row in rows))

    def test_no_implicit_largest_title_promotion(self):
        with self.assertRaisesRegex(ValueError,'Select exactly one main feature'):
            self.review.promote_optical_movie_multititle(self.source,self.root/'library'/'First Movie','First Movie',{}, {})
        self.assertTrue((self.source/'title00.mkv').exists())

    def test_explicit_main_feature_routes_extras(self):
        dest=self.root/'library'/'First Movie'
        out=self.review.promote_optical_movie_multititle(self.source,dest,'First Movie',{},
                             {'title01.mkv':'main-feature','title00.mkv':'featurettes'})
        self.assertTrue((dest/'First Movie.mkv').exists())
        self.assertEqual((dest/'First Movie.mkv').read_bytes(),b'1'*1024)
        self.assertTrue((dest/'featurettes'/'title00.mkv').exists())
        self.assertEqual(len(out),2)

    def test_legacy_movie_with_multiple_tracks_is_repairable(self):
        movie=self.root/'media'/'library'/'movies'/'Legacy Movie'
        movie.mkdir(parents=True)
        (movie/'Legacy Movie.mkv').write_bytes(b'extra')
        (movie/'title02.mkv').write_bytes(b'actual-film')
        results=self.review.scan_library_optical_items(self.root)
        self.assertEqual(len(results),1)
        self.assertTrue(results[0]['legacy_multi_video'])
        roles={x['key']:('main-feature' if x['file']=='title02.mkv' else 'extras') for x in results[0]['titles']}
        self.review.refresh_jellyfin=lambda:None
        result=self.review.reclassify_library_optical(self.root,results[0]['id'],roles)
        self.assertTrue(result['ok'])
        self.assertEqual((movie/'Legacy Movie.mkv').read_bytes(),b'actual-film')
        self.assertTrue(list((movie/'extras').glob('Legacy Movie.mkv')))

    def test_classification_dominant_multi_video_requires_review(self):
        (self.source/'title00.mkv').write_bytes(b'0'*(600*1024*1024))
        (self.source/'title01.mkv').write_bytes(b'1'*(80*1024*1024))
        (self.source/'.pcga-source-hint').write_text('movie\n')
        result=self.classifier.inspect_local(self.source)
        self.assertEqual(result.action,'review')
        self.assertEqual(result.subtype,'dominant-feature')

if __name__=='__main__':unittest.main()
