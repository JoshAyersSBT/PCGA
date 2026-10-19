#!/usr/bin/env bash
set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HERE/upgrade_to_v0.19.37.sh"
exec bash "$TARGET" "$@"
