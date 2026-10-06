#!/usr/bin/env bash
set -Eeuo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE="$HERE/pc_game_archive_setup_v0.17.53-base.sh"
UPGRADE="$HERE/upgrade_to_v0.18.85.sh"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  exec sudo -E "$0" "$@"
fi

[[ -x "$BASE" ]] || { echo "[pcga-setup:error] Missing v0.17.53 base installer: $BASE" >&2; exit 1; }
[[ -x "$UPGRADE" ]] || { echo "[pcga-setup:error] Missing v0.18.85 upgrader: $UPGRADE" >&2; exit 1; }

printf '[pcga-setup] Installing PCGA v0.17.53 base appliance before applying the v0.18.85 shared game-LAN, multi-session Wine desktop, game-database, optical-runtime, portal, media, NAS, and game-stack upgrades...\n'
"$BASE" "$@"
printf '[pcga-setup] Applying v0.18.85 CDEmu/VHBA recovery with non-destructive COD2 single-player ISO fallback while preserving the working Wine 9 multiplayer path and current PCGA application upgrades...\n'
"$UPGRADE"
printf '[pcga-setup] PCGA v0.18.85 installation complete.\n'
