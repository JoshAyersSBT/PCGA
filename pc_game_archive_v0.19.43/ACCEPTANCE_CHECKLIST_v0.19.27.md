# v0.19.27 LAN NAS scanner — acceptance checklist

- [ ] Complete upgrade after optical jobs finish. Confirm portal API and Control Center show `0.19.27`.
- [ ] In **Control Center → Libraries**, confirm **Find NAS backup devices** precedes NAS storage tier.
- [ ] Press **Scan local network**. Check that only the primary RFC1918 LAN (up to /24) is scanned, and no new mount or backup job begins.
- [ ] Find an SMB/NFS device on the same LAN. A TCP response produces a candidate even if the share list is password-protected.
- [ ] Select **Use this device**; the NAS host, protocol and discovered share/export populate the existing form. Confirm draft values remain until saved even if portal status auto-refreshes.
- [ ] If a share isn't listed, enter its name or export path manually. Set credentials as needed; select **Mirror**, then explicitly choose **Save & connect**.
- [ ] Confirm NAS mount reports connected and verify write permissions using existing NAS tests before scheduling backups.
- [ ] Disconnect the NAS during a test scan; confirm it does not delete, offload, or overwrite any local movie.
- [ ] Confirm the prior v0.19.26 lossless/low-loss and verified-original NAS tier workflows still appear.

Note: Scanner discovers TCP services, not verified NAS hardware identity, capacity, credentials, or backup success.
