"""Regression safeguards for the PCGA fullscreen Jellyfin video-player UI."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / 'components' / 'pcga-status-server.py').read_text()
UPGRADE = (ROOT / 'upgrade_to_v0.19.37.sh').read_text()


class VideoFullscreen1928Tests(unittest.TestCase):
    def test_correct_timeline_grid_position(self):
        # Fourth column is elapsed time, fifth is the elastic timeline.
        self.assertIn('grid-template-columns:auto auto auto auto minmax(0,1fr) auto auto minmax(78px,140px) auto auto', SRC)
        self.assertIn('grid-template-columns:auto auto auto auto minmax(0,1fr) auto auto minmax(90px,150px) auto auto', SRC)
        self.assertNotIn('grid-template-columns:auto auto auto minmax(160px,1fr) auto auto auto', SRC)

    def test_large_accessible_seek_target(self):
        self.assertIn('#video-seek{width:100%;min-width:0;height:36px', SRC)
        self.assertIn('#video-seek::-webkit-slider-runnable-track{height:10px', SRC)
        self.assertIn('#video-seek::-moz-range-progress{height:10px', SRC)
        self.assertIn('#video-seek:focus-visible', SRC)
        self.assertIn("videoSeek.style.setProperty('--pcga-seek-fill'", SRC)

    def test_controls_fade_only_in_fullscreen(self):
        self.assertIn('.video-player-panel:fullscreen.video-idle .video-controls', SRC)
        self.assertIn('pointer-events:none;visibility:hidden', SRC)
        self.assertNotIn('.video-player-panel.video-idle .video-controls{', SRC)

    def test_idle_conditions_and_activity(self):
        for marker in (
            'function videoControlsMustStayVisible()',
            'videoPlayer.paused||videoPlayer.ended||videoPlayer.seeking',
            'videoSeekDragging||videoPlayer.readyState<2',
            "focused.matches(':focus-visible')",
            'function scheduleVideoIdle()',
            'function wakeVideoControls()',
            'function cancelVideoIdle()',
            "videoPlayerPanel?.addEventListener('pointermove',wakeVideoControls)",
            "videoPlayerPanel?.addEventListener('focusin',wakeVideoControls)",
            "document.addEventListener('fullscreenchange',()=>{renderVideoControls();wakeVideoControls()})",
            "videoPlayer.addEventListener('pause',()=>{cancelVideoIdle();renderVideoControls();",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, SRC)

    def test_release_guard_and_versions(self):
        self.assertIn('VERSION = "0.19.37"', SRC)
        self.assertIn("const PORTAL_BUILD_VERSION='0.19.37'", SRC)
        self.assertIn('function scheduleVideoIdle()', UPGRADE)
        self.assertIn('video-idle .video-controls', UPGRADE)


if __name__ == '__main__':
    unittest.main()
