# v0.19.29 Smart TV acceptance checklist

- [ ] Existing PCGA desktop browser remains Desktop in Automatic layout; tablet and phone layouts stay responsive.
- [ ] Samsung/Tizen and LG/webOS user-agent simulated browser routes to TV at 960×540 / 1920×1080.
- [ ] Generic remote-only 1280×720 browser routes to TV; desktop 1920×1080 browser stays Desktop.
- [ ] TV mode home-screen toggle works, survives page reload on a persistent browser origin, and can return to Automatic.
- [ ] Display settings persist screen-safe margins (3/5/7%) and TV text scale (100/115/130%) on this browser.
- [ ] On TV, 960×540 and 1280×720, controls inside Movies & TV, PC Games, Console Games, Control Center, Media search, and movie playback are visible without horizontal page overflow.
- [ ] Test TV remote arrow keys/OK/Back to open, navigate, select, scroll and exit a dialog without trapping focus.
- [ ] Playback fullscreen video remains edge-to-edge with accessible, overscan-safe controls; three-second auto-hide still works.
- [ ] Browser HTTPS warning remains accessible but does not cover most of a low-resolution TV viewport.
- [ ] Set larger font and larger safe-area options and verify controls remain accessible by scrolling.
- [ ] Validate actual target Smart TV firmware/browser; supported codec/HTTPS capabilities vary by vendor.
- [x] Python and Bash static syntax checks, portal JavaScript syntax check, 138 offline regression tests.
- [x] Chromium CSS geometry smoke checks at 960×540, 1280×720, 1920×1080, and 3840×2160; no horizontal document overflow in modal fixture.
- [x] Device detector evaluation for Tizen, webOS, remote-only browser, desktop, tablet and phone.
