# v0.19.30 — Acceptance Checklist

- [ ] Upgrade succeeds with `sudo ./upgrade.sh` (both scripts executable).
- [ ] Portal API and UI report version `0.19.30`.
- [ ] Movies & TV opens as a dedicated full-viewport browsing surface without affecting PC Games, Photos or Music.
- [ ] Continue Watching appears only when Jellyfin has resume data; Recently Added lists current library entries.
- [ ] Selecting a poster opens a title-detail view without starting playback.
- [ ] Synopsis, runtime, year, genres and cast display when supplied by Jellyfin; missing metadata falls back safely.
- [ ] Resume resumes; Start Over begins from zero; Play does not change the underlying media.
- [ ] Back restores prior library cards, scroll and focus with a TV remote.
- [ ] Category Load more retrieves next page without duplicating the previously loaded 60 titles.
- [ ] Manage reveals Upload movie / Upload TV / Home video / Correct movie labels; default view remains uncluttered.
- [ ] Check layout at 960x540, 1280x720, 1920x1080 and on actual Smart TV.
- [ ] Existing fullscreen player, ingestion, emulators, Steam, backups and music still work.
