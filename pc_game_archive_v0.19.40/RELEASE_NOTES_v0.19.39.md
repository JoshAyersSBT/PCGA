# v0.19.39 â€” Stable Wolf Catalog

## Problem

The live appliance repeatedly reloaded Wolf while reconciling game profiles. Wolf's TOML saves remove comments and change quoting/key order. PCGA treated missing comment markers as missing registrations, even when runner settings were intact. Heroic sync similarly appended another launcher whenever its marker comments disappeared; the captured PCGA profile contained 34 copies. Two existing titles were quarantined by the old comment-presence check.

## Changes

- Identify owned apps from their Docker runner's exact `PCGA_GAME_SET_ID` environment entry, within `moonlight-profile-id` only. Heroic also requires its managed mode setting.
- Compare parsed TOML and parsed Docker creation JSON. Ignore comments, quoting and JSON whitespace; keep runtime images, mounts, devices, environment and app counts meaningful.
- Remove duplicate owned Heroic tables and preserve unrelated app tables, profiles and global settings. Validate source ranges against parsed TOML before editing.
- Use one locked, persistent reload queue for game and Heroic changes. Check games, setup sessions, active control connections and launch reservations before reloading. Failed idle-state checks defer work.
- Verify actual app settings after a reload. Historical marker failures can recover when settings already match; the focused upgrade gives those old failures one controlled retry. New failures remain quarantined without recurring reloads.
- Patch only recognized installed functions, preserving unrelated local changes. Require v0.19.38/v0.19.39, back up scripts/config/state, and restore prior timer activity on success or failure.

## Validation

27 catalog and upgrade regressions cover serialized app entries captured from the appliance, 34-to-one Heroic cleanup, changed image/environment detection, custom profile preservation, quarantine recovery, no second restart, guarded function replacement, successful installation and rollback. The 35 v0.19.38 streaming, patch-status and packaging checks are retained.

A local dry run using all 43 captured PCGA app entries removes 33 Heroic duplicates, leaving 10 entries; a second pass is byte-identical. This is a dry run, not a claim that live installation or gameplay has been verified.

Live upgrade acceptance requires all four browser app catalogs to match Wolf's effective profile and a second full registration pass to leave the config and Wolf start time unchanged. The next chat verification should observe the resumed periodic timers as well.

The rollback simulation redirects only production state namespaces, preserving already-created temporary paths on Linux and Windows. Explicit path cases prevent repeated sandbox-prefix mapping. The package test correction does not change installed runtime code.
