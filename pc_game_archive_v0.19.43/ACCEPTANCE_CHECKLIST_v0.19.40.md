# Acceptance Checklist — v0.19.40

- [ ] Upgrade an existing v0.19.39 appliance using the versioned ZIP and `upgrade.sh`.
- [ ] Embedded manifest and Linux source checks pass; 1940, 1939 and 1938 regression suites pass.
- [ ] No active game, setup session or pending launch is interrupted.
- [ ] Installer reports its backup directory and restores prior timer activity.
- [ ] Portal and control API report v0.19.40.
- [ ] PCGA game entries and the Heroic launcher are not duplicated; custom apps and other profiles remain present.
- [ ] All four live lane app catalogs match Wolf's effective PCGA profile.
- [ ] A second reconciliation changes no Wolf config bytes and does not restart Wolf.
- [ ] Wolf Den stays running and browser pairing remains healthy.
- [ ] Launch each ready game and confirm video, audio, input, reconnect and clean termination. API readiness alone is not gameplay acceptance.
- [ ] Exercise rollback with a failed live validation and confirm scripts, config, registration state and timers are restored.
