# PC Game Archive v0.19.13

This version adds **optional native Steam and Steam Remote Play hosting** beside Epic/GOG support. It does not silently start Steam.

## Upgrade

Stop active game sessions, downloads and rips, then run `sudo ./upgrade_to_v0.19.13.sh`.

Open **Control Center → Games → Steam** to inspect prerequisites and explicitly start the isolated Steam runtime. It uses the third-party `josh5/steam-headless:2` image (unpinned digest) with host networking, GPU access, input devices and elevated container capabilities; assess compatibility/security before enabling on a trusted LAN. The Steam client handles sign-in, game install/update, Linux/Proton compatibility and Remote Play pairing.

Persistent files are kept in `<archive-root>/games/steam/{home,library,state,journal}`. The local Steam setup interface may be available on port 8083; never expose it directly to the public internet. Stream using a Steam Link client or signed-in Steam client. Steam setup and playback do not occur inside the PCGA portal.

The installed-games panel scans native Steam `appmanifest_*.acf` files under the managed library; Steam owns the contents. Existing Wolf streams and Epic/GOG games are unaffected.

### Requirements

A Linux host with Docker, a suitable GPU DRM render node, `/dev/uinput`, and `/dev/fuse`. Support of Steam Remote Play and input/encoding depends on the actual GPU, drivers, host networking and connected client.

### Limitations

- Steam sign-in and installs are managed by the native Steam client, not PCGA UI.
- Steam Link/Remote Play pairing and playback are external to the browser.
- Steam games do not yet become Wolf entries; this is a separate Steam streaming path.
- Runtime image is opt-in; production GPU and account tests remain necessary.
