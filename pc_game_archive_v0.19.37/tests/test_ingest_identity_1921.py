"""v0.19.21: fail closed on concurrent rip identity and offer safe correction."""
import importlib.machinery
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

COMP=Path(__file__).resolve().parents[1]/'components'

def module(name):
    loader=importlib.machinery.SourceFileLoader('test1921'+name,str(COMP/name))
    spec=importlib.util.spec_from_loader('test1921'+name,loader)
    m=importlib.util.module_from_spec(spec)
    sys.modules['test1921'+name]=m
    loader.exec_module(m)
    return m

class NewSafetyChecks(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name)

    def test_same_label_different_discs_never_guessed(self):
        m=module('pcga-media-intake')
        m.STATE=self.root/'state';m.DISCS=m.STATE/'discs';m.ITEMS=m.STATE/'items';m.COLLECTIONS=m.STATE/'collections'
        for key in ['disk_A','disk_B']:
            m.save(m.DISCS/(key+'.json'),{'fingerprint':key,'rip_status':'complete','title':'Vampire Hunter D: Bloodlust','volume_label':'Vampire Hunter D: Bloodlust'})
        out=self.root/'20261010-000000-Vampire Hunter D Bloodlust';out.mkdir()
        with self.assertRaises(SystemExit):m.attach_artifact(out)
        self.assertFalse((out/'.pcga-media.json').exists())
        exact=m.attach_artifact(out,'disk_B')
        self.assertEqual(exact['fingerprint'],'disk_B')
        self.assertEqual(m.load(out/'.pcga-media.json')['fingerprint'],'disk_B')

    def test_making_of_can_be_removed_from_movie_library_without_deletion(self):
        m=module('pcga-manual-review')
        folder=self.root/'media/library/movies/Vampire Hunter D Bloodlust (2001)'
        folder.mkdir(parents=True)
        (folder/'Vampire Hunter D Bloodlust (2001).mkv').write_bytes(b'bonus only')
        (folder/'.pcga-manual-review.json').write_text(json.dumps({'optical_titles':[{'destination':str(folder/'Vampire Hunter D Bloodlust (2001).mkv'),'role':'main-feature'}]}))
        self.assertEqual(len(m.scan_library_optical_items(self.root)),1)
        with patch.object(m,'refresh_jellyfin'):
            out=m.set_aside_incorrect_movie(self.root,m.library_optical_id(self.root,folder))
        destination=Path(out['destination'])
        self.assertFalse(folder.exists())
        self.assertEqual((destination/'Vampire Hunter D Bloodlust (2001).mkv').read_bytes(),b'bonus only')
        self.assertTrue(json.loads((destination/'.pcga-manual-review.json').read_text())['optical_reconciliation_blocked'])
        self.assertEqual((destination/'.pcga-classification.json').exists(),True)

    def test_serial_writer_and_blocking_sort_gate(self):
        script=(COMP/'pcga-arm-rip').read_text()
        self.assertIn('flock -x 8',script)
        self.assertIn('pcga-arm-shared-output.lock',script)
        self.assertIn('PCGA_SORT_SETTLE_MINUTES=0',script)
        self.assertIn('shared completed staging still has unprocessed files',script)

    def test_review_endpoints_and_interface(self):
        portal=(COMP/'pcga-status-server.py').read_text()
        review=(COMP/'pcga-manual-review').read_text()
        self.assertIn('set-aside-optical-movie',portal)
        self.assertIn('data-review-set-aside',portal)
        self.assertIn('data-open-movie-corrections',portal)
        self.assertIn('reviewLibrarySetAside()',portal)
        self.assertIn('/api/set-aside-optical-movie',review)

if __name__=='__main__':unittest.main()
