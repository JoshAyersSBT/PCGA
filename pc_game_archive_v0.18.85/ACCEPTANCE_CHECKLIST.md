# v0.18.85 Noble libMirage source-build acceptance

1. Upgrade does not reinstall COD2, reset Wine prefixes, alter preserved `COD2CD1..COD2CD6` images, or change the validated Wine `D:` filesystem mapping.
2. `libmirage-dev` is no longer a required Noble APT package; an unavailable distro libMirage package cannot block CDEmu bootstrap.
3. The upgrader installs available lower-level libMirage build dependencies independently, including libsndfile, libsamplerate, zlib, bzip2, xz, GLib, and compiler/CMake tooling.
4. `pcga-cdemu-userspace-bootstrap` verifies libMirage 3.3.3 SHA-256 `b480b08230b2255af40c3ac86344c0c77fc996866014e05a69d5554e9035d65b` before extracting or building it.
5. After source installation, `pkg-config --exists libmirage` and `pkg-config --modversion libmirage` succeed before CDEmu daemon configuration begins.
6. Existing VHBA 20260313 DKMS state remains valid and `/dev/vhba_ctl` is not rebuilt unnecessarily when already healthy.
7. Once daemon/client start, CDEmu creates a virtual optical `/dev/srN` in addition to physical drives and COD2 SP maps only Wine `D::` to that device.
8. COD2 Multiplayer remains on base Wine 9, original win32 prefix, and loop-backed ISO media with no CDEmu device.
9. CDEmu userspace failure remains diagnostic/nonfatal to Wolf streaming; SP retains the loop-backed fallback rather than exiting rc=90/91.
10. Cumulative acceptance history, manifest validation, and whitespace-tolerant `legacy-games` validation remain intact.

# v0.18.84 Noble-safe CDEmu/VHBA acceptance

1. Upgrade does not reinstall COD2, reset either Wine prefix, modify preserved `COD2CD1..COD2CD6` images, or change the validated Wine `D:` filesystem mapping.
2. The upgrader stops/disables `pcga-cdemu.service` before host repair and the installed service contains `Restart=no`; a missing VHBA module cannot create a five-second restart storm.
3. `dkms` and `linux-headers-$(uname -r)` are installed independently of optional CDEmu distro packages. An unavailable `cdemu-client`, `cdemu-daemon`, or `vhba-dkms` package cannot prevent DKMS installation.
4. `/usr/local/sbin/pcga-cdemu-userspace-bootstrap` is installed. If CDEmu distro packages are unavailable, it verifies the pinned CDEmu 3.3.0 daemon/client SHA-256 values before building and installing userspace under `/usr`.
5. `/usr/local/sbin/pcga-cdemu-bootstrap --repair` can use pinned VHBA 20260313 through DKMS to build for the running kernel; normal service starts remain network-free.
6. The service is enabled only when `cdemu`, `cdemu-daemon`, and character device `/dev/vhba_ctl` all exist. Otherwise it remains disabled and SP retains nonfatal loop-backed fallback.
7. When CDEmu is healthy, COD2 state records `runtime_cdemu_optical.status=ready`, the preserved `COD2CD1` image path, and its `/dev/srN`/`/dev/sgN` mapping.
8. Healthy COD2 SP keeps the existing `COD2CD1` mount as Wine `D:` and maps only `D::` to the CDEmu virtual CD-ROM.
9. The CDEmu `/dev/srN` and `/dev/sgN` are passed only to the `singleplayer` Wolf app. COD2 Multiplayer remains on base Wine 9, the installer-created win32 prefix, and the existing loop-backed ISO mapping.
10. If CDEmu remains unavailable, SP logs the host failure and uses the proven ISO loop device instead of exiting rc=90/91 or tearing down Wolf/Moonlight.
11. `pcga-cdemu.service` remains present in Streaming diagnostics with module/DKMS/journal context.
12. The cumulative acceptance history and whitespace-tolerant `legacy-games` validator remain intact.

## Historical v0.18.82 acceptance

1. Upgrade does not reinstall COD2, reset either Wine prefix, or modify the preserved `COD2CD1..COD2CD6` images.
2. `pcga-cdemu.service` loads VHBA and exposes one CDEmu virtual optical device on the host system bus.
3. COD2 state records `runtime_cdemu_optical.status=ready`, the preserved `COD2CD1` image path, and resolved `/dev/srN` mapping before the SP Wolf profile is reconciled.
4. COD2 SP keeps the existing mounted `COD2CD1` filesystem as Wine `D:` and maps only `D::` to `/dev/pcga-cdemu-cod2`.
5. SP logs `COD2CD1 CDEmu virtual-CD read probe: PASS`, then still reports `COD2CD1` and `DriveType=5` through Wine before launch.
6. The CDEmu `/dev/srN` (and `/dev/sgN` when present) is passed only to the `singleplayer` Wolf app.
7. COD2 multiplayer continues to select `base-image-wine`, uses the installer-created win32 prefix, and retains the v0.18.81 loop-backed optical mapping; no CDEmu dependency is added to MP.
8. Periodic orchestration does not unload/reload device 0 when it already contains the same `COD2CD1` ISO.
9. If CDEmu/VHBA is unavailable, SP fails with a focused PCGA media diagnostic while MP remains available.
10. The cumulative acceptance history and whitespace-tolerant `legacy-games` validator remain intact.

# v0.18.81 COD2 ISO-only optical acceptance

1. Upgrading from v0.18.80 does not reset the installed COD2 prefix or modify preserved COD2 ISOs.
2. COD2 state no longer requires `runtime_physical_auth`; stale physical-auth state is cleared during the upgrade.
3. Wolf receives each preserved ISO mount plus its read-only `/dev/loop*` device; no `/dev/sr*` or `/dev/pcga-physical-auth` device is required.
4. COD2 SP selects the archive slot whose ISO filesystem label is exactly `COD2CD1`, independent of archival slot order.
5. Before Wine launch, the runtime logs `COD2 SP ISO-backed optical D:` and a successful `COD2CD1 ISO loop-device read probe`.
6. Wine reports D: as volume `COD2CD1` and `DriveType=5` before COD2 SP is launched.
7. Multiplayer remains on the preserved-media path and is not forced onto the SP-specific COD2CD1 slot.
8. The `legacy-games` upgrade validator remains whitespace-tolerant.

# v0.18.80 COD2 physical-auth discovery acceptance

1. Upgrade from v0.18.79 without reinstalling Call of Duty 2 or altering preserved `COD2CD1..COD2CD6` images.
2. Insert the original physical disc labelled `COD2CD1` into any drive listed in `/etc/pc-game-archive/media-drives` (or a discovered `/dev/sr*`).
3. While optical preservation is active, COD2 state records physical-auth status `busy` rather than silently falling back to the cooked ISO.
4. After optical ingest becomes idle, the orchestrator resolves the disc label from the persisted optical-dispatch record, udev, or blkid and records `runtime_physical_auth.status=ready`.
5. Wolf receives both the read-only physical mount and `/dev/pcga-physical-auth`, plus the physical device's host group GID in `GroupAdd`.
6. COD2 SP logs the physical device node, passes a raw 2048-byte read probe, and maps D:/D:: to `/pcga-physical-auth` + `/dev/pcga-physical-auth` before Wine volume validation.
7. If the physical disc is absent or still busy, COD2 SP exits with PCGA code 88 and an explicit insert/wait diagnostic instead of launching against the preservation ISO and showing the game's generic disc dialog.
8. Multiplayer remains on the normal preserved-media path.
9. The `legacy-games` upgrader validation accepts compact or spaced JSON (`"NetworkMode":"legacy-games"` and `"NetworkMode": "legacy-games"`).
10. `ACCEPTANCE_CHECKLIST.md` retains cumulative historical acceptance criteria rather than replacing them with only the current release section.

# v0.18.79 COD2 physical-auth acceptance

1. Preserve the installed COD2 prefix and six archived optical images.
2. Insert the original disc whose filesystem label is exactly `COD2CD1` into a server optical drive.
3. PCGA may use that original disc read-only for the SP SafeDisc authentication experiment; the archived ISO remains authoritative for installation and preservation.
4. Multiplayer does not remap D: to the physical-auth device.
5. Removing the physical disc never deletes or changes preserved media.

# v0.18.78 COD2 Wine 11 optical-drive mapping acceptance

- [ ] Upgrade leaves the installed COD2 Wine 9/win32 prefix and all preserved media untouched.
- [ ] COD2 SP selects `portable-wow64-11.19` and uses the persistent runner-owned `#arch=win64` prefix.
- [ ] Runtime publishes D: to `/pcga-media/disc2` and D:: to `/dev/pcga-media-disc2` for the current COD2 set.
- [ ] After publishing D:/D::, runtime logs `refreshing wineserver after runtime D: optical mapping` before any final D: probe.
- [ ] `wine cmd /c vol D:` reports `COD2CD1` rather than an unlabeled `0000-0000` volume.
- [ ] Win32 logical-disk probing reports D: as `DriveType 5`.
- [ ] COD2 SP refuses launch with exit 81/82 if either the expected volume label or CD-ROM drive type is missing.
- [ ] Original-media `SECDRV.SYS` staging occurs only after optical validation succeeds.
- [ ] Multiplayer remains on base Wine 9 and setup remains unchanged.
- [ ] Generated runtime startup passes `bash -n`; Python components compile with SyntaxWarning fatal; manifest and ZIP integrity pass.

## Previous release acceptance

# v0.18.77 COD2 portable Wine runner acceptance

