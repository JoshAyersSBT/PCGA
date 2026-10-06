# v0.18.85

- Fixes the Noble userspace bootstrap blocker exposed after DKMS/VHBA succeeded: `libmirage-dev` and `gir1.2-mirage-3.2` are not available from the target Ubuntu 24.04/Noble archive, so CDEmu source configuration could never reach the daemon/client build.
- Removes `libmirage-dev` from the Noble APT prerequisite list and installs the lower-level libMirage build dependencies independently (`libsndfile1-dev`, `libsamplerate0-dev`, `zlib1g-dev`, `libbz2-dev`, `liblzma-dev`, GLib and related tooling).
- Extends `pcga-cdemu-userspace-bootstrap` to fetch SHA-256-verified upstream libMirage 3.3.3, build/install it under `/usr`, run `ldconfig`, and require a successful `pkg-config libmirage` probe before configuring CDEmu.
- Retains the verified VHBA 20260313 DKMS path and the pinned CDEmu 3.3.0 daemon/client sources. No COD2 media, prefix, Wine runner, or drive-letter mapping is changed.
- Keeps CDEmu failure nonfatal to the Wolf/Moonlight stream and keeps COD2 Multiplayer completely isolated on its previously working Wine 9 path.

# v0.18.84

- Fixes the actual host-side blocker found on Ubuntu 24.04/Noble: the previous upgrader attempted `cdemu-client`, `cdemu-daemon`, `vhba-dkms`, `dkms`, and build prerequisites in one APT transaction. When Noble did not offer the CDEmu packages, APT rejected the whole transaction and `dkms` was never installed.
- Installs DKMS, the running-kernel headers, compiler/CMake tooling, Python GI, GLib/libao/libMirage development files, and other CDEmu prerequisites independently. An unavailable optional package can no longer suppress installation of the prerequisites that are available.
- Adds `pcga-cdemu-userspace-bootstrap`. If the configured Ubuntu suite has no CDEmu packages, PCGA builds CDEmu daemon/client 3.3.0 from pinned Debian upstream tarballs after verifying SHA-256 (`0181e3…3d65` daemon, `5a22a6…4b270` client).
- Retains the pinned VHBA 20260313 DKMS repair path. With DKMS now installed independently, `/usr/local/sbin/pcga-cdemu-bootstrap --repair` can actually build and install `vhba` for the running kernel.
- Stops and disables a failed CDEmu service before repair and changes `pcga-cdemu.service` to `Restart=no`, eliminating the observed five-second restart storm when VHBA is unavailable. The service is enabled only after the client, daemon, and `/dev/vhba_ctl` all validate.
- COD2 SP keeps the validated `COD2CD1` filesystem mapping on Wine `D:`. CDEmu changes only the low-level `D::` device when healthy; loop-backed fallback stays nonfatal for diagnostics.
- COD2 Multiplayer remains isolated on the previously working base Wine 9 + original win32 prefix + loop-backed ISO path and receives no CDEmu device. No COD2 reinstall or media rewrite is performed.

# v0.18.82

- Added a CDEmu-backed virtual optical-device path for **Call of Duty 2 single-player only**. The proven `COD2CD1` ISO filesystem remains Wine `D:`; only `D::` changes from the ISO's generic `/dev/loop*` node to a CDEmu VHBA `/dev/sr*` device loaded from the same preserved ISO.
- Added appliance CDEmu host infrastructure (`cdemu-client`, `cdemu-daemon`, `vhba-dkms`, `pcga-cdemu.service`) and system-bus policy. The orchestrator records CDEmu readiness, image, `/dev/sr*`, `/dev/sg*`, label, and emulation flags in `runtime_cdemu_optical`.
- Enabled CDEmu bad-sector and DPM emulation when supported. These flags improve optical-device fidelity but do not fabricate SafeDisc information that was never present in a cooked ISO.
- COD2 SP fails explicitly if the CDEmu virtual CD-ROM is unavailable or unreadable, preventing a silent fallback to the already-tested loop-device path.
- Preserved the previously working multiplayer behavior: `CoD2MP_s.exe` continues to use base Wine 9, the original win32 prefix, and the existing loop-backed optical mapping. Setup, preserved ISOs, and installed payload are unchanged.
- Avoids unloading/reloading an already-correct CDEmu image during periodic orchestration so an active SP session is not disrupted.

# v0.18.81

- Removed the v0.18.79/v0.18.80 physical-disc dependency from Call of Duty 2 single-player. PCGA now treats the preserved ISO set as the only runtime optical-media source.
- COD2 SP identifies the archive slot whose ISO volume label is `COD2CD1` and explicitly maps its mounted filesystem to Wine `D:` and its read-only loop block device to `D::`.
- Added an ISO loop-device read probe and explicit image/mount/raw-device diagnostics before COD2 SP launch.
- Clears stale `runtime_physical_auth` state and rebuilds only the generated COD2 runtime image/Wolf registration; the installed prefix and preserved media are not reset.
- Retains portable Wine 11.19 WoW64, original `SECDRV.SYS` staging, and the corrected whitespace-tolerant `legacy-games` validator.

# v0.18.80

- Hardened COD2 physical SafeDisc authentication discovery. The orchestrator now checks PCGA's persisted optical-dispatch state first, then udev and blkid, so an inserted `COD2CD1` is not lost merely because the raw drive is temporarily busy.
- Physical-auth state is explicit (`ready`, `busy`, or `not-present`) and records candidate drives/label sources for diagnostics. COD2 SP refuses to silently launch against the cooked ISO when physical authentication is unavailable.
- Wolf now adds the host optical device's actual group GID to the game container and COD2 SP performs a raw block-device read probe before launch.
- Fixed the v0.18.79 whitespace-sensitive `legacy-games` network validation false positive.
- Restored the cumulative acceptance checklist that v0.18.79 accidentally truncated.

# v0.18.79

- Added a preservation-safe **physical COD2CD1 authentication fallback** for Call of Duty 2 single-player. v0.18.78 now proves Wine 11 sees the correct `COD2CD1` label and CD-ROM drive type before launch, yet SafeDisc still rejects the loop-backed cooked ISO; v0.18.79 can temporarily present the user's original disc for the protection check without replacing the preserved archive.
- The orchestrator scans physical `/dev/sr*` optical drives for the exact `COD2CD1` volume label, mounts a match read-only under PCGA runtime media, and records the device/mount in game state. No unrelated optical disc is selected.
- Wolf receives the matching physical drive as `/dev/pcga-physical-auth` plus a read-only filesystem bind. Only the **single-player** launch variant remaps D:/D:: to that physical medium; multiplayer and the six preserved archive mappings remain unchanged.
- The portable Wine 11.19 runner, isolated WoW64 SP prefix, strict `COD2CD1`/`DRIVE_CDROM` preflight, and original-media `SECDRV.SYS` staging remain intact. The upgrade does not reinstall COD2 or modify archived ISOs.
- This release is intentionally a diagnostic/proof step before changing PCGA's preservation format. If the physical disc authenticates successfully, the archive pipeline should next gain raw protected-CD capture and virtual optical-device emulation rather than treating a 2048-byte-sector ISO as sufficient for SafeDisc titles.

# v0.18.78

- Fixed COD2 SP optical mapping under the portable Wine 11.19 runner-owned WoW64 prefix. Archive-drive registration for E:..J: could start wineserver before the active D:/D:: symlinks were published, causing Wine 11 to cache D: as an unlabeled `0000-0000` volume even though PCGA attached the correct preserved COD2 disc.
- Normal runtime media setup now restarts the currently selected wineserver after the final D:/D:: mapping and before Wine drive registration/volume probes, mirroring the refresh already used by the repaired COD2 setup path.
- COD2 single-player now validates the active optical mapping twice through Windows-side APIs before SafeDisc startup: `vol D:` must report `COD2CD1`, and logical-disk probing must report D: as `DRIVE_CDROM (5)`. A stale mapping fails closed with a focused media error instead of opening COD2's misleading "insert the correct CD/DVD-ROM" dialog.
- Keeps the v0.18.77 portable Wine 11.19 runner, isolated WoW64 SP prefix, original-media `SECDRV.SYS` staging, Wine 9 multiplayer/setup paths, and preserved optical media unchanged. The upgrade invalidates only the generated COD2 runtime image; no reinstall or re-rip is requested.

# v0.18.77

- Replaced the failing WineHQ APT-based COD2 runner with a pinned portable **Wine 11.19 amd64-wow64** archive. The runtime image downloads `wine-11.19-amd64-wow64.tar.xz` from Kron4ek/Wine-Builds and verifies SHA-256 `a1fe858b45d12c9b16b91c7601d9b934f68430f7b6b95e240212ab6e2a198d8a` before accepting it.
- The portable new-WoW64 build can run 32-bit Windows programs without 32-bit Unix libraries, avoiding WineHQ/Ubuntu package dependency conflicts inside the Games-on-Whales image.
- Changed the runner identity to `portable-wow64-11.19`, invalidating cached v0.18.76 base-Wine fallback state and forcing one clean COD2 runtime-image rebuild without touching the installed game prefix or preserved optical media.
- COD2 setup and multiplayer remain on the known base Wine 9 path; only single-player uses the experimental portable Wine runner.
- Retains the v0.18.75 original-media `SECDRV.SYS` staging, scoped `winxp` override, isolated runner-owned prefix, OLE/Flash post-install suppression, and structured SafeDisc failure diagnostics.
- If the portable image build fails, PCGA falls back to base Wine without demoting or reinstalling COD2 and keeps the isolated Docker build output in `runtime_build_log`.

