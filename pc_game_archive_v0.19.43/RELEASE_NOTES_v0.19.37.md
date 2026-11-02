# PC Game Archive v0.19.37 — HTTPS Diagnostics upgrade validation

## Fixed

- Fix the v0.19.36 false-negative failure after `Portal-native Manual Review bridge validated`. The upgrader made its *second* Diagnostics catalog query on `http://127.0.0.1:8098`, but `proxy_diagnostics()` intentionally returns HTTP 426 outside TLS. The failed `curl -f` supplied empty standard output to `json.load()`, producing a JSONDecodeError and falsely claiming Jellyfin was absent.
- Validate the Diagnostics catalog exactly once at `https://127.0.0.1:8443/api/diagnostics/catalog` with `/etc/pc-game-archive/tls/pcga-ca.crt`. Verify streaming-service presence and, when Jellyfin is enabled, both the Jellyfin service entry and membership in the Media profile.
- Distinguish TLS/network failure, non-200 HTTP status with JSON error detail, invalid schema, absent service, and absent Media membership. Never parse failed curl output through an unguarded JSON pipeline.
- Preserve HTTPS-only enforcement for log service metadata and logs. No insecure access is enabled.
- Preserve Jellyfin reachability check on `/api/jellyfin/health` (which intentionally is allowed on port 8098).

## Operational note

The reported HTTP 426 is produced by the PCGA Diagnostics API itself, not Jellyfin. If the upgrade reached Manual Review validation, many deployed components may already be at v0.19.36, but the upgrade's final acceptance step did not complete. Re-run with the corrected v0.19.37 package. The installed Jellyfin data directory and media are not automatically changed by this fix.

## Preservation

All prior v0.19.36 stream-aware duplicate tooling, quarantine and restore workflows, seven-day purge safeguards, and optical disk-space reserve protection are retained. The updater does not initiate deduplication.
