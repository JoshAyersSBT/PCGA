# PC Game Archive v0.19.27 — LAN NAS discovery

## Scope

- Adds **Control Center → Libraries → Find NAS backup devices** to detect local SMB and NFS backup candidates.
- Read-only, opt-in scan of the server's primary RFC1918 IPv4 LAN (bounded to /24, at most 254 hosts) using TCP 445 and TCP 2049; skips container bridges and VPN interfaces.
- Best-effort share/export listing using optional `smbclient` (anonymous SMB) and `showmount` (NFS exports). Devices with protected shares remain selectable with manual share name and credentials.
- Background systemd scan, cached results, status polling, and **Use this device** action populate existing NAS configuration inputs without saving or connecting.
- Existing SMB/NFS mount manager, scheduled mirroring, Smart offload and checksum-verified low-loss NAS tiering remain unchanged.

## Security and operational constraints

- Never sends stored credentials during discovery. No mounts, writes or automated backups during scan.
- A responding port is not proof of a real NAS, writable share, capacity, health, or supported permissions.
- No automatic discovery on service startup. No scans of additional subnets, VLANs, VPNs or Internet targets.
- Administrators must review credentials and explicitly **Save & connect**, then verify access before enabling a backup schedule.
- Existing media, Steam setup, ROMs, and NAS configurations are unchanged by upgrade.

## Installation

Wait for optical jobs to finish and run `sudo ./upgrade_to_v0.19.27.sh` from the extracted release directory.

## CLI

`sudo pcga-nas-discover scan` starts a foreground read-only scan.

`sudo pcga-nas-discover status` returns last known results without scanning.

## Acceptance checklist

1. Open Control Center → Libraries; confirm scanner appears above NAS configuration.
2. Scan with a NAS and SMB/NFS service present on the PCGA server's primary LAN.
3. Verify a detected share can populate host, protocol and share/export when selected; ensure NAS remains unmounted until **Save & connect**.
4. For a password-protected NAS, confirm that host remains selectable even when share enumeration returns none.
5. Configure Mirror mode, authenticate and confirm access; then use existing backup tools and review checksum verification.
6. Verify a disconnected NAS does not cause writes, deletion, or automatic local-master offload.

Static tests cannot confirm behavior of third-party NAS devices or routing/firewall rules on the user's live network.