# v0.18.74

- Fixed the **v0.18.73 COD2 upgrade regression** where the inherited v0.18.69 synthetic-media migration ran on every upgrade and could demote an already-READY COD2 install back to interactive setup. Legacy loop repair now runs only when no COD2 record is READY, so routine upgrades leave a healthy installed prefix untouched.
- Fixed the immediate COD2 reinstall crash captured in diagnostics: Wolf launched `/pcga-source/setup.exe` while a concurrent reconciliation had torn down/rebuilt the synthetic `COD2DVD` source. COD2 now validates the exact `findmnt` mount, `setup.exe`, MSI flatten marker, `Setup/Data/main/iw_02.iwd`, and raw loop device before a setup app can be published.
- Replaced the unreliable `Path.is_mount()` fast-path check for COD2 synthetic optical media with PCGA's existing exact-mount detector, preventing periodic orchestrator passes from repeatedly rebuilding a healthy loop-backed setup source.
- Reinstall now clears all derived COD2 synthetic-media state before rebuilding it from preserved `COD2CD1..COD2CD6` images, preventing stale mount/device flags from surviving a reset.
- Hardened the isolated Wine 11.19 experiment. The per-game image now installs the side-by-side `wine-devel` payload rather than explicitly forcing WineHQ i386/amd64 subpackages over the GOW base image. If the isolated runner still cannot build, PCGA automatically builds a base-Wine fallback image and keeps the game streamable instead of leaving the title `ready / failed`.
- Setup/reinstall continues to use the base GOW Wine image. The isolated WineHQ runner remains gameplay-only and cannot modify the preserved installer media or host Wine packages.

# v0.18.73

- Added an **isolated per-game Wine runner layer**. The host Wine installation and unrelated PCGA titles remain unchanged; a title can now request a WineHQ runtime embedded only in its generated game image.
- COD2 retail now selects **WineHQ development 11.19** at `/opt/wine-devel` for gameplay while retaining the already-verified `win32` prefix, preserved `COD2CD1..COD2CD6` media, and existing SP/MP executable selection. The image installs the pinned `wine-devel`, `wine-devel-amd64`, and `wine-devel-i386:i386` packages rather than changing `/usr/bin/wine` on the appliance.
- The runtime logs both the selected runner ID and the effective Wine executable/version before launch and fails closed if a stale Wolf image does not contain the required runner.
- Generalized COD2 SafeDisc detection from only `c0000142` to any failed `ZwLoadDriver(...SecDrv...)`, including the observed win32 `c000000d` result. A structured `runtime-logs/last-failure.json` record persists the executable, NTSTATUS, Wine runner, and Wine version.
- Known COD2 SafeDisc failures now return a dedicated PCGA compatibility exit code and close the empty compositor immediately instead of deliberately holding a black stream for the normal failure grace period.
- Upgrade invalidates only COD2's generated runtime image/build hash. It does **not** reset the working win32 prefix or preserved optical media, so testing Wine 11.19 does not require another six-disc reinstall.

# v0.18.72

- Added an appliance-owned **Call of Duty 2 retail SafeDisc compatibility profile**. COD2 now requires a genuine `win32` Wine prefix while keeping the original `CoD2SP_s.exe`, `CoD2MP_s.exe`, and preserved optical media unchanged.
- Added a one-time migration for an already-ready COD2 `#arch=win64` install. The orchestrator resets only the mutable Wine install prefix, retains the preserved `COD2CD1..COD2CD6` images/runtime-media inventory, creates a new install generation, and returns the title to the existing synthetic six-disc interactive installer.
- Interactive setup now validates Wine prefix architecture before accepting an existing prefix. If the compatibility profile requires `win32` but the prefix reports `win64`, the prefix is rebuilt from scratch with `WINEARCH=win32`; the rebuilt `#arch` marker is verified before setup continues.
- Normal game startup now logs the actual and required Wine architecture and refuses to launch a mismatched prefix instead of producing a short black stream. COD2 sessions also identify the preserved-media SafeDisc 4.60/SecDrv compatibility path explicitly.
- The runtime captures the game Wine output long enough to recognize the observed `ZwLoadDriver ... SecDrv ... c0000142` failure. If COD2 SP still hits that error from a verified win32 session, the log identifies Wine's DRM compatibility layer as the remaining boundary rather than blaming optical media or the portal.
- Retains v0.18.71 executable-role launch variants: COD2 single-player remains the default and multiplayer remains a separate selectable Wolf/portal app. No cracked/no-CD executable or SafeDisc bypass is downloaded or installed.

# v0.18.71

- Added executable-role launch variants. When PCGA detects a same-directory SP/MP executable pair with the same normalized family, it records `launch_variants`, keeps the already-selected executable as the default, and builds one runtime image that selects the requested executable through `PCGA_LAUNCH_VARIANT`.
- Wolf registration now publishes a stable default app plus separate non-default variant apps, with unique child-container names. Post-reload verification requires every expected variant app to survive before the title is considered fully reconciled.
- The PCGA portal shows **Choose mode** on multi-launch titles and exposes separate **Play Single-player** / **Play Multiplayer** buttons in the game profile instead of silently choosing one mode.
- Browser-stream reservations, container discovery, session ownership, Resume, and activity records preserve the selected launch variant.
- Existing ready installs are migrated lazily by the orchestrator (`launch_variant_detection_v01871`) and their runtime image/Wolf block is refreshed without reinstalling preserved media.
- COD2 remains single-player by default because `CoD2SP_s.exe` is the finalized v0.18.70 launch target; `CoD2MP_s.exe` becomes an explicit alternate rather than an automatic fallback. No SafeDisc/SecDrv bypass is added.

# v0.18.70

- Fixed the COD2 post-install `OLE error 80040154` shown after the six-disc install reaches the installed desktop. Diagnostics identify CLSID `{D27CDB6E-AE6D-11CF-96B8-444553540000}`, the obsolete Shockwave Flash ActiveX control used by the retail launcher shell, while both `CoD2SP_s.exe` and `CoD2MP_s.exe` are already installed.
- COD2 setup now watches for that exact post-install Flash failure. It only bypasses the shell after a strict direct-runtime probe finds both SP and MP executables, `mss32.dll`, and at least five `main/*.iwd` payload files for three consecutive checks. PCGA then terminates the obsolete shell, records installer success, and lets the host finalizer promote the direct game executable.
- Added upgrade recovery for an already-completed v0.18.69 COD2 prefix: once the setup container is no longer active, a validated COD2 payload plus the captured Flash CLSID failure is enough to synthesize the durable completion marker and finalize the title without rerunning the six-disc installer.
- PCGA does not install or download Adobe Flash. Future COD2 runtime sessions launch the native game executable directly, with single-player preferred over multiplayer.
- Retains v0.18.69 Wolf reload quarantine, v0.18.68 mount-safe setup-source reconciliation, and v0.18.67 D:/D:: optical-drive refresh unchanged.

# v0.18.69

- Fixed the Wolf reload storm exposed after v0.18.68. If Wolf dropped one managed app block after the initial reload and one in-place repair restart, PCGA kept the entire pending app set armed; the periodic orchestrator then restarted Wolf twice every minute, interrupting Moonlight before otherwise healthy games could launch.
- A repeatedly rejected Wolf app is now quarantined per title after two immediate reload attempts. Other accepted PCGA apps are promoted to `ready` / `setup-ready`, the global reload queue is cleared, and later timer cycles do not restart Wolf just because the quarantined title remains unavailable.
- The periodic full-catalog repair pass skips quarantined app registrations, preventing it from silently re-arming the restart loop.
- **Retry stream** is now an explicit forced Wolf-registration retry. It clears quarantine for only the selected title and gives that app one fresh registration/reload attempt without reinstalling the game.
- Retains v0.18.68 mount-safe COD2 setup reconciliation and v0.18.67's D:/D:: synthetic-optical Wine refresh unchanged.

# v0.18.68

- Fixed the v0.18.67 portal-launch regression shown by diagnostics: `pcga-game-orchestrator.service` repeatedly failed with `OSError: [Errno 30] Read-only file system: '00000001.TMP'`, leaving COD2 in `status=failed` and therefore removing it from Wolf's launchable app reconciliation.
- Made `prepare_interactive_source()` mount-aware. It now detects an exact `setup-source` mount, detaches it before staging, and returns a visible `setup-source-busy` state instead of recursively deleting a live read-only optical filesystem.
- COD2 reinstall now stops if synthetic optical cleanup cannot detach the existing mount; it no longer continues into generic staging against a read-only `COD2DVD` tree.
- Added automatic recovery for COD2 states poisoned by the v0.18.67 `00000001.TMP`/EROFS failure, restoring `setup-required` before the generic silent-install path runs.
- Once COD2's genuine synthetic optical source is valid, generic setup-source scope restaging and installer reselection are skipped; the verified `COD2DVD` source is authoritative.
- Added bounded traceback logging for any future per-game exception that escapes the orchestrator, so diagnostics identify the exact failing operation instead of only the exception basename.
- Retains v0.18.67's Wine D:/D:: wineserver refresh, v0.18.66's genuine COD2DVD ISO and authoritative MSI Media table, and the existing portal/Wolf streaming architecture.

