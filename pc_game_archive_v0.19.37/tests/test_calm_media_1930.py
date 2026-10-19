"""v0.19.30: Calm video browsing, source-owned metadata and bounded paging."""
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from unittest.mock import patch
import json, types, unittest

ROOT=Path(__file__).resolve().parents[1]
CODE=(ROOT/'components/pcga-status-server.py').read_text()

def load():
    module=types.ModuleType('pcga_media_1930_test')
    module.__file__=str(ROOT/'components/pcga-status-server.py')
    exec(compile(CODE,module.__file__,'exec'),module.__dict__)
    return module

class CalmVideoBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.m=load()

    def test_title_details_are_server_side_and_bounded(self):
        m=self.m
        iid='abc123'
        item={'Id':iid,'Name':'Film','Type':'Movie','Overview':'Details', 'People':[{'Type':'Actor','Name':'A Name'}], 'Genres':['Mystery'], 'RunTimeTicks':72000000000}
        with patch.object(m,'jellyfin_playback_user',return_value=('user123','Demo')), \
             patch.object(m,'jellyfin_request',return_value=(200,{},json.dumps(item).encode())) as request:
            detail=m.jellyfin_media_details(iid)
        self.assertEqual(detail['id'],iid)
        self.assertEqual(detail['cast'],['A Name'])
        self.assertEqual(detail['runtime_seconds'],7200)
        self.assertEqual(request.call_args[0][0],'/Users/user123/Items/abc123')
        for bad in ('../../password','', 'abc/?#'):
            with self.subTest(id=bad),self.assertRaises(ValueError):m.jellyfin_media_details(bad)

    def test_page_offsets_do_not_reorder_results(self):
        m=self.m
        def jellyfin_fake(path,timeout=10.0):
            query=parse_qs(urlparse(path).query)
            start=int(query.get('StartIndex',['0'])[0]); count=int(query.get('Limit',['0'])[0])
            data={'Items':[{'Id':f'item{i:03d}','Name':f'Movie {i}','Type':'Movie','RunTimeTicks':6000000000} for i in range(start,min(start+count,85))]}
            return 200,{},json.dumps(data).encode()
        with patch.object(m,'jellyfin_playback_user',return_value=('user123','Demo')), \
             patch.object(m,'jellyfin_request',side_effect=jellyfin_fake):
            first=m.jellyfin_library_items('','movies',60,start_index=0)
            second=m.jellyfin_library_items('','movies',60,start_index=60)
        self.assertEqual(len(first['items']),60)
        self.assertTrue(first['has_more'])
        self.assertEqual(first['next_index'],60)
        self.assertEqual(len(second['items']),25)
        self.assertFalse(second['has_more'])
        self.assertEqual(first['items'][-1]['id'],'item059')
        self.assertEqual(second['items'][0]['id'],'item060')

    def test_calm_controls_and_backend_wiring(self):
        required=('function openJellyfinDetail(item)', 'function libraryBack()', 'function loadMoreJellyfinLibrary()',
                  'data-library-play', 'data-library-manage', 'data-library-more', 'data-library-back',
                  'Recently Added', 'aria-expanded="false"', 'No automatic previews or playback',
                  '/api/jellyfin/title-details', 'library-detail-layout')
        for marker in required:
            with self.subTest(marker=marker):self.assertIn(marker,CODE)
        self.assertIn("function playLibraryItem(index){const item=libraryItems[Number(index)];if(!item)return;openJellyfinDetail(item)",CODE)
        self.assertNotIn('data-library-autoplay',CODE)
        self.assertIn('VERSION="0.19.37"',(ROOT/'upgrade_to_v0.19.37.sh').read_text())

if __name__=='__main__':unittest.main()
