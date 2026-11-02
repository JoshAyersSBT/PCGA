# PC Game Archive v0.19.36 — Stream-aware Blu-ray recovery

The v0.19.35 Jellyfin health and upgrade fixes remain intact. v0.19.36 adds a **manual-review, reversible** stream-aware consolidation path for main movies accidentally also published under `extras/`. This addresses the real *Ghost in the Shell (1995)* case: three ~21 GiB MKVs with matching encoded video and audio streams, disjoint subtitle sets, and different chapter metadata, so whole-file SHA-256 dedupe misses the redundancy.

## New workflow

- **Audit:** Control Center → Ingest & Review → Bonus-feature duplicate review → Stream-aware Blu-ray consolidation. Enter part of the movie title to bound I/O and choose **Compare video, audio & subtitles**. The independent `pcga-stream-prune scan-streams` tool streams actual track-level SHA-256 hashes through FFmpeg, without creating any full-size temporary files. It checks titles separately and only considers extras attached to exactly one main movie (never TV or another movie).
- **Candidate eligibility:** matching complete encoded video and audio payload hashes and comparable durations; a candidate keeper must contain *all* matched subtitle tracks (including language/forced flags), and chapter timestamps must be identical or recoverable from the existing main movie. Videos with attachments, unmatched tracks, changed files, hardlinks that could be altered elsewhere, unsafe paths or incompatible chapter layouts are skipped. Different visual-only matches stay review-only in the v0.19.34 scanner.
- **Stage (explicit action):** a freshly scanned candidate is rechecked and hashed again. If the richer keeper has no chapters, MKVToolNix injects the main movie's chapter markers and verifies that video/audio/subtitle hashes are unchanged. The richer version occupies the original main-movie path via same-filesystem rename. Prior main/extra copies are **moved to** `/srv/pc-game-archive/recovery-hold/stream-prune/<candidate-id>/` (relative to the configured archive root). A recovery manifest permits rollback.
- **Restore (explicit action):** returns the original main and extras to their exact paths, refusing overwrites and changed/linked recovery files.
- **Purge (explicit and delayed):** only after seven days and a second confirmation. Revalidates the remaining keeper's tracks and chapters and the held inodes before unlinking the held redundant files. **Staging and quarantine do not recover disk space; only purge does** on the same filesystem. No upgrade action prunes anything automatically.

The legacy `pcga-extra-prune` exact-copy and visual-only scans remain available. The stream-aware consolidation is a separate workflow.

## Storage-pressure protections

- Control plane storage diagnostics now report `normal` / `low` (under 10 GiB free) / `critical` (under 3 GiB free), and the portal status strip displays remaining disk space and an actionable low-space warning.
- New **optical** ARM jobs must reserve at least **10 GiB beyond the detected disc capacity**, increased from the previous 5 GiB reserve. Existing active rips are unaffected. This guard is preventive; it does not clean files or artificially increase free disk space.

## Install

```bash
unzip pc_game_archive_v0.19.36.zip
cd pc_game_archive_v0.19.36
sudo ./upgrade.sh
```

Requires `ffmpeg` and `ffprobe` for stream inspection, and `mkvextract` / `mkvpropedit` (package `mkvtoolnix`) **only when transferring missing chapters during staging**. The scanner reports missing dependencies; the upgrade never runs a pruning job.

### Optional host CLI

```bash
# Read-only, restrict scan to one title to avoid hashing the whole library:
sudo pcga-stream-prune scan-streams --title 'Ghost in the Shell'
sudo pcga-stream-prune status

# Only after reviewing candidate evidence and confirming playback plan:
sudo pcga-stream-prune stage --id CANDIDATE_ID --confirm
# Roll back if needed:
sudo pcga-stream-prune restore --id CANDIDATE_ID --confirm
# After seven days, playback verification, and separate authorization:
sudo pcga-stream-prune purge --id CANDIDATE_ID --confirm
```

**Existing manually staged files:** The files already moved into `/srv/pc-game-archive/recovery-hold/ghost-in-the-shell-1995` are **not automatically registered or modified** by this new service. Complete that earlier manual recovery separately. Re-running the scanner on already consolidated Ghost in the Shell will normally show no further candidates.

## Validation and limitations

The release is tested with offline regressions and synthetic stream/transaction fixtures, plus a real FFmpeg probe/streamhash smoke test. Live integration with your PCGA appliance/Jellyfin and chapter playback needs confirmation. This release deliberately excludes automatic remuxing of incompatible editions, video-only perceptual matches, automatic permanent deletion, NAS/backup migration, and TV-season promotion. Host integration depends on the installed systemd control plane and the existing upgrade prerequisites.