# v0.18.67

- Fixed the black setup stream captured on v0.18.66. The setup container reached the valid `COD2DVD` source, but stopped at `FATAL: D: optical-media probe cannot find D:\Setup\Data\main\iw_02.iwd` before `setup.exe` was launched.
- Root cause: E:..J: preserved-disc registry calls start `wineserver` before the synthetic D:/D:: links are created. That server generation can cache the pre-D: DOS-device map.
- COD2 setup now terminates/waits for the pre-D: wineserver generation, publishes D: -> `/pcga-source` and D:: -> `/dev/pcga-setup-media`, registers D: as `cdrom`, then restarts wineserver again before the Windows-side payload, volume-label, and DriveType probes.
- Added explicit D:/D:: symlink diagnostics plus a direct DOS-device symlink payload probe, making a real mapping failure distinguishable from Wine cache state.
- Disabled the per-disc D: switch helper during the COD2 single-volume setup session so portal/manual media switching cannot replace `COD2DVD` while InstallShield is running. Original preserved discs remain available as E:..J:.
- Retains v0.18.66 byte-only staging, real ISO-9660 `COD2DVD`, authoritative single-row MSI Media table, command-line-neutral MSI diagnostics, and fail-closed setup validation.

# v0.18.66

- Fixed the remaining COD2 pre-wizard staging abort from v0.18.65: `OSError: [Errno 30] Read-only file system: '.windows-label'`.
- Replaced `shutil.copytree(..., copy2)` for COD2 disc consolidation with a byte-only overlay helper. It skips root-level `.windows-label`, `.windows-serial`, and stale `.pcga-*` pseudo-files instead of allowing Wine/appliance metadata to enter the six-disc game payload.
- Moved COD2's temporary merge tree to a dedicated archive staging directory rather than placing it beside the loop-mounted `setup-source`, eliminating accidental reuse of read-only setup-media ancestry.
- Added an explicit COD2 setup guard that disables the generic Wine virtual-CD shim even if stale compatibility metadata contains `virtual_cd`. The generic shim remains available for titles that genuinely require it.
- Upgrade cleanup now handles disposable v0.18.63, v0.18.65, and v0.18.66 synthetic loop media and removes stale COD2 `virtual_cd` compatibility metadata from both canonical and duplicate records.
- Added focused `COD2 staging traceback:` logging so future host-staging failures include the failing call path.
- Rebuilt media is versioned as `setup-source-v01866.iso` with `.pcga-msi-media-flattened-v01866.json`; preserved source ISOs and Wine prefixes are not removed.

# v0.18.64

## v0.18.84

- Fixes the v0.18.82 COD2 single-player stream teardown when the host CDEmu/VHBA device is unavailable. SP now keeps the already-validated read-only ISO mount and loop-backed D:: as a diagnostic fallback instead of exiting the Wolf child container with rc=90/91.
- Adds `pcga-cdemu-bootstrap`, a boot-safe VHBA reconciler. The versioned upgrader can repair the running kernel with pinned upstream VHBA 20260313 through DKMS when the distro module cannot load; ordinary service starts remain network-free.
- CDEmu host reconciliation now records service/module/DKMS/journal failure context and has a sysfs fallback for resolving CDEmu `/dev/srN`/`/dev/sgN` nodes.
- Streaming diagnostics now include `pcga-cdemu.service`, making the actual host optical-emulation failure visible instead of only the downstream game-container exit.
- COD2 Multiplayer remains isolated on the previously working base Wine 9 + original win32 prefix + existing ISO/loop path. No CDEmu dependency is added to MP.
- Does not reinstall COD2 and does not change the proven Wine D: filesystem mapping.

## v0.18.64
- Fixed a catalog-visibility regression exposed by COD2 restaging. Duplicate-title consolidation could select a different canonical UUID while leaving `catalog_hidden=true` / `duplicate_of=<old-id>` in the newly canonical install-state record, causing the only visible PC Games card to disappear even though the preserved game and setup state still existed.
- Canonical duplicate selection now mildly penalizes already-hidden/superseded sibling states so a stale setup/runtime image cannot outrank the currently visible canonical title during a transient rebuild.
- Whenever duplicate canonicalization chooses a canonical set, PCGA now explicitly clears stale `catalog_hidden` and `duplicate_of` flags from that canonical install-state record.
- The portal now treats visible set metadata as the canonical visibility source and tolerates stale hidden flags in install state until the orchestrator repairs them, preventing a title from vanishing between reconciliation passes.
- Wolf registry reconciliation applies the same self-heal so a recovered title can regain its setup/play app registration without requiring a re-rip or metadata re-selection.
- The upgrader performs a one-time consistency repair for any visible set whose install-state is still hidden. Preserved optical images, COD2's synthetic `COD2DVD` media, and Wine prefixes are not deleted by this migration.
- No COD2 installer/media behavior from v0.18.63 was changed in this release; v0.18.66 is deliberately limited to restoring catalog/runtime visibility before continuing the Error 1311 investigation.

# v0.18.62

## v0.18.62
- Fixed the actual regression exposed by the v0.18.61 diagnostics: host-side COD2 restaging was failing verification because `COD2.msi` still contained `Media.VolumeLabel` values `COD2CD3` and `COD2CD5`, yet the stale previous `setup-source` was left runnable and Wolf launched it anyway.
- Replaced the partial SQL `UPDATE`/`DELETE` Media-table rewrite with an authoritative `Media.idt` replacement. PCGA now exports the complete `Media` table, rewrites the desired rows in memory, imports the whole table with `msibuild -i Media.idt`, and re-exports it for strict verification.
- Cabinet-less COD2 media must verify as exactly one logical Media row, with the first `DiskId`, maximum original `LastSequence`, and every `DiskPrompt`/`VolumeLabel` normalized to the merged `COD2CD1` medium.
- COD2 staging now fails closed: if Media-table verification fails, PCGA deletes the invalid/stale disposable `setup-source`, clears its setup-runtime registration, and refuses to launch the old unprivileged runtime-union fallback. Preserved ISO images remain untouched.
- Added `setup_source_multidisc_merged_v01862`, `setup_source_msi_media_flattened_v01862`, and `.pcga-msi-media-flattened-v01862.json` so the next diagnostics prove that the installer was built from the newly verified source.
- Retains v0.18.61's command-line-neutral MSI tracing, explicit `D:\setup.exe` launch, runnable-payload validation, Wine virtual-desktop setup containment, and DXVK/WineD3D runtime selection.

# v0.18.61

- Removed the COD2 InstallShield `/v"/l*v ..."` injection introduced in v0.18.60; that retail bootstrapper reports error 1629 before its wizard opens when launched with the injected logging command line.
- COD2 setup again launches `D:\setup.exe` with no extra installer arguments, preserving the repaired D:-drive SourceDir path.
- Added command-line-neutral diagnostics: Windows Installer `Logging=voicewarmupx` policy inside the Wine prefix plus `WINEDEBUG=+msi,+msiexec`; generated `MSI*.LOG` files are mirrored into the setup session log.
- Retained v0.18.60 D-drive SourceDir repair, v0.18.59 runnable-payload validation, v0.18.58 single-medium Media-table flattening, merged six-CD SourceDir, virtual-desktop installer containment, and DXVK/WineD3D runtime selection.

# v0.18.59

- Fixed the COD2 post-install launch failure captured after the multi-disc work: Wine was launching `CoD2MP_s.exe` but aborting before Direct3D initialization because `mss32.dll` was missing, returning loader status `c0000135` / process rc 53.
- Added COD2 runtime-payload validation. A READY state now requires a COD2 game executable, `mss32.dll` in the same installed directory, and at least one `main/*.iwd` payload. Existing incomplete READY states are demoted automatically, their mutable Wine prefix is reset, and the six-disc installer is restaged from preserved media.
- Interactive COD2 setup no longer writes `.pcga-install-complete` merely because the legacy bootstrapper returned zero. The setup runtime validates the runnable payload after detached Wine/MSI processes finish; incomplete installs stay setup-required and emit an explicit diagnostic instead of being promoted.
- Added a runtime guard for stale per-player instances: if a surviving COD2 runtime copy is missing `mss32.dll`, PCGA exits immediately with a clear reinstall-required message instead of presenting a short black stream.
- Added an offline preferred-executable rule for COD2: the normal title card now prefers `CoD2SP_s.exe` and uses `CoD2MP_s.exe` only as the second direct-launch candidate. Existing valid READY states can be repaired to the single-player target without reinstalling.
- Retains v0.18.58's single-logical-medium MSI rewrite, host-staged six-CD SourceDir, Wine virtual-desktop installer containment, and DXVK/WineD3D runtime selection.

# v0.18.58

