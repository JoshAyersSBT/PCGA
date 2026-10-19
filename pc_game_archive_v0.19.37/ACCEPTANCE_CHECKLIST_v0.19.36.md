# v0.19.36 acceptance checklist

- [ ] Before upgrade, finish optical rips and make sure at least 2 GiB free for Jellyfin database startup.
- [ ] `sudo ./upgrade.sh` completes without resetting Jellyfin media/database or skipping an enabled unhealthy Jellyfin instance.
- [ ] `command -v pcga-stream-prune`; `command -v ffmpeg`; `command -v ffprobe`; `command -v mkvextract`; `command -v mkvpropedit` (the latter two needed for chapter restoration).
- [ ] Movies & TV → Manage → Review duplicate extras opens Ingest & Review and displays **Stream-aware Blu-ray consolidation**.
- [ ] A read-only scan of a title with main/extras matching compressed video/audio finds a consolidation candidate with subtitle union; unrelated movies and visually similar but different streams stay excluded.
- [ ] A title without extras, a hardlinked duplicate, an active optical rip, an unsafe path or missing/changed file produces no actionable candidate.
- [ ] **Stage** preserves the original main file and other eligible extras in `recovery-hold/stream-prune`, moves the richest file to the movie's original path and never makes a 20+ GiB file copy.
- [ ] If chapter transfer was needed, the published movie retains matching chapters and all video/audio/subtitle tracks.
- [ ] Verify start/end playback, chapter seeking, language/subtitle selection in PCGA/Jellyfin; refresh Jellyfin library to clear old extra entries.
- [ ] **Restore** returns originals to their original library paths, refuses overwrites/changed recovery files.
- [ ] **Purge** fails before seven days and requires separate confirmation; after purging eligible held inodes, filesystem `df -h /` gains free space.
- [ ] Portal status strip warns when the filesystem is low/critical and shows free disk space.
- [ ] A new optical rip is refused when free space would fall under full disc capacity plus 10 GiB; existing jobs are not interrupted.
- [ ] Manually staged recovery holds from prior releases are not silently deleted or adopted.

This release does **not** execute destructive changes during installation. Any preexisting backup/archival preservation policy still applies.
