# PCGA v0.19.33 — Extras pruning acceptance checks

Before upgrading, finish all ARM optical rips. Back up irreplaceable movie data.

1. Upgrade using `sudo ./upgrade.sh`; expect API and portal build `0.19.33`.
2. Movies & TV → Manage → Review duplicate extras opens Ingest & Review settings.
3. Run Scan extras. It should examine settled movie and TV title folders without modifying them; this can take minutes for large files.
4. Place an exact copy of a main-feature MKV inside the same movie's `behind the scenes/` folder. It should appear as a candidate, with the main movie as the preserved copy.
5. Different video bytes with the same filename or runtime must not be flagged; other movie folders must remain independent.
6. Approve Move copy to quarantine. The extra disappears from the active library folder while the main movie remains playable. Refresh Jellyfin's library if the old tile is cached.
7. Confirm Restore moves the file back to its original location and checksum matches; it must refuse to overwrite a path reused since quarantine.
8. Confirm a permanent purge is not available before seven days, requires separate confirmation, and does not affect the retained main title.
9. With an ARM rip active, scan/quarantine/restore/purge must refuse rather than race with the media pipeline.
10. Check application logs if a job errors: `journalctl -u 'pcga-extra-prune-*' -n 100 --no-pager`.

Known limit: Separate encodings or remuxes are not flagged without identical bytes. Pending/quarantined files still consume space; only eventual purge can free independent file storage.