- Fixed COD2 Error 1311 persisting after v0.18.57: normalizing `Media.VolumeLabel` alone did not remove the MSI's logical multi-disc boundary. The staged COD2 MSI is now inspected as a complete `Media` table, including `DiskId`, `LastSequence`, `DiskPrompt`, `Cabinet`, and `VolumeLabel`.
- For COD2's cabinet-less six-CD MSI, PCGA collapses the disposable staged `Media` table to one logical row: the first `DiskId` is retained, its `LastSequence` is extended to the maximum original sequence, and its prompt/volume label are normalized to the merged `COD2CD1` source. This prevents Wine MSI from advancing to a second logical medium while all loose files are already present in the merged SourceDir.
- If a COD2 MSI contains cabinet-backed media rows, PCGA fails conservative: it preserves those row boundaries, normalizes labels/prompts, verifies external cabinet availability, and creates only unambiguous root aliases. Preserved ISO images remain immutable.
- Added `.pcga-msi-media-flattened-v01858.json` to the disposable setup tree. Setup diagnostics print a bounded audit of the pre/post Media table so the next capture proves exactly what MSI was executed.
- COD2 v0.18.57 states are restaged once under `setup_source_multidisc_merged_v01858`; the failed mutable setup prefix and setup runtime are rebuilt without touching preserved optical images.
- Prevented premature READY promotion while a title's interactive setup container is still active. Current interactive installs require the completion marker before promotion, preventing a partially copied COD2 executable from being mistaken for a completed install while Error 1311 is still on screen.

# v0.18.57

- Fixed COD2's next multi-disc installer boundary: after v0.18.56 made the merged `Z:\pcga-source` payload readable, Windows Installer advanced to its CD2 `Media` row and raised Error 1311 because the staged source still presented only the CD1 volume label.
- Added `msitools` (`msiinfo` + `msibuild`) as an appliance dependency for deterministic inspection/editing of staged Windows Installer databases.
- During COD2 six-CD staging, PCGA identifies the title MSI, records its pre-patch `Media.VolumeLabel` values, normalizes every Media row to the synthetic merged label `COD2CD1`, re-exports the table, and fails closed if verification does not match.
- The MSI edit is applied only to the disposable `setup-source`; preserved optical images remain immutable.
- Added `.pcga-msi-media-normalized.json` to the staged tree and setup-session diagnostics so future captures prove whether the normalized Media table was actually used.
- Corrected merged Wine `D:` presentation: AUTO mode now uses the directory-backed staged source without a competing raw `d::` block-device link, while still registering D: as `cdrom` and using `.windows-label` for volume identity.
- Existing v0.18.56 COD2 setup state is restaged under `setup_source_multidisc_merged_v01857`, the failed setup prefix is reset, and the setup runtime is rebuilt automatically.

# v0.18.56

- Fixed the COD2 `1603` root cause shown by v0.18.55 diagnostics: MSI was copying from `Z:\pcga-source`, not the runtime-only merged `D:` tree, and failed specifically on `Setup/Data/main/iw_02.iwd` with file-not-found error 2.
- Replaced COD2's unprivileged in-container merge as the primary path with a host-side temporary setup-source merge assembled by the root orchestrator from all six preserved images.
- Logical media order is recovered from `COD2CD1`..`COD2CD6` labels, so scrambled archive slots are handled deterministically. CD6 is staged first and CD1 last.
- The staged tree is validated for `setup.exe` and `Setup/Data/main/iw_02.iwd`, normalized world-readable for uid 1000, and tagged with the CD1 Wine helper label.
- During COD2 setup, `/pcga-source` and MSI SourceDir `Z:\pcga-source` expose the same complete six-disc file tree.
- Existing failed COD2 setup states from v0.18.54/55 are migrated automatically; after successful restaging PCGA resets only the mutable failed Wine prefix and rebuilds the setup runtime.
- Added explicit pre-GUI probes for the host staged path, the MSI `Z:` SourceDir, and `D:` so the next media-validation boundary could be diagnosed.
- Preserved optical images remain immutable; the merged source is disposable staging and is removed after successful installation.

# v0.18.55

- Added explicit PCGA Direct3D backend management instead of relying on the unused Lutris runner defaults. Generated Wolf/Wine game sessions now choose DXVK or WineD3D themselves.
- **Automatic** graphics mode probes `vulkaninfo --summary`, rejects Lavapipe/llvmpipe CPU Vulkan and Vulkan API versions below 1.3, and safely falls back to WineD3D when hardware Vulkan is not usable.
- Automatic/DXVK mode provisions pinned Winetricks verb `dxvk2062` (DXVK 2.6.2) into the mutable game prefix and records the D3D9 native DLL override in runtime diagnostics.
- Added Portal Settings → PC Games → **Direct3D graphics backend** with Automatic, Prefer DXVK, and WineD3D/OpenGL options.
- Added optional `PCGA_DXVK_HUD=1` verification and `[pcga-graphics]` logging for Vulkan device/API, provisioning, selected backend and fallback reason.
- DXVK is game-runtime only: OpenGL and DirectDraw-era titles retain their existing paths, and interactive installer containment remains unchanged.
- Retained all v0.18.54 COD2 merged-media and v0.18.53 installer/session fixes.

# v0.18.54

- Call of Duty 2 six-CD setup sessions now synthesize a read-only merged install-media view at Wine `D:` instead of relying on live `D:` symlink swaps while Windows Installer is copying payload files.
- COD2 volume labels such as `COD2CD1`..`COD2CD6` are used to recover physical disc order even when preserved-media slots were ingested in reverse order.
- The merged view overlays physical CD6 through CD1, matching established COD2 CD-to-DVD installation layouts so CD1 wins duplicate bootstrap files while unique `Setup/Data` payloads from every disc remain visible.
- Original preserved images stay immutable and continue to be exposed individually on E:..J:; the raw CD1 loop device supplies optical identity while `D:` serves the merged file tree.
- Setup diagnostics now probe `D:\\Setup\\Data\\main\\iw_02.iwd`, the exact payload path historically associated with COD2 Wine/Windows Installer 1603 failures.
- The stream toolbar shows an active **AUTO** media state for COD2 setup; numbered disc buttons remain available only as explicit manual overrides.
- The v0.18.53 Wine virtual-desktop/modal containment remains enabled, so this release fixes the next installation stage without regressing the key-code dialog fix.

# v0.18.53

- Interactive Wine setup sessions now run inside a dedicated `PCGASetup` Wine virtual desktop, keeping legacy InstallShield parent/modal z-order inside Wine instead of exposing each top-level dialog separately to nested Sway/Xwayland.
- This addresses the COD2 key-code state where Wine and the setup container remain alive but the visible parent becomes effectively non-interactive, consistent with a hidden/behind modal dialog owning input.
- Installer-only defaults disable esync/fsync (`WINEESYNC=0`, `WINEFSYNC=0`) to reduce synchronization edge cases in old setup engines without changing normal game runtime behavior.
- Nested Sway setup sessions now default to software cursors (`WLR_NO_HARDWARE_CURSORS=1`), avoiding the hardware-cursor/swapchain path associated with the repeated `No free output buffer slot` errors in the COD2 trace.
- Setup diagnostics now identify the launch mode and desktop size; direct Wine remains available as a diagnostic fallback with `PCGA_SETUP_VIRTUAL_DESKTOP=0`.
- The v0.18.52 durable Resume setup/game and non-destructive Reconnect video behavior is retained unchanged.

# v0.18.52

- Active PC game/setup sessions are now first-class resumable portal objects. The Sessions modal exposes **Resume game/setup** beside **End session**, reconnecting the browser lane while leaving the existing Wine container alive.
- PC game library cards and game-detail pages now show **SESSION ACTIVE / SETUP ACTIVE** and a **Resume** action for sessions owned by the current persistent portal client instead of offering a duplicate Play/Install launch.
- Clicking Play/Install for a title that this browser already owns now resumes that session by default rather than reserving another Moonlight lane and starting a duplicate Wine desktop.
- The stream toolbar renames ambiguous **Reload** to **Reconnect video** and explicitly keeps the Wine/game container alive while the embedded Moonlight client reconnects.
- PC game library opening now refreshes durable session ownership first, so browser reload/navigation can rediscover active sessions from the host-side session-owner registry.
- This recovery path addresses the COD2 setup trace where the setup container remained alive after the CD-key step while the nested compositor emitted `No free output buffer slot`; PCGA no longer treats loss of the browser surface as loss of the installer session.

# v0.18.51

- Compatibility sweeps now print a final **PORTAL MANUAL TEST CANDIDATES** list containing every passing title, its canonical UUID, suggested `PLAY`/`INSTALL` portal action, and the visible game/installer window that satisfied the probe.
- Attention results and failures are printed in separate terminal sections so a user can immediately decide which titles to exercise manually through the portal.
- Compatibility report schema is now 4 and persists `portal_test_candidates` plus `attention_candidates` for downstream tooling.
- `game-archive game-compat-report` remains JSON-only by default; `game-archive game-compat-report --summary` prints the same human-readable candidate list from the latest saved report.

# v0.18.50

