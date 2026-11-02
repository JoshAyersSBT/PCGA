# PC Game Archive v0.19.38 — Live Streaming Health

Repairs appliance-wide game streaming after LAN address changes and hardens Wolf Den's private API relay across restarts. The authentication timer checks the live connection on all four browser lanes instead of trusting a saved ready flag. Repairs wait for active games and pending launches to finish.

## Upgrade

This focused release upgrades an existing **v0.19.37** appliance. It does not rerun historical media migrations, download Docker images, or rebuild game runtimes.

```bash
unzip pc_game_archive_v0.19.38.zip
cd pc_game_archive_v0.19.38
sudo bash ./upgrade.sh
```

The same ZIP can be uploaded under the HTTPS portal's System patch installer. Close game sessions first. The upgrader validates source compatibility and checksums, runs regression tests, backs up changed files under /var/backups/pc-game-archive/, and rolls back if live startup checks fail.

See [release notes](RELEASE_NOTES_v0.19.38.md) and [acceptance checklist](ACCEPTANCE_CHECKLIST_v0.19.38.md). Previous release components and regression fixtures remain included. Historical base/setup scripts are retained as reference; use a v0.19.37 appliance as the starting point for this upgrade.

This release validates streaming infrastructure. A ready connection does not establish that every Windows game is compatible or fully installed.

## Build the release archive

Use the bundled builder to preserve Linux line endings and executable modes and regenerate the embedded checksum manifest:

```bash
python3 tools/build_release.py ../pc_game_archive_v0.19.38.zip
```

The builder rejects CR/CRLF and byte-order marks in release sources, checks Python syntax, and verifies every archived file against the source bytes and manifest before writing the ZIP checksum.
