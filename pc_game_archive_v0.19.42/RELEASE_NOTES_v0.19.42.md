# PC Game Archive v0.19.42

This is a corrective release for the v0.19.41 NetBird container upgrade. The v0.19.41 installer looked for the word `netbird` across the entire Control Center source, which also contains NetBird Remote Networking actions, and then incorrectly rejected a valid v0.19.40 control plane. The corrected upgrade inspects only the `DOCKER_SERVICES` mapping and the `compose_files` function before applying those small changes.

The release carries forward the dedicated, opt-in NetBird Docker peer from v0.19.41. Its peer identity remains persistent, its setup key is passed through a protected temporary file, and connection readiness requires NetBird's management and startup health checks.

Upgrade from v0.19.40 or v0.19.41 with the standard `upgrade.sh` entrypoint. A failed v0.19.41 attempt stops before the backup and file-write phase, so it should still be safe to retry from v0.19.40. The new installer also accepts v0.19.41 in case that version is already present.