- Multi-disc setup recovery now preserves and reuses `source_isos` / `runtime_media`, and can recover conservatively title-linked source-only optical rows, when canonicalization has moved current intake ownership away from the launchable title. A demotion to `setup-required` can no longer erase the only preserved-media path needed to restage the installer.
- Multi-disc installer recovery scans every preserved disc and selects the strongest autorun/vendor bootstrapper instead of assuming the current runtime slot 1 is the installation disc. The chosen media slot becomes the initial active D: for setup.
- Wolf post-reload verification now ignores setup/ready states that do not yet have a generated setup/runtime image, preventing an intentionally demoted title from being misreported as a dropped Wolf app.
- Compatibility probes use a non-production container name and a probe label so the periodic PCGA transient-container reaper cannot delete a fast-crashing test before its traceback is captured.
- Fixed setup-image preflight serializing Python `None` as the literal Docker image name `None`.
- Compatibility report schema 3 distinguishes auxiliary registration/configuration windows from confirmed game windows and reports them as `attention` instead of a false pass.

# v0.18.49

- Compatibility probes now inherit Wolf-equivalent device access: `GOW_REQUIRED_DEVICES`, supplementary device GIDs, `/dev/dri`, input/sound devices, and a private `/run/user/wolf` XDG runtime directory. This removes the v0.18.48 false failures where every probe lost render-node access and fell back to software rendering.
- Compatibility sweeps now restart Wolf/Wolf-Den before catalog reconciliation, leaving the orchestrator as the final writer/reloader of managed app blocks instead of allowing a post-reconcile Wolf-Den restart to erase a freshly repaired registration.
- Production Wolf app profiles now include PCGA optical block devices in `GOW_REQUIRED_DEVICES`, improving raw CD/DVD access for Wine drive-type and copy-protection probes.
- Wolf batched reloads verify that every pending UUID-managed app block survived the daemon reload; one bounded in-place repair/restart is attempted if Wolf rewrites the config.
- Multi-disc `portable-copy` recovery now falls back to persisted `runtime_media` and declared disc counts when intake-source ownership has moved, so a six-disc COD2 record cannot remain READY merely because `scan_sources()` no longer returns its original source rows.
- Duplicate convergence recognizes sufficiently long colon-subtitles as conservative aliases (for example `JEDIOUTCAST` ↔ `Star Wars Jedi Knight II: Jedi Outcast`) while keeping the stronger installed runtime as canonical.

# v0.18.48

- Fixed compatibility-test false negatives caused by missing Wolf-injected `/tmp/.X11-unix` and `/run/user/wolf` runtime directories.
- Compatibility sweeps now test only canonical `ready` / `setup-required` records and report source-only metadata remnants separately under `ignored_records`.
- Current-probe tracebacks no longer mix in stale historical installer/runtime logs.
- Added registry-wide Wolf app reconciliation so every launchable canonical state owns the current UUID-derived app block even when it has no active intake source mapping.
- Updated sweep summary fields to distinguish tested games from ignored preservation/source records.

# v0.18.47

- Added `pcga-game-compat-test`, an appliance-wide canonical game launch sweep.
- The sweep safely removes only validated transient Wolf game/setup children before testing and restarts Wolf/Wolf-Den from a clean state.
- Added isolated disposable probes for both ready game runtimes and setup-required installer runtimes; preserved media, install templates, and player homes are never modified.
- Ready games must keep a non-error Xwayland window alive for 15 seconds; immediate/early Wine crashes now fail the sweep instead of being counted as launchable.
- Each result includes `failure_reason`, `failure_traceback`, bounded Docker logs, visible window titles, exit status, Wolf registration diagnostics, selected launcher/installer, and static media/prefix/image findings.
- Reports are checkpointed during the run and saved to `/var/lib/pc-game-archive/game-compat-tests/latest.json` plus timestamped report history.
- Added `game-archive game-compat-test` and `game-archive game-compat-report`.

# v0.18.46
- Multi-disc titles that are still marked `portable-copy` are re-evaluated on every reconciliation until they actually leave that invalid state; stale v0.18.39/v0.18.44 migration markers can no longer preserve the broken COD2 launcher.

- Replaces metadata-derived Wolf application titles with immutable UUID-derived internal keys (`PCGA Game <id>` / `PCGA Setup <id>`) so punctuation such as `:` can never corrupt Docker bind-volume syntax.
- Separates the portal/stream display title from the Wolf internal title, preserving friendly metadata in the UI while keeping runtime identifiers stable across metadata edits.
- Uses UUID-derived transient Docker child names rather than mutable game titles.
- Reaps running `PCGA-*` child containers after their logs prove that Wine/setup entered a terminal failure path, preventing failed desktops from blocking unrelated Wolf catalog reloads.
- Reduces failed-setup postmortem grace from 20 seconds to 1 second because setup diagnostics are persisted to host storage.
- Changes the PC-game orchestrator recovery cadence from five minutes to one minute with a shorter randomized delay.
- Adds `launchable` / `setup_launchable` portal state so READY or installer-ready titles retain **Retry stream** / **Retry installer** actions after a failed attempt; otherwise the card exposes **Repair launch** instead of becoming actionless.
- Upgrade-time cleanup removes only already-terminal failed transient child containers before the synchronous local reconciliation pass.

# v0.18.45

- Re-ranks already-staged interactive setup sources instead of repairing only missing/MSI targets; stale nested helpers such as `GameData/Setup.exe` can be replaced by the current disc-authored/root bootstrapper.
- Adds one v0.18.45 preserved-disc-root verification for suspicious single-title setup targets even when an old v0.18.39 scope-repair marker is present or the stored `source_path` has already become `.`.
- Treats `AdbeRdr*`, Adobe/Acrobat Reader, DirectX/.NET/VC redistributable, PhysX, PunkBuster/GameSpy, and `LaunchBFII`/`LaunchEAW` package identities as weak/non-game evidence.
- Applies the same bundled-payload filtering in the optical game metadata collector so future discs do not become catalog titles named after bundled support software.
- Invalidates and rebuilds the setup Wolf runtime whenever a stale target is replaced; preserved optical media and existing recoverable Wine data remain intact.
- Retains Battlefront II direct-executable/windowed compatibility and the bounded managed-runtime fallback for a genuinely correct CLR-based installer.

# v0.18.44

- Forces legacy multi-disc `portable-copy` states back through disc-root installer discovery even when an older v0.18.39 migration marker is present.
- Penalizes multi-disc portable runtimes during canonical selection and metadata-target resolution, so a setup/completed Wine prefix wins over a copied optical `Launch.exe`.
- Normalizes preserved-source identities before duplicate grouping and expands convergence to linked installed/metadata UUIDs that no longer own a current source mapping.
- Uses current and historical state/database title aliases when linking duplicate UUIDs, then preserves the strongest runtime while migrating user-selected metadata/artwork.
- Detects Wine's crash debugger (`winedbg`) in both primary-start and detached-child phases; unhandled game crashes now terminate Wine and the transient Wolf child container rather than holding a black stream.
- Filters superseded/hidden PC-game logs from the current diagnostic catalog and shows only the log appropriate to the title's current setup/runtime state.
- Adds compact diagnostic snapshot schema 2: only services in the selected profile are exported and per-log duplicate service metadata is omitted.
- Carries forward v0.18.43 AutoRemove/session teardown, v0.18.42 Python warning cleanup, v0.18.41 multi-disc/prefix repair, and v0.18.40 selectable metadata profiling.

# v0.18.43

- Makes Wolf-created PCGA game/setup desktops transient Docker state: generated app definitions set `HostConfig.AutoRemove=true`, while portal session termination now performs `docker stop` followed by `docker rm -f`.
- Prunes exited legacy `PCGA-*` child containers before Wolf-reload safety checks so dead desktops no longer block catalog reconciliation or remain in diagnostics indefinitely.
- Adds a Sway/Xwayland window watchdog to Wine runtimes. A process that stays alive without ever mapping a game window is terminated as a black-screen launch, and detached Wine helpers are killed after the last game window disappears instead of keeping the container alive for the former 12-hour `wineserver -w` timeout.
- Removes the misleading **Streaming status** card/detail action. The portal now distinguishes ready-to-stream, installer-ready, preparing-stream, and stream-error states while **Sessions** remains the source of truth for actually running desktops.
- Strengthens duplicate convergence so persisted merge history, identical RAWG IDs, shared non-compilation preserved media, and conservative acronym aliases such as `cod2` ↔ `Call of Duty 2` can identify one logical title even after metadata renamed only one historical UUID.
- Keeps the strongest working runtime UUID as canonical and migrates the newest user-selected web metadata plus cached artwork onto it rather than replacing a functioning launcher with a weaker metadata-only record.
- Resolves future metadata application onto the strongest linked runtime UUID, preventing the profiler from creating a separate metadata-paired card beside the usable launcher.
- Removes a duplicate legacy portal `pcGameMetadataApply` function that could override the v0.18.40 select/preview/apply workflow and make **Use selected metadata** ineffective.
- Retains the v0.18.41 multi-disc portable-state repair, portable Wine-prefix seeding, bundled-installer filtering, and v0.18.40 broader selectable RAWG profile search.
- Removes the Python 3.12 `invalid escape sequence '\('` validation warning and promotes `SyntaxWarning` to an error in release Python validation.

# v0.18.40

