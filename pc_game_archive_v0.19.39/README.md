# PC Game Archive v0.19.39 — Stable Wolf Catalog

Stops catalog reconciliation from repeatedly restarting Wolf after its TOML writer changes formatting or removes comments. App ownership and equality now use parsed runner settings. Duplicate Heroic launcher entries are consolidated in the PCGA Moonlight profile, and the focused upgrade retries historical comment-marker registration failures once.

## Upgrade

Start from an installed **v0.19.38** appliance. Rerunning v0.19.39 is supported.

```bash
unzip -oq pc_game_archive_v0.19.39.zip
cd pc_game_archive_v0.19.39
sudo bash ./upgrade.sh
```

The standard entrypoint verifies the manifest and runs the catalog, upgrade, streaming-health and packaging regression checks. The installer pauses previously active reconciliation timers, waits for in-flight jobs, and verifies that games and pending launches are idle. It guards the functions being replaced so unrelated local fixes survive.

Changed files, Wolf configuration, game registration state and pending reload records are backed up under `/var/backups/pc-game-archive/v0.19.39-<timestamp>/`. The upgrade reconciles prepared registrations without building runtime images, refreshes browser trust if needed, compares the full app lists on all four live lanes, and requires a second reconciliation to leave both Wolf's config and start time unchanged. It restores previous files/state on validation failure and restores prior timer activity on success or failure.

See [release notes](RELEASE_NOTES_v0.19.39.md) and [acceptance checklist](ACCEPTANCE_CHECKLIST_v0.19.39.md). Historical release scripts remain included as reference; `upgrade.sh` selects the focused v0.19.39 path.

This release repairs backend registration and restart behavior. Gameplay still requires a launch and video/audio/input check for each installed title. Battlefront II remains an interactive setup task.

## Build

```bash
python3 tools/build_release.py ../pc_game_archive_v0.19.39.zip
```

The builder preserves Linux line endings and executable modes, validates Python sources, and verifies every archive entry against its embedded checksum manifest. A separate ZIP checksum is written beside the release.
