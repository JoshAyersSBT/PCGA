# PCGA v0.19.24 — Verified lossless cold storage

## Purpose

Permit byte-identical storage compression of infrequently watched published movie/TV/home video files, while keeping PCGA's lossless MakeMKV extraction and media-identification safeguards unchanged. Zstandard (level 6) wraps the **complete file** and therefore preserves all original video/audio/subtitle streams, chapters and metadata exactly after restoration.

## Design

- **Default is no-op.** Compression never starts automatically and the upgrade does not touch media data. The operator explicitly selects **Compress & move offline** and confirms Jellyfin unavailability.
- **Cold storage, not playback:** `.zst` files live under `media/cold-archive/lossless` and are not playable by Jellyfin. The UI provides a restore control.
- **Measured gain:** compression is discarded if the finished result is less than 2% smaller. Results are reported as actual bytes saved, not estimates.
- **End-to-end verification:** SHA-256 of original, compressed file and decompressed output; atomic move into cold directory; revalidate unchanged source before deleting original. Restoring validates the packed checksum and byte-identical output before publishing the original filename; the archived copy is removed only after successful restore.
- **Input safety:** limited to approved library-relative video paths; rejects path traversal and symlinks, recently changed inputs, output collisions and insufficient temporary space. A global cold-archive lock serializes archive/restore jobs without pausing the optical drive workers.
- **Host-side privileged jobs:** the portal asks pcga-control to queue an explicit systemd transient unit. The browser never gets filesystem write authority or root tokens. Job records survive browser closing.

## Size expectations

Blu-ray discs already use compressed video. Lossless general-purpose compression on typical `.mkv` remuxes often produces very little benefit. The 2% minimum prevents wasting archive storage on ineffective compression. Material space reductions are possible with *selective stream removal* or *quality-oriented re-encoding*, but stream removal is destructive with respect to the removed streams and normal HEVC/AV1 re-encoding is lossy. Neither is enabled here.

## Limitations

- No automatic decode-on-play; the movie is offline while cold archived.
- Cold compressed files cannot be streamed directly from Jellyfin.
- Requires enough free disk space to create the compressed copy safely. Disk throughput and CPU consumption can be substantial for 50–150 GiB titles.
- Current compression is per published file, not per-disc playlist, and does not attempt to deduplicate alternate cuts or replace the disc-native MakeMKV extraction model.
- Maintains ARM's single-writer output lock; independent multi-drive staging remains future work.

## Verify

```bash
sudo pcga-lossless-archive inventory
sudo systemctl list-units 'pcga-lossless-*' --all
sudo journalctl -u 'pcga-lossless-*' --no-pager -n 100
```

Test on a small already-published movie first; inspect it before and after restoration. There is no automatic archival during an upgrade.