- Reworks the PC-game profiler into an explicit **search → select/preview → apply** workflow so web metadata is never committed merely because a result appeared in search.
- Broadens RAWG discovery beyond the old one-shot precise PC query: PCGA now merges precise PC, broad PC, cleaned-title, and global fallback searches, deduplicates provider IDs, and ranks the combined candidates.
- Adds search-term cleanup for noisy optical/setup identities such as `COD2CD1`, `setupBF2`, `Disc 1`, `DVD-ROM`, `syscheck`, installer/update labels, while retaining the exact user-entered query as the first search.
- Penalizes obvious setup/updater catalog results when a cleaned game-title query is available, reducing cases where utility-like matches hide the real game.
- Accepts a pasted RAWG game URL or numeric RAWG ID as a direct profile lookup path.
- Adds a read-only full-profile preview before application, including release date, developer, publisher, platforms, genres/tags, description, ESRB/Metacritic/RAWG rating fields, official website, and remote artwork when supplied.
- Makes result selection visually persistent and provides a single **Use selected metadata** action; the existing user-authoritative/locked metadata semantics and preserved-media ownership remain unchanged.

# v0.18.39

- Repairs PC-game launch target selection using the v0.18.38 streaming snapshot: maintenance helpers such as `fpupdate.exe`, `syscheck.exe`, update/patch/config tools, `IDriver.exe`, and `CDKey.exe` no longer qualify as game binaries.
- Gives exact/near-exact game executable names a strong score and adds direct Star Wars Empire at War / Forces of Corruption preferences so an installed prefix converges on `swfoc.exe`, `sweaw.exe`, or `starwarsg.exe` rather than an updater.
- Changes duplicate canonical scoring to prefer a recoverable completed Wine installation over a copied optical `portable` payload. A READY state with a stale helper launch target is scored by whether the prefix contains a valid replacement.
- Treats auto-derived edition strings as weak during duplicate consolidation; only explicitly user-confirmed distinct editions block merging.
- Stops ordinary single-title discs from narrowing installer discovery to metadata hint subdirectories such as `GameData`; only true compilation/anthology records use subdirectory source mappings.
- Migrates already-staged non-compilation setup sessions back to the preserved disc root without re-ripping, rebuilding only the mutable setup source/runtime.
- Adds bounded managed-installer recovery: if a correct interactive setup immediately reports `Wine Mono is not installed`, PCGA first tries a local Wine-Mono MSI and then a bounded Winetricks `dotnet40` fallback before retrying once.
- Hardens installed-template permissions both in the orchestrator and upgrade migration so Wolf uid 1000 can copy legacy `portable` templates before Wine starts.
- Runs one synchronous no-network game-repair pass during upgrade so launch-target repair, setup-root restaging, duplicate convergence, and permission normalization are applied before the PC Games UI is reopened.

# v0.18.38

- Consolidates duplicate PC-game library records into one canonical card while retaining superseded install/source state for recovery and diagnostics.
- Adds an orchestrator migration that selects the strongest existing ready/setup record, merges preserved source bundles into it, marks duplicate UUIDs as superseded, and removes their stale Wolf app blocks so same-title GameStream entries no longer collide.
- Serializes pre-rip game-set metadata updates across optical drives, preventing two drives that finish at the same time from minting separate UUIDs for the same title.
- Recognizes compact multi-disc mastering labels such as `COD2CD1` / `COD2CD2` as one title family while preserving sequel numbers such as the `2` in `COD2`.
- Repairs portable-game runtime templates whose ISO-derived directory modes were unreadable to Wolf's uid 1000, fixing `/pcga-template/portable: Permission denied` launch failures without changing preserved images.
- Rejects installer/runtime helpers such as `IDriver.exe` and `CDKey.exe` as game launch targets and treats leaked helper names such as `setupBF2` and `CDKey` as weak identity evidence.
- Redirects historical duplicate game/profile URLs to the canonical title after migration so old activity links remain useful.

# v0.18.37

- Fixed `pcga-network-identity` parsing of the secure-context state after DHCP/TLS reconciliation.
- Replaced the space-separated `read` handoff with newline-delimited `mapfile` parsing so the result is independent of the script's restricted global `IFS`.
- Added explicit validation for the parsed IPv4 address and the two boolean reconciliation flags.
- Allows systems where v0.18.36 already updated `.env`/TLS before failing to complete the same reconciliation safely without regenerating the trusted local CA.

# v0.18.36

- Added boot-time dynamic LAN identity reconciliation so a DHCP address change updates `PCGA_LAN_IP` before secure streaming, DNS, or thin-client services start.
- Changed secure-context address discovery to prefer the current default-route source address over the persisted `.env` value; the old value is now only a last-resort fallback.
- Made `PCGA_LAN_IP` updates atomic and tied certificate issuance to the discovered address, while preserving the long-lived PCGA local CA so already-trusted clients do not need to trust a new root certificate.
- Added `pcga-network-identity.service` ordered after `network-online.target` and before the game stack, LAN DNS, service-auth, and thin-client bootstrap services.
- Reloaded `pcga-status` when the leaf certificate changes and recreated the four Moonlight Web lanes only when their certificate or WebRTC/NAT identity must change.
- Made LAN DNS and Moonlight bootstrap prefer live routing information instead of a stale persisted DHCP address.
- Added game-stack reconciliation for Wolf/Moonlight containers that Docker auto-started with an old `WOLF_INTERNAL_IP` or `WEBRTC_NAT_1TO1_HOST`.
- Added upgrade validation that `.env`, the TLS SAN, and every Moonlight lane all advertise the current DHCP-selected IPv4 address.

# v0.18.35

- Fixed optical installer selection so disc-authored `autorun.inf` targets and vendor bootstrap executables such as `setup.exe` outrank raw MSI payloads.
- Added an in-place repair for v0.18.34 setup states that staged an MSI even though the preserved disc contains a higher-level executable bootstrapper; no re-rip is required.
- Multi-disc titles now stage a concrete disc-1 bootstrapper for the interactive Wolf/Moonlight setup session instead of stopping at a generic `setup-required` state.
- Added Disc 1/2/3… controls directly to the full-screen PC-game stream toolbar when a title owns more than one logical disc.
- Made portal disc switching session-scoped and client-owned: switching D: in one Wine desktop does not change another client's simultaneous session of the same title.
- Persisted the active disc in per-session ownership state while retaining the old game-set-wide switch behavior for legacy callers.
- Added installer-ranking and portal/control-plane validation for the multi-disc setup path.

# v0.18.34

- Added a persistent shared `legacy-games` Docker bridge for Wolf-created Wine game/setup desktops.
- Attached LANCommander to both the PCGA default Compose network and `legacy-games`, preserving portal/catalog connectivity while giving game sessions a stable LAN-side service hostname.
- Set Wolf PC-game Docker runners to `NetworkMode=legacy-games`; simultaneous sessions now receive independent addresses on one appliance-local L2 segment.
- Added LANCommander/IPX relay discovery variables to each Wine runtime (`lancommander:1337`, UDP/213).
- Pinned LANCommander to v2.1.16.
- Added game-stack boot reconciliation for a missing/pruned shared game network.
- Exposed runtime LAN IP/network information through the PC-game session API and Sessions modal.
- Kept per-client multi-session ownership from v0.18.33 intact; shared LAN membership does not weaken client-scoped stop/session controls.
- Added upgrade validation that LANCommander is attached to `legacy-games` and generated Wolf app runners are configured for that network.
- Physical home-LAN bridging remains intentionally out of scope for this phase.

# v0.18.33

- Adds a four-lane Moonlight Web pool (ports 8101–8104). Every lane has independent persistent Moonlight/Wolf pairing state so simultaneous Wine desktops do not share one GameStream client certificate.
- Gives each browser a stable PCGA portal-client ID and reserves a stream lane before launch. Wolf runtime containers are claimed back to that client/lane reservation and persisted in `/var/lib/pc-game-archive/game-runtime/session-owners.json`.
- Converts the embedded PC-game stream into a multi-session workspace. **Back** hides the workspace without unloading its iframes; launching another game creates another live tab; switching tabs returns to the existing desktop.
- Scopes **PC Games → Sessions**, **End session**, and **End my sessions** to the requesting portal client. Another browser/client's owned sessions are never selected by these actions.
- Makes pending reservations releasable before Wolf creates a container and preserves reservation ownership metadata through validated Docker shutdown.
- Starts, bootstraps, and health-checks all four Moonlight Web lanes during upgrade and normal game-stack startup. Tailscale Serve publishes all four ports for the same behavior on remote thin clients.
- Keeps Wolf app-catalog reload safety global: a catalog restart is deferred while any managed runtime is active, while already-registered apps can launch concurrently across lanes.

# v0.18.32

- Adds server-side RAWG search for canonical PC-game metadata, using a root-readable API key configured from the portal rather than exposing provider credentials to the browser.
- Adds **Search game database** to preserved-disc assignment and **Find metadata** to existing PC-game details.
- Lets one user selection create/update a canonical title profile and optionally assign the current preserved disc to that title in the same operation.
- Stores title, release date/year, developer, publisher, genres/tags, description, website, ratings/age-rating fields, RAWG external ID, source URL and attribution when available.
- Caches selected artwork, hero images and screenshots into PCGA's existing per-title asset directory so profiles remain useful when the database is temporarily unavailable.
- Marks explicitly selected profiles `locked_by_user`; periodic Steam enrichment no longer overwrites the user's canonical database selection.
- Preserves title-owned `optical-disc-set` media/fingerprints and all immutable ISO/BIN/checksum artifacts while metadata is replaced.
- Adds RAWG attribution links to search results and any library/profile surface displaying RAWG-derived metadata.

