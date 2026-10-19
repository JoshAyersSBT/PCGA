## v0.19.37 — Secure Diagnostics upgrade acceptance

- Fix HTTPS-only Diagnostics upgrade validation: a stale HTTP 8098 catalog request returned 426 and was misreported as missing Jellyfin.
- Reuse one CA-validated HTTPS 8443 catalog response to verify streaming, service presence and optional Jellyfin Media profile membership.
- Produce explicit, safe errors for HTTP/JSON/schema/service failures without relaxing Diagnostics TLS enforcement.
- All v0.19.36 stream-aware consolidation, rollback and storage reserves are retained.

## v0.19.36 — Stream-aware Blu-ray pruning and low-space protection
- Adds full compressed video/audio streamhash comparison, subtitle-superset and chapter compatibility verification within the same movie title. Unlike whole-file checksums, candidates can include different MKV packaging with matching payloads.
- Opt-in staged rename with recovery manifest, reversible restore, and separately confirmed seven-day delayed purge. No automatic purging, remuxing, or cross-title merges.
- Presents stream-aware candidates and staged holds in Control Center > Ingest & Review alongside existing exact-byte and visual-only scans.
- Warns when archive disk free space is under 10/3 GiB and raises new optical ingest reserve to disc size plus 10 GiB to protect Jellyfin database headroom.

## v0.19.35
- Reconcile enabled Jellyfin when missing or stopped, health-check host and portal access, and preserve healthy playback.
- Include Jellyfin in Diagnostics even when the container is missing; provide clear Movies & TV recovery actions.

## v0.19.34 — Visual duplicate review

- Adds opt-in, read-only decoded-frame fingerprint sampling of near-equal-duration videos under the same movie/TV title, with a recognized extra required.
- Suppresses exact byte-identical matches from visual results, leaving those to SHA-256 pruning.
- Ignores uninformative blank frames; requires a conservative multi-frame match and revalidates file identity after decoding.
- Adds separate visual results to Control Center, with evidence but no quarantine or delete buttons.
- Keeps original media, playlists, metadata and encoding jobs untouched. Requires FFmpeg and ffprobe; processes as a background systemd job.

## v0.19.33 — Recoverable exact-copy extras pruning
- SHA-256 audited duplicates within the same movie or series; main features are never deleted.
- Opt-in review, quarantine, restore and delayed manual purge; no automatic deletion.
- Background scan via host control plane and Movies & TV > Manage entry.
- Preserves alternate cuts, different encodes and legitimate non-identical bonus features.

## v0.19.32 — Bonus features playback

- Added a read-only Jellyfin bonus-feature API and responsive movie/series detail section with focusable, explicit playback controls.
- Uses exact Jellyfin parent relations and independently retrieves local trailers; no metadata guesses or unrelated title merges.
- Plays selected features through the existing player with no autoplay or next-episode chaining, restoring focus to the selected extra on exit.
- Handles deduplication, missing data, unavailable APIs and misclassified/unpublished extras safely.

## v0.19.31
- Season-aware TV guide, episode progress, user-specific Next Up and intentional playback completion.
- TV remote focus preservation, exact API input validation and bound episode paging.

## v0.19.30 — Calm media browsing

- Full-screen Movies & TV browser that retains the existing PCGA portal/player stack.
- New read-only, user-scoped Jellyfin title-detail endpoint, explicitly selected before playback.
- Continue Watching, Recently Added, Movies, TV Series, Other Video shelves; category pagination with an explicit Load More action.
- Viewer focus, scroll and loaded results preserved when returning from title details; remote Back restores previous view.
- Upload and correction buttons tucked behind Manage; no autoplay trailers, previews or countdowns.
- CSS scoped to Movies & TV to avoid altering shared PC Games, console or photo UI.
- v0.19.30 upgrade entry points are executable; release checks and dedicated tests added.

## v0.19.29 — Smart TV layout, overscan, remote controls