- [ ] Upgrading an already-installed COD2 title does not reset or delete its Wine 9/win32 install prefix.
- [ ] COD2 runtime image requests runner `portable-wow64-11.19`.
- [ ] Generated Dockerfile downloads `wine-11.19-amd64-wow64.tar.xz` from the pinned release URL.
- [ ] Docker build validates SHA-256 `a1fe858b45d12c9b16b91c7601d9b934f68430f7b6b95e240212ab6e2a198d8a`.
- [ ] Accepted isolated image contains `/opt/wine-11.19-amd64-wow64/bin/wine` and `wineserver`; `wine --version` reports 11.19.
- [ ] COD2 SP creates/uses a runner-owned WoW64 prefix and logs `selected=portable-wow64-11.19`.
- [ ] COD2 MP continues to use base Wine 9 and the preserved installer-created win32 prefix.
- [ ] Original-media `SECDRV.SYS`, the scoped XP override, and COD2CD1 optical presentation remain active for SP.
- [ ] If the portable runner build fails, COD2 remains installed and receives base-Wine fallback with `runtime_build_log` preserved.

- [ ] Upgrade does not add a WineHQ repository or Wine package to the PCGA host; portable runner content exists only inside the COD2 image.
- [ ] Upgrade from v0.18.74 does not reset a READY COD2 prefix or preserved optical media.
- [ ] A completed COD2 setup session writes `.pcga-install-complete` and closes the obsolete Flash/OLE shell without leaving the portal on an apparent installer crash.
- [ ] OLE recognition accepts Shockwave CLSID `{D27CDB6E-AE6D-11CF-96B8-444553540000}`, `0x80040154`, `REGDB_E_CLASSNOTREG`, and `CLASS_E_CLASSNOTAVAILABLE`.
- [ ] COD2 Single-player leaves the installed `#arch=win32` prefix unchanged.
- [ ] SP finds `SECDRV.SYS` on preserved COD2 media and logs the staged original-media driver SHA-256.
- [ ] The staged driver is present under `windows/system32/drivers` and `windows/syswow64/drivers` in the active SP prefix.
- [ ] `CoD2SP_s.exe` receives the Wine AppDefaults Windows version override `winxp`; MP does not.
- [ ] If isolated-prefix creation fails, SP falls back to base Wine without modifying or deleting the installed prefix.
- [ ] A remaining `ZwLoadDriver(SecDrv)` failure is persisted as a legacy-DRM failure and the empty stream closes instead of hanging on black.

## Previous release acceptance

- Upgrade completes without changing host `/usr/bin/wine` packages or APT sources.
- COD2 state remains `ready` with the existing `#arch=win32` prefix and preserved runtime-media records.
- Multiplayer remains launchable as the explicit alternate variant.
- If single-player still fails at SecDrv, `runtime-logs/last-failure.json` is written and the black compositor grace period is skipped.

# v0.18.72 focused acceptance

- [ ] `pcga-game-compat-resolver` returns the appliance-owned `cod2-retail-safedisc-win32-prefix` rule for canonical **Call of Duty 2** / Steam AppID 2630 and records `wine_arch=win32`, `legacy_drm=safedisc-4.60-secdrv`, and expected label `COD2CD1`.
- [ ] A ready COD2 install whose `prefix/system.reg` contains `#arch=win64` is migrated exactly once to `setup-required` with `setup_reason=cod2-win32-prefix-migration`; preserved source/runtime-media records are not deleted.
- [ ] That migration clears the mutable prefix and stale game runtime image, assigns a new install generation, and rebuilds/reuses the existing synthetic COD2DVD setup source from preserved COD2CD1..COD2CD6 media.
- [ ] Interactive setup exports `WINEARCH=win32` only while creating the fresh prefix, then verifies the rebuilt prefix contains `#arch=win32` before launching COD2 setup.
- [ ] A normal COD2 runtime logs `Wine prefix architecture: existing=win32 required=win32` and refuses mismatched prefixes with exit 87 before starting the game executable.
- [ ] COD2 startup logs the SafeDisc 4.60/SecDrv compatibility path without modifying or replacing the original game executable.
- [ ] If `CoD2SP_s.exe` exits nonzero with `ZwLoadDriver ... SecDrv ... c0000142`, the persisted runtime log emits the focused COD2 SafeDisc diagnostic.
- [ ] v0.18.71 SP/MP launch variants remain intact, with single-player default and multiplayer selectable independently.
- [ ] Generated setup and game runtime startup scripts pass `bash -n`; Python components pass `python3 -W error::SyntaxWarning -m py_compile`; manifest and ZIP integrity pass.

---

# v0.18.71 focused acceptance

- [ ] A ready install containing a conservative same-family SP/MP pair records exactly two `launch_variants` with stable keys, labels, executable paths, and one default.
- [ ] COD2 detects `CoD2SP_s.exe` as `singleplayer` and `CoD2MP_s.exe` as `multiplayer`, while keeping single-player as the default selected executable.
- [ ] Titles without a matched same-directory SP/MP family continue to expose one ordinary Play action and do not receive invented variants.
- [ ] The generated runtime startup script selects the requested executable from `PCGA_LAUNCH_VARIANT`, rejects unknown keys, and passes `bash -n`.
- [ ] Wolf TOML contains the stable default app plus a unique non-default app for each alternate variant; generated TOML parses successfully and each app carries `PCGA_GAME_SET_ID` plus its launch variant.
- [ ] The library card shows **Choose mode** for multi-launch titles; the detail modal exposes separate Play buttons and sends the selected `variant` through the stream endpoint.
- [ ] Stream reservations and active-session ownership preserve `launch_variant`; Resume reconnects to the same Wolf app rather than the default app.
- [ ] Existing ready installs migrate through `launch_variant_detection_v01871` without deleting the install prefix or preserved media.
- [ ] Shell syntax, Python `SyntaxWarning`-fatal compilation, YAML parsing, portal JavaScript syntax, focused variant discovery/runtime/TOML/API tests, manifest verification, clean-extraction verification, and ZIP integrity pass.

---

# v0.18.70 focused acceptance

- [ ] A completed COD2 install containing both `CoD2SP_s.exe` and `CoD2MP_s.exe`, `mss32.dll`, and multiple `main/*.iwd` files is not forced to rerun setup merely because the retail post-install launcher reports `OLE error 80040154`.
- [ ] The setup log identifies `{D27CDB6E-AE6D-11CF-96B8-444553540000}` as the failing legacy shell signature before any bypass occurs.
- [ ] The setup runtime requires the strict direct-payload probe for three consecutive checks before it terminates the obsolete shell and writes `.pcga-install-complete`.
- [ ] PCGA does not install/download Flash or register a replacement ActiveX control.
- [ ] After the setup container ends, an existing v0.18.69 prefix with the validated payload plus the recorded Flash failure is promoted without reinstalling; `cod2_flash_launcher_bypassed_v01870=true` is recorded.
- [ ] The finalized title selects `CoD2SP_s.exe` ahead of `CoD2MP_s.exe` for its default Play action.
- [ ] v0.18.69 Wolf reload quarantine, v0.18.68 mount-safe staging, and v0.18.67 COD2DVD D:/D:: registration remain intact.
- [ ] Shell syntax, Python `SyntaxWarning`-fatal compilation, YAML parsing, generated COD2 setup Bash validation, host recovery simulation, manifest verification, and ZIP integrity pass.

---

# v0.18.69 focused acceptance

- [ ] With two pending Wolf app registrations, if one app survives reload and another is removed by Wolf after both the initial reload and the single repair restart, the surviving app becomes `ready` / `setup-ready`.
- [ ] The rejected app becomes `stream_state=failed` with `wolf_registration_quarantined_v01869=true` and a visible per-title diagnostic.
- [ ] `wolf-restart-pending.json` is cleared after quarantine; the next periodic orchestrator pass must perform **zero** Wolf restarts solely because of the rejected app.
- [ ] The full-catalog Wolf repair pass skips quarantined titles and does not silently re-arm the restart loop.
- [ ] Portal **Retry stream** invokes a forced metadata-only Wolf reconciliation for the selected title, clearing only that title's quarantine for one explicit retry.
- [ ] COD2 remains registered independently of the quarantined Jedi Outcast entry and can reach a stable Moonlight/Wolf launch attempt without once-per-minute Wolf SIGTERM churn.
- [ ] Shell syntax, Python `SyntaxWarning`-fatal compilation, YAML parsing, the focused Wolf-rejection regression test, manifest verification, and ZIP integrity pass.

---

# v0.18.68 focused acceptance

- `pcga-game-orchestrator.service` must complete successfully after COD2 reconciliation; the prior `Read-only file system: '00000001.TMP'` loop must not recur.
- If `install_root/setup-source` is an exact mountpoint, generic staging must unmount it before `shutil.rmtree()` or return `setup-source-busy`; it must never recursively delete a live optical mount.
- A COD2 state left `failed` by the v0.18.67 EROFS regression must recover automatically to `setup-required` and remain eligible for Wolf setup-app registration.
- COD2 reinstall must not proceed when `_cleanup_cod2_synthetic_setup_media()` reports a busy mount.
- A valid `setup_source_multidisc_optical_v01866` COD2 state must skip generic setup-source restaging/reselection and retain the verified synthetic `COD2DVD` source.
- Any uncaught per-game orchestrator exception must emit `orchestrator traceback:` lines in the journal.
- Existing v0.18.67 D:/D:: wineserver refresh diagnostics and v0.18.66 Media-table/ISO checks must remain present.

---

# v0.18.68 focused acceptance

