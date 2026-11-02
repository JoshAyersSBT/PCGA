# PC Game Archive v0.19.23 — Structure-aware optical video ingestion

## Architecture added

1. **Disc identity:** `pcga-optical-identify` now samples several disk sectors (read-only) on video discs; basic volume label, device name and medium size alone are considered weak identity. When content samples cannot be read, ARM's output remains unbound and requires manual verification.
2. **Logical-title manifest:** `pcga-disc-structure begin` snapshots ARM's output stage, persists the disc fingerprint and MakeMKV logical title table (title indexes, duration, chapters, Blu-ray playlist names when exposed), and optionally collects DVD IFO-backed title/chapter/cell information via `lsdvd`.
3. **Safe completion:** `pcga-disc-structure finish` claims **only entirely new top-level output artifacts** generated during the locked rip, attaches provenance sidecars where verified, records file-level ffprobe observations, and records any failed/unclaimed artifacts. Never assigns an identity by similar name, time or file size.
4. **Review before publication:** The classification engine forces any verified disc-structure artifact to Manual Review, even if a metadata provider identifies a single movie with high confidence. The review UI includes source playlist, chapter-count and DVD navigation evidence where available, and requires explicit feature selection.
5. **Preserve chapters:** MakeMKV remains the normal lossless extractor of *logical titles*; the assembly utility is still available for verified independent files, **not for blindly concatenating DVD VOBs or Blu-ray M2TS segments**.
6. **Serial output safety:** The existing exclusive ARM output lock remains, and the background sorter now waits until the ripper has attached provenance before moving content.

## Installation

```bash
unzip pc_game_archive_v0.19.23.zip
cd pc_game_archive_v0.19.23
sudo ./upgrade_to_v0.19.23.sh
```

The upgrader refuses to change the optical-ripping workflow while a rip is active. It attempts to install the optional Ubuntu `lsdvd` package. If unavailable, MakeMKV's title table is still retained and review is required; failures are not bypassed by raw VOB concatenation.

**IMPORTANT:** A disc left in a drive before upgrading might have an old weak fingerprint in the optical dispatcher. Reinsert or explicitly re-identify it before starting the next automatic rip to refresh metadata. Work with one test disc per drive initially.

## Inspect exact optical job provenance

```bash
sudo pcga-disc-structure list
sudo pcga-disc-structure show --job <32-character-job-id>
```

The immutable `start.json` and separate `result.json` are retained beneath `/var/lib/pc-game-archive/optical-jobs/<job-id>/`.

## Safety and remaining limitations

- Existing misidentified Jellyfin films are **not moved or deleted automatically**. Use Movies & TV → Correct movie labels, and verify each title before promotion.
- A MakeMKV-extracted file with an incorrectly chosen DVD title/PGC or Blu-ray playlist still needs operator selection; no automatic 'longest file = movie' promotion is permitted for new structured jobs.
- `lsdvd` reports IFO navigation; it is not a full DVD VM interpreter. MakeMKV remains responsible for authored logical-title extraction. Encrypted or unusually authored discs can require expert/manual extraction.
- Blu-ray playlist metadata is retained when exposed by MakeMKV; full BDMV playlist sequence reconstruction is **not yet implemented**.
- True **parallel two-drive output staging** is **not yet implemented**: ARM writes shared output locations, so this version deliberately keeps rip jobs serialized rather than risking cross-disc mixing. Future per-drive ARM workers need verified isolated mounts and independent state before this safeguard may be removed.
- This release has been tested with synthetic/simulated artifacts, not the actual Vampire Hunter D disc or live server hardware.
