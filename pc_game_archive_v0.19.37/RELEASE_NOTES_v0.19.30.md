# v0.19.30 — Calm Movies & TV UX foundation

## Scope

- Movies & TV is now an immersive, screen-filling browsing surface while remaining inside PCGA.
- A title opens a details screen, not immediate playback. Details use the existing selected Jellyfin user and server-held token; no authentication token is sent to the browser.
- Explicit Play, Resume, Start Over, and Browse episodes actions. No autoplay while browsing.
- Resume and recently added shelves are sourced from Jellyfin; other shelves are grouped by media type.
- Explicit paged catalog loading for long movie/video lists. TV episode browsing retains its existing 300-item initial ceiling until the season-focused release.
- Navigation restores previous items, scrolling and focus on return; TV remote Escape/Back works from details.
- Content management actions are still present but move to Manage.

## Known limitations

- Season-centric episode navigation, collections/versions/extras tabs, and My List are **not implemented** in this release; they belong to the next UX iterations.
- The Jellyfin item endpoint may have incomplete artwork/cast/synopses; the portal displays simple fallbacks.
- The new UI does not modify watch history, media files, existing Jellyfin libraries, or playback encoding.
- Release tests use synthetic library data and Chromium; validate with the actual Jellyfin server and Smart TV.

## Upgrade

Extract `pc_game_archive_v0.19.30.zip` and run `sudo ./upgrade.sh` from within `pc_game_archive_v0.19.30`, with any optical rips completed first. Do not use the historical v0.19.29 upgrader.
