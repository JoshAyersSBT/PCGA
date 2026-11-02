# PCGA v0.19.33 — Bonus-feature duplicate cleanup

PCGA now identifies byte-for-byte identical video copies in recognized bonus-feature directories under the same movie or television title. It never identifies duplicates from names, lengths, cover art, or metadata alone. All source-quality and alternate edits are preserved when their bytes differ.

## Upgrade

```bash
unzip pc_game_archive_v0.19.33.zip
cd pc_game_archive_v0.19.33
sudo ./upgrade.sh
```

No files are changed by the upgrade. From **Movies & TV → Manage → Review duplicate extras**, or **Control Center → Ingest & Review → Bonus-feature duplicate review**, choose **Scan extras for duplicates**. A scan can take a while on large Blu-rays. Each candidate shows the main/keeper path and the matching extra.

**Move copy to quarantine** removes the extra from Jellyfin's active folder without deleting its bytes. **Restore** returns it provided the path has not been reused. **Permanently delete** becomes available only after seven days and requires its own explicit confirmation. Until that final purge, no disk-space savings are expected from regular duplicate files. Scan and quarantine are opt-in. If Jellyfin still shows old entries, run its library scan.

Under the hood: `sudo pcga-extra-prune scan`, `status`, `quarantine --id ID --confirm`, `restore --id ID --confirm`, `purge --id ID --confirm`. Files and checksums are inspected again at action time. The existing generic dedupe service is unchanged.

### Limitations
- It is not video fingerprinting: separately encoded versions or content-identical videos with different bytes will not be flagged.
- Files must be in a recognized extras directory inside the same movie or series title tree. It does not inspect arbitrary mounts or unrelated movies.
- The quarantine location must be on the same local filesystem so moves are atomic.
- Jellyfin can cache library records; refresh its library if needed.
