# PCGA v0.19.31 — Intentional TV Viewing

## Included

- Native Jellyfin season discovery, episode lists and **Next Up** from the current Jellyfin user's watch state.
- Season chooser (specials included), artwork, episode descriptions, watch/resume indicators, and episode-level detail before playback.
- Episode search scoped to the selected season; no unbounded scroll or unintended season switch.
- A non-autoplay **Playback complete** screen offering **Next episode** only when there is a known subsequent episode in the loaded season, and **Return to library**.
- Existing player retained: quality/audio/subtitles, timeline, fullscreen, remote focus. Exit restores focus to the initiating action.
- Responses are bounded to 500 episodes per season and exclude virtual/missing media. No invented next-episode metadata.

## Limitations

- Next episode at a season boundary must be selected explicitly from the series guide (or via Jellyfin Next Up); the completion screen never guesses the next season.
- The end-of-playback choice is not an autoplay queue or timer.
- Live Smart TV / Jellyfin server verification is still needed.

## Upgrade

Run `sudo ./upgrade.sh` from the extracted release directory. Preserve existing media, account data and settings.
