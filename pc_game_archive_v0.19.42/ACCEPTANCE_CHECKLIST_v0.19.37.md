# v0.19.37 acceptance checklist

- [ ] Finish active ARM optical ingest before executing `sudo ./upgrade.sh`.
- [ ] The upgrade prints `HTTPS Diagnostics catalog and Media profile validated`, without HTTP 426 / JSONDecodeError.
- [ ] `curl --cacert /etc/pc-game-archive/tls/pcga-ca.crt -sS https://127.0.0.1:8443/api/diagnostics/catalog` returns `ok: true` with Jellyfin in the Media profile.
- [ ] `curl -sS -i http://127.0.0.1:8098/api/diagnostics/catalog` still returns HTTP 426 (security requirement).
- [ ] `curl -i http://127.0.0.1:8096/health` returns HTTP 200; check Jellyfin container and free disk if unavailable.
- [ ] Control Center → Diagnostics → Media lists Jellyfin; log retrieval works over HTTPS.
- [ ] Movies & TV displays films and can play a title.
- [ ] Existing stream-aware duplicate scans and recovery-hold files remain untouched after upgrade.