- Uses known TV browser user agents and remote-only landscape heuristics to select ten-foot layout before mobile fallback.
- Adds TV mode quick toggle, per-browser overscan (3/5/7%), and TV text scaling (100/115/130%).
- Applies TV-safe margins to interactive UI, and larger focusable controls while keeping videos/backgrounds edge-to-edge.
- Makes playback and modal layouts more predictable on 540p/720p/1080p/4K CSS viewports.
- Supports common TV remote Back keys and disables animated D-pad focus scrolling in TV mode.
- Adds TV regression tests and fixes the embedded version labels and upgrade guards.

## v0.19.28 — Responsive fullscreen media controls

- Corrects the CSS grid so the movie seek timeline, not the elapsed-time label, consumes flexible width.
- Enlarges the seek rail, thumb and pointer hit area; fills the elapsed part with the current theme accent.
- Adds a three-second fullscreen-only inactivity fade for controls and the stream badge, and hides the cursor while idle.
- Wakes on pointer, keyboard, touch, playback resume and fullscreen changes; suppresses idle hiding while paused, buffering, scrubbing or keyboard focus is active.
- Adds source regression coverage and validates behavior/layout with headless Chromium.
- Does not change media files, Jellyfin configuration, stream choices, ingestion or background jobs.

## v0.19.27 — LAN NAS discovery

- Opt-in bounded LAN scanner for SMB and NFS backup candidates, with cached results and optional anonymous share listing.
- NAS discovery controls integrated with existing storage-tier form; selection does not mount or back up until explicitly confirmed.
- Regression tests for private-LAN limits, safe discovery, missing tools, and source integration.

# PCGA v0.19.26 — NAS tier for original masters

- Adds checksum-verified NAS offload and restore of published low-loss original MKVs.
- Retains local playable Jellyfin copy and disallows Smart offload for this workflow.
- Exposes confirmed per-title operations and background logs in Control Center.
- Blocks unverified, disconnected, or conflicting NAS destinations.
- Adds transfer serialization with existing NAS mount operations.

# PCGA v0.19.25 — Quality-oriented playable HEVC/AV1 copies

- Adds optional host-side FFmpeg HEVC/AV1 encoding with Balanced and High profiles, source-stability checks and conservative stream verification.
- Adds a staged/non-destructive publish flow and a verified rollback to the exact original master.
- Exposes conversion, publish and rollback in the portal Control Center with background job progress, encoder availability and confirmation.
- Retains master MKVs; no claims of net disk savings until they are independently tiered to other storage.
- Adds seven low-loss regression tests, including real FFmpeg encode and rollback.

## v0.19.24 — Verified reversible compression

- Added administrator-controlled Zstandard cold archiving and byte-for-byte restoration for settled Movies, TV and Home Videos.
- Required explicit offline confirmation; kept `.mkv` playable unless the archive saves at least 2% and verifies against original SHA-256.
- Added background systemd jobs, portal inventory and restore controls; exposed measured savings and statuses.
- Excluded cold data from Jellyfin scan paths; no automatic codecs conversion, quality reduction, raw material deletion or library rewrites on upgrade.
- Added regression tests for round trips, already-compressed files, malicious paths/symlinks, tampered archives, overwrite refusal and recently-ingested files.

## v0.19.23
- DVD MakeMKV logical-title and optional lsdvd IFO inventory, content-sampled optical identity, exclusive-job artifact attestation, fail-closed review and sorter race gate.
- Preserved manual correction, game portal, and all earlier releases.

# PCGA v0.19.23 — Explicit split-feature assembly

- Preview and select ordered video segments inside a single Manual Review source; do not infer sequences from disc labels or durations.
- Background, non-destructive FFmpeg concat with compatible-stream validation and output-duration verification; sources untouched.
- Assemble into a new review candidate and force human confirmation before movie publication.
- Add job tracking, segment UI/API and four end-to-end/safety regression tests.
- Do not auto-join DVD VIDEO_TS, Blu-ray BDMV playlists or unrelated extras.

# PCGA v0.19.23 — Safe optical output and missing-feature corrections

