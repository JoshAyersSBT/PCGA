#!/usr/bin/env bash
set -Eeuo pipefail
VERSION="0.19.39"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ $EUID -eq 0 ]] || exec sudo -E bash "$0" "$@"
[[ -f /opt/pc-game-archive/.env && -f /usr/local/sbin/pcga-control ]] || { echo 'Existing PCGA stack not found' >&2; exit 1; }
cd "$HERE"
sha256sum --check --quiet MANIFEST.sha256
export PYTHONDONTWRITEBYTECODE=1
python3 -m unittest discover -s "$HERE/tests" -p '*1939.py' -q
python3 -m unittest discover -s "$HERE/tests" -p '*1938.py' -q
python3 "$HERE/upgrade_catalog.py"
