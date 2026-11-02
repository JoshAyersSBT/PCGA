# PC Game Archive v0.19.26 — Verified NAS Tier for Original Masters

This opt-in tier takes **original source-quality MKV masters from already published low-loss conversions** and copies them to PCGA's existing configured NAS mount. The playable, optimized Jellyfin MKV remains local and available throughout.

## Safety model

- Configure SMB/NFS storage in **Control Center → Storage / NAS**, select **Mirror** mode (not Smart offload), before enabling offload.
- The NAS mount must be real and match the configured endpoint; a plain local directory at `/mnt/pcga-nas` is never an acceptable fallback.
- Offload verifies the playable MKV against its conversion manifest; copies the original into a temporary NAS file; fsyncs; verifies its SHA-256 and byte length; atomically publishes it; reads it back and verifies again; saves a persistent tier record; **only then** deletes the local master.
- A matching existing NAS file is verified, never overwritten. Conflicting files halt the job.
- A source master never leaves its local location when NAS mount verification, copy, or hashing fails.
- Restore copies the NAS original to a temporary local file; verifies SHA-256; atomically installs it in master storage. NAS copy remains. Existing low-loss rollback becomes available again after restore.
- The offload and restore jobs run via systemd and expose inventory/job reports. Existing optical ripping and Jellyfin files are never modified.
- Source-relative paths and symlink checks restrict all paths to PCGA-managed storage.
- SHA-256 validates file content but is not a substitute for independent backups, filesystem checksums or off-site replication.

## Workflow

1. Complete a low-loss encode and **Publish optimized movie**.
2. Configure the PCGA NAS connection in Control Center. Verify it is mounted.
3. In **Ingest & Review → Low-loss playable copies**, choose the published conversion.
4. Choose **Offload verified original to NAS** and confirm. Monitor the background job.
5. When needed, choose **Restore exact original from NAS**, then **Restore original movie** to roll back the optimized playable copy.

CLI: `sudo pcga-low-loss-tier inventory`, `sudo pcga-low-loss-tier offload 'movies/Title (2020)/Title (2020).mkv'`, `sudo pcga-low-loss-tier restore 'movies/Title (2020)/Title (2020).mkv'`.

## Limitations

- Master tiering is opt-in per movie; it does not schedule automatic offloads or handle movies without a verified published low-loss original.
- NAS access and writable free space are required; the NAS should have reliable storage/backup and appropriate access controls.
- A network outage after a completed offload makes the original temporarily unavailable to restore, but the local optimized Jellyfin version remains playable.
- Concurrent master tier operations serialize with the low-loss encoding and cold-archive storage lock.
- Final verification requires a real NAS mount on the target server; offline tests use an isolated filesystem fixture.