- [ ] Upgrade from v0.18.66 with the black COD2 setup stream / `D: optical-media probe cannot find D:\Setup\Data\main\iw_02.iwd` failure.
- [ ] Setup log shows `refreshing wineserver before COD2 D: optical mapping`.
- [ ] Setup log shows D: -> `/pcga-source` and D:: -> `/dev/pcga-setup-media`, followed by `DOS-device symlink payload probe found D:/Setup/Data/main/iw_02.iwd`.
- [ ] Setup log shows `restarting wineserver after COD2 D: optical registration`.
- [ ] Windows-side `D:\Setup\Data\main\iw_02.iwd` probe succeeds, `vol D:` reports `COD2DVD`, and DriveType is `5`.
- [ ] `D:\setup.exe` reaches the InstallShield wizard instead of leaving only the black Sway desktop.
- [ ] No `/tmp/pcga-disc-switch` helper is generated for the COD2 single-volume setup session; D: remains pinned to COD2DVD while E:..J: retain the six preserved discs.
- [ ] Shell syntax, Python SyntaxWarning-fatal compilation, YAML parsing, generated COD2 prelude syntax, manifest verification, and ZIP integrity pass.

# v0.18.66 focused acceptance

- [ ] Upgrade from the v0.18.65 failure state where the orchestrator logs `Read-only file system: '.windows-label'`.
- [ ] The upgrader removes/detaches only disposable COD2 setup loops from v0.18.63/v0.18.65/v0.18.66; preservation ISOs remain untouched.
- [ ] Exactly one COD2 canonical record is left setup-capable; stale duplicate records remain hidden/superseded.
- [ ] COD2 staging logs never attempt to copy root-level `.windows-label` / `.windows-serial` / stale `.pcga-*` markers from a source disc.
- [ ] The canonical record creates `setup-source-v01866.iso`, mounts it read-only at `setup-source`, and reports volume label `COD2DVD`.
- [ ] The pre-wizard path reaches the optical probes and then `D:\setup.exe`; it must not abort with `OSError: [Errno 30] Read-only file system: '.windows-label'`.
- [ ] If host staging fails, diagnostics include `COD2 staging traceback:` lines naming the failing operation.
- [ ] `vol D:` reports `COD2DVD`, Win32 drive type is `5`, the v0.18.66 Media marker is present, and `D:\Setup\Data\main\iw_02.iwd` is readable before the installer starts.
- [ ] Shell syntax, Python `SyntaxWarning`-fatal compilation, YAML parsing, rendered portal JavaScript checks, manifest verification, and ZIP integrity pass.

# v0.18.64 focused acceptance
## v0.18.64 canonical catalog visibility recovery

- [ ] A visible game-set record whose install-state still has `catalog_hidden=true` or a stale `duplicate_of` is shown in **PC Games** instead of disappearing.
- [ ] The next orchestrator reconciliation clears those stale state flags for the visible canonical UUID.
- [ ] A hidden/superseded sibling state with a stale setup/runtime image cannot steal canonical status merely because the visible title temporarily clears its runtime image during restaging.
- [ ] If a genuinely stronger recoverable installed sibling becomes canonical, its state is unhidden in the same reconciliation pass.
- [ ] Wolf reconciliation no longer skips a visible canonical set solely because of stale install-state visibility flags.
- [ ] The upgrade migration changes only stale catalog visibility fields; preserved ISOs, setup-source ISO, installed payload, and Wine prefix remain untouched.
- [ ] COD2 remains setup-required/available according to its actual state after the card is restored; v0.18.66 does not claim to solve Error 1311.
- [ ] Python `SyntaxWarning`-fatal compilation, shell syntax, YAML, embedded portal JavaScript, manifest verification, and ZIP integrity pass.


- [ ] End any existing COD2 setup session before upgrading; the v0.18.62 child does not have `/dev/pcga-setup-media`.
- [ ] Upgrade to v0.18.66 and allow one game-orchestrator reconciliation cycle. COD2 should remain **SETUP REQUIRED** until the synthetic optical source is staged successfully.
- [ ] Start COD2 installation and confirm setup diagnostics contain `active optical drive D: = genuine synthetic COD2DVD ISO (/dev/pcga-setup-media)`.
- [ ] Confirm `vol D:` reports `COD2DVD`.
- [ ] Confirm `Win32 synthetic-drive probe` reports `D:` with drive type `5` (`DRIVE_CDROM`).
- [ ] Confirm the v0.18.66 Media audit marker is present and its `after` table contains one logical medium labelled `COD2DVD`.
- [ ] Confirm `D:\Setup\Data\main\iw_02.iwd` passes the optical-media probe before the installer GUI opens.
- [ ] Enter the legitimate retail key and continue through file transfer. Error 1311 requesting Call of Duty 2 CD 2 must not recur.
- [ ] If any optical identity check fails, the installer must not launch; diagnostics should emit a `FATAL` line instead of allowing another ambiguous 1311/1603 cycle.
- [ ] After a successful installation, confirm COD2 payload validation finds a game executable, `mss32.dll`, and `main/*.iwd`, then the synthetic setup ISO is unmounted and removed while all six preserved source images remain unchanged.

# v0.18.62 focused acceptance

- [ ] End any currently running COD2 setup session before upgrading so no v0.18.61 container keeps the stale source mounted.
- [ ] Upgrade and allow one reconciliation pass. The orchestrator must no longer report `COD2.msi still contains non-merged Media.VolumeLabel values: ['COD2CD3', 'COD2CD5']`.
- [ ] State records `setup_source_multidisc_merged_v01862=true` and `setup_source_msi_media_flattened_v01862` after successful staging.
- [ ] The staged tree contains `.pcga-msi-media-flattened-v01862.json`. Its `after` table has one row for cabinet-less COD2, and both `DiskPrompt` and `VolumeLabel` equal the merged CD1 label.
- [ ] Start COD2 Install. Setup diagnostics contain `COD2 MSI Media single-volume flatten marker present`, the Media audit, and `Windows installer source forced to D:\setup.exe`.
- [ ] No legacy/runtime merge fallback is used. If host staging ever fails verification, the installer must not launch; diagnostics should say the validated host-staged source is unavailable.
- [ ] Continue through the CD-key and file-transfer stages with AUTO selected. The previous `1603` / `1311` media-boundary failures should not recur.
- [ ] After setup completes, COD2 payload validation finds a game executable, `mss32.dll`, and `main/*.iwd` before READY promotion.
- [ ] Launch the game; only then evaluate the independent `[pcga-graphics]` DXVK/WineD3D path.

# v0.18.61 focused acceptance (historical)

- [x] Removed the injected InstallShield `/v` argument that caused error 1629.
- [x] Preserved explicit `D:\setup.exe` launch and command-line-neutral MSI tracing.
- [ ] Superseded for COD2 media staging by v0.18.62 because v0.18.61's SQL Media-table rewrite failed verification while leaving the stale source runnable.

# v0.18.58 focused acceptance (historical)

- [ ] End the current v0.18.57 COD2 setup session before upgrading; an already-running MSI cannot acquire the rewritten Media table.
- [ ] Upgrade to v0.18.58 and allow reconciliation to restage COD2 with `setup_source_multidisc_merged_v01858=true` and `setup_source_msi_media_flattened_v01858` populated.
- [ ] Start **Install** for Call of Duty 2 and confirm the setup log contains `COD2 MSI Media single-volume flatten marker present`.
- [ ] Confirm the following `COD2 MSI Media audit:` shows the original multi-row Media table and an `after` table with a single row for a cabinet-less COD2 MSI; its `LastSequence` must equal the maximum original sequence.
- [ ] Confirm the pre-GUI probes find `iw_02.iwd` through both `Z:\pcga-source` and `D:\Setup\Data\main\iw_02.iwd`.
- [ ] Enter the legitimate retail key and continue through file transfer without pressing the 1..6 buttons. The **Error 1311 / Call of Duty 2 CD 2** prompt must not recur.
- [ ] While setup is active, confirm the catalog does not promote COD2 to READY simply because a partial game executable exists.
- [ ] After setup exits successfully, confirm `.pcga-install-complete` is present, COD2 promotes to READY, and the disposable setup source can be cleaned without changing preserved ISO images.
- [ ] Launch COD2 and validate the independent `[pcga-graphics]` DXVK/WineD3D runtime path.

# v0.18.57 focused acceptance (historical)

- [ ] End the current v0.18.56 COD2 setup session before upgrading; its already-running MSI still contains the original six `Media.VolumeLabel` values.
- [ ] Upgrade to v0.18.57 and allow reconciliation to restage COD2 once with `setup_source_multidisc_merged_v01857=true` and `setup_source_msi_media_normalized_v01857` populated.
- [ ] Confirm `msiinfo` and `msibuild` are installed on the host.
- [ ] Start **Install** for Call of Duty 2 and confirm the setup log contains `COD2 MSI Media.VolumeLabel normalization marker present`.
- [ ] Confirm the pre-GUI probes find `iw_02.iwd` through both `Z:\pcga-source` and `D:\Setup\Data\main\iw_02.iwd`.
- [ ] Confirm the D: diagnostics no longer show the v0.18.56 `Invalid function` result and that D: is reported as a CD-ROM backed by the staged merged source.
- [ ] Enter the legitimate retail key and continue through file transfer without pressing the 1..6 buttons. The **Error 1311 / Call of Duty 2 CD 2** prompt must not recur.
- [ ] If setup reaches later physical-disc boundaries, it should continue automatically from the merged source rather than requesting CD3..CD6.
- [ ] After installation completes, confirm PCGA promotes the installed executable and removes the disposable setup-source without changing any preserved ISO.
- [ ] Launch COD2 and then validate the independent `[pcga-graphics]` DXVK/WineD3D runtime path.

# v0.18.56 focused acceptance (historical)

- [x] Host staging eliminated the unprivileged `/pcga-media/discN` traversal failure.
- [x] `Z:\pcga-source\Setup\Data\main\iw_02.iwd` became readable and the installer crossed the original `1603`/file-copy boundary.
- [ ] v0.18.56 still failed at the next MSI media transition with Error 1311 for Call of Duty 2 CD 2; v0.18.57 supersedes this check.

# v0.18.55 focused acceptance

