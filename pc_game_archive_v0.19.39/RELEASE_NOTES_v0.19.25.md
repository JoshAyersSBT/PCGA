# PCGA v0.19.25 — opt-in HEVC/AV1 low-loss encoding

## Features
- New host-side `pcga-low-loss-encode` with commands `inventory`, `encode`, `publish`, `rollback` and `job`.
- Quality-oriented, not bit-exact: H.265/HEVC (libx265) or AV1 (libsvtav1); Balanced and High presets. Copy source audio/subtitle/attachments, chapter map and Matroska metadata where possible.
- Only an eligible settled MKV may be encoded. HDR/Dolby Vision, unusual pixel formats, unknown data tracks and multiple primary video streams fail closed instead of compromising preservation.
- FFprobe comparison before accepting output: video codec, resolution, bit-depth class, non-video stream codecs/count, chapters, and duration; SHA-256 hashes before/after, source-stability checks, minimum 10% savings threshold.
- Staged playable copy lives outside Jellyfin. Explicitly publish only after manual inspection. Publish retains the original under `media/cold-archive/low-loss-masters`. Rollback restores byte-for-byte original from master.
- Control Center → Ingest & Review provides source selection, codec/quality choice, enqueue actions and per-job background states/progress. Host jobs are launched by `systemd-run` with reduced CPU and I/O scheduling weights; browser never executes shell commands.
- The v0.19.24 lossless archive and low-loss jobs share a storage operations lock. The old byte-exact archive mode remains unchanged otherwise.
- Original versions and stored Steam profiles, game library metadata, ripped media and optical job artifacts are untouched on upgrade.

## Safety / storage tradeoffs
- Normal video encodes are inherently lossy; low-loss is not synonymous with reversible or identical.
- No automatic replace/offload/delete. **Retaining original master on the same disk makes total storage usage larger**, even if the Jellyfin playable copy is smaller.
- Actual savings, quality and performance vary by original codec, content complexity and selected profile. Already-efficient HEVC/AV1 files may be skipped.
- Published files are standard MKV with AV1/HEVC video. Jellyfin/client support varies and may require playback transcoding.
- HDR10/HLG/Dolby Vision are explicitly excluded from this initial implementation; correct mastering display/color and dynamic metadata handling remains future work.
- Static suite and short synthetic FFmpeg sample exercise functionality; no full-length UHD movie on the actual PCGA server was transcoded or visually reviewed in this build environment.

## Validation / acceptance
1. Verify `/api/status` and `/api/control/state` report v0.19.25, and `low_loss` inventory appears in Control Center.
2. Confirm settled MKVs are shown while recently modified/foreign/symlink sources are not.
3. Encode a short **SDR** test movie with HEVC; confirm original SHA-256 unchanged and new MKV has expected codec, audio and chapters.
4. Check `low-loss/staged` contains the candidate but Jellyfin still plays the original.
5. Publish after examining the staged file. Verify live library points to the new encoded MKV and `cold-archive/low-loss-masters` retains the original checksum.
6. Roll back; confirm exact original checksum and that verified optimized copy is returned to staging.
7. Verify scripts reject HDR, tampered master/staged files, files changed since encoding, traversal, symlinks, too-young files and unknown streams.
8. Confirm successful low-loss jobs never affect ARM rip concurrency policy, classification, existing Zstandard archives, or other services.
