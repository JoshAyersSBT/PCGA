# PC Game Archive v0.19.37 — Secure Diagnostics Upgrade Fix

Repairs the v0.19.36 upgrade false failure (`curl: (22) HTTP 426` followed by `Jellyfin is missing from the Media diagnostic profile`). PCGA intentionally serves Diagnostics only over HTTPS, but the last upgrader check used the insecure HTTP port. This release requests the secure API and verifies the Media profile in the same response. **Jellyfin, libraries, and media are not reset.**

## Upgrade

```bash
unzip pc_game_archive_v0.19.37.zip
cd pc_game_archive_v0.19.37
sudo ./upgrade.sh
```

See [release notes](RELEASE_NOTES_v0.19.37.md) and [acceptance checklist](ACCEPTANCE_CHECKLIST_v0.19.37.md). All v0.19.36 stream-aware Blu-ray consolidation and low-space protections remain included.
