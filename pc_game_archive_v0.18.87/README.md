# PC Game Archive v0.18.87

### v0.18.87 editable optical titles + existing-rip reconciliation + audiobook search repair

The Review modal now treats optical title classification as editable metadata rather than a one-time automatic decision. Multi-title movie candidates show each MakeMKV title and let the user choose Main Feature, Featurette, Deleted Scene, Trailer/Preview, Behind the Scenes, Interview, Short, Extra, or Archive Only before promotion. A new **Existing disc titles** view exposes the same controls for movies that are already in the library, so a title can be corrected later without reripping the disc.

PCGA also reconciles already-promoted optical movies against settled review/completed rip artifacts that carry the same optical fingerprint. Missing video titles are hard-linked where possible (copy fallback) into `extras/Recovered Disc Titles/`; source rip files are never deleted. Recovered tracks then appear in Existing disc titles for manual role selection. The v0.18.87 upgrader runs this reconciliation once, and the Review modal exposes **Scan current rips for missing extras** for later rescans.

The managed MakeMKV video-title threshold is reduced from 120 seconds to 30 seconds so future/reprocessed DVDs and Blu-rays retain short trailers, deleted scenes, featurettes, and other bonus clips that were previously filtered before PCGA ever saw them. Reconciliation can recover only titles already present in settled rip artifacts; a title omitted by the old 120-second threshold requires the source disc to be presented again before PCGA can capture it.

Audiobook search keeps the LibriVox public-domain provider but now uses the canonical `https://librivox.org/api/feed/audiobooks/` endpoint. If LibriVox returns 400/404 for the query-string selector form, PCGA automatically retries the API's documented path-style form. Existing audiobook streaming, chapter resume state, and local collection are preserved.

COD2 behavior is intentionally unchanged from v0.18.86 in this release.


### v0.18.86 COD2 intro-startup repair + optical movie extras promotion

Call of Duty 2 single-player now keeps the validated Wine 11.19 + CDEmu optical runtime unchanged and adds only the retail engine argument `+set com_introplayed 1`. The v0.18.85 diagnostic showed that SP mapped a game window and stayed alive rather than crashing, so v0.18.86 targets the known legacy intro-movie startup stall instead of changing Wine, CDEmu, `D:`, or the preserved `COD2CD1` image again. Multiplayer remains isolated on the previously working base Wine 9/original win32-prefix path and receives no new arguments.

Movie optical promotion no longer treats every multi-title MakeMKV rip as an anthology. When the optical manifest represents one logical movie, PCGA selects the dominant feature from title duration/size/chapter evidence, promotes it under the canonical Jellyfin movie filename, and preserves every additional video under Jellyfin-friendly bonus-feature folders such as `extras/`, `featurettes/`, `behind the scenes/`, `deleted scenes/`, `interviews/`, `shorts/`, and `trailers/`. True anthologies/collections with multiple distinct logical media IDs remain review-blocked rather than being flattened. TV season-disc handling remains on the existing multi-episode path.

The upgrade preserves installed games, Wine prefixes, preserved optical images, and the working CDEmu/VHBA stack. It invalidates only COD2's generated runtime image so the SP-only launch argument is picked up.

### v0.18.85 Noble libMirage source bootstrap

Ubuntu 24.04/Noble on the target appliance does not publish `libmirage-dev` or the CDEmu userspace packages in its configured archive. v0.18.85 therefore treats libMirage as part of the pinned CDEmu source stack rather than as an APT prerequisite. The upgrader installs only lower-level development packages available on Noble, then `/usr/local/sbin/pcga-cdemu-userspace-bootstrap` downloads and SHA-256 verifies libMirage 3.3.3 (`b480b08230b2255af40c3ac86344c0c77fc996866014e05a69d5554e9035d65b`), builds it under `/usr`, verifies `pkg-config libmirage`, and only then builds the existing pinned CDEmu 3.3.0 daemon/client.