- Stage only one ARM optical writer at a time while raw/completed locations remain shared; the second drive waits rather than risking mixed or overwritten output.
- Drain the completed directory under the same single-writer lock before allowing another rip; block on stranded output.
- Never associate ARM output with disc metadata using folder names or completion timestamps; only verified upstream fingerprints can bind a disc identity.
- Include single-video misidentified movies in the Existing disc titles repair list, even if the older ingest lost its provenance.
- Add **Set aside: missing / incorrect feature** to move a wrongly published, extras-only movie back into the review queue non-destructively.
- Add **Correct movie labels** to the Movies & TV window for direct access to published-title corrections.
- Preserve all existing optical media; do not auto-delete or auto-merge movie folders.
- Adds safety and review regressions; working simultaneous per-drive output isolation remains future work.

# PCGA v0.19.20 — Published movie correction and title previews

- Optical metadata association no longer guesses by completion time or loosely overlapping names. Ambiguous associations remain unbound for review.
- Multi-video optical movie rips remain in Manual Review even if an online metadata provider returns high confidence.
- Manual Review exposes main-feature and extras role selectors even if pre-rip optical identity could not be attached.
- Movie promotion requires explicit main-feature selection for any multi-video artifact. Bonus titles remain preserved under Jellyfin-compatible extras directories.
- Previously published movie folders containing multiple videos now appear in the published-title correction UI, even without optical provenance. Files remain untouched until an operator explicitly reassigns roles.

## v0.19.20 — Published library reclassification
- Preview each optical title independently in both queued and published review.
- Repair a wrongly joined movie by separating a selected title into a new, explicitly named library folder; refuse merges or overwrites.
- Correct a previously promoted movie title/year, including its canonical main-feature filename and classification manifest.
- Preserve all video content and refresh Jellyfin after the user confirms a correction.
- Prevent corrected titles from being automatically reattached by the older extras reconciler; make reconciliation an explicit opt-in action instead of a step in the upgrader.
- Fix duplicate-basename title selections with source-relative path keys; reject invalid role values rather than silently converting them into extras.
- Add reclassification and collision regression tests.

## v0.19.18 — Steam Headless fixes carried forward
- Fix Steam Headless v3 setup link: HTTPS TCP/UDP 8483, not HTTP 8083.
- Persist `SHUI_ENCODER=auto|software` in Docker container environment; safe
  host-managed preference and explicit rebuild preserve verified Steam mounts.
- On upgrade, identify existing decode-only H.264 GPUs and non-disruptively
  preserve the software encoder preference (no automatic container restart).
- Keep SHUI, Steam client, first-run setup, and Sunshine health separate.
  Authenticated HTTP 401 means HTTPS UI is reachable, not Steam is logged in.
- Never mark Steam streaming ready for Sunshine's placeholder process.
- Add encoder controls and first-run setup guidance to Games & Emulation.
- Add Steam integration regressions and release consistency checks.

## v0.19.17
- Manage native emulator installations from Control Center → Games & Emulation, with background systemd jobs, live status and logs.
- Flatpak and Flathub prepared during user-requested install; no firmware distributed.

# PCGA v0.19.15 — Unified PC Store Library

- Shows installed Steam games alongside Epic, GOG and Amazon in the PC Store Library.
- Adds the Steam filter with installed game count and searches titles/AppIDs.
- Steam cards have an explicit Steam Link handoff, not unsupported PCGA install/maintenance actions.
- Keeps Steam credentials and Proton configuration inside native Steam Headless.
- Moves native Steam runtime controls into the store account controls within Games & Emulation.
- Displays provider-specific errors without hiding a working Steam library if the other store catalog is unavailable.
- Retains native Steam titles in the PC Games source browser.

Steam Link pairing and authentication require live validation on the appliance.

## Packaging correction (v0.19.15)

- Fix upgrade validation to check stable PC Games browser hooks instead of an obsolete exact text phrase. No Steam data or credentials are modified by this correction.

## v0.19.16
- Registered Dolphin, PCSX2, RPCS3 and shadPS4 as native console emulator targets.
- Added opt-in Flatpak install/update/status CLI and visible Console Games guidance.
- Retained EmulatorJS/browser-play separation; no unverified native launch actions.