- [ ] Open Portal Settings → PC Games and confirm **Direct3D graphics backend** defaults to `Automatic — DXVK when available`.
- [ ] Launch a D3D9-era title such as COD2, Battlefront II, or Empire at War on Vulkan-capable hardware and confirm `runtime-logs/session.log` contains `[pcga-graphics] Vulkan available` followed by `backend=dxvk verb=dxvk2062`.
- [ ] Confirm the DXVK log line includes a `d3d9` native DLL override after first-time provisioning.
- [ ] Temporarily set `PCGA_DXVK_HUD=1` in `/etc/pc-game-archive/game-runtime.env`, relaunch a Direct3D title, and confirm the DXVK device/FPS HUD appears; restore the setting to `0` afterward.
- [ ] On a host without hardware Vulkan 1.3, or when the only Vulkan device is Lavapipe/llvmpipe, confirm the session logs a `[pcga-graphics] ... falling back to WineD3D` reason and still attempts the title instead of aborting the session.
- [ ] Confirm an OpenGL title such as Jedi Outcast is unaffected by the DXVK override path.
- [ ] Confirm DirectDraw-era titles remain on WineD3D and do not depend on DXVK.
- [ ] Re-run the v0.18.54 COD2 install test: merged six-CD setup media and the InstallShield virtual desktop still function independently of the game graphics backend.

# v0.18.54 focused acceptance

- [ ] End the current failed COD2 setup session before upgrading; the old container cannot acquire the new merged-media mapping.
- [ ] Upgrade to v0.18.57, launch **Install** from the canonical Call of Duty 2 card, and confirm the setup log contains `COD2 staged merged setup source:`.
- [ ] Confirm the same log contains successful host-staged, MSI SourceDir, and D: probes for `iw_02.iwd` before the installer GUI starts.
- [ ] Enter the legitimate retail key and advance beyond the key-code screen. The previous `Feature transfer error / -1603` must not occur at the first payload-copy boundary.
- [ ] Allow setup to continue without manually pressing the 1..6 disc buttons. The host-staged setup source should make all six CDs available through both MSI SourceDir (`Z:\\pcga-source`) and stable D:.
- [ ] If a later media prompt appears, capture Streaming diagnostics before manually switching discs; the log should include the recovered `COD2CDn` slot mapping and active merged-media state.
- [ ] Verify E:..J: remain mounted as the six individual preserved discs and that no source ISO was modified.

## v0.18.53 regression checks

- [ ] End any pre-v0.18.53 COD2 setup session before upgrading, then launch **Install** again from the canonical Call of Duty 2 card.
- [ ] `pcga-setup-session.log` contains `launch mode: Wine virtual desktop PCGASetup,1920x1080` before the installer UI appears.
- [ ] During pointer movement/clicks through the installer, repeated wlroots `No free output buffer slot` bursts are eliminated or materially reduced by the setup-only software-cursor path.
- [ ] The browser stream shows one Wine desktop containing the InstallShield UI rather than independent top-level installer surfaces managed by Sway.
- [ ] Enter the COD2 key, press **Next**, and confirm any validation/confirmation dialog is visible and interactive inside the Wine desktop; the key-code parent must not remain visible but input-blocked by an unseen modal.
- [ ] Continue beyond the key-code step and verify the setup process/container remains alive through the next InstallShield page or file-copy phase.
- [ ] Press **Back**, return to PC Games, and use **Resume setup**; the same installer state returns without allocating a second lane/container.
- [ ] Use **Reconnect video** during the same setup session and verify it rebuilds only the Moonlight browser stream while preserving the Wine virtual desktop and installer state.
- [ ] Normal ready-game launches remain direct Wine game runtimes and do not acquire the `PCGASetup` virtual desktop wrapper.

# v0.18.43 focused acceptance

- [ ] Starting a new game or setup creates a `PCGA-*` child container whose Docker inspect data has `HostConfig.AutoRemove=true`.
- [ ] **PC Games → Sessions → End session** stops the selected Wine desktop and removes the Docker container object; `docker ps -a --filter name=PCGA-...` does not retain it.
- [ ] **End my sessions** only removes sessions owned by that portal client and leaves another client's simultaneous desktop untouched.
- [ ] An already-exited pre-v0.18.43 `PCGA-*` child object is pruned during orchestration and does not block a deferred Wolf reload.
- [ ] A Wine launch that remains alive without ever mapping an Xwayland/Sway game window is terminated after the bounded startup window and its transient container disappears instead of holding a black stream indefinitely.
- [ ] A launcher that hands off to a real child game process remains alive while the child game window exists; after the last game window disappears, stale Wine helpers are boundedly terminated and the child container is removed.
- [ ] Library cards that are merely registered/ready no longer show **Streaming status**. **Play in portal** appears only for playable titles; **Prepare stream** is used for pending reconciliation; actual live desktops appear under **Sessions**.
- [ ] Historical `cod2` and user-metadata `Call of Duty 2` records linked by merge history, RAWG id, preserved media, or the conservative `cod2` acronym alias render as one card.
- [ ] When the raw/working COD2 UUID has the valid launcher and the other UUID has selected RAWG metadata/artwork, the working UUID remains canonical and receives the selected metadata rather than being superseded by the weaker record.
- [ ] Applying metadata from **Find metadata** while viewing the working raw title updates that linked working runtime and does not create a second pretty-but-unplayable card.
- [ ] The profiler has exactly one metadata-apply JavaScript path: select a result, preview it, then **Use selected metadata** successfully commits it.
- [ ] A legacy multi-disc COD2 state marked `portable-copy` is rescanned and returned to setup instead of streaming `portable/Launch.exe`.
- [ ] A genuine single-disc portable title with no existing prefix gets a valid Wine prefix before runtime generation and no longer fails solely with missing `C:\windows`/`kernel32.dll`.
- [ ] A BF2-like disc containing root `Setup.exe`, nested `GameData/Setup.exe`, and an Adobe Reader installer selects the root game bootstrapper unless `autorun.inf` explicitly says otherwise.
- [ ] Run the upgrader under Python 3.12+ and confirm validation emits no `SyntaxWarning: invalid escape sequence` messages; compile all Python components with `-W error::SyntaxWarning`.

# v0.18.40 focused acceptance

- [ ] Open **Find metadata** for an existing PC game and confirm search results can be selected without immediately modifying the local title.
- [ ] Selecting a candidate highlights it and loads a full web-profile preview with title, release/developer/publisher, platforms, genres/tags, description, ratings, source link, and artwork when RAWG supplies them.
- [ ] No canonical title fields change until **Use selected metadata** is pressed.
- [ ] Applying the selected candidate updates the intended game-set UUID and retains preserved disc ownership/fingerprints and install/runtime state.
- [ ] Searching `COD2CD1` includes a cleaned `COD2` search variant while retaining the original exact query.
- [ ] Searching `setupBF2` includes `setup BF2` and `BF2` variants and can surface a Battlefield 2 candidate even if an unrelated setup-named result is returned by the exact query.
- [ ] A few poor precise-PC results do not prevent broader PC/global candidates from appearing.
- [ ] Duplicate RAWG records returned by several search passes appear only once and are ordered by PCGA match score.
- [ ] Pasting a valid RAWG game URL or numeric RAWG game ID returns that record as a direct candidate.
- [ ] Reopening Settings does not expose or clear the stored RAWG API key; the browser still receives configuration state only.

# v0.18.39 focused acceptance

- [ ] Launch the current COD2 canonical card and confirm the runtime no longer exits before Wine with `cp: cannot access '/pcga-template/./portable': Permission denied`.
- [ ] When both a portable-copy COD2 record and a completed installed-prefix COD2 record exist, duplicate reconciliation selects the recoverable installed prefix as canonical when it contains a valid game executable.
- [ ] A stale COD2 state pointing at `Common Files/InstallShield/.../IDriver.exe` is repaired to a real installed game executable or demoted to setup-required; `IDriver.exe` is never streamed as the game.
- [ ] Launch the Empire at War / Forces of Corruption title and confirm diagnostics do not show `launching fpupdate.exe`; the selected target is a direct game executable such as `swfoc.exe`, `sweaw.exe`, or `starwarsg.exe` when present.
- [ ] `syscheck`, `fpupdate`, updater/patch/config helpers and similar executable stems are treated as weak identity evidence and cannot become permanent customer-facing game titles solely from file discovery.
- [ ] For a normal single-title disc whose metadata contains `source_path=GameData`, installer discovery scans the disc root. A root `autorun.inf`/`setup.exe` outranks a nested `GameData/Setup.exe`.
- [ ] An already-staged setup session created from a non-compilation `GameData` subpath is restaged from the preserved disc root without changing the ISO/BIN/checksum artifacts.
- [ ] If an interactive installer reports `Wine Mono is not installed`, diagnostics show one bounded managed-runtime provisioning attempt and at most one automatic installer retry.
- [ ] User-confirmed distinct editions remain separate cards, while conflicting auto-derived edition strings do not prevent duplicate UUID consolidation.
- [ ] Upgrade runs a local/no-network repair pass before completion and leaves active preservation data intact.

# v0.18.38 focused acceptance

- [ ] Open **PC Games** after upgrade and confirm repeated `cod2` / `setupBF2` records collapse to one canonical card per title rather than one card per install/source UUID.
- [ ] The canonical card reports the number of consolidated records when more than one historical PCGA record exists.
- [ ] `journalctl -u pcga-game-orchestrator.service` reports duplicate-title consolidation once, and subsequent runs do not recreate the superseded Wolf app profiles.
- [ ] Two optical drives completing different discs of one game concurrently reuse a single game-set UUID.
- [ ] Labels such as `COD2CD1` and `COD2CD2` are recognized as discs in the `COD2` family, while `COD2` itself remains the sequel title.
- [ ] A previously failing portable runtime no longer logs `cp: cannot access '/pcga-template/./portable': Permission denied`.
- [ ] An installed prefix whose apparent targets are InstallShield `Common Files/.../IDriver.exe` or a `CDKey.exe` utility is not promoted with those helpers; PCGA either finds the real game executable or returns the title to setup.
- [ ] Existing preserved ISOs, checksums, and superseded install prefixes remain present after catalog reconciliation.