The already-working VHBA 20260313 DKMS installation is retained. COD2 SP still keeps the proven `COD2CD1` filesystem at Wine `D:` and uses CDEmu only for the low-level `D::` device when the virtual `/dev/srN` is healthy. Multiplayer remains on the previously working base-Wine 9/win32/loop-backed path and receives no CDEmu device.


### v0.18.84 Noble-safe CDEmu/VHBA bootstrap

Call of Duty 2 Single-player keeps the already-validated `COD2CD1` ISO filesystem on Wine `D:`. The remaining experiment is strictly below that layer: when CDEmu is healthy, its VHBA virtual SCSI CD-ROM backs Wine `D::`; when it is not healthy, SP keeps the proven loop-backed `D::` as a nonfatal diagnostic fallback. Multiplayer remains on its previously working Wine 9/win32/loop-backed path and does not consume CDEmu devices.

The v0.18.83 host diagnostic exposed the actual bootstrap failure on Ubuntu 24.04/Noble: kernel headers were installed, but `dkms`, `cdemu`, and `cdemu-daemon` were absent. Earlier upgrades requested distro CDEmu packages and DKMS in a single APT command; because Noble may not publish the CDEmu packages in the configured suite, APT could reject the whole transaction before installing `dkms`. v0.18.84 installs each available prerequisite independently.

If distro CDEmu packages are unavailable, `/usr/local/sbin/pcga-cdemu-userspace-bootstrap` builds CDEmu 3.3.0 client and daemon from pinned, SHA-256-verified upstream source. `/usr/local/sbin/pcga-cdemu-bootstrap --repair` then builds pinned VHBA 20260313 through DKMS for the running kernel. The appliance service is enabled only after CDEmu userspace and `/dev/vhba_ctl` exist. `pcga-cdemu.service` uses `Restart=no`, so a missing module cannot create the previous five-second restart storm.

A successful host repair should add a CDEmu virtual optical device in addition to the physical `/dev/sr0`/`/dev/sr1` drives. COD2 SP then keeps its existing `D:` mount while mapping `D::` to that CDEmu `/dev/srN`; no physical disc is required and the preserved ISO remains authoritative.


## v0.18.82 — CDEmu-backed COD2 single-player optical device

v0.18.82 keeps the proven COD2CD1 ISO filesystem mapping unchanged and adds CDEmu only beneath the single-player raw optical path. The preserved `COD2CD1` ISO remains mounted at Wine `D:` exactly as in v0.18.81; for **single-player only**, Wine `D::` is attached to a CDEmu VHBA virtual CD-ROM loaded from that same preserved ISO. This lets Wine/SafeDisc issue MMC/SCSI-style optical commands against a virtual CD-ROM instead of a generic loop block device without changing the game files, drive letter, volume label, or archive source.

The host installs `cdemu-client`, `cdemu-daemon`, and `vhba-dkms`, runs one appliance-owned CDEmu device on the system bus, and records the resolved `/dev/srN`/`/dev/sgN` mapping in COD2 runtime state. CDEmu bad-sector and DPM emulation flags are enabled when supported, but PCGA does not claim that these can recreate protection data absent from a cooked ISO. If the existing ISO still fails SafeDisc, a protection-aware raw preservation format remains the next step.

**Multiplayer is intentionally isolated from this experiment.** COD2 MP previously launched successfully, so `CoD2MP_s.exe` remains on base Wine 9, the installer-created win32 prefix, and the existing loop-backed preserved-media path. CDEmu is passed only to the single-player Wolf app. Setup is unchanged. No reinstall or re-rip is performed.


## v0.18.81 — ISO-only COD2 optical runtime

v0.18.81 removes the v0.18.79/v0.18.80 physical-disc authentication experiment. PCGA is an archive appliance: the preserved COD2CD1..COD2CD6 ISO set is authoritative and no original disc is required at runtime. COD2 single-player now selects the archived ISO whose volume label is `COD2CD1`, presents its mounted filesystem as Wine D:, presents the corresponding read-only loop block device as D::, restarts the selected wineserver, registers D: as `cdrom`, and refuses launch if the ISO/mount/loop device is missing or unreadable.

