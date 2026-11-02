# PCGA v0.19.34 — Visual similarity review acceptance checklist

1. Finish optical rips, back up irreplaceable media, then upgrade using `sudo ./upgrade.sh`. Confirm the portal API reports `0.19.34`.
2. Navigate to Movies & TV → Manage → Review duplicate extras, or Control Center → Ingest & Review. Existing exact-copy audit/quarantine controls must still work.
3. Press **Compare video content (review only)**. The service should run a separate background scan without changing file content, names, Jellyfin library state, or classification.
4. Use two intentionally differently encoded videos of the same footage in a single movie tree with one file in `behind the scenes/`. A likely visual match may appear after the scan.
5. The output must label the results **review only**, with video paths, duration, usable frame agreement, and an explicit warning that audio/subtitles/chapters/editions may differ. There must be **no quarantine or purge button** on visual matches.
6. Confirm videos in separate movie directories are never compared. Confirm black/static content does not generate a false positive. Exact-byte duplicates still belong to the existing SHA-256 scan.
7. During an active optical rip, the scan should refuse to run. A changed or symlinked file must not become a candidate.
8. Confirm `sudo pcga-extra-prune status` reports independent `scan` and `visual_scan` objects. Inspect background errors with `journalctl -u 'pcga-extra-prune-*' -n 100 --no-pager`.
9. Test the scanner's output in the PCGA portal on the actual Smart TV and check that Controls remain reachable with the remote. Long filenames must wrap instead of overflowing a dialog.

**Limits:** A visual match is not proof of a redundant file. The scanner samples a small number of frames and can miss alternative edits, different timing, or visually altered footage. It does not identify duplicate audio or video across different parent titles. Nothing is removed automatically.