# v0.18.37 focused acceptance

- [ ] `systemctl start pcga-network-identity.service` succeeds when `/var/lib/pc-game-archive/bootstrap/secure-context.json` contains `lan_ip`, `certificate_reissued`, and `lan_ip_changed`.
- [ ] A secure-context state equivalent to `192.168.4.31 / false / false` is parsed as three fields rather than the literal string `192.168.4.31 0 0`.
- [ ] `/var/lib/pc-game-archive/bootstrap/network-identity.json` reports `state: ready` and the current DHCP-selected IP.
- [ ] Existing v0.18.36 leaf certificate/CA files are reused when their SANs already match the current address.
- [ ] `pcga-game-stack.service`, `pcga-lan-dns.service`, and `pcga-thin-client-bootstrap.service` start normally after the identity oneshot completes.

# v0.18.36 focused acceptance

- [ ] Set `/opt/pc-game-archive/.env` `PCGA_LAN_IP` to an intentionally stale LAN address, reboot with a different DHCP lease, and confirm the value is automatically replaced with the current default-route IPv4 address.
- [ ] `systemctl status pcga-network-identity.service` reports a successful oneshot before `pcga-game-stack.service`, `pcga-lan-dns.service`, and `pcga-thin-client-bootstrap.service` start.
- [ ] `/var/lib/pc-game-archive/bootstrap/network-identity.json` records the previous and current addresses and marks `lan_ip_changed: true` for the DHCP move.
- [ ] The trusted `/etc/pc-game-archive/tls/pcga-ca.crt` fingerprint is unchanged across the DHCP move.
- [ ] `/etc/pc-game-archive/tls/pcga-server.crt` contains `DNS:pcga.portal` and `IP Address:<current DHCP address>` after startup.
- [ ] `docker inspect pcga-moonlight-web{,-2,-3,-4}` shows `WEBRTC_NAT_1TO1_HOST=<current DHCP address>` on all four lanes.
- [ ] `docker inspect wolf` shows `WOLF_INTERNAL_IP=<current DHCP address>` after game-stack reconciliation.
- [ ] A previously trusted secure client reconnects after the address change without importing a new PCGA CA certificate.
- [ ] `pcga.portal`/`pcga.local` resolve to the new address after boot when the corresponding PCGA DNS/mDNS path is enabled.
- [ ] Reboot again without changing the DHCP address and confirm the leaf certificate and Moonlight containers are not unnecessarily regenerated/recreated.

# v0.18.35 focused acceptance

- [ ] A staged source containing both `COD2.msi` and root `setup.exe` selects `setup.exe`; an MSI-only source still selects the MSI.
- [ ] An existing setup-required state whose `setup_installer` is an MSI is repaired to the higher-level executable bootstrapper without modifying preserved media.
- [ ] A 3-disc title opens an interactive setup stream with Disc 1 active and renders Disc 1/2/3 controls in the stream toolbar.
- [ ] Switching to Disc 2 changes only the selected owned runtime's Wine `D:` mapping; a second client's session remains on its own active disc.
- [ ] Ending/relaunching setup does not lose title disc ownership, fingerprints, or the staged setup source.

# v0.18.33 acceptance checklist

## Multiple Wine desktops owned by one portal client

- [ ] From one HTTPS PCGA portal browser, launch a ready PC game and confirm the stream toolbar identifies lane 1.
- [ ] Press **Back** and confirm the first Wine/Wolf runtime remains active rather than being terminated or unloaded.
- [ ] From the same browser, launch a second ready PC game (or a second instance where supported) and confirm a second stream tab appears on a different lane.
- [ ] Switch between the stream tabs and confirm both Wine desktops remain live with independent keyboard/gamepad/video streams.
- [ ] Repeat up to four concurrent sessions and confirm lanes 8101, 8102, 8103, and 8104 are independently reachable and paired.
- [ ] A fifth concurrent launch fails cleanly with a no-free-stream-lane message and does not disturb the four running sessions.
- [ ] **End session** in the stream toolbar terminates only the selected runtime and leaves the other tabs/sessions running.
- [ ] **PC Games → Sessions** lists only runtimes owned by the current portal-client ID and shows their lane numbers.
- [ ] **End my sessions** terminates all sessions owned by the current portal client without selecting another client's sessions.
- [ ] Open the portal in a second browser/profile, launch a game, and confirm the first browser's session manager neither lists nor can stop the second browser's runtime.
- [ ] `/var/lib/pc-game-archive/game-runtime/session-owners.json` maps each claimed runtime to a `client_id`, `lane`, and `reservation_id`, and dead containers are pruned on reconciliation.
- [ ] A launch abandoned before Wolf creates a runtime releases its pending reservation when End Session is requested or automatically expires it after the bounded reservation lifetime.
- [ ] Reboot/restart the game stack and confirm all four `pcga-moonlight-web*` containers start and `/var/lib/pc-game-archive/bootstrap/moonlight-web.json` reports `lane_count: 4` with every lane ready.
- [ ] With PCGA Remote Access enabled, Tailscale Serve exposes the secure portal and Moonlight Web lanes on 8101–8104.

## Preserved PC-game disc inventory and manual ownership

- [ ] **PC Games → Disc images** lists preserved ISO/BIN bundles even when automatic title assignment is wrong or absent.
- [ ] Each disc entry shows its fingerprint, volume label when available, image format/size, preserved bundle path, current owner, disc number/count, and role.
- [ ] A disc can be reassigned to an existing PC game title from the portal without modifying the ISO/BIN payload or `SHA256SUMS`.
- [ ] Reassignment updates `/var/lib/pc-game-archive/game-intake/discs/<fingerprint>.json` and every matching preserved `.pcga-game.json` sidecar.
- [ ] The disc disappears from the previous title's `media.discs` inventory and appears in the newly selected title's `optical-disc-set`.
- [ ] Disc number, disc count, and role entered in the portal survive a subsequent metadata/orchestrator rescan.
- [ ] A missing title can be created from the disc assignment view and immediately selected as the image owner.
- [ ] A preserved image that has `.pcga-optical.json` but no canonical game-disc record is still visible and can be materialized into a canonical record by manual assignment.
- [ ] Reassigning metadata never deletes a preserved copy, changes the optical fingerprint, or rewrites the disc image.


## Fresh Wine GUI generation after headless probes

- [ ] A Jedi Outcast runtime that performs `wine reg` / `wine cmd` media checks before Sway later logs `[pcga-wine-session] resetting pre-compositor Wine helpers before GUI launch` after `Xwayland ready`.
- [ ] After the reset, the wrapper logs `Wine GUI launch boundary ready` with the active `DISPLAY` before applying the Jedi process environment or launching `jk2sp.exe`.
- [ ] `xset -display "$DISPLAY" q` is rechecked after the wineserver reset when `xset` is available; failure exits rc=71 instead of starting Wine into a black stream.
- [ ] A fresh Jedi Outcast launch no longer reports `nodrv_CreateWindow` after the Xwayland-ready line.
- [ ] Interactive setup sessions perform the same pre-compositor wineserver reset before the installer GUI starts.
- [ ] The reset does not remove the `JEDIOUTCAST` drive mapping, installed prefix, saves, or compatibility profile.

## Xwayland launch-readiness

- [ ] A fresh direct Wine game launch logs `[pcga-wine-session] waiting for Xwayland` before Wine is invoked.
- [ ] When Sway supplies `DISPLAY`, PCGA waits for the corresponding `/tmp/.X11-unix/X*` socket instead of immediately starting Wine.
- [ ] When `xdpyinfo` or `xset` is present, PCGA does not declare Xwayland ready until the probe succeeds.
- [ ] In the minimal fallback path, a discovered X11 socket receives a short settle delay before Wine starts.
- [ ] Jedi Outcast no longer logs `nodrv_CreateWindow` / `Make sure that your X server is running and that $DISPLAY is set correctly` during a normal launch.
- [ ] If Xwayland never becomes ready, the wrapper exits with rc=71 and a specific readiness error instead of holding an unexplained black stream.
- [ ] The existing Jedi Outcast argv remains split into separate elements and the `JEDIOUTCAST` compatibility CD remains visible after the readiness fix.

## Session shutdown feedback

- [ ] From **PC Games → Sessions**, confirm **End session** for one running game. Before the host stop call returns, the row immediately enters an in-progress state, displays a busy indicator and **Ending…**, and explains that PCGA is waiting for the runtime container to exit.
- [ ] While a session is ending, its stop button is disabled and a second click cannot issue a duplicate stop request.
- [ ] **End all** immediately changes to **Ending all…**, marks active rows as shutting down, and blocks duplicate bulk-stop actions until the request resolves.
- [ ] From the embedded PC-game stream, confirming **End session** keeps the overlay open while shutdown is pending, dims the stream frame, changes the button to **Ending…**, and disables conflicting stream-toolbar actions.
- [ ] On successful shutdown, the stream closes (or the session row disappears) only after the server confirms the runtime container stopped; the normal success status is then shown.
- [ ] On stop failure, controls are restored, the in-progress state is removed, and the portal reports the failure instead of leaving the UI stuck busy.
- [ ] With `prefers-reduced-motion: reduce`, the busy indicator remains visible without continuous rotation.


## Preserved optical media / retail CD checks

