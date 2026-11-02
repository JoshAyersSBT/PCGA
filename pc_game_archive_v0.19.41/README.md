# PC Game Archive v0.19.41 — Containerized NetBird peer

Adds a dedicated NetBird peer container managed through the existing Control Center. NetBird uses host networking so the appliance and streams can reach its encrypted overlay, while peer identity persists across container and host restarts. Setup keys are written to a root-only temporary file, read inside the container, and removed after enrollment.

## Upgrade

Start from an installed **v0.19.40** appliance. The focused upgrade keeps the Wolf catalog safeguards and adds the NetBird Compose service and helper. It does not enroll the appliance or start an overlay connection by itself.

```bash
unzip -oq pc_game_archive_v0.19.41.zip
cd pc_game_archive_v0.19.41
sudo bash ./upgrade.sh
```

After the upgrade, open Control Center → Remote Networking, install NetBird, then connect the appliance with a setup key from your NetBird management console. The peer identity is persisted at `/var/lib/pc-game-archive/netbird`. The setup key is kept out of Compose environment metadata and PCGA configuration.

The client and server must join the same NetBird network, and its access policy must permit the client to reach the PCGA portal and Moonlight lanes. The current thin-client bootstrap does not distribute a client enrollment key; enroll the client through its own NetBird flow or a separate setup-key handoff.

## Build

```bash
python3 tools/build_release.py ../pc_game_archive_v0.19.41.zip
```

The builder validates Linux line endings, Python syntax, archive contents, and the embedded SHA-256 manifest, then writes a checksum beside the release ZIP.
