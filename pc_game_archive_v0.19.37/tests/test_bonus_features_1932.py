"""v0.19.32: Jellyfin-owned extras are accessible through calm title-details playback."""
from pathlib import Path
from unittest.mock import patch
import importlib.util, json, types, unittest
from urllib.parse import parse_qs, urlsplit
ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT/'components/pcga-status-server.py'
SOURCE = SERVER.read_text()

def load():
    module = types.ModuleType('pcga_bonus_1932')
    module.__file__ = str(SERVER)
    exec(compile(SOURCE, str(SERVER), 'exec'), module.__dict__)
    return module

class BonusFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m=load()

    def test_making_of_and_local_trailer_playable_and_deduplicated(self):
        calls=[]
        def request(path,timeout=9.0):
            calls.append(path)
            if path.startswith('/Items/movie01/SpecialFeatures'):
                data=[
                    {'Id':'behind1','Name':'Making of the Movie','Type':'Video','ExtraType':'BehindTheScenes','RunTimeTicks':13200000000},
                    {'Id':'trailer1','Name':'Trailer','Type':'Trailer','ExtraType':'Trailer'},
                    {'Id':'movie01','Name':'Bad same id','Type':'Video'},
                    {'Id':'invalid/path','Name':'Bad ID','Type':'Video'},
                    {'Id':'sound','Name':'Soundtrack','Type':'Audio'},
                ]
            else:
                data=[{'Id':'trailer1','Name':'Trailer','Type':'Trailer'}, {'Id':'trailer2','Name':'Extended trailer','Type':'Trailer'}]
            return 200,{},json.dumps(data).encode()
        with patch.object(self.m,'jellyfin_playback_user',return_value=('viewer01','Viewer')),patch.object(self.m,'jellyfin_request',side_effect=request):
            d=self.m.jellyfin_title_extras('movie01')
        self.assertTrue(d['available']);self.assertFalse(d['partial']);self.assertEqual(d['count'],3)
        self.assertEqual(set(x['id'] for x in d['items']),{'behind1','trailer1','trailer2'})
        self.assertEqual(d['items'][0]['category'],'Behind the scenes')
        self.assertEqual(d['items'][0]['runtime_seconds'],1320)
        self.assertEqual(d['items'][1]['category'],'Trailers')
        self.assertEqual(len(calls),2)
        self.assertEqual(parse_qs(urlsplit(calls[0]).query)['userId'],['viewer01'])

    def test_unsupported_trailer_endpoint_does_not_hide_special_features(self):
        def request(path,timeout=9.0):
            if path.endswith('/LocalTrailers'):return 404,{},b''
            return 200,{},b'[{"Id":"making","Name":"Behind-the-scenes","Type":"Video"}]'
        with patch.object(self.m,'jellyfin_playback_user',return_value=('u','U')),patch.object(self.m,'jellyfin_request',side_effect=request):
            d=self.m.jellyfin_title_extras('film')
        self.assertTrue(d['available']);self.assertTrue(d['partial']);self.assertEqual(d['count'],1)

    def test_both_apis_unavailable_exposes_failure_not_empty_library(self):
        with patch.object(self.m,'jellyfin_playback_user',return_value=('u','U')),patch.object(self.m,'jellyfin_request',return_value=(503,{},b'fail')):
            d=self.m.jellyfin_title_extras('film')
        self.assertFalse(d['available']);self.assertEqual(d['count'],0)

    def test_no_extras_stays_empty_and_does_not_scan_by_name(self):
        calls=[]
        def request(path,timeout=9.0):
            calls.append(path)
            return 200,{},b'[]'
        with patch.object(self.m,'jellyfin_playback_user',return_value=('u','U')),patch.object(self.m,'jellyfin_request',side_effect=request):
            d=self.m.jellyfin_title_extras('film')
        self.assertTrue(d['available']);self.assertEqual(d['count'],0)
        self.assertTrue(all('film' in path for path in calls))
        self.assertNotIn('SearchTerm', ''.join(calls))

    def test_fails_closed_on_invalid_ids(self):
        for bad in ('../system','', 'id?test=1'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.m.jellyfin_title_extras(bad)

    def test_portal_uses_existing_video_player_without_autoplay(self):
        for marker in ('/api/jellyfin/title-extras','function libraryExtrasMarkup(',
                       'function loadJellyfinExtras(', 'library-extras-list',
                       'data-library-extra-index','videoPendingNext=null;playVideoItem(extra,null)',
                       'libraryExtras=state.extras||[]','libraryExtras.slice()',
                       'No automatic previews or playback','aria-label="Play bonus feature'):
            with self.subTest(marker=marker):self.assertIn(marker,SOURCE)
        self.assertNotIn('autoplay-extra',SOURCE)
        self.assertIn('VERSION="0.19.37"',(ROOT/'upgrade_to_v0.19.37.sh').read_text())

if __name__=='__main__':unittest.main()