The portable Wine 11.19 runner, isolated WoW64 single-player prefix, original-media `SECDRV.SYS` staging, and SP/MP launch variants remain unchanged. This release does not reinstall COD2 or modify the preserved ISO files.

This release verifies ISO presentation only. A standard cooked ISO may still be insufficient for some SafeDisc checks because it cannot encode every low-level CD property; if Wine sees `COD2CD1` as `DriveType=5` and the title still rejects it, PCGA should move to a protection-aware raw-image format rather than reintroducing a physical-disc dependency.

## v0.18.79 — COD2 physical SafeDisc authentication fallback

Call of Duty 2 single-player now reaches Wine 11.19 and passes PCGA's strict `COD2CD1` label/CD-ROM checks, but SafeDisc can still reject the loop-backed preservation ISO. v0.18.79 can use the original physical `COD2CD1` disc for authentication while leaving the archived six-disc ISO set authoritative for installation and preservation.

Insert the original disc labelled `COD2CD1` into either server optical drive. The orchestrator automatically detects only that exact label, mounts it read-only, and makes it available to COD2 SP as D:. Multiplayer continues using the normal preserved-media path. Removing the disc causes later reconciliation to clear the temporary physical-auth state.

This release does not reinstall COD2, modify the Wine 11 runner, or rewrite preserved media. It is a controlled test to distinguish a SafeDisc low-level-media requirement from a remaining Wine issue.

## v0.18.77 — COD2 OLE finalization and isolated SafeDisc runtime

v0.18.77 replaces the failing WineHQ-in-container APT experiment with a pinned **portable Wine 11.19 new-WoW64 runner**. COD2 single-player downloads the `wine-11.19-amd64-wow64.tar.xz` release from Kron4ek/Wine-Builds, verifies its published SHA-256, and extracts it only into the generated COD2 runtime image. The host Wine installation, Ubuntu APT sources, setup environment, multiplayer runtime, and other PCGA games remain unchanged. If the portable runner cannot build, the exact Docker build output is retained in `runtime_build_log`.

v0.18.77 keeps the repaired v0.18.74 COD2 installer path, but restores the intended post-install behavior: once the MSI log and direct COD2 runtime payload are complete, PCGA finalizes the native `CoD2SP_s.exe` / `CoD2MP_s.exe` installation and terminates the obsolete Shockwave Flash/OLE launcher before it can turn a successful install into an apparent setup crash. Detection accepts the historical Shockwave CLSID as well as `0x80040154`, `REGDB_E_CLASSNOTREG`, and `CLASS_E_CLASSNOTAVAILABLE`.

The isolated Wine experiment is also corrected. Wine 11 no longer points at the installer's pure `WINEARCH=win32` prefix. COD2 single-player creates a persistent runner-owned portable Wine 11.19 default/WoW64 prefix, projects the already-installed game payload into that prefix with hard links where possible, stages the original `SECDRV.SYS` from the preserved COD2 optical media into the Windows drivers directories, and scopes a Windows XP compatibility setting to `CoD2SP_s.exe`. Multiplayer stays on the known-good base Wine runtime and the original win32 prefix. If the isolated runner cannot initialize, SP falls back to base Wine without modifying the installed prefix.

This upgrade does **not** reset COD2 or require another reinstall when the v0.18.74 install is already complete. It invalidates only the generated COD2 runtime image so the corrected startup logic is picked up.


## v0.18.74 — COD2 reinstall recovery and isolated-runner fallback

v0.18.73 exposed two independent regressions while testing the isolated WineHQ runner. First, an inherited v0.18.69 migration could demote an already-installed COD2 title back to setup and clear its mutable prefix. Second, COD2's synthetic `COD2DVD` setup source was still using an unreliable `Path.is_mount()` fast-path check, allowing a periodic reconciliation pass to tear down or rebuild the loop-backed source while Wolf was starting the installer. The resulting setup session exited before Wine with `PCGA setup executable missing: /pcga-source/setup.exe`.

