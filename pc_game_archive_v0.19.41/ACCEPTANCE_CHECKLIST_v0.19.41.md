# Acceptance Checklist — v0.19.41

- [ ] Upgrade an existing v0.19.40 appliance using the versioned ZIP and `upgrade.sh`.
- [ ] The embedded manifest, Linux line endings, Python compilation, and versioned regression suites pass.
- [ ] The upgrade records a backup and restores pre-existing timer activity.
- [ ] Portal and control API report v0.19.41.
- [ ] NetBird installation creates the opt-in container and reports daemon liveness before enrollment.
- [ ] Connecting with a server setup key enrolls the appliance; the setup-key file is removed afterward.
- [ ] NetBird identity survives container restart and reconnects without a saved setup key.
- [ ] Disconnect stops the peer and preserves its identity for intentional reconnect.
- [ ] The thin-client bootstrap does not expose an enrollment key.
- [ ] Existing Wolf catalog validation passes and all four stream lanes remain healthy.
- [ ] A failed live validation restores scripts, game state, Wolf config, portal build and timer activity.
- [ ] From a separately enrolled client peer, verify access to the portal and each Moonlight lane under the intended NetBird policy.