# v0.18.31

- Adds **PC Games → Disc images**, a portal inventory of preservation-backed PC optical rips with fingerprint, volume label, ISO/BIN format and size, archived bundle path, ownership, and disc-set metadata.
- Keeps successfully preserved but not-yet-classified images visible so a user can recover from bad or incomplete automatic identification.
- Adds host control actions `pc-game-disc-library`, `pc-game-disc-assign`, and `pc-game-title-create`.
- Lets users reassign a ripped image to an existing title and set disc number, disc count, and role, or create a missing title from the same workflow.
- Makes reassignment preservation-safe: image payloads/checksums are untouched, while both the canonical fingerprint record and matching `.pcga-game.json` archive sidecars are synchronized.
- Rebuilds both old and new title `optical-disc-set` inventories after reassignment and asks the game orchestrator to reconcile affected titles.

# v0.18.30

- Makes the PC game title/set record the canonical owner of optical media. Each title now carries an `optical-disc-set` inventory with disc fingerprints, number/count, role, label, layout, and review status.
- Adds conservative title-family matching so later discs from an explicitly multi-disc title attach to the existing title instead of automatically becoming separate library games.
- Migrates existing title records from canonical disc metadata during upgrade without deleting or rewriting preserved disc records.
- Attaches every logical title disc to the same Wolf/Wine session. Multi-disc titles expose stable archive mappings on E:/F:/G:… while D: is the active legacy optical drive.
- Adds `/tmp/pcga-disc-switch` and the `pc-game-disc-switch` control action so D: can change to another already-attached preserved disc without restarting the stream.
- Persists the active disc in install state and exposes title media/disc state through the PCGA game profile API.

# PC Game Archive v0.18.29

## 0.18.29

### Merged Wine optical-drive repair

- Merged the two v0.18.28 optical-drive branches without discarding either branch's safety checks.
- Preserved ISO filesystem views remain mounted read-only, while the corresponding host `/dev/loopN` devices are passed read-only into Wolf children as `/dev/pcga-media-discN` and used for Wine `X::` raw-device mappings.
- Jedi Outcast keeps its appliance-owned compatibility overlay at `D:` (`d:` -> `.pcga-virtual-cd-d`) while `d::` points at the preserved block device selected by matching the real filesystem label when possible.
- `HKLM\Software\Wine\Drives` is written through both `/reg:32` and `/reg:64`, preserving the earlier branch's cross-bitness drive-type repair.
- Runtime diagnostics verify the volume label and query Win32 logical disks; the target state is `D:` = `DriveType 5` with `VolumeName JEDIOUTCAST`.
- The original game executable remains unmodified.

## 0.18.28

### Wine optical block-device passthrough

- Fixed the remaining Jedi Outcast retail CD check: v0.18.27 exposed the correct `JEDIOUTCAST` label and required files, but Wine reported `D:` as `DriveType 3` because only a directory drive existed and `dosdevices/d::` was absent.
- PCGA now records the read-only host `/dev/loopN` backing each preserved ISO and passes it into the Wolf child container as `/dev/pcga-media-discN` with read-only device permissions.
- Wine `X:` continues to point at the mounted/compatibility filesystem view while `X::` points at the actual block device, matching Wine's CD-ROM device model.
- Drive type metadata is written to both 32-bit and 64-bit `HKLM\Software\Wine\Drives` views.
- Compatibility virtual CDs prefer a preserved disc whose filesystem label matches the expected label, so Jedi Outcast's synthetic `D:` uses the real `JEDIOUTCAST` media as its raw backing device when available.
- No game executable is modified.

## 0.18.27

### Wine GUI-generation reset after headless prefix/media probes

- Fixed the remaining black-screen path exposed after v0.18.26: Xwayland itself is reachable, but Wine still reports `nodrv_CreateWindow` because PCGA performs prefix/media registry probes with Wine before GOW starts Sway. Those pre-compositor Wine commands can leave `wineserver`/Explorer helper processes alive from a headless generation.
- After the Xwayland readiness barrier succeeds, the runtime now terminates any Wine helpers created by the earlier media/registry probes, re-checks the X endpoint, and only then starts the real game. This makes the game the first GUI Wine client of a fresh wineserver generation with `DISPLAY` already valid.
- The same reset is applied before interactive installer GUIs because prefix validation, `wineboot`, Winetricks, and optical-drive registration can also run before the compositor.
- Added `Wine GUI launch boundary ready` diagnostics with `DISPLAY`/`XAUTHORITY` plus an explicit failure if Xwayland becomes unreachable between the readiness probe and Wine launch.
- Retains the working `JEDIOUTCAST` virtual CD, direct `jk2sp.exe` selection, NUL-delimited argv transport, and v0.18.26 Xwayland readiness barrier.

## 0.18.26

### Xwayland launch-readiness barrier

- Fixed a direct-game startup race where the Wine process could begin before Sway/Xwayland was ready to accept X11 clients. The failure appears as `nodrv_CreateWindow` / `Make sure that your X server is running and that $DISPLAY is set correctly` while the Moonlight stream itself remains healthy and black.
- The generated Wine session wrapper now waits up to 15 seconds for a usable Xwayland display before launching the game. It honors Sway's inherited `DISPLAY`, discovers the X11 Unix socket when necessary, and uses `xdpyinfo` or `xset` as an active readiness probe when either utility exists.
- Minimal images without an X11 probe utility fall back to the X11 socket plus a short settle delay. A readiness timeout now exits explicitly with rc=71 instead of launching Wine into a guaranteed black session.
- Added `[pcga-wine-session] waiting for Xwayland` and `Xwayland ready` diagnostics so future captures distinguish compositor readiness from game/runtime failures.
- Retains v0.18.25's NUL-delimited argv repair and v0.18.24's working `JEDIOUTCAST` compatibility-CD presentation.

## 0.18.25

### Streamed Wine argv repair

- Fixed a nested escaping bug in the generated PC-game runtime: the orchestrator's Python f-string emitted a literal NUL byte into `startup.sh` instead of the shell text `\0`. Bash ignored the embedded NUL, causing the target executable and all compatibility arguments to be concatenated into one filename before Wine was launched.
- Runtime and setup handoffs now preserve real NUL-delimited records and reconstruct them with `mapfile -d ''`.
- Added a shell-safe `[pcga-wine-session] argv:` diagnostic so future captures show exactly which executable and arguments Wine received.
- Added release validation for the double-escaped NUL source representation and a generated-runtime regression test covering `Program Files (x86)` plus id Tech 3 `+set` arguments.
- Retains v0.18.24's direct `jk2sp.exe` preference and `JEDIOUTCAST` compatibility CD presentation.

## 0.18.24

- Prefer the direct Jedi Outcast `jk2sp.exe` game binary over the retail `JediOutcast.exe` launcher shell and repair existing READY states automatically.
- Persist a successful interactive-install completion marker and finalize stopped setup sessions immediately through the host control plane, so subsequent streams do not require another full installation.
- Add an appliance-owned Wine virtual-CD recipe for retail Jedi Outcast. It presents the expected `JEDIOUTCAST` label and CD sentinel paths while preserving the source ISO read-only and without modifying the game executable.
- Reserve the compatibility CD letter and shift raw preserved-disc mappings to later drive letters when necessary.


## Session shutdown feedback

- Add an immediate visual shutdown state when a user ends a PC game or setup session from the portal.
- The active session row changes to an amber in-progress state, shows a spinner and **Ending…**, and reports that PCGA is waiting for the runtime container to exit.
- **End all** now shows **Ending all…** while the stop request is in flight and disables duplicate stop actions.
- Ending a session from the embedded stream keeps the stream overlay visible, dims the frame, disables conflicting stream controls, and shows **Ending…** until the host confirms container shutdown.
- The portal also emits an informational status message immediately after the user confirms the action, so a slow graceful container stop no longer looks like an ignored command.
- Reduced-motion clients receive a static busy indicator instead of a rotating animation.

## Previous v0.18.22 notes

## Streaming compositor compatibility regression

- Fixes a v0.18.21 runtime regression where game-specific OpenGL compatibility variables such as `MESA_EXTENSION_MAX_YEAR=2003` were exported before Games-on-Whales launched Sway.
- Those variables are now scoped only to the Wine game process and its children. Sway/wlroots starts with the host Mesa feature set, while Jedi Outcast still receives the extension-string workaround it needs.
- Runtime logs now say `applying game-process environment` to make this boundary explicit.
- Preserved-disc mappings remain diagnostic and non-fatal; a failed `VOL` probe no longer obscures the compositor root cause.

## Previous v0.18.21 notes

## Retail CD-ROM runtime presentation

- Present each preserved PC-game ISO to Wolf/Wine as read-only optical media instead of discarding the source after installation.
- Create stable host loop mounts at `/run/pcga-game-media/<game-set>/discN` and bind both the mounted filesystem and original ISO into the managed Wolf runtime.
- Map preserved media to Wine `D:`, `E:`, ... drives, create both `d:` and raw `d::` dosdevice links, and mark each drive `cdrom` in `HKLM\Software\Wine\Drives`.
- Log `wine cmd /c vol <drive>:` at launch so diagnostics show the volume label Wine actually sees.
- Repair already-installed games without reinstalling by reusing `source_isos` from the install state.
- Keep the media read-only and preservation-backed; no game executable patching or synthetic no-CD payload is used.
- Run the orchestrator in the host mount namespace (`PrivateTmp=false`) so Docker can bind the loop mounts, and run the orchestrator 15 seconds after boot so `/run` media mounts are recreated promptly after reboot.
- This closes the Jedi Outcast progression failure where the renderer starts successfully but the retail build reports `CD not in drive` when starting a game.

