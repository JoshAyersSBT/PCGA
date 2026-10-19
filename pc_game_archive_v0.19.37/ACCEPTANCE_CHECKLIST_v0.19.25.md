# PCGA v0.19.25 acceptance checklist

- [ ] Release versions in upgrader, portal API, Control Center, client JavaScript and host API agree on 0.19.25.
- [ ] `pcga-low-loss-encode inventory` lists only managed, older MKV files and available encoders.
- [ ] HEVC/AV1 jobs can be queued through Control Center with chosen quality preset.
- [ ] An encode job keeps the original file playable; output is in `media/low-loss/staged` only.
- [ ] Stream, chapter, duration and SHA-256 checks pass before a result is shown as encoded.
- [ ] Publishes are explicitly confirmed; originals move to `media/cold-archive/low-loss-masters` and are never deleted.
- [ ] Rollback restores the exact original content hash and keeps the optimized MKV staged.
- [ ] No codec path accepts HDR/DV and unknown/multiple video streams silently.
- [ ] Failed or too-large encodes produce no library replacement and report a useful error.
- [ ] Zstandard archiving, optical ingest, Steam, emulator controls and portal navigation remain unaffected.
- [ ] Test space on the NAS/archive destination before treating smaller playable MKVs as actual system-wide storage savings.