- [ ] An already-installed single-disc PC game with `source_isos` gains a `runtime_media` entry without reinstalling the game.
- [ ] `/run/pcga-game-media/<set-id>/disc1` is a read-only loop mount of the preserved ISO and remains visible to the Docker daemon after the oneshot orchestrator exits.
- [ ] The generated Wolf app mounts both the disc filesystem at `/pcga-media/disc1` and the original ISO at `/pcga-media/disc1.iso`.
- [ ] The Wine prefix contains `dosdevices/d:` -> `/pcga-media/disc1` and `dosdevices/d::` -> `/pcga-media/disc1.iso`; `HKLM\Software\Wine\Drives` reports `d:` as `cdrom`.
- [ ] Runtime logs contain `[pcga-media] mapped preserved disc 1 as D:` and the `wine cmd /c vol D:` result.
- [ ] The Jedi Outcast retail image reports the original `JEDIOUTCAST` volume label and starting a new game no longer produces `CD not in drive`.
- [ ] Multi-disc sources are mapped to sequential read-only Wine CD-ROM letters without modifying the preservation images.
- [ ] Rebooting the host recreates `/run/pcga-game-media` through the 15-second boot orchestrator timer before normal use.
- [ ] No no-CD patch, modified `jk2sp.exe`, or fabricated replacement media is installed.

## v0.18.19 branch-merge regression

- [ ] A file-by-file comparison against both v0.18.19 inputs shows no executable/component feature is dropped; only the version-bearing files and merged documentation differ.
- [ ] Moonlight receiving the first video packet is not treated as proof the game is healthy; Wine/runtime exit diagnostics remain visible.
- [ ] The portal Compatibility card reports the PCGA known-good rule, auto-applied runtime environment, and launch arguments rather than presenting them only as advisory evidence.
- [ ] Repeated ProtonDB evidence can auto-apply `MESA_EXTENSION_MAX_YEAR` / `__GL_ExtensionStringVersion` only when at least two reports agree; other Proton environment variables remain advisory.
- [ ] A setup prefix missing `kernel32.dll` is rebuilt, and a prefix with a present-but-unloadable `kernel32.dll` is also rejected by the `wine cmd /c ver` probe and rebuilt.

- [ ] Jedi Outcast (`6030` or canonical retail title) resolves the `pcga-known-good` id Tech 3 profile and exports `MESA_EXTENSION_MAX_YEAR=2003` plus `__GL_ExtensionStringVersion=17700`.
- [ ] On an AMD/Intel Mesa host, Jedi Outcast reaches the game renderer without the startup `jk2sp.exe` OpenGL-extension page fault.
- [ ] Jedi Academy (`6020`) receives the same bounded-extension compatibility rule.
- [ ] A game installed under a path containing `Program Files (x86)` launches through the NUL-delimited argv handoff with no `sh: Syntax error: "(" unexpected`.
- [ ] Existing v0.18.18 compatibility cache entries are refreshed after upgrade because the resolver version changes.
- [ ] An interactive setup prefix with a present but unusable `kernel32.dll` fails the loader probe, is rebuilt, and passes `wine cmd /c ver` before Setup.exe starts.
- [ ] A non-zero primary Wine launch kills stale prefix helpers instead of leaving a long-lived black compositor session.

- [ ] Ingest a game with a resolved Steam AppID; its canonical game record gains a `compatibility.matches.protondb` entry without changing preserved source media.
- [ ] A successful ProtonDB lookup records the exact AppID summary; a provider outage/no-report response does not produce false `0.99` match confidence.
- [ ] A title with a clear approved PlayOnLinux match records the matched recipe, score, Wine-version evidence, components, and executable names.
- [ ] An ambiguous PlayOnLinux title/edition match is retained only as candidates/evidence and is not auto-applied.
- [ ] An unapproved PlayOnLinux recipe is not auto-applied.
- [ ] Unknown `POL_Install_*` calls are reported as unsupported and are never executed.
- [ ] Provider script/report text is never passed to a shell.
- [ ] A high-confidence approved recipe applies only allow-listed Winetricks verbs/Windows version and preferred executable hints.
- [ ] `WINEARCH` is used only when creating a fresh prefix; an existing prefix of another architecture remains usable.
- [ ] Compatibility Winetricks setup is bounded by `PCGA_COMPAT_WINETRICKS_SECONDS` (default 300) and failure falls back to generic Wine behavior.
- [ ] Preferred executables from a known-good recipe receive selection priority without overriding the existing unsafe/helper-executable filters.
- [ ] PC Games → game detail shows the Compatibility card with ProtonDB/PlayOnLinux evidence and any warnings.
- [ ] **Refresh compatibility** forces a new lookup and refreshes the game detail without requiring SSH.
- [ ] Disabling ProtonDB or PlayOnLinux in Settings updates `game-metadata.env` and subsequent resolution skips that provider.
- [ ] A matched profile remains cached across normal orchestrator passes; an error/no-match profile retries after six hours; changing the canonical title or Steam AppID invalidates the profile immediately.


- [ ] Open **PC Games → Sessions** with no game running; the portal reports no active game/setup sessions and disables **End all**.
- [ ] Start a PCGA game or interactive setup stream; the session appears with the correct title/type and a short container id.
- [ ] **Back** from the stream closes only the browser stream view and leaves the runtime active.
- [ ] **End session** from the stream toolbar asks for confirmation and terminates the matching PCGA runtime.
- [ ] End one session from **PC Games → Sessions**; unrelated PCGA sessions remain running.
- [ ] **End all** requires confirmation and terminates every active PCGA game/setup runtime.
- [ ] The control plane refuses a container that lacks `PCGA_GAME_SET_ID` or does not use a `pcga/game-*` / `pcga/setup-*` image.
- [ ] When Stream is blocked by `managed runtime container active: ...`, the session manager opens automatically. After the final blocker is ended, the requested stream is retried without waiting for the five-minute timer.

- [ ] Run the PC-game orchestrator twice without changing metadata; the second pass does not request or perform a Wolf restart.
- [ ] With a PCGA game/setup session active, a real Wolf profile change remains `pending-restart` and does not terminate the active session.
- [ ] After the session closes, pressing Stream triggers immediate reconciliation without waiting for the five-minute timer.
- [ ] A Moonlight-visible app streams even if persisted state still says `pending-restart`.
- [ ] `LaunchBFII*` / `LaunchEAW*` source helpers do not become logical game titles.


- [ ] Two preserved bundles with the same optical fingerprint and `disc_count=1` resolve to one logical ISO and do not produce a multi-disc setup state.
- [ ] A genuine two-disc set with distinct fingerprints/disc numbers remains classified as multi-disc.
- [ ] Interactive setup with a missing `kernel32.dll` rebuilds only the mutable Wine prefix, runs `wineboot`, and refuses to start Setup.exe if the prefix is still invalid.
- [ ] A setup bootstrap EXE that exits while another Wine child remains does not tear down Sway/Xwayland until the Wine session is finished.
- [ ] Existing `LaunchEAW.exe` / `LaunchBFII.exe` ready-state targets are replaced by direct game executables when available.
- [ ] Empire at War launches with windowed 1920x1080 compatibility arguments; Battlefront II retains its `/win` compatibility path.

- [ ] A reconciliation containing multiple changed PC games causes at most one Wolf restart.
- [ ] Starting/running a `PCGA-*` game container prevents Wolf from being restarted by the orchestrator.
- [ ] A deferred `pending-restart` app writes `/var/lib/pc-game-archive/game-runtime/wolf-restart-pending.json` and becomes ready on a later idle orchestration pass, even when no new source work is queued.
- [ ] Portal Diagnostics can open a persisted PC-game `runtime-logs/session.log` without an unbound-local-variable error.
- [ ] Sending TERM to a runtime wrapper records `received signal=TERM` and a shell exit record.
- [ ] Runtime log records `id`, Wine version, and whether the runtime user can read/write the render node.
- [ ] Existing portal, media, DNS, themes, and game-ingest workflows remain intact.

- [ ] `pcga-lan-dns.service` is installed and enabled.
- [ ] DNS helper binds only the PCGA LAN address on TCP/UDP 53.
- [ ] DNS helper does not configure or serve DHCP.
- [ ] `pcga.portal` resolves to the appliance LAN IPv4 address when querying the PCGA DNS service directly.
- [ ] Non-PCGA DNS queries use the preserved upstream resolver file.
- [ ] Existing DNS service on port 53 is not replaced automatically.
- [ ] Avahi publishes `pcga.local` as a fallback alias.
- [ ] Portal TLS certificate contains `DNS:pcga.portal`.
- [ ] Existing PCGA CA is preserved when only the leaf certificate needs reissuing.
- [ ] If TCP 443 is free, Compose publishes `443:8443` and `https://pcga.portal/` reaches the portal.
- [ ] If TCP 443 is busy, PCGA preserves the owner and keeps the friendly portal on `:8443`.
- [ ] Existing `https://<LAN-IP>:8443/` access continues to work.
- [ ] `/api/secure-context` reports the LAN DNS name and friendly portal URL.
- [ ] Thin-client bootstrap continues advertising the original IP-based LAN URL and additionally advertises the named URL.
- [ ] Settings and media/game launch paths continue to function after opening the portal through `pcga.portal`.
- [ ] Shell, Python, manifest, Compose and archive path-safety validation pass.


## v0.18.22 scoped graphics environment

- [ ] Launch Jedi Outcast and verify Sway does not log `BGRA8888 format not supported by GLES2`.
- [ ] Verify runtime log contains `applying game-process environment MESA_EXTENSION_MAX_YEAR=2003`.
- [ ] Verify the environment line appears after the Sway launcher begins, not before `launcher /tmp/pcga-wine-session.sh`.
- [ ] Verify a non-id-Tech-3 game starts without inheriting Jedi-specific Mesa/NVIDIA extension variables.
- [ ] Verify preserved optical-media mapping remains present and any `VOL` probe failure is non-fatal.