## v0.18.20 consolidated baseline carried forward

- Preserve the cumulative compatibility-resolver, portal session-management, Wolf reconciliation, streamed-Wine launch, prefix-recovery, and Jedi/id Tech 3 compatibility work consolidated in v0.18.20.
- Treat Moonlight RTSP success / first-video-packet receipt as transport evidence only, not as proof that the Wine game process is healthy. Runtime/setup exit diagnostics remain authoritative for application-launch failures.

## Legacy OpenGL / streamed Wine launch fixes

- Add an appliance-owned known-good compatibility rule for **Star Wars: Jedi Knight II - Jedi Outcast** (Steam AppID `6030`, with narrow retail-title fallback) and **Jedi Academy** (`6020`). The rule applies `MESA_EXTENSION_MAX_YEAR=2003` for Mesa/AMD/Intel and `__GL_ExtensionStringVersion=17700` for NVIDIA so the original id Tech 3 renderer cannot overflow its fixed-size OpenGL extension buffer on modern drivers.
- Apply normalized compatibility `runtime_environment` values directly to the streamed Wine process instead of merely displaying them as provider evidence.
- Permit repeated ProtonDB evidence to auto-apply only the two allow-listed Wine/OpenGL variables (`MESA_EXTENSION_MAX_YEAR` and `__GL_ExtensionStringVersion`); Proton-specific environment knobs remain advisory.
- Keep Jedi Outcast/Academy windowed at 1920x1080 inside the PCGA compositor through declarative launch arguments; prefer the real game executable over wrappers.
- Replace the Games-on-Whales launcher argv handoff with a NUL-delimited argument file and a fixed no-argument wrapper. Windows install paths such as `Program Files (x86)` therefore survive the launcher boundary without `/bin/sh` interpreting parentheses.
- Strengthen setup-prefix validation: a prefix must pass a real `wine cmd /c ver` loader probe, not merely contain `kernel32.dll`; unusable mutable prefixes are rebuilt and revalidated before the installer starts.
- Retain the earlier missing-`kernel32.dll` recovery path while also detecting the harder case where `kernel32.dll` exists but Wine still cannot load it.
- Do not hold a black streamed compositor open after a failed primary Wine launch. Detached Wine children are supervised only after a successful launcher hand-off.

## Automatic PC-game compatibility resolver

- Add `pcga-game-compat-resolver`, invoked after game identity/Steam metadata enrichment, with per-game results stored in the canonical intake record and a local provider cache.
- Match ProtonDB by exact Steam AppID and retain summary tier/confidence/report totals plus recent community Proton-version and allow-listed environment evidence when available. Proton-specific runtime hints remain advisory while PCGA uses its appliance-managed Wine runtime.
- Match PlayOnLinux by normalized title with ambiguity protection, then parse approved installer pages for Wine architecture/version, Windows version, install methods, allow-listed `POL_Install_*` component calls, and known executable names.
- Normalize both providers into one PCGA compatibility profile instead of coupling the launcher directly to either provider's schema.
- Automatically apply only approved/high-confidence PlayOnLinux settings that are safe to express declaratively: fresh-prefix architecture, allow-listed Winetricks components/Windows version, and preferred executable names. Existing prefix architecture is preserved.
- Bound Winetricks application to five minutes by default and fall back to generic Wine behavior if a compatibility tweak cannot be applied.
- Cache successful compatibility results for 30 days; retry error/ambiguous/no-match results after six hours, and invalidate immediately when title or Steam AppID changes.

## Compatibility portal controls

- Add a Compatibility card to PC-game details showing ProtonDB and PlayOnLinux evidence, PCGA auto-applied settings, advisory hints, and resolver warnings.
- Add **Refresh compatibility** to force an immediate provider re-resolution for one game.
- Add independent **ProtonDB compatibility knowledge** and **PlayOnLinux known-good recipes** switches under PC-game settings.

## Compatibility security

- Never execute downloaded PlayOnLinux installer scripts. The resolver parses recognized declarative facts only.
- Never execute ProtonDB report text or arbitrary launch options. Only a small allow-list of environment keys is retained as advisory evidence.
- Unknown PlayOnLinux component calls are recorded for diagnosis but ignored for automatic changes.


## Portal-managed PC game sessions

- Add an **Active PC game sessions** manager to the PC Games portal surface. It lists only Wolf-created PCGA game/setup runtime containers and shows the game title, session type, runtime age, and short container id.
- Allow users to end one selected session or end all active PCGA game/setup sessions from the portal, with confirmation before termination.
- Add **End session** to the in-portal Moonlight stream toolbar. **Back** now only closes the browser view; **End session** terminates the underlying PCGA runtime.
- When a deferred Wolf app reload is blocked by an old managed runtime, the Stream flow opens the session manager automatically. After the final blocking session is ended, PCGA immediately retries the requested stream.
- Keep the privileged stop path constrained to containers that have both a valid `PCGA_GAME_SET_ID` and a `pcga/game-*` or `pcga/setup-*` runtime image, preventing the portal from becoming an arbitrary Docker-stop interface.
- After the last PCGA runtime exits, wake the game orchestrator immediately so deferred Wolf catalog reloads do not wait for the periodic timer.

## Wolf catalog / browser-stream readiness

- Make PCGA-managed Wolf app reconciliation idempotent: unchanged app blocks remain in place and no longer create false `pending-restart` work on every orchestrator pass.
- Allow the portal to stream an app immediately when Moonlight Web can already see it, even if an older persisted `pending-restart` flag remains.
- When a real pending Wolf reload exists, the Stream button asks the host control plane for an immediate lightweight reconciliation instead of waiting for the five-minute timer.
- Preserve the safety rule that Wolf is never restarted while a managed PCGA game/setup session is active, while making that state actionable in the portal.
- Treat `LaunchBFII*` / `LaunchEAW*` helper executable names, including numeric preservation suffixes, as weak identity evidence.


## Legacy Wine setup / launch reliability

- Validate the streamed interactive Wine prefix before setup; rebuild only the mutable prefix when `kernel32.dll` is missing and verify `wineboot` succeeds before launching media.
- Keep Sway/Xwayland alive while detached Wine child processes remain, preventing bootstrap installers/launchers from producing a black screen when the first EXE hands off and exits.
- Prefer direct game executables over `Launch*.exe` wrappers when both are installed; existing ready-state launcher targets are repaired without a reinstall.
- Add Empire at War windowed/resolution compatibility while retaining Battlefront II's windowed compatibility launch arguments.
- Deduplicate preserved optical copies by fingerprint/disc metadata so a re-ripped single disc cannot become a false multi-disc game in the portal.

## PC-game runtime stability

- Batch Wolf application-profile changes and restart Wolf at most once per orchestration pass instead of once per game.
- Never restart Wolf while a managed `PCGA-*` game/setup container or active GameStream control session is present. Pending profile reloads are persisted and retried by later orchestrator timer passes, including passes with no new ingest work.
- Add runtime signal/exit logging so externally terminated sessions are distinguishable from Wine/game exit codes.
- Log runtime user identity, Wine version, XDG state, and `/dev/dri` access for GPU-permission diagnosis.
- Suppress irrelevant AT-SPI probing in headless game sessions.
- Fix persisted PC-game/setup log reads in Portal Diagnostics (`p.returncode` was referenced for file logs even though no subprocess existed).

## Friendly LAN endpoint (carried forward)

- Added a managed LAN DNS responder for the exact appliance name `pcga.portal`.
- Added `pcga.local` as an mDNS/Avahi fallback without changing the server hostname.
- The LAN DNS responder binds only to the appliance LAN IPv4 address and never enables DHCP.
- Non-PCGA DNS queries are forwarded through a preserved upstream-resolver snapshot.
- If another DNS service already owns port 53, PCGA leaves it untouched and reports that the `pcga.portal` record must be added there.

## HTTPS identity

- The PCGA portal certificate now includes `DNS:pcga.portal` in its SAN list.
- Existing PCGA CA trust remains valid; only the leaf appliance certificate is reissued when necessary.
- When host TCP 443 is free, `pcga-status` publishes `443:8443`, allowing `https://pcga.portal/` with no port suffix.
- When 443 is occupied, existing services are preserved and the friendly URL falls back to `https://pcga.portal:8443/`.
- Existing `https://<LAN-IP>:8443/` behavior remains intact.

## Thin-client compatibility

- Thin-client bootstrap keeps the address-based LAN portal URL for guaranteed first-pairing compatibility.
- It additionally advertises `named_portal_url` / `namedPortalUrl` and `lan_dns_name` so clients can adopt the friendly identity after LAN DNS is configured.

## Safety

- PCGA never takes over the LAN DHCP role.
- Optional UFW rules are restricted to the detected LAN interface.
- The LAN DNS helper keeps its upstream nameservers separate from the DHCP-provided resolver path to avoid self-recursive DNS loops.
