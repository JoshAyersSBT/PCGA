# PC Game Archive v0.19.38 — Live streaming health and Wolf Den relay recovery

## Fixed

- Accept Moonlight Web's bodyless HTTP 200 authentication probe. Host registration and app-list routes still require valid JSON; an authentication HTTP error remains a failure. Endpoint names are included in JSON-format errors so authentication and pairing faults can be distinguished.

- Repacked Linux source files with LF-only line endings. The original Windows-built archive could fail immediately with `set: pipefail: invalid option name`. A reproducible release builder now rejects CR/CRLF and byte-order marks before packaging, verifies the archive against its source bytes and checksum manifest, and Git enforces LF checkouts.

- Detect stale Wolf registrations after DHCP changes even when the saved Moonlight bootstrap state still says `ready`. Check the current LAN address, each lane's default appliance authentication, its live host registration, and actual app-list access with certificate verification and bounded requests.
- Reconcile pairing automatically on the existing authentication timer. Failures remain visible in service logs; game/setup sessions, GameStream control connections, and pending portal launches defer disruptive repair.
- Harden Wolf Den's vendor startup script without rebuilding its image. Replace a stale private relay socket at startup, verify a real API request through that relay, and select the `unix://` URI at the .NET process boundary. Unsupported vendor entrypoints are rejected before installed files change.
- Refresh the portal's loaded TLS certificate and display/API build version during the normal versioned upgrade. Preserve HTTPS-only Diagnostics.
- Require the patch runner's durable completion record before reporting success. A failed or collected transient unit cannot become a false success; an empty patch log falls back to the redacted service journal.

## Upgrade behavior

The `upgrade.sh` entrypoint dispatches to `upgrade_to_v0.19.38.sh`. This is a focused upgrade from v0.19.37; it does not repeat older storage/media migrations or pull images. Bundle hashes, Python regression tests, shell syntax, installed-source compatibility, idle-session checks, and free space are checked before installation. Affected files are backed up under `/var/backups/pc-game-archive/v0.19.38-<UTC timestamp>/`. Startup and live checks trigger restoration on failure.

Game files, Wine prefixes, preservation media, authentication credentials, and SSH access settings are retained. No compatibility claim is inferred from catalog registration alone. Game-specific launch failures and unfinished installers require separate launch testing.

## Validation

Regression cases cover all four independent lanes, saved-ready DHCP drift, changed live registration, missing pairing, malformed app responses, TLS verification failures, invalid lane records, active-session deferral, pending launches, vendor entrypoint compatibility, and idempotent configuration changes.

Upstream references: [Wolf .NET bindings](https://github.com/games-on-whales/GamesOnWhales.Wolf.Net.Bindings), [Wolf Den startup](https://github.com/games-on-whales/wolf-den/blob/stable/WolfLeash/DockerOverlay/entrypoint.sh), [socat Unix socket options](https://manpages.debian.org/trixie/socat/socat.1.en.html).
