# Native console emulators — PCGA v0.19.17

The RomM library already recognizes `ngc`, `wii`, `ps2`, `ps3`, and `ps4`. These platforms now map to the appropriate native emulator in `/api/games/emulators` and Console Games settings. They do **not** acquire an EmulatorJS browser core or a fake Play button.

| Emulator | Platforms | System Flatpak |
| --- | --- | --- |
| Dolphin | `ngc`, `wii` | `org.DolphinEmu.dolphin-emu` |
| PCSX2 | `ps2` | `net.pcsx2.PCSX2` |
| RPCS3 | `ps3` | `net.rpcs3.RPCS3` |
| shadPS4 | `ps4` | `net.shadps4.shadPS4` |

## Opt-in host setup

```bash
sudo apt-get install flatpak
sudo flatpak remote-add --system --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
sudo pcga-native-emulators install all
sudo pcga-native-emulators status
```

The upgrade does not fetch binaries, commercial games, encryption keys, console firmware, or BIOS images. These must be sourced legally by the operator. Only import games that you are authorized to use. Create `ngc`, `wii`, `ps2`, `ps3`, `ps4` folders in the existing ROM library for RomM discovery; do not move existing content. For PS3, directory-based dumps require special handling by the eventual game launcher. PS4 support is experimental and game compatibility varies greatly.

**Not yet included:** headless graphics compositor launch, native input/audio/video forwarding, Flatpak ROM filesystem grants, game-specific process lifecycle control, and browser play. A Flatpak being installed is not proof that an emulator can run on the server's GPU. No automatic native launch is exposed until that pipeline is tested.
