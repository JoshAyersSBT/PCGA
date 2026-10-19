# v0.19.27 NAS discovery

See `ACCEPTANCE_CHECKLIST_v0.19.27.md` for scan safety, selection, and connection checks.

# v0.19.26 NAS master tier acceptance

See `ACCEPTANCE_CHECKLIST_v0.19.26.md` for NAS failure and transfer validation.

# v0.19.23 authored optical title & provenance acceptance

- [ ] Complete any active rip before upgrading; deploy, then eject/reinsert test discs to refresh fingerprints.
- [ ] Insert a DVD containing a feature and a making-of: inspect `sudo pcga-disc-structure list`, then `show --job` for MakeMKV chapter/title inventory and IFO navigation when available.
- [ ] Confirm the movie feature is NOT auto-promoted before title/bonus review, even if metadata lookup identifies the movie.
- [ ] Confirm bonus titles are offered as extras and a missing feature can remain in review without deleting files.
- [ ] Test two different discs with the same volume label: verify distinct fingerprints, output claims and source manifests.
- [ ] Confirm the ARM second drive waits while shared output is occupied; no mixed output published under another disc identity.
- [ ] Confirm source video files and already published Jellyfin movies are unchanged during upgrade.
- [ ] Confirm a raw VOB sequence is NOT blindly concatenated and a Blu-ray clip playlist is not inferred from filenames.
- [ ] Verify fallback review when `lsdvd`/MakeMKV navigation probing fails or the media fingerprint is weak.

# v0.19.23 optical segment acceptance

- [ ] With two rips idle, install the release and open Manual Review.
- [ ] Select a review source with two or more video files; preview each part.
- [ ] Confirm chapter selection and explicit playback order create a new review item.
- [ ] Verify original segments are still present and unchanged.
- [ ] Verify new assembled candidate remains in Manual Review (no automatic Jellyfin publication).
- [ ] Verify beginning, every boundary, audio sync and ending, then publish manually.
- [ ] Deliberately select incompatible clips and verify no resulting movie is published.
- [ ] Check published correction retains 22-minute making-of as an extra, not the main film.
- [ ] Ensure cross-drive identity remains isolated under v0.19.21 staging lock.

# PCGA v0.19.20 acceptance checklist

- [ ] Manual Review → Existing disc titles shows one clip preview per physical video file.
- [ ] Main-feature reassignment moves the incorrect former feature into extras.
- [ ] Separate movie creates a new folder with the selected file, without removing the original movie or overwriting another existing folder.
- [ ] Correct movie title/year renames its folder and main film and updates the recorded classification.
- [ ] Deliberate corrections remain intact after restart and upgrade; no automatic extras recovery undoes them.
- [ ] Source files retain distinct identities when two optical drives rip simultaneously.

- [ ] sr0 and sr1 complete different films concurrently without mixing metadata.
- [ ] Unidentifiable or identical disc labels stay provisional and unbound.
- [ ] A multi-video optical movie remains in Manual Review rather than being automatically sent to Jellyfin.
- [ ] Manual Review shows title role selectors even when optical provenance is absent.
- [ ] Exactly one explicitly selected title becomes the main movie; other titles remain accessible as extras.
- [ ] Previously published movie folders with two or more video tracks appear for manual role repair.
- [ ] No existing published video files are deleted or reassigned during upgrade.

## Steam safeguards carried forward

- [ ] Upgrade installs without a false positive portal UI/version guard.
- [ ] No upgrade-induced Docker Steam restart or deleted Steam profile data.
- [ ] Control Center → Games & Emulation displays Steam encoder preference.
- [ ] SHUI setup opens `https://<server-LAN-IP>:8483/` (self-signed certificate).
- [ ] A real SHUI HTTP 401 is reported as reachable, not Steam logged in.
- [ ] Steam Headless first-run setup reports pending until enrollment finishes.
- [ ] Sunshine placeholder `sleep infinity` is not reported streaming-ready.
- [ ] Steam account login is labeled unverified until user signs in.
- [ ] Software encoder preference survives `--apply` recreation.
- [ ] The existing Steam library and account data survive recreation.
- [ ] Steam Link or remote play is checked on actual LAN hardware.

# v0.19.15 validation checklist

- [ ] PC Games → Store Library shows Epic, GOG, Amazon, and Steam tabs.
- [ ] All stores includes installed Steam games and the other store catalog items.
- [ ] Steam tab filters to installed games; title and AppID searches work.
- [ ] Steam runtime controls appear near store account controls in Games & Emulation.
- [ ] Steam games offer Steam Link guidance, not Epic/GOG install buttons.
- [ ] Existing Epic/GOG download, update, verify, and uninstall actions still work.
- [ ] Steam disconnected/runtimes absent show diagnostics without crashing library.
- [ ] Existing PCGA PC-game launch and streaming remain functional.
