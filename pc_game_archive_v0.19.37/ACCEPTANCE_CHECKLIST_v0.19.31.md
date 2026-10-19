# PCGA v0.19.31 — TV Journey Acceptance Checklist

- [ ] Upgrade from v0.19.30 using `sudo ./upgrade.sh` without reinitializing Jellyfin or touching media.
- [ ] Portal API and Control Center show `0.19.31`.
- [ ] Select a TV series, open Browse episodes, and see real Jellyfin seasons (including Specials if present).
- [ ] Season chooser changes episodes without adding redundant Back stack entries; browser remote focus remains on the selector.
- [ ] Episode rows show summaries, running times, artwork, watched/resume indicators from that Jellyfin user.
- [ ] Next Up is shown only if Jellyfin provides an episode from the selected series.
- [ ] Selecting an episode opens details before Play/Resume/Start Over; no auto-playing previews.
- [ ] Closing the player returns focus to the initiating action; TV Back traverses episode → season → series → library.
- [ ] At the end of playback, the app waits for explicit Next Episode or Return to library. No countdown or automatic playback.
- [ ] Repeat at a season boundary, for Specials, and on a series without episodes/metadata.
- [ ] Repeat on 960×540, 1280×720, 1920×1080 and actual Smart TV; verify no inaccessible buttons.
- [ ] Confirm game, music, photo, rip, NAS and Steam workflows remain unaffected.
