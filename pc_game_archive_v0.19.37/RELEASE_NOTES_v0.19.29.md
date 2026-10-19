# PC Game Archive v0.19.29 — Smart TV 10-foot UI support

## Purpose

Make the web portal usable on Smart TV browsers that report 960×540, 1280×720, 1920×1080, or native 3840×2160 CSS viewports, with remote-only input and display overscan.

## Changes

- Fixes device-layout detection ordering: known Tizen, webOS, HbbTV, NetCast, Viera, Roku, BRAVIA, Fire TV, etc. browsers select TV geometry even when their pointer or CSS viewport suggests desktop/mobile; remote-only landscape views choose TV before the small-viewport fallback. Ambiguous generic browsers retain the explicit manual override.
- Adds a home-screen **TV mode** toggle and persists the chosen layout per browser using existing portal customization settings.
- Adds **TV screen-safe margins** (3%, 5% default, 7%) and **TV text and control size** (100%, 115%, 130%) in Control Center → Display → Screen layout.
- Applies the configurable safe area to actionable content, modal dialogs, banners, and fullscreen playback controls; backgrounds and the actual movie video remain edge-to-edge.
- Increases focus visibility, minimum action sizes, library card and label readability, and scrollable modal behaviors in TV mode; retains tablet, mobile, desktop, and ultrawide profiles.
- Supports common TV Back key names in open dialogs by mapping them to existing Escape handling; the Back key on the home page remains available to the browser.
- Switches remote-focus scrolling to immediate movement in TV layout (and when reduced motion is preferred), avoiding slow scroll animations between rows.
- Corrects embedded Control Center version text to 0.19.29.

## Standards applied

- Google Android TV layout overscan guideline: 5% side/top/bottom safe regions, keep backgrounds edge-to-edge. https://developer.android.com/training/tv/playback/compose/layouts
- Google TV ten-foot focus and distance recommendations: https://developer.android.google.cn/design/ui/tv/guides/foundations/design-for-tv?hl=en
- Apple tvOS HIG safe area and focus-spacing principles: https://developer.apple.com/design/human-interface-guidelines/layout
- MDN media queries, viewport units, pointer types and reduced motion: https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media

## Limitations

- TV vendor browsers differ in CSS viewport sizes, media codec support, keyboard-event names, and certificate handling. A real-device acceptance test is still necessary.
- No assumption that physical 4K pixels equal CSS pixels; a manual override is provided for browsers with unreliable UA and input-device reporting.
- This release only changes portal UI and local display preferences; no optical-ingest, storage, user data, game, or media content should be modified by these UI changes.

## Upgrade

Wait for any currently active optical rips to finish (the existing upgrader enforces safety):

```bash
unzip pc_game_archive_v0.19.29.zip
cd pc_game_archive_v0.19.29
sudo ./upgrade.sh  # delegates to the canonical v0.19.29 upgrader
```

After upgrading, hard-refresh/reopen the TV browser. On the home screen select TV mode, or Control Center → Display → Layout mode → TV / 10-foot. Configure overscan and text size as appropriate.
