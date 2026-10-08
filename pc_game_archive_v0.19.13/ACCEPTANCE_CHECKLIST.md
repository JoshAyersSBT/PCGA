# Steam integration acceptance checklist

- [ ] Confirm Docker and DRM GPU devices, `/dev/uinput`, `/dev/fuse`.
- [ ] Enable only on trusted LAN; inspect firewall restrictions for Steam Headless UI.
- [ ] Start Steam in Control Center, verify runtime becomes running.
- [ ] Sign in inside native Steam client and install one Linux game and one Proton game.
- [ ] Refresh Installed Steam games and see both titles.
- [ ] Pair Steam Link to the PCGA Steam host and stream both games with a controller.
- [ ] Stop/restart Steam and verify installed games/config remain.
- [ ] Verify Epic/GOG downloads, Wolf sessions and other PCGA services remain unchanged.
