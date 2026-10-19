"""TV-safe CSS, viewport detection, persistence, remote focus, and release preflight checks."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/'components/pcga-status-server.py').read_text()
UPGRADE=(ROOT/'upgrade_to_v0.19.37.sh').read_text()

class TvLayout1929(unittest.TestCase):
    def test_all_standards_based_safe_area_controls_present(self):
        for x in ('--tv-safe-x','--tv-safe-y','data-device-layout="tv"','tvSafeArea:5','tvTextScale:100',
                  'id="setting-tv-safe-area"','id="setting-tv-text-scale"','var(--tv-safe-x,5vw)',
                  'body[data-device-layout="tv"] .shell','body[data-device-layout="tv"] .review-layout',
                  'body[data-device-layout="tv"] .settings-grid','body[data-device-layout="tv"] .video-player-modal{padding:0}'):
            with self.subTest(component=x):self.assertIn(x,SRC)
    def test_smart_tv_browser_detection_before_mobile(self):
        logic=SRC.split('function detectDeviceLayout(){',1)[1].split('function activeDeviceLayout()',1)[0]
        self.assertIn('pcgaSmartTvBrowser()',logic)
        self.assertIn("w>=820&&h>=470&&aspect>=1.45&&noHover&&noPointer",logic)
        self.assertLess(logic.index("if(pcgaSmartTvBrowser())return'tv'"),logic.index("if(w<=680)return'mobile'"))
        self.assertIn('Tizen|Web0S|WebOS|NetCast|HbbTV',SRC)
    def test_client_only_persistence_and_recovery(self):
        for x in ("id=\"quick-tv-mode\"", "quick.setAttribute('aria-pressed',String(tv))", "portalSettings.layoutMode=activeDeviceLayout()==='tv'?'auto':'tv'", "savePortalSettings();syncSettingsControls()", "localStorage.setItem(PORTAL_SETTINGS_KEY"):
            with self.subTest(component=x):self.assertIn(x,SRC)
        self.assertIn("[3,5,7].includes(Number(raw.tvSafeArea))",SRC)
        self.assertIn("[100,115,130].includes(Number(raw.tvTextScale))",SRC)
    def test_remote_focus_not_only_hover(self):
        self.assertIn('body[data-device-layout="tv"] .pcga-nav-selected{outline:3px',SRC)
        self.assertIn('function pcgaDirectionalCandidate(current,key)',SRC)
        self.assertIn('function pcgaTrapModalTab(e)',SRC)
    def test_versions_and_guard(self):
        self.assertIn('VERSION="0.19.37"',UPGRADE)
        self.assertIn('VERSION = "0.19.37"',SRC)
        self.assertIn("const PORTAL_BUILD_VERSION='0.19.37'",SRC)
        self.assertIn("'id=\"quick-tv-mode\"'",UPGRADE)
        self.assertIn("'id=\"setting-tv-safe-area\"'",UPGRADE)

if __name__=='__main__':unittest.main()
