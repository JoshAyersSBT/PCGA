# PCGA v0.19.26 acceptance checklist

- [ ] Portal API, UI, control plane and upgrade script all report 0.19.26.
- [ ] Configure and mount a PCGA NAS via Control Center; verify correct CIFS/NFS endpoint and free space.
- [ ] Complete a low-loss encode and publish; Jellyfin plays optimized MKV.
- [ ] Offload original: remote SHA-256 matches manifest, local original is removed, optimized Jellyfin file remains unchanged.
- [ ] Unmount NAS and try transfer: operation refuses; no local data is deleted.
- [ ] Test an occupied mismatched remote destination: no overwrite, no local removal.
- [ ] Restore original and confirm SHA-256 matches original rip; NAS copy remains.
- [ ] Roll back low-loss conversion after restoring local master.
- [ ] Confirm concurrent optical ripping/ingest and existing NAS mirror/offload are unaffected.
- [ ] Confirm interrupted transfers leave intact originals or independently verified remote masters.
