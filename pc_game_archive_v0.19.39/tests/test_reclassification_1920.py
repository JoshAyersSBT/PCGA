"""Published optical corrections must be actionable, isolated, and non-destructive."""
import importlib.machinery
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

COMP=Path(__file__).resolve().parents[1]/'components'

def load(name):
    loader=importlib.machinery.SourceFileLoader('reclass1920',str(COMP/name))
    spec=importlib.util.spec_from_loader('reclass1920',loader)
    m=importlib.util.module_from_spec(spec);sys.modules['reclass1920']=m;loader.exec_module(m)
    return m

class OpticalTitleCorrections(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name)
        self.r=load('pcga-manual-review')
        self.movie=self.root/'media/library/movies/Movie A (2001)'
        self.movie.mkdir(parents=True)
        (self.movie/'Movie A (2001).mkv').write_bytes(b'actual movie A')
        (self.movie/'extras').mkdir()
        (self.movie/'extras/title01.mkv').write_bytes(b'actual movie B')
        self.id=self.r.library_optical_id(self.root,self.movie)
        self.refresh=patch.object(self.r,'refresh_jellyfin');self.refresh.start();self.addCleanup(self.refresh.stop)

    def test_separate_two_mixed_movies(self):
        result=self.r.split_library_optical_title(self.root,self.id,'extras/title01.mkv','Movie B','2004')
        other=self.root/'media/library/movies/Movie B (2004)'
        self.assertTrue(result['ok'])
        self.assertEqual((other/'Movie B (2004).mkv').read_bytes(),b'actual movie B')
        self.assertEqual((self.movie/'Movie A (2001).mkv').read_bytes(),b'actual movie A')
        self.assertFalse((self.movie/'extras/title01.mkv').exists())
        old=self.r.library_optical_item_payload(self.root,self.movie)
        self.assertEqual(len(old['titles']),1)
        self.assertEqual(old['titles'][0]['role'],'main-feature')
        self.assertTrue(json.loads((self.movie/'.pcga-manual-review.json').read_text())['optical_reconciliation_blocked'])
        self.assertTrue(json.loads((other/'.pcga-manual-review.json').read_text())['optical_reconciliation_blocked'])

    def test_refuse_conflicting_destination(self):
        occupied=self.root/'media/library/movies/Movie B (2004)';occupied.mkdir()
        (occupied/'Movie B (2004).mkv').write_bytes(b'untouched')
        with self.assertRaisesRegex(FileExistsError,'Destination already exists'):
            self.r.split_library_optical_title(self.root,self.id,'extras/title01.mkv','Movie B','2004')
        self.assertEqual((occupied/'Movie B (2004).mkv').read_bytes(),b'untouched')
        self.assertTrue((self.movie/'extras/title01.mkv').exists())

    def test_refuse_separating_sole_main(self):
        with self.assertRaisesRegex(ValueError,'First assign and save the correct main'):
            self.r.split_library_optical_title(self.root,self.id,'Movie A (2001).mkv','Other','')
        self.assertTrue((self.movie/'Movie A (2001).mkv').exists())

    def test_refuse_traversal_and_invalid_role(self):
        with self.assertRaisesRegex(ValueError,'Selected title is no longer'):
            self.r.split_library_optical_title(self.root,self.id,'../../foo','Other','')
        with self.assertRaises(ValueError):
            self.r.requested_optical_role('garbage')

    def test_reclassify_then_separate_wrong_main(self):
        # A mistaken prior main can be changed to extras and the real feature promoted.
        # First designate the new main and then split the incorrect bonus/movie.
        self.r.reclassify_library_optical(self.root,self.id,{
            'Movie A (2001).mkv':'extras', 'extras/title01.mkv':'main-feature'
        })
        self.assertEqual((self.movie/'Movie A (2001).mkv').read_bytes(),b'actual movie B')
        # Since the other file now sits in extras, separating it must be possible.
        rows=self.r.library_optical_item_payload(self.root,self.movie)['titles']
        extra=next(row for row in rows if row['role']=='extras')
        # Reusing the existing folder is intentionally forbidden; source movie must be
        # relabelled separately before moving the second title to its final name.
        with self.assertRaises(FileExistsError):
            self.r.split_library_optical_title(self.root,self.id,extra['key'],'Movie A','2001')

    def test_correct_movie_identity_preserves_extras_and_updates_manifest(self):
        result=self.r.rename_library_optical_movie(self.root,self.id,'Correct Feature','2011')
        renamed=self.root/'media/library/movies/Correct Feature (2011)'
        self.assertFalse(self.movie.exists())
        self.assertTrue(result['ok'])
        self.assertEqual((renamed/'Correct Feature (2011).mkv').read_bytes(),b'actual movie A')
        self.assertEqual((renamed/'extras/title01.mkv').read_bytes(),b'actual movie B')
        rows=self.r.library_optical_item_payload(self.root,renamed)['titles']
        self.assertEqual(len(rows),2)
        self.assertEqual(len([x for x in rows if x['role']=='main-feature']),1)
        self.assertTrue(json.loads((renamed/'.pcga-manual-review.json').read_text())['optical_reconciliation_blocked'])

    def test_correct_movie_identity_refuses_merge(self):
        occupied=self.root/'media/library/movies/Correct Feature (2011)'
        occupied.mkdir()
        with self.assertRaises(FileExistsError):
            self.r.rename_library_optical_movie(self.root,self.id,'Correct Feature','2011')
        self.assertTrue(self.movie.exists())

    def test_portal_is_wired(self):
        portal=(COMP/'pcga-status-server.py').read_text()
        self.assertIn('"split-optical-title"',portal)
        self.assertIn('"rename-optical-movie"',portal)
        self.assertIn('data-review-rename',portal)
        self.assertIn('data-review-split',portal)
        self.assertIn('reviewLibrarySplit(',portal)
        self.assertIn('track=${encodeURIComponent(r.key)}',portal)
        upgraders=sorted(COMP.parent.glob('upgrade_to_v*.sh'))
        self.assertEqual(len(upgraders),1)
        upgrader=upgraders[0].read_text()
        self.assertIn('Skipping automatic published-title reconciliation',upgrader)

if __name__=='__main__': unittest.main()
