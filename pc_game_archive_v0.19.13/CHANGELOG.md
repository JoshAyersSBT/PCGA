# PCGA v0.19.13 — Optional native Steam integration (initial release)

- Adds an opt-in Steam Headless runtime for the native Steam client, Steam Play/Proton and Steam Remote Play.
- Steam uses its own authentication, downloads and updates; PCGA does not collect credentials.
- Adds Control Center → Games Steam status/start/stop, local setup link, and a read-only installed Steam-games view.
- Steam games are discovered via appmanifest files from the dedicated persistent Steam library.
- Existing Epic/GOG store queues and Wolf sessions remain separate and unchanged.

**Limitations:** Steam's initial login/setup is still performed in its native client; Steam Link pairing is performed in Steam Link/Steam. Steam games are not imported into Wolf, and Steam streaming is not embedded inside the PCGA browser. Steam Headless host networking and privileges require a trusted LAN. Tested with fixtures only; real GPU, Steam login and Remote Play need appliance testing.