v0.18.74 repairs that lifecycle. A READY COD2 install is never demoted by the legacy synthetic-media migration. A reinstall rebuilds only derived synthetic-media state from the preserved `COD2CD1..COD2CD6` images, and PCGA does not publish the Setup app until the exact `findmnt` mount, `setup.exe`, MSI flatten marker, `Setup/Data/main/iw_02.iwd`, and raw loop device all validate. The setup launcher also rechecks the marker and payload sentinel immediately before invoking Wine, so a source race fails with a useful diagnostic instead of an apparently crashing installer.

The WineHQ 11.19 experiment remains gameplay-only. The generated COD2 runtime installs the side-by-side `wine-devel` payload under `/opt/wine-devel`; setup continues to use the base Games-on-Whales Wine environment. If the isolated runner image cannot be built, PCGA automatically builds a base-Wine runtime fallback and records the requested runner/fallback state instead of leaving COD2 as `ready / failed`.

Because a v0.18.73 **Reinstall** action already removes the mutable Wine prefix, an affected machine must complete one repaired reinstall after upgrading to v0.18.74. Preserved optical images are not discarded by this recovery.

## v0.18.73 — isolated WineHQ runner for COD2 SafeDisc testing

v0.18.73 introduced a per-game Wine runner layer for COD2 gameplay, requesting WineHQ development 11.19 under `/opt/wine-devel` while leaving host Wine and unrelated game images unchanged. It also generalized the SafeDisc/SecDrv failure capture and added `runtime-logs/last-failure.json`.

That release contained the COD2 reinstall/source-lifecycle regressions corrected by v0.18.74 and should not be used as the recovery target.

## v0.18.72 — COD2 win32 SafeDisc compatibility startup

The v0.18.71 COD2 runtime diagnostics isolated the campaign failure from the portal, Wolf, Xwayland, GPU, and optical-media layers. `CoD2SP_s.exe` was launched correctly with `COD2CD1` visible as a real Win32 CD-ROM volume, but the existing Wine template was `#arch=win64` and the campaign exited before mapping a window after `ZwLoadDriver(...SecDrv...)` returned `c0000142`. Multiplayer continued to map a normal game window.

v0.18.72 makes COD2 retail an appliance-owned `win32` compatibility case. On upgrade, a ready COD2 install is migrated only when its actual prefix is `win64`: PCGA clears the mutable prefix, preserves the six source images and runtime-media inventory, creates a new install generation, and returns COD2 to the already-supported synthetic six-disc setup flow. The setup runtime creates the new prefix with `WINEARCH=win32` and verifies `#arch=win32` before the installer is allowed to continue.

The normal runtime independently verifies the prefix architecture before launch and logs `existing=<arch> required=win32`. COD2 also emits a SafeDisc/SecDrv compatibility diagnostic. If a verified win32 campaign still returns the same SecDrv `c0000142`, PCGA reports that explicitly so the remaining limitation is distinguishable from media mapping. The release does not patch the game or install a no-CD/cracked executable.

The single-player/multiplayer mode selection introduced in v0.18.71 is retained: `CoD2SP_s.exe` is the default launch target and `CoD2MP_s.exe` remains an explicit alternate Wolf/portal app.

## v0.18.71 — explicit single-player / multiplayer launch variants

PCGA now treats distinct game executables as first-class launch choices when an installed title exposes a conservative same-directory SP/MP pair. Detection is executable-based rather than metadata-based: the selected runtime executable must carry a strong single-player or multiplayer marker (for example `CoD2SP_s.exe`) and the opposite-role executable must share the same normalized family (for example `CoD2MP_s.exe`). Unrelated helper, updater, and dedicated-server executables are not promoted merely because a game's metadata mentions multiplayer.

