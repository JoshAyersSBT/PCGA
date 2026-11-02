# Acceptance Checklist â€” v0.19.40

- [ ] Upgrade an existing v0.19.38 appliance using the versioned ZIP and `upgrade.sh`.
- [ ] Manifest, Linux text format and all 62 focused regression checks pass.
- [ ] No active game/setup session or pending launch is interrupted.
- [ ] Installer reports its backup directory and restores prior timer activity.
- [ ] Portal and control API report v0.19.40.
- [ ] Exactly one Heroic launcher exists in the PCGA profile; custom apps and other profiles remain present.
- [ ] Historical comment-marker failures for prepared games recover; genuine registration failures remain visible.
- [ ] All four live lane app catalogs match Wolf's effective PCGA profile.
- [ ] A second reconciliation changes no Wolf config bytes and does not restart Wolf.
- [ ] Observe at least two game-orchestrator cycles and a Heroic sync cycle after timers resume: Wolf start time stays stable and no duplicate entries return.
- [ ] Wolf Den stays running and browser pairing remains healthy.
- [ ] Launch each ready game and confirm video, audio, input, reconnect and clean termination. Do not count API readiness as gameplay acceptance.
- [ ] Complete Battlefront II's interactive installer separately.
- [ ] Exercise rollback with a failed live validation: prior scripts, config, registration state and timers are restored.
