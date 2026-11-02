# v0.19.38 acceptance checklist

- [ ] Start from v0.19.37 and finish active game/setup sessions before `sudo bash ./upgrade.sh`.
- [ ] SHA-256 manifest validation and streaming regression tests pass before installed files change.
- [ ] The archive's scripts and extensionless components use LF line endings; `bash -n upgrade_to_v0.19.38.sh` succeeds on Linux before running the upgrade.
- [ ] An unsupported vendor entrypoint or live source mismatch aborts without replacing application components.
- [ ] The upgrade prints its backup path and completes with portal/API version 0.19.38.
- [ ] Wolf Den remains running for at least 60 seconds without new restarts or private API relay errors.
- [ ] `sudo /usr/local/sbin/pcga-stream-health` reports `ready: true` for all four lanes using the current address.
- [ ] Each catalog title is visible on all four lanes. Treat an interactive installer as setup, not installed gameplay.
- [ ] A stale registration is detected even while persisted bootstrap state says ready; the authentication timer repairs it while idle.
- [ ] Pairing repair is deferred while a game/setup session or pending portal launch exists.
- [ ] HTTPS Diagnostics still works, and its HTTP endpoint still requires HTTPS.
- [ ] The portal serves the current certificate after recreation and its API/UI report the new version.
- [ ] Test representative installed games separately and inspect fresh runtime logs; do not treat infrastructure checks as gameplay verification.
- [ ] Preserved media, game prefixes, store credentials, and SSH access settings remain intact.