## v0.18.27 argv serialization regression checks

- [ ] Generated `startup.sh` contains no literal NUL bytes and contains the shell expression `printf '%s\0'` for the runtime argv file.
- [ ] A target under `Program Files (x86)` survives the launcher boundary without `sh: Syntax error: "(" unexpected`.
- [ ] Jedi Outcast logs `[pcga-wine-session] argv:` with `jk2sp.exe`, `+set`, `r_fullscreen`, `0`, and each remaining compatibility option as separate shell-quoted fields.
- [ ] Wine never reports a concatenated pseudo-filename such as `jk2sp.exe+setr_fullscreen0...`.
- [ ] The Jedi compatibility CD still reports volume label `JEDIOUTCAST` and verifies `D:\gamedata\gamedata\jk2sp.exe`.
- [ ] Interactive setup uses the same corrected NUL handoff and retains exact installer paths containing spaces or parentheses.


## v0.18.24 install/CD regression checks

- [ ] After a successful Jedi Outcast interactive install, ending the setup session causes the host finalizer to promote the game to READY without reopening Setup.
- [ ] A subsequent Jedi Outcast stream launches `jk2sp.exe` directly rather than `JediOutcast.exe` or `setup.exe`.
- [ ] Existing installs whose launch target is `JediOutcast.exe` are repaired to the higher-priority `jk2sp.exe` target without reinstalling.
- [ ] The Jedi Outcast runtime reports a Wine CD-ROM drive labeled `JEDIOUTCAST` and verifies `D:\gamedata\gamedata\jk2sp.exe`.
- [ ] The compatibility CD overlay is backed by preserved media/installed content and does not patch the game executable.
- [ ] Generic preserved optical images remain read-only and are shifted off the reserved compatibility drive letter.



## v0.18.31 merged optical drive-type validation

- [ ] `runtime_media` state includes a `/dev/loopN` device for every mounted preserved ISO.
- [ ] The generated Wolf app passes each loop device read-only as `/dev/pcga-media-discN`.
- [ ] A Jedi Outcast runtime has both `dosdevices/d:` and `dosdevices/d::`; `d::` resolves to a block device rather than a regular `.iso` file.
- [ ] `dosdevices/d:` still resolves to `.pcga-virtual-cd-d`, preserving the compatibility overlay and retail sentinel layout.
- [ ] `wine cmd /c vol D:` reports `JEDIOUTCAST` after the raw-device mapping is installed.
- [ ] Both 32-bit and 64-bit Wine `HKLM\Software\Wine\Drives` views mark `d:` as `cdrom`.
- [ ] `wine wmic logicaldisk get DeviceID,DriveType,VolumeName` reports `D:` as `DriveType 5` and `VolumeName JEDIOUTCAST`.
- [ ] `D:\gamedata\gamedata\jk2sp.exe` remains readable and the original game executable is unmodified.

## v0.18.31 title/disc ownership and multi-disc runtime

- [ ] Ingesting Disc 1 and Disc 2 of one title produces one title/set record with `media.kind = optical-disc-set` and two owned disc members.
- [ ] Existing disc metadata records remain intact after upgrade; the title-level inventory is additive.
- [ ] A two-disc runtime contains both `/pcga-media/disc1` and `/pcga-media/disc2` plus both raw `/dev/pcga-media-discN` devices.
- [ ] `D:` reports Wine/Win32 `DriveType=5` and points at the active disc.
- [ ] Multi-disc sessions expose stable `E:`/`F:` mappings for the full disc set.
- [ ] `pc-game-disc-switch` changes `D:` to another attached disc without restarting the runtime container.
- [ ] The selected active disc is persisted to the title's install state for the next launch.


## v0.18.33 game database profile search

- [ ] Settings → **PC games & LAN sessions** shows RAWG game-database configuration without ever echoing a saved API key back into the browser.
- [ ] Saving a valid RAWG API key writes `RAWG_API_KEY` to root-readable `/etc/pc-game-archive/game-metadata.env` and subsequent portal searches work without a service rebuild.
- [ ] **PC Games → Disc images → Inspect / assign → Search game database** searches RAWG and displays title, release year, platform/genre hints, artwork, and an active RAWG attribution/source link.
- [ ] Selecting a result for an unassigned preserved disc creates one confirmed PCGA title profile and assigns that disc to the new/existing title.
- [ ] Selecting a result for an already-owned disc updates the owning title profile without changing the preserved image, checksum, fingerprint, disc number/count/role, or other title-owned disc members.
- [ ] Existing **PC Games → Details → Find metadata** can replace an incomplete/incorrect title profile without requiring rerip or reinstall.
- [ ] Applying a RAWG result stores `external_ids.rawg`, `metadata_profile.provider=rawg`, provider ID, source URL, attribution, `selected_by_user=true`, and `locked_by_user=true`.
- [ ] The selected profile can populate release/developer/publisher/genres/description/site/rating fields when RAWG supplies them, while missing provider fields do not erase preservation ownership/provenance.
- [ ] RAWG artwork/screenshots are cached locally under the title asset directory; loss of Internet access after selection does not remove the locally cached artwork.
- [ ] A user-selected database profile prevents periodic Steam descriptive enrichment from replacing it, while ProtonDB/PlayOnLinux compatibility resolution still runs independently.
- [ ] Applying metadata to a multi-disc title preserves `media.kind=optical-disc-set`, every `disc_fingerprint`, and live multi-disc runtime/switch behavior.
- [ ] RAWG-derived library cards/details include an active RAWG link as attribution.
- [ ] Search/API failures leave the existing PCGA title/disc records unchanged and report a useful portal error.

## v0.18.34 shared Wine/LANCommander game LAN

- [ ] Upgrade preserves an existing `legacy-games` Docker network and its subnet; a missing network is recreated as an attachable bridge using the configured/default `10.40.0.0/16` subnet.
- [ ] `compose.game-lan.yml` attaches LANCommander to both the normal PCGA Compose network and `legacy-games`.
- [ ] `docker inspect lancommander` reports a non-empty IPv4 address under `NetworkSettings.Networks.legacy-games`.
- [ ] Generated Wolf PC-game and setup apps contain `HostConfig.NetworkMode = legacy-games`.
- [ ] A launched `PCGA-*` runtime and a simultaneous second runtime receive different addresses on `legacy-games`.
- [ ] `PC Games → Sessions` shows the shared-LAN address for each running desktop.
- [ ] Two sessions owned by the same portal client remain independently switchable/endable while sharing the LAN.
- [ ] Two sessions owned by different portal clients share the LAN but retain separate ownership; **End my sessions** does not terminate the other client's container.
- [ ] `lancommander` resolves from a running game container and TCP/1337 is reachable from that container.
- [ ] Runtime environment contains `PCGA_LANCOMMANDER_URL=http://lancommander:1337`, `PCGA_IPX_RELAY_HOST=lancommander`, and `PCGA_IPX_RELAY_PORT=213`.
- [ ] LANCommander remains reachable through the PCGA portal/native admin path after dual-homing.
- [ ] A known TCP/UDP broadcast-discovery LAN game can host in one Wine session and discover/join from another PCGA Wine session.
- [ ] IPX games are not marked automatically compatible merely because UDP/213 is available; a compatible wrapper/interposer/profile is still required.
- [ ] No physical-LAN macvlan/ipvlan bridge is created by this release.



## v0.18.44 multi-disc crash/dedup diagnostics

- [ ] A legacy multi-disc title with `install_method=portable-copy` and `portable_source_scope_repaired_v01839=true` is still re-evaluated and cannot remain a portable-ready runtime.
- [ ] COD2-like linked records choose the multi-disc setup/completed-prefix UUID over a one-disc/portable metadata UUID, while the selected `Call of Duty 2` metadata and artwork remain visible.
- [ ] After reconciliation, the superseded COD2 UUID is marked hidden/duplicate and no longer generates a separate Wolf app or portal card.
- [ ] A Wine application that raises an unhandled exception and starts `winedbg` exits the PCGA runtime with a failure instead of keeping the Moonlight lane open.
- [ ] The resulting transient `PCGA-*` child container is removed after the crash.
- [ ] Streaming diagnostics omit superseded game UUID logs.
- [ ] A ready game contributes its runtime log but not an old setup log; a setup-required game contributes its setup log but not an old runtime log when both exist.
- [ ] Downloaded streaming diagnostics use `snapshot_schema: 2`, include only the selected profile's services, and do not repeat the service descriptor inside every log object.
- [ ] Python compilation with `SyntaxWarning` promoted to an error, Bash syntax, Compose YAML parsing, portal JavaScript syntax, generated runtime shell syntax, manifest verification, and ZIP integrity all pass.

## v0.18.45 Battlefront II / stale setup target repair

- [ ] A legacy setup state pointing at `GameData/Setup.exe` is re-ranked even when `setup_source_scope_repaired_v01839=true` and `installer.source_path` is already `.`.
- [ ] On a BFII-like disc containing a root game bootstrapper plus nested `GameData/Setup.exe` and Adobe Reader support payloads, the root/disc-authored bootstrapper wins.
- [ ] `AdbeRdr934 en US`, Adobe/Acrobat Reader package names, DirectX/.NET/VC redistributable names, and `LaunchBFII*` are not retained as customer-facing game titles.
- [ ] Existing suspicious titles are re-derived from preserved-media evidence without deleting/re-ripping the ISO.
- [ ] Replacing a stale setup target clears the previous setup runtime image/build hash and returns the Wolf app to pending reconciliation.
- [ ] If the corrected bootstrapper completes Battlefront II installation, the installed runtime resolves to `BattlefrontII.exe` and retains `/win /resolution 1920 1080`.
- [ ] A genuinely correct CLR-based installer can still use the bounded Wine-Mono/Winetricks fallback; nested support helpers are not used merely to trigger that fallback.
- [ ] Python `SyntaxWarning`-fatal compilation, shell syntax, YAML, portal JavaScript, focused stale-target ranking tests, manifest verification, and ZIP integrity pass.