For titles with a confirmed pair, the portal no longer sends the library-card Play button directly to one arbitrary executable. The card shows **Choose mode**, and the detail modal exposes separate **Play Single-player** and **Play Multiplayer** actions. The existing selected executable remains the default; PCGA does not silently switch a user's campaign launch to multiplayer. Each mode has its own Wolf app identity and container name while sharing the same preserved install template, Wine prefix generation, saves, optical media, LAN bridge, and runtime image. Session reservations persist the selected mode so browser-lane claims and Resume return to the same executable.

Call of Duty 2 is the first verified case: the v0.18.70 finalized retail install is detected as `CoD2SP_s.exe` (default single-player) plus `CoD2MP_s.exe` (multiplayer). This release changes selection/launch plumbing only; it does not alter COD2's preserved six-disc install, synthetic setup media, or copy-protection behavior.

## v0.18.70 — COD2 direct-runtime finalization after obsolete Flash launcher

Retail Call of Duty 2 can finish installing successfully and then open a Flash-based launcher shell. On current Wine this may show `OLE error 80040154` because Shockwave Flash ActiveX CLSID `{D27CDB6E-AE6D-11CF-96B8-444553540000}` is not registered. v0.18.70 treats that shell as optional post-install baggage only after the actual COD2 runtime payload validates. It never installs Flash: completed installs are finalized against `CoD2SP_s.exe` / `CoD2MP_s.exe`, with single-player preferred. Existing v0.18.69 installs that already copied the full runtime are recovered automatically after the setup stream is ended.


## v0.18.69 — isolate rejected Wolf apps instead of restarting the whole streaming stack

The v0.18.68 recovery got `pcga-game-orchestrator.service` back to `status=0/SUCCESS`, but the next launch test exposed a second control-plane problem. Wolf consistently discarded the Jedi Outcast managed app block after reload. PCGA treated that one rejected profile as if the entire pending catalog still needed a daemon reload, so the timer restarted Wolf twice on every orchestration pass. The visible symptom was that portal Play/Install buttons never reached a stable Wolf session long enough to create a `PCGA-Game-*` or `PCGA-Setup-*` container.

v0.18.69 changes that failure mode from global to per-title. After the normal reload plus one repair restart, any app block Wolf still removes is marked failed and quarantined from automatic reloads. Apps that survived the same reload are immediately marked ready, the pending-restart file is cleared, and the next timer cycle performs zero Wolf restarts. The portal's **Retry stream** action now performs an explicit forced retry for only the selected quarantined title.

COD2's synthetic `COD2DVD` media and Wine setup logic are intentionally unchanged in this release. The purpose of v0.18.69 is to restore a stable portal → Moonlight → Wolf launch window before continuing COD2 installer debugging.


## v0.18.68 — mount-safe COD2 setup reconciliation and launch recovery

The v0.18.67 diagnostics exposed a control-plane failure rather than a Wolf container-launch failure. The PC-game orchestrator was exiting once per minute with `OSError: [Errno 30] Read-only file system: '00000001.TMP'`. COD2's `setup-source` was a live read-only synthetic `COD2DVD` ISO mount, but the generic multi-disc/reinstall staging path still called `shutil.rmtree(setup-source)` as if it were an ordinary writable directory. The failed reconciliation marked the canonical COD2 state `failed`, preventing its Wolf app from being considered launchable.

v0.18.68 makes interactive setup staging mount-aware. A live setup-source mount is detached before any generic restage; if an active stream keeps it busy, the state remains `setup-required` with `setup-source-busy` instead of failing the whole orchestrator. Reinstall now respects failed COD2 synthetic-media cleanup, and stale v0.18.67 EROFS states are automatically recovered to `setup-required` before the silent-install fallback can run. Once the genuine COD2DVD source is present, generic setup-source restaging is skipped entirely and the synthetic optical tree is treated as authoritative.

This release intentionally leaves the v0.18.67 Wine D:/D:: refresh and the v0.18.66 COD2DVD/MSI layout unchanged. It repairs the lifecycle around that media so portal Install/Retry/Play registration can recover normally. The orchestrator now also records a bounded Python traceback if any future per-game exception escapes reconciliation.
