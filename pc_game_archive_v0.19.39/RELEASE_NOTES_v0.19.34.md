# PC Game Archive v0.19.34 — Review-only visual duplicate detection

Separate encodes can contain similar video frames while their SHA-256 checksums differ. The optional **Compare video content (review only)** action samples 8 decoded frames at distributed playback positions, converts each sample to a small perceptual hash, checks duration consistency, and flags strong similarity *within the same title* when at least one file is an extra. Flat/dark frames are discounted. FFmpeg and ffprobe are required.

**Visual suggestions do not authorize deletion**. The portal shows only side-by-side paths, frame agreement and cautions. No automatic quarantine, deletion, promotion or merging is possible through this new feature. The existing exact-hash workflow remains unchanged, including its separate confirmation and 7-day quarantine.

### Install

```bash
unzip pc_game_archive_v0.19.34.zip
cd pc_game_archive_v0.19.34
sudo ./upgrade.sh
```

### Use

In **Movies & TV → Manage → Review duplicate extras** or **Control Center → Ingest & Review**, click **Compare video content (review only)**. Refresh results after the background job finishes. CLI: `sudo pcga-extra-prune scan-visual` then `sudo pcga-extra-prune status`.

### Limits and safety

- Only settled regular files in an individual library title tree are considered. The scan will not cross movie boundaries.
- Same duration and similar video *do not prove* matching audio, subtitles, chapters, commentary, editions or licensing.
- Modified files and symlinks are rejected. Very large (>64 video-file) title groups are skipped rather than scanning without bounds.
- A negative result does not prove videos differ: fades, reframes, credits, segment timing, differing frame rates, and heavily edited editions can defeat sparse sampling.
- Visual analysis runs on the PCGA host, may consume CPU and disk I/O, and is opt-in. It refuses to start during an active optical rip.