## v0.18.46 streaming stabilization / immutable Wolf IDs
- [ ] A multi-disc title left as `portable-copy` with old repair markers is re-scanned and cannot remain READY solely because the marker exists.

- [ ] A game titled `Planescape: Torment` generates a Wolf app title with no `:` (for example `PCGA Game 42d8a7cd3099`) and Docker no longer reports `invalid volume specification`.
- [ ] `Star Wars Jedi Knight II: Jedi Outcast` and other punctuation-heavy metadata titles use the same UUID-derived naming rule.
- [ ] Changing web metadata/title does not change the Wolf internal app key for the same game-set UUID.
- [ ] Portal cards and stream tabs still show the human game title while native Wolf/Moonlight matching uses the internal key.
- [ ] A terminally failed setup/game child container is removed by the orchestrator and no longer blocks a pending Wolf reload.
- [ ] A failed setup session exits its transient container promptly after the persisted failure log is written.
- [ ] `pcga-game-orchestrator.timer` runs at one-minute cadence with bounded jitter.
- [ ] A READY title whose last stream state is failed still exposes **Retry stream**.
- [ ] A setup-required title with a generated setup runtime still exposes **Retry installer** after a failed attempt.
- [ ] A title without a generated launch runtime exposes **Repair launch** instead of an actionless card.
- [ ] Existing preserved optical media, install prefixes, user-selected metadata and compatibility state are unchanged by the Wolf internal-title migration.
- [ ] Python `SyntaxWarning`-fatal compilation, shell syntax, YAML, portal JavaScript, immutable-title focused tests, manifest verification, and ZIP integrity pass.


## v0.18.47 appliance-wide compatibility sweep

- [ ] `sudo game-archive game-compat-test` removes stale validated `PCGA-*` child containers before the sweep.
- [ ] The sweep reconciles the canonical game catalog without reinstalling titles and restarts Wolf/Wolf-Den from a clean transient-session state.
- [ ] One canonical result is emitted per visible game UUID; superseded/hidden duplicate records are skipped.
- [ ] A ready game is probed from its generated `pcga/game-*` image in a disposable home and must hold a non-error window for at least 15 seconds.
- [ ] A setup-required title is probed from `pcga/setup-*` with a disposable `/pcga-install` prefix and cannot modify the real installation.
- [ ] Missing launch executable/runtime image/setup installer, invalid prefix, missing Wolf registration, Docker create/start errors, Wine debugger crashes, runtime error windows, and timeouts produce `outcome=fail`.
- [ ] Every failed result contains a non-empty `failure_reason` and `failure_traceback`.
- [ ] `/var/lib/pc-game-archive/game-compat-tests/latest.json` and a timestamped report are generated atomically.
- [ ] Killing/rebooting during a sweep leaves `latest.partial.json` with completed game results.
- [ ] No `PCGA-Compat-*` test container remains after a completed sweep.
- [ ] `game-archive game-compat-report` prints the most recent JSON report.


## v0.18.49 compatibility sweep fidelity

- [ ] `game-archive game-compat-test` ignores source-only records whose state is not `ready` or `setup-required`, while retaining them in `ignored_records`.
- [ ] Disposable probes mount writable Wolf-equivalent `/tmp/.X11-unix` and `/run/user/wolf` directories and advance beyond GoW user initialization.
- [ ] A current probe failure traceback contains only evidence from that probe, not stale `installer_log` text from an earlier installation attempt.
- [ ] Running the orchestrator repairs a missing managed Wolf block for a launchable state even if that state has no current intake source mapping.
- [ ] `summary.tested + summary.ignored_source_records` describes the sweep population without counting source-only remnants as game failures.

## v0.18.49 compatibility fidelity / Wolf recovery

- [ ] Run `sudo game-archive game-compat-test --timeout 60`; probe logs show `XDG_RUNTIME_DIR=/run/user/wolf`, not `/tmp/.X11-unix`.
- [ ] Probe `id` output includes the DRI render-node supplementary GID; no `runtime user cannot read/write /dev/dri/renderD128` warning appears.
- [ ] Wine optical probes can read mapped `/dev/pcga-media-disc*` devices without group-permission failures.
- [ ] A missing/stale UUID Wolf app block is repaired during reconciliation and remains present after the Wolf reload.
- [ ] A multi-disc `READY + portable-copy` record is demoted to setup even when its only current media evidence is persisted `runtime_media`.
- [ ] `JEDIOUTCAST` and `Star Wars Jedi Knight II: Jedi Outcast` converge when both records are present, preserving the stronger installed runtime and selected metadata.
- [ ] Source-only preservation records remain under `ignored_records` and do not affect the compatibility pass rate.


## v0.18.50 persisted-media setup recovery / crash capture

- [ ] A canonical multi-disc title with no current source rows can recover valid persisted `source_isos`/`runtime_media` or conservatively title-linked source-only bundles and restage interactive setup without re-ripping.
- [ ] Multi-disc recovery scans all preserved members and prefers an autorun/root vendor bootstrapper over payload MSI/portable candidates.
- [ ] The selected bootstrap member is persisted as `setup_bootstrap_disc` and becomes `runtime_active_disc` for the initial installer session.
- [ ] `silent_install()` does not overwrite a surviving preserved ISO inventory with an empty list when source ownership has moved.
- [ ] A `setup-required` title with no generated setup image is not falsely reported as a Wolf app that was dropped during reload.
- [ ] Compatibility probe containers do not use the production `PCGA-*` child prefix and survive long enough for Docker/Wine logs to be collected after a fast crash.
- [ ] Missing setup/runtime images are represented as an empty image reference, never the literal Docker repository `None`.
- [ ] A ready game that only opens `Electronic Registration`/configuration utility windows reports `outcome=attention`, not `pass`.
- [ ] Report schema is 3 and summary includes `attention`.
- [ ] Python `SyntaxWarning`-fatal compilation, shell syntax, YAML, portal JavaScript, focused persisted-media/probe tests, manifest verification, and ZIP integrity pass.


## v0.18.51 compatibility portal-test summary

- [ ] A completed `sudo game-archive game-compat-test` prints `=== PORTAL MANUAL TEST CANDIDATES ===` after the aggregate summary.
- [ ] Every `outcome=pass` title appears once as `PASS N: [PLAY|INSTALL] <title> | <game_set_id> | <window/stage>`.
- [ ] `outcome=attention` titles are listed under a separate **NEEDS MANUAL ATTENTION** heading and are not presented as portal-ready passes.
- [ ] `outcome=fail` titles are listed under **NOT READY FOR PORTAL TESTING**.
- [ ] `latest.json` uses schema 4 and stores compact `portal_test_candidates` and `attention_candidates` arrays.
- [ ] `game-archive game-compat-report` still emits valid JSON with no human prose mixed into stdout.
- [ ] `game-archive game-compat-report --summary` prints the saved portal candidate list without running a new compatibility sweep.


## v0.18.52 resumable PC game/setup sessions

- [ ] Start an interactive setup session, press **Back**, reopen PC Games, and confirm the title shows **SETUP ACTIVE** with **Resume setup** instead of another Install action.
- [ ] Open **Sessions** and confirm an owned active desktop has **Resume game/setup** and **End session** as separate actions.
- [ ] Resume an active session and confirm its Docker container ID is unchanged.
- [ ] Reload the secure portal, reopen PC Games, and confirm the same host-side owned session is rediscovered through the persistent browser client ID.
- [ ] Clicking Play/Install for a title with an already-owned active session resumes it rather than creating a second reservation/container.
- [ ] **Reconnect video** reloads only the embedded Moonlight stream surface and does not stop/remove the Wine runtime container.
- [ ] A hidden stream iframe remains alive when **Back** is used within the same portal page.
- [ ] Ending the resumed session still performs the normal bounded stop plus container removal.
- [ ] Shell, Python, YAML, embedded JavaScript, manifest, and ZIP integrity checks pass.

## v0.18.74 COD2 reinstall recovery / isolated Wine fallback

- [ ] Upgrading a COD2 record that is already `status=ready` does not run the legacy v0.18.69 synthetic-media migration and does not remove or reset its Wine prefix.
- [ ] A user-requested COD2 reinstall clears mutable prefix and derived synthetic-media state but preserves the archived `COD2CD1..COD2CD6` ISO set.
- [ ] COD2 setup is not published to Wolf until exact `findmnt` validation confirms the synthetic `COD2DVD` mount and raw loop device.
- [ ] The validated synthetic setup source contains `setup.exe`, `.pcga-msi-media-flattened-v01866.json`, and `Setup/Data/main/iw_02.iwd`.
- [ ] A periodic orchestrator reconciliation does not unmount/rebuild a healthy COD2 synthetic setup source while an installer session is being launched.
- [ ] If the setup source disappears between reconciliation and Wine launch, startup exits with the explicit missing marker/payload diagnostic rather than invoking an invalid installer path.
- [ ] COD2 setup/reinstall uses the base Games-on-Whales Wine runner, not `/opt/wine-devel`.
- [ ] COD2 gameplay requests the isolated WineHQ `wine-devel` runner without replacing the base image `/usr/bin/wine`.
- [ ] If the isolated WineHQ runtime image build fails, PCGA successfully generates a base-Wine fallback runtime and records `runtime_wine_runner_fallback_v01874=true` instead of leaving the title `ready / failed`.
- [ ] A successful later isolated-runner build clears the fallback marker and prior runtime-build failure state.
- [ ] Python compilation, shell syntax, manifest verification, and ZIP integrity checks pass.
