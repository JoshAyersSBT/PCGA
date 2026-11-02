# PCGA v0.19.40 — Stable Wolf catalog reconciliation

## Problem

Wolf rewrites its configuration and can remove comments or normalize TOML and JSON formatting. The earlier reconciler treated those formatting changes as missing game registrations, which could repeatedly reload Wolf and duplicate Heroic entries.

## Changes

- Identify PCGA-owned game entries from the exact managed runtime environment and compare parsed app settings rather than comment markers.
- Reconcile Heroic entries without duplicating them, while preserving unrelated apps, profiles and global settings.
- Serialize catalog reloads and defer them while streams or launches are active.
- Give previously quarantined registrations one controlled recovery attempt, then keep genuine failures visible without repeated reloads.
- Back up changed scripts, configuration and registration state, validate all four live browser catalogs, and restore the previous state if validation fails.
- Keep the standard `upgrade.sh` entrypoint and accept an existing v0.19.39 appliance; rerunning v0.19.40 is supported.

## Validation

The release runs the 1940 upgrade and rollback tests, the 1939 catalog regressions, and the retained 1938 streaming and packaging regressions before changing the appliance. Live acceptance still requires verifying all four lane catalogs and confirming a second reconciliation leaves Wolf's configuration and start time unchanged.
