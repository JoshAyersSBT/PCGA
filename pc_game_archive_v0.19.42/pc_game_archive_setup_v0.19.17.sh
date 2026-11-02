#!/usr/bin/env bash
set -Eeuo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE="$HERE/pc_game_archive_setup_v0.17.53-base.sh"
UPGRADE="$HERE/upgrade_to_v0.19.17.sh"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  exec sudo -E "$0" "$@"
fi

[[ -x "$BASE" ]] || { echo "[pcga-setup:error] Missing v0.17.53 base installer: $BASE" >&2; exit 1; }
[[ -x "$UPGRADE" ]] || { echo "[pcga-setup:error] Missing v0.19.17 upgrader: $UPGRADE" >&2; exit 1; }

printf '[pcga-setup] Installing PCGA v0.17.53 base appliance before applying the v0.19.17 shared game-LAN, multi-session Wine desktop, game-database, optical-runtime, portal, media, NAS, and game-stack upgrades...\n'
"$BASE" "$@"
printf '[pcga-setup] Applying v0.19.17 Epic/GOG update, verify and guarded uninstall support with the existing Proton/UMU controls, with Amazon account/library browsing preserved alongside PCGA media, responsive portal, remote networking and existing game streaming...\n'
"$UPGRADE"
printf '[pcga-setup] PCGA v0.19.17 installation complete.\n'
