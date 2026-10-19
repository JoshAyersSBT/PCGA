# PCGA v0.19.32 — Bonus Features in Movies & TV

## Included

- Movies & TV title-details screens now show a **Bonus features** section for movies, television shows, and other titles where Jellyfin has linked special features.
- Reads Jellyfin's `GET /Items/{itemId}/SpecialFeatures?userId=...` and `GET /Items/{itemId}/LocalTrailers` endpoints, with exact parent-item relationships. Does **not** guess an extra's parent based on filename, runtime or ingestion timing.
- Organizes extras under Behind the scenes, Featurettes, Deleted scenes, Interviews, Scenes, Clips, Shorts, Trailers, Samples, and Other extras using source metadata.
- Each extra has its own focusable **Play** action; uses the existing Jellyfin player with audio selection, subtitles, playback progress, and fullscreen controls.
- Viewing an extra never queues the next television episode and never autoplays another bonus video. Closing the player returns to the selected extra in the parent title detail view.
- Empty and unavailable extras states are distinct, and partial API failures do not hide features supplied by another supported endpoint.
- Preserves existing ingestion, review, original-master storage and Jellyfin library files; upgrade is read-only with regard to media.

## Finding an extra

Open **Movies & TV → select a movie or series → Bonus features**, then select the specific title and choose Play. The section appears below the synopsis and normal playback actions; scroll down on the TV remote.

**Jellyfin must already recognize the extra under that movie or series.** Store it in a Jellyfin-supported `behind the scenes`, `featurettes`, `extras`, `interviews`, `deleted scenes`, or similar folder under the parent directory, then refresh Jellyfin's library. PCGA does not attach an unrelated movie automatically. Extra features that are still in PCGA Manual Review, or mislabeled as a standalone movie, must be corrected/published before they can appear here.

## Deployment

Finish active optical jobs; unpack and run:

```bash
unzip pc_game_archive_v0.19.32.zip
cd pc_game_archive_v0.19.32
sudo ./upgrade.sh
```

Both upgrade entry points are executable. Refresh Smart TV/browser tabs after installing.

## Validation and limitations

Offline unit tests validate Jellyfin's item-scoped associations, deduplication, invalid-ID rejection, partial failures, missing extras, and the explicit UI playback path. JavaScript and Python syntax, upgrade-shell syntax, SHA-256 manifest and ZIP integrity are validated prior to packaging.

Smart TV rendering and actual playback with your Jellyfin server still need live validation. Source media that Jellyfin has not indexed as extras will not appear through these endpoints; do not guess-match it into the wrong movie.
