"""v0.19.32 Jellyfin TV guide contract and intentional episode choices."""
import json
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'components/pcga-status-server.py'

def module():
    m=types.ModuleType('pcga_tv_1931')
    m.__file__=str(SRC)
    exec(compile(SRC.read_text(),str(SRC),'exec'),m.__dict__)
    return m

class TvJourneyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.m=module()

    def test_series_guide_native_seasons_and_progress(self):
        calls=[]
        def fake(path,timeout=12.0):
            calls.append(path)
            qs=parse_qs(urlsplit(path).query)
            if '/Seasons?' in path:
                data={'Items':[{'Id':'specials','Name':'Specials','IndexNumber':0},{'Id':'s2','Name':'Season 2','IndexNumber':2},{'Id':'s1','Name':'Season 1','IndexNumber':1}]}
            elif '/Episodes?' in path:
                self.assertEqual(qs['SeasonId'],['s1'])
                data={'Items':[
                    {'Id':'e2','Name':'Middle','SeriesId':'show1','IndexNumber':2,'ParentIndexNumber':1,'RunTimeTicks':6000000000,'UserData':{'PlaybackPositionTicks':3000000000}},
                    {'Id':'e1','Name':'Start','SeriesId':'show1','IndexNumber':1,'ParentIndexNumber':1,'RunTimeTicks':6000000000,'UserData':{'Played':True}},
                    {'Id':'missing','Name':'Unavailable','SeriesId':'show1','IsMissing':True},
                    {'Id':'notthis','SeriesId':'other','Name':'Foreign'}]}
            elif '/NextUp?' in path:
                data={'Items':[{'Id':'e2','Name':'Middle','SeriesId':'show1','IndexNumber':2,'ParentIndexNumber':1}]}
            else: raise AssertionError(path)
            return 200,{},json.dumps(data).encode()
        with patch.object(self.m,'jellyfin_playback_user',return_value=('user1','TV')),patch.object(self.m,'jellyfin_request',side_effect=fake):
            guide=self.m.jellyfin_series_guide('show1')
        self.assertEqual([x['id'] for x in guide['seasons']],['specials','s1','s2'])
        self.assertEqual(guide['season_id'],'s1')
        self.assertEqual([x['id'] for x in guide['episodes']],['e1','e2'])
        self.assertTrue(guide['episodes'][0]['played'])
        self.assertEqual(guide['episodes'][1]['played_percent'],50.0)
        self.assertEqual(guide['next_up']['id'],'e2')
        self.assertTrue(all('UserId=user1' in path for path in calls))

    def test_wrong_season_and_invalid_id_refused_before_episode_fetch(self):
        calls=[]
        def fake(path,timeout=12.0):
            calls.append(path)
            return 200,{},json.dumps({'Items':[{'Id':'s1','IndexNumber':1}]}).encode()
        with patch.object(self.m,'jellyfin_playback_user',return_value=('u','U')),patch.object(self.m,'jellyfin_request',side_effect=fake):
            with self.assertRaises(ValueError):self.m.jellyfin_series_guide('series','other-season')
        self.assertEqual(len(calls),1)
        for invalid in ('../../etc','', 'abc?x=123'):
            with self.assertRaises(ValueError): self.m.jellyfin_series_guide(invalid)

    def test_next_up_failure_is_not_guessed(self):
        def fake(path,timeout=12.0):
            if '/NextUp?' in path: return 503,{},b'{}'
            if '/Seasons?' in path: return 200,{},b'{"Items":[{"Id":"s1","IndexNumber":1}]}'
            return 200,{},b'{"Items":[{"Id":"e1","Name":"First","SeriesId":"show"}]}'
        with patch.object(self.m,'jellyfin_playback_user',return_value=('u','U')),patch.object(self.m,'jellyfin_request',side_effect=fake):
            guide=self.m.jellyfin_series_guide('show')
        self.assertIsNone(guide['next_up'])
        self.assertEqual(len(guide['episodes']),1)

    def test_season_selection_does_not_fetch_foreign_episodes(self):
        def fake(path,timeout=12.0):
            if '/Seasons?' in path: return 200,{},b'{"Items":[{"Id":"s2","IndexNumber":2},{"Id":"s1","IndexNumber":1}]}'
            if '/NextUp?' in path: return 200,{},b'{"Items":[]}'
            self.assertEqual(parse_qs(urlsplit(path).query)['SeasonId'],['s2'])
            return 200,{},b'{"Items":[{"Id":"e3","SeriesId":"show","Name":"Second"}]}'
        with patch.object(self.m,'jellyfin_playback_user',return_value=('u','U')),patch.object(self.m,'jellyfin_request',side_effect=fake):
            guide=self.m.jellyfin_series_guide('show','s2')
        self.assertEqual(guide['season_id'],'s2')
        self.assertEqual([x['id'] for x in guide['episodes']],['e3'])

    def test_next_up_from_unrelated_series_is_rejected(self):
        def fake(path,timeout=12.0):
            if '/Seasons?' in path: return 200,{},b'{"Items":[{"Id":"s1","IndexNumber":1}]}'
            if '/NextUp?' in path: return 200,{},b'{"Items":[{"Id":"foreign","SeriesId":"not-this-show"}]}'
            return 200,{},b'{"Items":[]}'
        with patch.object(self.m,'jellyfin_playback_user',return_value=('u','U')),patch.object(self.m,'jellyfin_request',side_effect=fake):
            data=self.m.jellyfin_series_guide('show')
        self.assertIsNone(data['next_up'])

    def test_remote_back_navigation_restores_previous_screen(self):
        s=SRC.read_text()
        self.assertIn("if(document.getElementById('library-browser').classList.contains('show')){e.preventDefault();libraryBack();return}",s)
        self.assertIn("pushHistory?document.querySelector('#library-panel .library-episode",s)

    def test_no_autoplay_and_explicit_completion(self):
        s=SRC.read_text()
        for marker in ('/api/jellyfin/series-guide','library-season-select','seriesEpisodeMarkup',
                       'function finishVideoIntentionally()','data-video-done','data-video-next',
                       'videoPlayer.addEventListener(\'ended\',()=>{if(videoPortalPlayer.active)finishVideoIntentionally()}):'):
            if marker.endswith(':'):marker=marker[:-1]
            self.assertIn(marker,s)
        self.assertNotIn('setTimeout(()=>playVideoItem(next',s)
        self.assertIn('VERSION="0.19.37"',(ROOT/'upgrade_to_v0.19.37.sh').read_text())

if __name__=='__main__':unittest.main()
