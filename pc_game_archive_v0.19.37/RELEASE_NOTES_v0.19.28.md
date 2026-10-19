# PC Game Archive v0.19.28 — Fullscreen video playback refinements

This release fixes the portal Jellyfin player's cramped seek timeline and controls that remained permanently visible during fullscreen playback.

- The seek bar now owns the flexible width of the playback grid (rather than the elapsed-time label).
- A 10px-high track, 20px thumb, and 36px-high input target make seeking easier on large screens and with touch/pointer controls.
- Fullscreen controls and the technical stream badge fade after approximately three seconds of inactivity while a movie plays. Moving the mouse, touching the player, pressing a key, or interacting with the controls reveals them.
- Paused, buffering, seeking and keyboard-focused states retain their controls for accessibility. Esc/exit fullscreen restores standard layout. Reduced-motion preference disables animations.
- Small-screen and TV responsive layouts remain supported.
- Existing playback sessions, preferences, media content and Jellyfin API behavior are unaffected.

## Upgrade

From the extracted release folder: `sudo ./upgrade_to_v0.19.28.sh`.

Reload existing portal tabs after the upgrade. Test with a title in **Movies & TV** at desktop and TV screen sizes.

## Testing

Offline Python regression suite, JavaScript syntax validation, and browser layout/idle tests. The upgrade still requires live acceptance on your PCGA appliance.
