#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COMP="$HERE/components"
VERSION="0.19.37"
STACK_DIR=/opt/pc-game-archive
STATUS_DIR="$STACK_DIR/status"

[[ -r "$COMP/pcga-upgrade-diagnostics-check" ]] || die "Missing secure Diagnostics response validator"

[[ $EUID -eq 0 ]] || exec sudo -E bash "$0" "$@"
log(){ printf '[pcga-upgrade] %s\n' "$*"; }
die(){ printf '[pcga-upgrade:error] %s\n' "$*" >&2; exit 1; }

[[ -d "$STACK_DIR" ]] || die "Existing PCGA stack not found at $STACK_DIR. Use the full setup script instead."
[[ -r /etc/pc-game-archive/archive-root ]] || die "Missing /etc/pc-game-archive/archive-root"
ROOT="$(cat /etc/pc-game-archive/archive-root)"
[[ -n "$ROOT" && "$ROOT" = /* ]] || die "Invalid archive root: '$ROOT'"

# v0.19.31 calm browsing preflight before host modifications.
for marker in 'def jellyfin_media_details(' 'data-library-play' 'data-library-back' 'data-library-more' 'data-library-manage' 'function libraryBack()' 'library-detail-layout'; do
  grep -Fq "$marker" "$COMP/pcga-status-server.py" || die "Calm media browser component missing: $marker"
done
# v0.19.31 TV journey: native season/episode catalog and explicit episode completion.
for marker in 'def jellyfin_series_guide(' 'api/jellyfin/series-guide' 'library-season-select' 'function finishVideoIntentionally()' 'data-video-next' 'video-finished' 'nextEpisodeFromGuide'; do
  grep -Fq "$marker" "$COMP/pcga-status-server.py" || die "TV episode journey missing: $marker"
done
# v0.19.32 bonus features must be source-linked, playable and navigable.
for marker in 'def jellyfin_title_extras(' '/api/jellyfin/title-extras' 'data-library-extra-index' 'loadJellyfinExtras(' 'library-extras-list' 'videoPendingNext=null;playVideoItem(extra,null)'; do
  grep -Fq "$marker" "$COMP/pcga-status-server.py" || die "Jellyfin bonus-feature browsing missing: $marker"
done
# Validate release consistency before making any host changes.
grep -Fxq "VERSION = \"$VERSION\"" "$COMP/pcga-status-server.py" || die "Bundled portal API version does not match $VERSION"
grep -Fxq "VERSION = \"$VERSION\"" "$COMP/pcga-control" || die "Bundled control API version does not match $VERSION"
grep -Fq "const PORTAL_BUILD_VERSION='$VERSION'" "$COMP/pcga-status-server.py" || die "Bundled portal UI version does not match $VERSION"
grep -Fq 'function pcgaSmartTvBrowser()' "$COMP/pcga-status-server.py" || die "TV browser detection missing"
grep -Fq 'body[data-device-layout="tv"] .shell' "$COMP/pcga-status-server.py" || die "TV safe-area layout missing"
grep -Fq 'id="setting-tv-safe-area"' "$COMP/pcga-status-server.py" || die "TV overscan setting missing"
grep -Fq 'id="quick-tv-mode"' "$COMP/pcga-status-server.py" || die "TV mode override missing"
# Prevent regressions in parallel optical metadata and bonus-feature routing.
grep -Fq 'if not explicit_fingerprint:' "$COMP/pcga-media-intake" || die "Optical artifact binding still trusts names or timestamps"
grep -Fq 'needs_feature_review' "$COMP/pcga-classify" || die "Multi-title promotion protection missing"
grep -Fq 'Select exactly one main feature in Manual Review' "$COMP/pcga-manual-review" || die "Main-feature selection enforcement missing"
grep -Fq 'pcga-arm-shared-output.lock' "$COMP/pcga-arm-rip" || die "ARM single-writer output lock missing"
grep -Fq 'set_aside_incorrect_movie' "$COMP/pcga-manual-review" || die "Safe missing-feature correction unavailable"
grep -Fq 'def assemble_segment_job' "$COMP/pcga-manual-review" || die "Optical segment assembly worker missing"
grep -Fq 'data-review-assemble' "$COMP/pcga-status-server.py" || die "Segment assembly UI missing"
grep -Fq 'optical-segment-assembly' "$COMP/pcga-classify" || die "Segment candidate must require review"
grep -Fq 'data-review-set-aside' "$COMP/pcga-status-server.py" || die "Set-aside movie UI unavailable"
[[ -f "$COMP/pcga-disc-structure" ]] || die "Missing optical provenance component"
grep -Fq 'pcga-disc-structure finish' "$COMP/pcga-arm-rip" || die "Disc-job finalization missing"
grep -Fq 'structured_optical' "$COMP/pcga-classify" || die "Optical-review fail-closed policy missing"
# Check lossless archive UI and job controls before touching host files.
grep -Fq 'cc-lossless-archive' "$COMP/pcga-status-server.py" || die "Lossless archive Control Center UI missing"
grep -Fq 'lossless-archive-start' "$COMP/pcga-control" || die "Lossless archive control action missing"
grep -Fq 'def decoded_sha256' "$COMP/pcga-lossless-archive" || die "Lossless archive verification missing"
grep -Fq 'cc-low-loss-source' "$COMP/pcga-status-server.py" || die "Low-loss encoder UI missing"
grep -Fq 'low-loss-encode-start' "$COMP/pcga-control" || die "Low-loss host action missing"
grep -Fq 'def compare_streams' "$COMP/pcga-low-loss-encode" || die "Low-loss verification missing"
grep -Fq 'low-loss-tier-offload-start' "$COMP/pcga-control" || die "NAS master tier action missing"
grep -Fq 'cc-low-loss-tier-offload' "$COMP/pcga-status-server.py" || die "NAS master tier UI missing"
grep -Fq 'def copy_verified' "$COMP/pcga-low-loss-tier" || die "NAS master checksum verification missing"
# Fullscreen media player must preserve timeline width and idle-control behavior.
grep -Fq 'function scheduleVideoIdle()' "$COMP/pcga-status-server.py" || die "Fullscreen playback control auto-hide missing"
grep -Fq 'minmax(0,1fr) auto auto minmax(90px,150px)' "$COMP/pcga-status-server.py" || die "Fullscreen seek layout missing"
grep -Fq 'video-idle .video-controls' "$COMP/pcga-status-server.py" || die "Fullscreen idle controls styling missing"
# NAS scanner must be bundled, API-wired and visible in Storage settings.
[[ -f "$COMP/pcga-nas-discover" ]] || die "NAS discovery helper missing"
grep -Fq 'nas-discover-start' "$COMP/pcga-control" || die "NAS scanner control endpoint missing"
grep -Fq 'cc-nas-discovery-results' "$COMP/pcga-status-server.py" || die "NAS scanner UI missing"
# Validate functional Steam v3 UI + host encoder wiring before touching the host.
grep -Fq 'cc-steam-encoder' "$COMP/pcga-status-server.py" || die "Steam encoder settings UI missing"
grep -Fq 'cc-steam-sunshine' "$COMP/pcga-status-server.py" || die "Steam Sunshine health UI missing"
grep -Fq ":8483/" "$COMP/pcga-status-server.py" || die "Steam HTTPS port 8483 link missing"
grep -Fq 'SHUI_ENCODER={configured_encoder()}' "$COMP/pcga-steam-native" || die "Steam Headless encoder persistence missing"
grep -Fq "'streaming_ready': bool(stream_ready)" "$COMP/pcga-steam-native" || die "Steam streaming readiness is not checked"
grep -Fq 'steam-native-encoder-apply' "$COMP/pcga-control" || die "Steam encoder apply control action missing"




# v0.19.36: Jellyfin must be discoverable, started when enabled, and checked
# through both the host and portal namespaces before declaring success.
grep -Fq 'def jellyfin_health_status()' "$COMP/pcga-status-server.py" || die "Jellyfin portal health probe missing"
grep -Fq 'data-library-diagnostics' "$COMP/pcga-status-server.py" || die "Movies & TV troubleshooting action missing"
grep -Fq '"docker:jellyfin"' "$COMP/pcga-control" || die "Missing Jellyfin diagnostic placeholder"

# v0.19.34: require read-only visual fingerprint scanner and review UI before changes.
grep -Fq 'def scan_visual(' "$COMP/pcga-extra-prune" || die "Visual fingerprint scanner missing"
grep -Fq 'def analyze_group(' "$COMP/pcga-stream-prune" || die "Stream-aware reconciliation engine missing"
grep -Fq 'data-stream-prune-stage' "$COMP/pcga-status-server.py" || die "Stream-aware portal controls missing"
grep -Fq 'name == "stream-prune-scan"' "$COMP/pcga-control" || die "Stream-aware control action missing"
grep -Fq 'id="cc-extra-prune-visual-scan"' "$COMP/pcga-status-server.py" || die "Visual scan control missing"
grep -Fq 'name == "extra-prune-scan-visual"' "$COMP/pcga-control" || die "Visual scanner action missing"
# v0.19.33: require the complete extras pruner before replacing host components.
[[ -f "$COMP/pcga-extra-prune" ]] || die "Missing extras pruning engine"
python3 -W error::SyntaxWarning -m py_compile "$COMP/pcga-extra-prune" || die "Extras pruning engine does not compile"
grep -Fq 'id="cc-extra-prune-scan"' "$COMP/pcga-status-server.py" || die "Portal is missing extras pruning controls"
grep -Fq 'name == "extra-prune-scan"' "$COMP/pcga-control" || die "Control plane is missing extras pruning action"

# Changing the concurrency policy mid-rip would leave the active, old-version
# ARM process outside the new exclusive staging lock. Fail before touching files.
if systemctl list-units --plain --no-legend --state=active,activating 'pcga-arm-rip@*.service' 2>/dev/null | grep -q 'pcga-arm-rip@'; then
  die "ARM rip still running; finish all optical jobs before applying v$VERSION concurrency protection"
fi
if docker exec arm-rippers sh -lc "ps -eo args | grep -Eq '[p]ython3 /opt/arm/arm/ripper/main.py|[m]akemkvcon|[H]andBrakeCLI'" 2>/dev/null; then
  die "ARM worker still active; finish both rips before upgrading"
fi
# Preflight repair of Wolf Compose. This runs before any service or Compose
# operation so a partially upgraded, unparsable compose.wolf.yml cannot block
# the reconciliation that repairs it.
repair_wolf_compose() {
  local f="$STACK_DIR/compose.wolf.yml"
  [[ -f "$f" ]] || return 0

  python3 - "$f" <<'PYWOLFPREFLIGHT'
from pathlib import Path
import sys
p = Path(sys.argv[1])
lines = p.read_text().splitlines()

def is_managed_wolf_env(line):
    s = line.lstrip()
    if s.startswith('#'):
        return False
    return (
        s.startswith('WOLF_INTERNAL_IP:') or
        s.startswith('"WOLF_INTERNAL_IP":') or
        s.startswith("'WOLF_INTERNAL_IP':") or
        s.startswith('- WOLF_INTERNAL_IP=') or
        s.startswith('- "WOLF_INTERNAL_IP=') or
        s.startswith("- 'WOLF_INTERNAL_IP=") or
        s.startswith('WOLF_USE_ZERO_COPY:') or
        s.startswith('"WOLF_USE_ZERO_COPY":') or
        s.startswith("'WOLF_USE_ZERO_COPY':") or
        s.startswith('- WOLF_USE_ZERO_COPY=') or
        s.startswith('- "WOLF_USE_ZERO_COPY=') or
        s.startswith("- 'WOLF_USE_ZERO_COPY=")
    )

clean = [line for line in lines if not is_managed_wolf_env(line)]
out = []
inserted = False
for line in clean:
    out.append(line)
    if inserted:
        continue
    stripped = line.lstrip()
    indent = line[:len(line)-len(stripped)]
    if stripped.startswith('WOLF_SOCKET_PATH:') or stripped.startswith('"WOLF_SOCKET_PATH":') or stripped.startswith("'WOLF_SOCKET_PATH':"):
        out.append(indent + 'WOLF_INTERNAL_IP: "${PCGA_LAN_IP}"')
        out.append(indent + 'WOLF_USE_ZERO_COPY: "FALSE"')
        inserted = True
    elif stripped.startswith('- WOLF_SOCKET_PATH=') or stripped.startswith('- "WOLF_SOCKET_PATH=') or stripped.startswith("- 'WOLF_SOCKET_PATH="):
        out.append(indent + '- WOLF_INTERNAL_IP=${PCGA_LAN_IP}')
        out.append(indent + '- WOLF_USE_ZERO_COPY=FALSE')
        inserted = True

if not inserted:
    raise SystemExit('Could not locate WOLF_SOCKET_PATH in compose.wolf.yml')
p.write_text('\n'.join(out) + '\n')
PYWOLFPREFLIGHT

  local count zero_count
  count="$(grep -Ec '^[[:space:]]*(WOLF_INTERNAL_IP:|-[[:space:]]*WOLF_INTERNAL_IP=)' "$f" || true)"
  [[ "$count" == "1" ]] || die "Wolf Compose repair produced $count WOLF_INTERNAL_IP entries"
  zero_count="$(grep -Ec '^[[:space:]]*(WOLF_USE_ZERO_COPY:|-[[:space:]]*WOLF_USE_ZERO_COPY=)' "$f" || true)"
  [[ "$zero_count" == "1" ]] || die "Wolf Compose repair produced $zero_count WOLF_USE_ZERO_COPY entries"

  local err
  err="$(mktemp)"
  if ! (cd "$STACK_DIR" && docker compose -f compose.wolf.yml config >/dev/null 2>"$err"); then
    printf '[pcga-upgrade:error] compose.wolf.yml is invalid after preflight repair:\n' >&2
    cat "$err" >&2 || true
    printf '[pcga-upgrade:error] Numbered compose.wolf.yml:\n' >&2
    nl -ba "$f" | sed -n '1,180p' >&2
    rm -f "$err"
    exit 1
  fi
  rm -f "$err"
}

# Wolf Compose must not be mutated before the backup below.

IMMICH_PORT="2283"
if [[ -r "$STACK_DIR/.env" ]]; then
  p="$(awk -F= '$1=="IMMICH_PORT" {print substr($0,index($0,"=")+1)}' "$STACK_DIR/.env" | tail -n1)"
  [[ -n "$p" ]] && IMMICH_PORT="$p"
fi
[[ "$IMMICH_PORT" =~ ^[0-9]+$ ]] && (( IMMICH_PORT >= 1 && IMMICH_PORT <= 65535 )) || die "Invalid IMMICH_PORT '$IMMICH_PORT'"

ROMM_PORT="8082"
if [[ -r "$STACK_DIR/.env" ]]; then
  p="$(awk -F= '$1=="ROMM_PORT" {print substr($0,index($0,"=")+1)}' "$STACK_DIR/.env" | tail -n1)"
  [[ -n "$p" ]] && ROMM_PORT="$p"
fi
[[ "$ROMM_PORT" =~ ^[0-9]+$ ]] && (( ROMM_PORT >= 1 && ROMM_PORT <= 65535 )) || die "Invalid ROMM_PORT '$ROMM_PORT'"
JELLYFIN_CURRENT="$(awk -F= '$1=="JELLYFIN_PORT"{print $2}' "$STACK_DIR/.env" 2>/dev/null | tail -n1)"; JELLYFIN_CURRENT="${JELLYFIN_CURRENT:-8096}"
ARM_CURRENT="$(awk -F= '$1=="ARM_PORT"{print $2}' "$STACK_DIR/.env" 2>/dev/null | tail -n1)"; ARM_CURRENT="${ARM_CURRENT:-8081}"
STATUS_CURRENT="$(awk -F= '$1=="PCGA_STATUS_PORT"{print $2}' "$STACK_DIR/.env" 2>/dev/null | tail -n1)"; STATUS_CURRENT="${STATUS_CURRENT:-8098}"
for busy in "$IMMICH_PORT" "$JELLYFIN_CURRENT" "$ARM_CURRENT" "$STATUS_CURRENT" "8080" "1337" "8093" "8101" "8102" "8103" "8104" "8443"; do
  [[ "$ROMM_PORT" != "$busy" ]] || die "ROMM_PORT $ROMM_PORT conflicts with an existing PCGA service port"
done

TZ_VALUE="$(awk -F= '$1=="TZ" {print substr($0,index($0,"=")+1)}' "$STACK_DIR/.env" 2>/dev/null | tail -n1)"
TZ_VALUE="${TZ_VALUE:-America/New_York}"

for f in \
  pcga-lossless-archive pcga-low-loss-encode pcga-low-loss-tier pcga-disc-structure pcga-arm-configure pcga-arm-rip pcga-arm-watch pcga-makemkv-preflight pcga-optical-identify pcga-game-disc-metadata pcga-game-intake pcga-game-orchestrator pcga-heroic-bootstrap pcga-heroic-sync pcga-steam-native pcga-store-provider pcga-store-bootstrap pcga-store-bootstrap.service pcga-store-jobs pcga-store-jobs.service pcga-store-ingest pcga-store-game-startup pcga-store-compat pcga-store-umu.service pcga-store-ingest.service pcga-store-ingest.timer pcga-heroic-bootstrap.service pcga-heroic-sync.service pcga-heroic-sync.timer pcga-game-compat-resolver pcga-game-compat-test pcga-cdemu-bootstrap pcga-cdemu-userspace-bootstrap pcga-cdemu.service pcga-game-orchestrator.service pcga-game-orchestrator.timer pcga-media-disc-metadata pcga-media-intake pcga-optical-dispatch pcga-optical-dispatch@.service pcga-optical-watch pcga-optical-watch.service pcga-pc-disc-rip pcga-pc-disc-rip@.service pcga-optical-health pcga-appliance-credentials pcga-romm-bootstrap pcga-native-emulators pcga-lancommander-bootstrap pcga-immich-bootstrap pcga-jellyfin-appliance-user pcga-service-auth pcga-secure-context-bootstrap pcga-network-identity pcga-network-identity.service pcga-moonlight-web-bootstrap pcga-tailscale-remote pcga-netbird-remote pcga-zerotier-remote pcga-thin-client-bootstrap pcga-thin-client-bootstrap.service pcga-lan-dns pcga-lan-dns.service pcga-media-sort pcga-ingest-reconcile pcga-classify pcga-metadata-classify pcga-manual-review pcga-public-media pcga-status-server.py \
  pcga-game-stack-start pcga-game-stack.service pcga-service-auth.service pcga-service-auth.timer \
  pcga-media-sort.service pcga-media-sort.path pcga-media-sort.timer \
  pcga-metadata-classify.service pcga-metadata-classify.path pcga-metadata-classify.timer pcga-public-media.service pcga-dedupe pcga-dedupe.service pcga-dedupe.timer pcga-control pcga-control.service \
  pcga-nas-storage pcga-nas-mount.service pcga-nas-sync.service pcga-nas-sync.timer; do
  [[ -f "$COMP/$f" ]] || die "Release component missing: $f"
done
[[ -f "$COMP/compose.moonlight-web.yml" ]] || die "Release component missing: compose.moonlight-web.yml"
[[ -f "$COMP/compose.game-lan.yml" ]] || die "Release component missing: compose.game-lan.yml"

# v0.18.24 retains post-rip scheduling and adds preservation-backed runtime optical media but does not replace ARM/MakeMKV workers.
# Active optical rips may continue while the sorter/classifier units are repaired.
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/var/backups/pc-game-archive/v$VERSION-$STAMP"
install -d -m 0700 "$BACKUP"
log "Backing up sorter/classifier/UI files to $BACKUP"
for f in \
  /usr/local/sbin/pcga-lossless-archive \
  /usr/local/sbin/pcga-low-loss-encode \
  /usr/local/sbin/pcga-low-loss-tier \
  /usr/local/sbin/pcga-arm-configure \
  /usr/local/sbin/pcga-disc-structure \
  /usr/local/sbin/pcga-arm-rip \
  /usr/local/sbin/pcga-arm-watch \
  /usr/local/sbin/pcga-makemkv-preflight \
  /usr/local/sbin/pcga-optical-identify \
  /usr/local/sbin/pcga-game-disc-metadata \
  /usr/local/sbin/pcga-game-intake \
  /usr/local/sbin/pcga-game-orchestrator \
  /usr/local/sbin/pcga-heroic-bootstrap \
  /usr/local/sbin/pcga-heroic-sync \
  /usr/local/sbin/pcga-steam-native \
  /usr/local/sbin/pcga-store-provider \
  /usr/local/sbin/pcga-store-bootstrap \
  /etc/systemd/system/pcga-store-bootstrap.service \
  /usr/local/sbin/pcga-store-jobs \
  /usr/local/sbin/pcga-store-ingest \
  /usr/local/sbin/pcga-store-compat \
  /etc/systemd/system/pcga-store-umu.service \
  /etc/systemd/system/pcga-store-ingest.service \
  /etc/systemd/system/pcga-store-ingest.timer \
  /etc/systemd/system/pcga-store-jobs.service \
  /etc/systemd/system/pcga-heroic-bootstrap.service \
  /etc/systemd/system/pcga-heroic-sync.service \
  /etc/systemd/system/pcga-heroic-sync.timer \
  /usr/local/sbin/pcga-game-compat-resolver \
  /usr/local/sbin/pcga-game-compat-test \
  /etc/systemd/system/pcga-cdemu.service \
  /etc/systemd/system/pcga-game-orchestrator.service \
  /etc/systemd/system/pcga-game-orchestrator.timer \
  /usr/local/sbin/pcga-media-disc-metadata \
  /usr/local/sbin/pcga-media-intake \
  /usr/local/sbin/pcga-optical-dispatch \
  /usr/local/sbin/pcga-optical-watch \
  /usr/local/sbin/pcga-pc-disc-rip \
  /usr/local/sbin/pcga-optical-health \
  /etc/systemd/system/pcga-arm-watch.service \
  /etc/systemd/system/pcga-optical-watch.service \
  /etc/systemd/system/pcga-optical-dispatch@.service \
  /etc/systemd/system/pcga-pc-disc-rip@.service \
  /etc/udev/rules.d/52-pcga-media-rip.rules \
  /usr/local/sbin/pcga-media-sort \
  /usr/local/sbin/pcga-ingest-reconcile \
  /usr/local/sbin/pcga-classify \
  /usr/local/sbin/pcga-metadata-classify \
  /usr/local/sbin/pcga-manual-review \
  /usr/local/sbin/pcga-public-media \
  /usr/local/sbin/pcga-dedupe \
  /usr/local/sbin/pcga-control \
  /usr/local/bin/game-archive \
  /usr/local/sbin/pcga-jellyfin-configure \
  /usr/local/sbin/pcga-appliance-credentials \
  /usr/local/sbin/pcga-immich-bootstrap \
  /usr/local/sbin/pcga-jellyfin-appliance-user \
  /usr/local/sbin/pcga-game-stack-start \
  /usr/local/sbin/pcga-service-auth \
  /usr/local/sbin/pcga-moonlight-web-bootstrap \
  /usr/local/sbin/pcga-secure-context-bootstrap \
  /usr/local/sbin/pcga-network-identity \
  /etc/systemd/system/pcga-network-identity.service \
  /usr/local/sbin/pcga-tailscale-remote \
  /usr/local/sbin/pcga-netbird-remote \
  /usr/local/sbin/pcga-zerotier-remote \
  /usr/local/sbin/pcga-thin-client-bootstrap \
  /etc/systemd/system/pcga-thin-client-bootstrap.service \
  /usr/local/sbin/pcga-lan-dns \
  /etc/systemd/system/pcga-lan-dns.service \
  /etc/avahi/hosts \
  /etc/hosts \
  /etc/pc-game-archive/lan-https-port \
  /etc/pc-game-archive/lan-dns-upstream.conf \
  /etc/pc-game-archive/tls \
  /etc/systemd/system/pcga-game-stack.service \
  /etc/systemd/system/pcga-service-auth.service \
  /etc/systemd/system/pcga-service-auth.timer \
  /etc/pc-game-archive/secrets/appliance-admin.env \
  /etc/systemd/system/pcga-public-media.service \
  /etc/systemd/system/pcga-dedupe.service \
  /etc/systemd/system/pcga-dedupe.timer \
  /etc/systemd/system/pcga-control.service \
  /usr/local/sbin/pcga-nas-storage \
  /usr/local/sbin/pcga-nas-discover \
  /etc/systemd/system/pcga-nas-mount.service \
  /etc/systemd/system/pcga-nas-sync.service \
  /etc/systemd/system/pcga-nas-sync.timer \
  /etc/pc-game-archive/secrets/nas.credentials \
  /etc/pc-game-archive/appliance.json \
  /etc/pc-game-archive/control-token \
  /etc/systemd/system/pcga-media-sort.service \
  /etc/systemd/system/pcga-media-sort.path \
  /etc/systemd/system/pcga-media-sort.timer \
  /etc/systemd/system/pcga-metadata-classify.service \
  /etc/systemd/system/pcga-metadata-classify.path \
  /etc/systemd/system/pcga-metadata-classify.timer \
  /etc/pc-game-archive/immich.env \
  /etc/pc-game-archive/romm.env \
  "$STACK_DIR/compose.immich.yml" \
  "$STACK_DIR/compose.romm.yml" \
  "$STACK_DIR/compose.wolf.yml" \
  "$STACK_DIR/compose.moonlight-web.yml" \
  "$STACK_DIR/compose.game-lan.yml" \
  "$STACK_DIR/compose.nas.yml" \
  "$STACK_DIR/compose.yml" \
  "$STACK_DIR/.env" \
  "$STATUS_DIR/server.py"; do
  [[ -e "$f" ]] || continue
  dest="$BACKUP${f}"
  install -d -m 0700 "$(dirname "$dest")"
  cp -a "$f" "$dest"
done

# The preflight repair is intentionally after the snapshot, and before the
# first Docker Compose transaction. If parsing still fails, the original file
# is available inside $BACKUP for rollback.
repair_wolf_compose

# Repair the PC-game Install/Retry path immediately after backup, before the
# larger stack transaction. The portal runs in Docker and delegates retry to
# pcga-control on the host; neither the container nor browser executes host
# binaries directly. Applying this here makes the fix survive an unrelated
# later migration failure without sacrificing the pre-upgrade backup.
install -d -m 0755 /usr/local/sbin /etc/systemd/system "$STATUS_DIR"
install -m 0755 "$COMP/pcga-game-orchestrator" /usr/local/sbin/pcga-game-orchestrator
# v0.18.69 repairs the COD2 pre-wizard failure seen after the synthetic optical
# conversion.  Two old duplicate UUIDs could both retain setup state, and the
# v0.18.63 cleanup path could unlink an ISO while its /dev/loop mount remained
# active.  Stop only COD2 setup containers, detach only COD2 disposable loop
# media, then reassert one historical canonical UUID.  Preserved/ripped ISOs and
# the Wine prefix are not deleted here.
COD2_IDS_FILE="$(mktemp)"
python3 - "$COD2_IDS_FILE" <<'PYPCGA65IDS'
import json,re,sys
from pathlib import Path
out=Path(sys.argv[1]); sets=Path('/var/lib/pc-game-archive/game-intake/sets'); states=Path('/var/lib/pc-game-archive/game-installs')
def load(p):
    try:return json.loads(p.read_text()) if p.is_file() else {}
    except Exception:return {}
def cod2(g,s):
    title=str(g.get('title') or s.get('title') or '').casefold()
    norm=re.sub(r'[^a-z0-9]+','',title)
    ext=g.get('external_ids') if isinstance(g.get('external_ids'),dict) else {}
    return norm in {'callofduty2','cod2'} or str(ext.get('steam') or '')=='2630'
ids=[]
for p in sorted(sets.glob('*.json')) if sets.exists() else []:
    g=load(p); sid=str(g.get('id') or p.stem); st=load(states/f'{sid}.json')
    if cod2(g,st): ids.append(sid)
for p in sorted(states.glob('*.json')) if states.exists() else []:
    sid=p.stem
    if sid in ids: continue
    st=load(p); g=load(sets/f'{sid}.json')
    if cod2(g,st): ids.append(sid)
out.write_text('\n'.join(ids)+('\n' if ids else ''))
PYPCGA65IDS
mapfile -t PCGA65_COD2_IDS < "$COD2_IDS_FILE"
rm -f "$COD2_IDS_FILE"

COD2_ANY_READY=0
for sid in "${PCGA65_COD2_IDS[@]:-}"; do
  [[ -n "$sid" ]] || continue
  if python3 - "/var/lib/pc-game-archive/game-installs/$sid.json" <<'PYPCGA74READY' >/dev/null 2>&1
import json,sys
try:
    d=json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if d.get('status') == 'ready' else 1)
PYPCGA74READY
  then
    COD2_ANY_READY=1
    break
  fi
done

# The v0.18.69 loop-repair migration used to run on every upgrade and forcibly
# demote a healthy COD2 install back to setup-required.  Only invoke that legacy
# cleanup when *no* canonical/duplicate COD2 record is currently READY. A healthy
# installed prefix is now immutable across routine upgrades.
if (( ${#PCGA65_COD2_IDS[@]} )) && (( COD2_ANY_READY == 0 )); then
  log "Repairing non-ready COD2 duplicate/synthetic setup state for ${#PCGA65_COD2_IDS[@]} record(s)"
  # Stop only streamed setup containers belonging to these COD2 UUIDs. This
  # releases bind references to deleted loop images before host unmount/detach.
  while read -r cid image cname; do
    [[ -n "$cid" ]] || continue
    for sid in "${PCGA65_COD2_IDS[@]}"; do
      compact="${sid//-/}"
      if [[ "$image" == "pcga/setup-$sid" || "$cname" == *"${sid%%-*}"* || "$cname" == *"$compact"* ]]; then
        log "Stopping stale COD2 setup container $cname"
        docker stop -t 8 "$cid" >/dev/null 2>&1 || true
        break
      fi
    done
  done < <(docker ps --format '{{.ID}} {{.Image}} {{.Names}}' 2>/dev/null || true)

  for sid in "${PCGA65_COD2_IDS[@]}"; do
    ir="$ROOT/games/installed/$sid"
    target="$ir/setup-source"
    if [[ -d "$target" ]] && findmnt -rn -M "$target" >/dev/null 2>&1; then
      log "Unmounting stale COD2 synthetic source for $sid"
      umount "$target" || die "Could not unmount stale COD2 setup source $target"
    fi
    # Detach loop devices whose backing file belongs to the disposable synthetic
    # setup ISO, including the `(deleted)` loops shown by v0.18.64 diagnostics.
    while read -r loopdev backing rest; do
      [[ -n "$loopdev" ]] || continue
      case "$backing" in
        "$ir/setup-source-v01863.iso"*|"$ir/setup-source-v01865.iso"*|"$ir/setup-source-v01866.iso"*)
          losetup -d "$loopdev" >/dev/null 2>&1 || true ;;
      esac
    done < <(losetup -l -n -O NAME,BACK-FILE 2>/dev/null || true)
    rm -f "$ir/setup-source-v01863.iso" "$ir/.setup-source-v01863.iso.tmp" \
          "$ir/setup-source-v01865.iso" "$ir/.setup-source-v01865.iso.tmp" \
          "$ir/setup-source-v01866.iso" "$ir/.setup-source-v01866.iso.tmp" || true
    rm -rf "$ir/.setup-source-v01863.tmp" "$ir/.setup-source-v01865.tmp" "$ir/.setup-source-v01866.tmp" || true
    if [[ -e "$target" ]] && ! findmnt -rn -M "$target" >/dev/null 2>&1; then
      rm -rf "$target"
    fi
    install -d -m 0755 "$target"
  done

  python3 - "${PCGA65_COD2_IDS[@]}" <<'PYPCGA65CANON'
import json,os,sys,time
from pathlib import Path
ids=[x for x in sys.argv[1:] if x]
sets=Path('/var/lib/pc-game-archive/game-intake/sets'); states=Path('/var/lib/pc-game-archive/game-installs')
def load(p):
    try:return json.loads(p.read_text()) if p.is_file() else {}
    except Exception:return {}
def save(p,d):
    p.parent.mkdir(parents=True,exist_ok=True); tmp=p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n'); os.replace(tmp,p)
if ids:
    member=set(ids)
    historical=[]; visible=[]
    for sid in ids:
        g=load(sets/f'{sid}.json'); st=load(states/f'{sid}.json')
        merged={str(x) for x in g.get('merged_set_ids') or [] if str(x)}
        if merged & (member-{sid}) and not g.get('superseded_by'):
            historical.append(sid)
        if not g.get('catalog_hidden') and not g.get('superseded_by') and not st.get('catalog_hidden') and not st.get('duplicate_of'):
            visible.append(sid)
    if len(historical)==1: canonical=historical[0]
    elif len(visible)==1: canonical=visible[0]
    else:
        # Deterministic fallback: prefer the record already referencing the most
        # merged siblings, then the record with the larger preserved disc count.
        def score(sid):
            g=load(sets/f'{sid}.json'); st=load(states/f'{sid}.json')
            merged=len([x for x in g.get('merged_set_ids') or [] if str(x) in member])
            media=g.get('media') if isinstance(g.get('media'),dict) else {}
            try: discs=max(int(media.get('disc_count') or 0),int(st.get('source_logical_disc_count') or 0))
            except Exception: discs=0
            return (merged,discs,sid)
        canonical=max(ids,key=score)
    now=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    for sid in ids:
        gp=sets/f'{sid}.json'; sp=states/f'{sid}.json'; g=load(gp); st=load(sp)
        if sid==canonical:
            if g:
                compat=g.get('compatibility') if isinstance(g.get('compatibility'),dict) else {}
                profile=compat.get('profile') if isinstance(compat.get('profile'),dict) else {}
                if profile.pop('virtual_cd',None) is not None:
                    compat['profile']=profile; g['compatibility']=compat
                g.pop('superseded_by',None); g['catalog_hidden']=False
                old=[str(x) for x in g.get('merged_set_ids') or [] if str(x)]
                g['merged_set_ids']=list(dict.fromkeys(old+[x for x in ids if x!=canonical]))[-32:]
                g['updated_at']=now; save(gp,g)
            if st:
                st['catalog_hidden']=False; st['duplicate_of']=None
                st['status']='setup-required'; st['phase']='interactive-setup'
                st['setup_reason']='v0.18.69-cod2-loop-repair'
                st['setup_source']=None; st['setup_installer']='setup.exe'; st['setup_kind']='exe'
                st['setup_runtime_image']=None; st['setup_runtime_build_hash']=None; st['setup_runtime_log']=None
                st['stream_state']='pending'; st['stream_app_title']=None
                for key in list(st):
                    if key.startswith('setup_source_multidisc_optical_v0186') or key.startswith('setup_source_iso_v0186') or key.startswith('setup_source_device_v0186') or key.startswith('setup_source_volume_label_v0186') or key.startswith('setup_source_msi_media_flattened_v0186'):
                        st.pop(key,None)
                st['detail']='v0.18.69 removed stale/deleted synthetic loop media; COD2 will rebuild one canonical read-only COD2DVD source'
                save(sp,st)
        else:
            if g:
                compat=g.get('compatibility') if isinstance(g.get('compatibility'),dict) else {}
                profile=compat.get('profile') if isinstance(compat.get('profile'),dict) else {}
                if profile.pop('virtual_cd',None) is not None:
                    compat['profile']=profile; g['compatibility']=compat
                g['catalog_hidden']=True; g['superseded_by']=canonical; g['superseded_at']=now; save(gp,g)
            if st:
                st['catalog_hidden']=True; st['duplicate_of']=canonical
                st['stream_state']='superseded'; st['stream_app_title']=None
                st['setup_runtime_image']=None; st['setup_runtime_build_hash']=None
                st['detail']=f'Duplicate COD2 state consolidated into {canonical}; preserved source retained'
                save(sp,st)
    print(f'[pcga-upgrade] COD2 canonical UUID pinned to {canonical}; stale sibling setup states hidden')
PYPCGA65CANON
elif (( ${#PCGA65_COD2_IDS[@]} )); then
  log "COD2 has a READY install; skipping legacy synthetic-media migration so the installed prefix remains untouched"
fi

# v0.18.69 repairs a visibility invariant exposed while COD2 was being restaged.
# Duplicate set metadata may identify one record as canonical while its install
# state still carries catalog_hidden/duplicate_of from an older consolidation.
# Clear only those stale state flags when the corresponding set record is visible.
python3 - <<'PYPCGACATALOGVIS'
import json, os
from pathlib import Path
sets=Path('/var/lib/pc-game-archive/game-intake/sets')
states=Path('/var/lib/pc-game-archive/game-installs')
repaired=[]
for q in sorted(states.glob('*.json')) if states.exists() else []:
    try: st=json.loads(q.read_text())
    except Exception: continue
    sid=str(st.get('game_set_id') or st.get('set_id') or q.stem)
    gp=sets/f'{sid}.json'
    try: game=json.loads(gp.read_text()) if gp.is_file() else {}
    except Exception: game={}
    if not game or game.get('catalog_hidden') or game.get('superseded_by'):
        continue
    if not (st.get('catalog_hidden') or st.get('duplicate_of')):
        continue
    st['catalog_hidden']=False
    st['duplicate_of']=None
    tmp=q.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(st,indent=2,sort_keys=True)+'\n')
    os.replace(tmp,q)
    repaired.append(sid)
if repaired:
    print('[pcga-upgrade] Recovered stale canonical PC-game visibility for: '+', '.join(repaired))
PYPCGACATALOGVIS
# v0.18.36 migrates the library from disc-centric discovery to a title-owned
# optical-disc-set model. This is additive: preserved disc records remain intact.
python3 - <<'PYPCGADISCOWNERSHIP'
import json, os
from pathlib import Path
state=Path('/var/lib/pc-game-archive/game-intake'); sets=state/'sets'; discs=state/'discs'
if sets.exists():
  by_set={}
  for q in discs.glob('*.json') if discs.exists() else []:
    try:d=json.loads(q.read_text())
    except Exception:continue
    ids=d.get('game_set_ids') if isinstance(d.get('game_set_ids'),list) else [d.get('game_set_id')]
    for sid in [str(x or '') for x in ids if x]:
      by_set.setdefault(sid,[]).append({
        'fingerprint':str(d.get('fingerprint') or q.stem),'disc_number':d.get('disc_number'),
        'disc_count':d.get('disc_count'),'disc_role':d.get('disc_role'),'volume_label':d.get('volume_label'),
        'metadata_status':d.get('metadata_status'),'layout':d.get('layout')})
  for q in sets.glob('*.json'):
    try:rec=json.loads(q.read_text())
    except Exception:continue
    sid=str(rec.get('id') or q.stem); rows=by_set.get(sid,[])
    rows.sort(key=lambda x:(x['disc_number'] if isinstance(x.get('disc_number'),int) else 9999,str(x.get('volume_label') or '').casefold()))
    declared=[x['disc_count'] for x in rows if isinstance(x.get('disc_count'),int) and x['disc_count']>0]
    rec['media']={'schema':1,'kind':'optical-disc-set','disc_count':max(declared) if declared else len(rows),'discs':rows}
    rec['disc_fingerprints']=[x['fingerprint'] for x in rows if x.get('fingerprint')]
    tmp=q.with_suffix('.json.tmp');tmp.write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n');os.replace(tmp,q)
PYPCGADISCOWNERSHIP
install -m 0755 "$COMP/pcga-game-compat-resolver" /usr/local/sbin/pcga-game-compat-resolver
install -m 0755 "$COMP/pcga-game-compat-test" /usr/local/sbin/pcga-game-compat-test
install -m 0755 "$COMP/pcga-cdemu-bootstrap" /usr/local/sbin/pcga-cdemu-bootstrap
install -m 0755 "$COMP/pcga-cdemu-userspace-bootstrap" /usr/local/sbin/pcga-cdemu-userspace-bootstrap
install -m 0644 "$COMP/pcga-cdemu.service" /etc/systemd/system/pcga-cdemu.service
install -m 0644 "$COMP/pcga-game-orchestrator.service" /etc/systemd/system/pcga-game-orchestrator.service
install -m 0644 "$COMP/pcga-game-orchestrator.timer" /etc/systemd/system/pcga-game-orchestrator.timer
install -m 0755 "$COMP/pcga-heroic-bootstrap" /usr/local/sbin/pcga-heroic-bootstrap
install -m 0755 "$COMP/pcga-heroic-sync" /usr/local/sbin/pcga-heroic-sync
install -m 0755 "$COMP/pcga-store-provider" /usr/local/sbin/pcga-store-provider
install -m 0755 "$COMP/pcga-store-bootstrap" /usr/local/sbin/pcga-store-bootstrap
install -m 0644 "$COMP/pcga-store-bootstrap.service" /etc/systemd/system/pcga-store-bootstrap.service
install -m 0755 "$COMP/pcga-store-compat" /usr/local/sbin/pcga-store-compat
install -m 0644 "$COMP/pcga-store-umu.service" /etc/systemd/system/pcga-store-umu.service
install -m 0755 "$COMP/pcga-store-ingest" /usr/local/sbin/pcga-store-ingest
install -m 0755 "$COMP/pcga-store-game-startup" /usr/local/sbin/pcga-store-game-startup
install -m 0644 "$COMP/pcga-store-ingest.service" /etc/systemd/system/pcga-store-ingest.service
install -m 0644 "$COMP/pcga-store-ingest.timer" /etc/systemd/system/pcga-store-ingest.timer
install -m 0755 "$COMP/pcga-store-jobs" /usr/local/sbin/pcga-store-jobs
install -m 0644 "$COMP/pcga-store-jobs.service" /etc/systemd/system/pcga-store-jobs.service
install -m 0644 "$COMP/pcga-heroic-bootstrap.service" /etc/systemd/system/pcga-heroic-bootstrap.service
install -m 0644 "$COMP/pcga-heroic-sync.service" /etc/systemd/system/pcga-heroic-sync.service
install -m 0644 "$COMP/pcga-heroic-sync.timer" /etc/systemd/system/pcga-heroic-sync.timer
install -m 0755 "$COMP/pcga-steam-native" /usr/local/sbin/pcga-steam-native
install -m 0755 "$COMP/pcga-control" /usr/local/sbin/pcga-control
install -m 0755 "$COMP/pcga-status-server.py" "$STATUS_DIR/server.py"
[[ -x /usr/local/sbin/pcga-game-orchestrator ]] || die "Unable to repair /usr/local/sbin/pcga-game-orchestrator"
systemctl daemon-reload
if systemctl cat pcga-control.service >/dev/null 2>&1; then
  systemctl restart pcga-control.service || die "Unable to restart PCGA control plane during early PC-game retry repair"
fi
if docker inspect pcga-status >/dev/null 2>&1; then
  docker restart pcga-status >/dev/null || die "Unable to restart pcga-status during early PC-game retry repair"
fi

# Preserve Moonlight Web's persistent v2/v3 account and pairing database before
# the prerelease migration. This is intentionally separate from the host-file
# backup because Docker volumes are not captured by the loop above.
if docker inspect pcga-moonlight-web >/dev/null 2>&1; then
  log "Backing up Moonlight Web persistent data before v3 migration"
  mkdir -p "$BACKUP/moonlight-web-server"
  docker cp pcga-moonlight-web:/moonlight-web/server/. "$BACKUP/moonlight-web-server/" 2>/dev/null \
    || log "Moonlight Web volume backup could not be copied; continuing with host-file backup"
fi

# Freeze insertion detection while replacing the dispatcher; active per-drive
# workers are allowed to finish.
systemctl stop pcga-arm-watch.service pcga-optical-watch.service 2>/dev/null || true
systemctl stop pcga-media-sort.path pcga-media-sort.timer \
  pcga-metadata-classify.path pcga-metadata-classify.timer 2>/dev/null || true
systemctl stop pcga-media-sort.service pcga-metadata-classify.service 2>/dev/null || true
# NAS copy/offload work mutates the same local media tree. Quiesce only the
# maintenance job during the upgrade; keep an already-mounted NAS available to
# media consumers until the new helper reconciles it.
systemctl stop pcga-nas-sync.timer pcga-nas-sync.service 2>/dev/null || true
# v0.17.17 could leave the periodic authentication/game-stack reconciler racing
# the upgrader's own Compose operations. Quiesce every PCGA game-container writer
# before changing compose files or container environment. These units are brought
# back after the serialized upgrade transaction below.
systemctl stop pcga-service-auth.timer pcga-service-auth.service pcga-game-stack.service pcga-game-orchestrator.timer pcga-game-orchestrator.service 2>/dev/null || true
# A broken VHBA prerequisite must never spin every five seconds during an upgrade.
systemctl disable --now pcga-cdemu.service >/dev/null 2>&1 || true
systemctl reset-failed pcga-cdemu.service >/dev/null 2>&1 || true

export DEBIAN_FRONTEND=noninteractive
if ! command -v ddrescue >/dev/null 2>&1 || ! command -v cdrdao >/dev/null 2>&1 || ! command -v toc2cue >/dev/null 2>&1; then
  log "Installing optical preservation tools (GNU ddrescue + cdrdao)"
  apt-get update >/dev/null
  apt-get install -y --no-install-recommends gddrescue cdrdao >/dev/null
fi
# v0.19.3: Ubuntu 24.04/Noble does not publish libMirage/CDEmu in the configured archive.
# Build libMirage from verified upstream source before CDEmu userspace; keep each
# distro prerequisite independent so optional package absence cannot cancel DKMS.
# v0.18.84 established the split prerequisite transaction and VHBA repair.
# CDEmu on Ubuntu 24.04/Noble must not be installed as one
# all-or-nothing APT transaction.  Noble provides DKMS/build dependencies, but
# may not publish cdemu-client/cdemu-daemon/vhba-dkms in the configured suite.
# Install each prerequisite independently so an unavailable CDEmu package can
# never prevent DKMS from being installed.  Missing userspace is then built
# from pinned, checksummed libMirage 3.3.3 + CDEmu 3.3.0 source by PCGA.
log "Reconciling CDEmu/VHBA build prerequisites for protected PC-CD runtime testing"
apt-get update >/dev/null
cdemu_prereqs=(
  dkms wget xz-utils build-essential "linux-headers-$(uname -r)"
  ca-certificates cmake pkg-config intltool gettext bash-completion
  python3 python3-gi gir1.2-glib-2.0
  libglib2.0-dev libao-dev libsndfile1-dev libsamplerate0-dev
  zlib1g-dev libbz2-dev liblzma-dev libgcrypt20-dev valac
  gobject-introspection libgirepository1.0-dev
)
cdemu_prereq_failed=0
for pkg in "${cdemu_prereqs[@]}"; do
  if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed'; then
    continue
  fi
  if ! apt-cache show "$pkg" >/dev/null 2>&1; then
    log "WARNING: CDEmu prerequisite is unavailable from configured APT sources: $pkg"
    cdemu_prereq_failed=1
    continue
  fi
  log "Installing CDEmu prerequisite: $pkg"
  if ! apt-get install -y --no-install-recommends "$pkg" >/dev/null; then
    log "WARNING: unable to install CDEmu prerequisite: $pkg"
    cdemu_prereq_failed=1
  fi
done

# mokutil is diagnostic-only; do not make optical emulation depend on it.
if ! command -v mokutil >/dev/null 2>&1 && apt-cache show mokutil >/dev/null 2>&1; then
  apt-get install -y --no-install-recommends mokutil >/dev/null 2>&1 || true
fi

# Prefer native packages if this Ubuntu suite supplies them, but attempt these
# independently from the required DKMS/build toolchain.
if ! command -v cdemu >/dev/null 2>&1 || ! command -v cdemu-daemon >/dev/null 2>&1; then
  if apt-cache show cdemu-client >/dev/null 2>&1 && apt-cache show cdemu-daemon >/dev/null 2>&1; then
    log "Installing distro CDEmu userspace packages"
    apt-get install -y --no-install-recommends cdemu-client cdemu-daemon >/dev/null 2>&1       || log "WARNING: distro CDEmu userspace install failed; pinned source fallback will be attempted"
  else
    log "CDEmu userspace packages are not published by the configured Ubuntu suite; using pinned source fallback"
  fi
fi
if ! /sbin/modinfo vhba >/dev/null 2>&1 && apt-cache show vhba-dkms >/dev/null 2>&1; then
  log "Installing distro VHBA DKMS package"
  apt-get install -y --no-install-recommends vhba-dkms >/dev/null 2>&1     || log "WARNING: distro vhba-dkms install failed; pinned VHBA source repair will be attempted"
fi

if (( cdemu_prereq_failed )); then
  log "WARNING: one or more CDEmu source-build prerequisites are missing; SP will keep the proven loop-backed ISO if source bootstrap cannot complete"
fi
if ! command -v dkms >/dev/null 2>&1; then
  log "WARNING: dkms is still unavailable; VHBA cannot be built for $(uname -r)"
fi
if ! command -v cdemu >/dev/null 2>&1 || ! command -v cdemu-daemon >/dev/null 2>&1; then
  if [[ -x /usr/local/sbin/pcga-cdemu-userspace-bootstrap ]]; then
    /usr/local/sbin/pcga-cdemu-userspace-bootstrap       || log "WARNING: pinned CDEmu userspace source bootstrap failed; SP will retain loop-backed ISO media"
  fi
fi

if ! command -v openssl >/dev/null 2>&1; then
  log "Installing OpenSSL for the PCGA local secure context"
  apt-get update >/dev/null
  apt-get install -y --no-install-recommends openssl ca-certificates >/dev/null
fi
if ! command -v zstd >/dev/null 2>&1; then
  log "Installing Zstandard for opt-in byte-exact cold archiving"
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends zstd
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  log "Installing FFmpeg for Manual Review thumbnails and short preview clips"
  apt-get update >/dev/null
  apt-get install -y --no-install-recommends ffmpeg >/dev/null
fi
if ! command -v msiinfo >/dev/null 2>&1 || ! command -v msibuild >/dev/null 2>&1; then
  log "Installing msitools for staged multi-disc Windows Installer media normalization"
  apt-get update >/dev/null
  apt-get install -y --no-install-recommends msitools >/dev/null
fi
if ! command -v xorriso >/dev/null 2>&1; then
  log "Installing xorriso for synthetic single-volume legacy game setup media"
  apt-get update >/dev/null
  apt-get install -y --no-install-recommends xorriso >/dev/null
fi
if ! command -v mount.cifs >/dev/null 2>&1 || ! command -v mount.nfs >/dev/null 2>&1 || ! command -v rsync >/dev/null 2>&1; then
  log "Installing NAS storage dependencies (SMB, NFS, rsync)"
  apt-get update >/dev/null
  apt-get install -y --no-install-recommends cifs-utils nfs-common rsync >/dev/null
fi
if ! command -v dnsmasq >/dev/null 2>&1 || ! command -v avahi-daemon >/dev/null 2>&1; then
  log "Installing LAN naming dependencies (dnsmasq + Avahi)"
  apt-get update >/dev/null
  apt-get install -y --no-install-recommends dnsmasq-base avahi-daemon avahi-utils >/dev/null
fi

# lsdvd uses libdvdread/IFO navigation to expose DVD title/chapter/cell
# structure; absence is explicitly reported and never triggers VOB guessing.
if ! command -v lsdvd >/dev/null 2>&1; then
  log "Preparing optional DVD IFO navigation scanner (lsdvd)"
  apt-get install -y --no-install-recommends lsdvd >/dev/null 2>&1 || log "WARNING: lsdvd unavailable; MakeMKV logical titles retained, IFO detail requires review"
fi

# FFmpeg is installed only when absent; encoder availability is shown honestly in UI.
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  log "Installing FFmpeg for opt-in quality-oriented media encoding"
  apt-get update >/dev/null
  apt-get install -y --no-install-recommends ffmpeg >/dev/null
fi
install -m 0755 "$COMP/pcga-low-loss-encode" /usr/local/sbin/pcga-low-loss-encode
install -m 0755 "$COMP/pcga-low-loss-tier" /usr/local/sbin/pcga-low-loss-tier
install -m 0755 "$COMP/pcga-lossless-archive" /usr/local/sbin/pcga-lossless-archive
install -m 0755 "$COMP/pcga-arm-configure" /usr/local/sbin/pcga-arm-configure
install -m 0755 "$COMP/pcga-disc-structure" /usr/local/sbin/pcga-disc-structure
install -m 0755 "$COMP/pcga-arm-rip" /usr/local/sbin/pcga-arm-rip
install -m 0755 "$COMP/pcga-arm-watch" /usr/local/sbin/pcga-arm-watch
install -m 0755 "$COMP/pcga-makemkv-preflight" /usr/local/sbin/pcga-makemkv-preflight
install -m 0755 "$COMP/pcga-optical-identify" /usr/local/sbin/pcga-optical-identify
install -m 0755 "$COMP/pcga-game-disc-metadata" /usr/local/sbin/pcga-game-disc-metadata
install -m 0755 "$COMP/pcga-game-intake" /usr/local/sbin/pcga-game-intake
install -m 0755 "$COMP/pcga-game-orchestrator" /usr/local/sbin/pcga-game-orchestrator
install -m 0755 "$COMP/pcga-game-compat-resolver" /usr/local/sbin/pcga-game-compat-resolver
install -m 0755 "$COMP/pcga-game-compat-test" /usr/local/sbin/pcga-game-compat-test
install -m 0755 "$COMP/pcga-cdemu-bootstrap" /usr/local/sbin/pcga-cdemu-bootstrap
install -m 0755 "$COMP/pcga-cdemu-userspace-bootstrap" /usr/local/sbin/pcga-cdemu-userspace-bootstrap
install -m 0644 "$COMP/pcga-cdemu.service" /etc/systemd/system/pcga-cdemu.service
install -m 0644 "$COMP/pcga-game-orchestrator.service" /etc/systemd/system/pcga-game-orchestrator.service
install -m 0644 "$COMP/pcga-game-orchestrator.timer" /etc/systemd/system/pcga-game-orchestrator.timer
install -m 0755 "$COMP/pcga-media-disc-metadata" /usr/local/sbin/pcga-media-disc-metadata
install -m 0755 "$COMP/pcga-media-intake" /usr/local/sbin/pcga-media-intake
install -m 0755 "$COMP/pcga-optical-dispatch" /usr/local/sbin/pcga-optical-dispatch
install -m 0644 "$COMP/pcga-optical-dispatch@.service" /etc/systemd/system/pcga-optical-dispatch@.service
install -m 0755 "$COMP/pcga-optical-watch" /usr/local/sbin/pcga-optical-watch
install -m 0644 "$COMP/pcga-optical-watch.service" /etc/systemd/system/pcga-optical-watch.service
install -m 0755 "$COMP/pcga-pc-disc-rip" /usr/local/sbin/pcga-pc-disc-rip
install -m 0644 "$COMP/pcga-pc-disc-rip@.service" /etc/systemd/system/pcga-pc-disc-rip@.service
install -m 0755 "$COMP/pcga-optical-health" /usr/local/sbin/pcga-optical-health
install -d -m 0755 /var/lib/pc-game-archive/optical-dispatch /var/lib/pc-game-archive/game-intake/sets /var/lib/pc-game-archive/game-intake/discs /var/lib/pc-game-archive/game-intake/collections /var/lib/pc-game-archive/game-intake/assets /var/lib/pc-game-archive/game-installs /var/lib/pc-game-archive/game-compat /var/lib/pc-game-archive/game-compat-tests /var/cache/pc-game-archive/game-compat "$ROOT/games/installed" /var/lib/pc-game-archive/media-intake/items /var/lib/pc-game-archive/media-intake/discs /var/lib/pc-game-archive/media-intake/collections "$ROOT/ingest/optical-work"
# The packaged daemon is normally session-bus activated. PCGA is headless, so
# run one root-owned appliance daemon on the system bus and reserve device 0 for
# protected PC-CD runtime presentation. Only root/orchestrator access is allowed.
install -d -m 0755 /etc/dbus-1/system.d
cat > /etc/dbus-1/system.d/pcga-cdemu.conf <<'PCGA_CDEMU_DBUS'
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="root">
    <allow own="net.sf.cdemu.CDEmuDaemon"/>
    <allow send_destination="net.sf.cdemu.CDEmuDaemon"/>
  </policy>
  <policy context="default">
    <deny send_destination="net.sf.cdemu.CDEmuDaemon"/>
  </policy>
</busconfig>
PCGA_CDEMU_DBUS
chmod 0644 /etc/dbus-1/system.d/pcga-cdemu.conf
systemctl reload dbus.service >/dev/null 2>&1 || true
systemctl daemon-reload
# Re-run userspace bootstrap here as well so a package installed later in the
# transaction or a partially repaired host is reconciled before service start.
if ! command -v cdemu >/dev/null 2>&1 || ! command -v cdemu-daemon >/dev/null 2>&1; then
  /usr/local/sbin/pcga-cdemu-userspace-bootstrap     || log "WARNING: CDEmu userspace remains unavailable; SP will retain the proven loop-backed ISO"
fi
if [[ -x /usr/local/sbin/pcga-cdemu-bootstrap ]]; then
  log "Reconciling VHBA against the running kernel for COD2 CDEmu"
  /usr/local/sbin/pcga-cdemu-bootstrap --repair     || log "WARNING: VHBA repair did not become ready; SP will retain the proven loop-backed ISO instead of terminating the stream"
fi
systemctl reset-failed pcga-cdemu.service >/dev/null 2>&1 || true
if command -v cdemu >/dev/null 2>&1 && command -v cdemu-daemon >/dev/null 2>&1 && [[ -c /dev/vhba_ctl ]]; then
  if systemctl enable --now pcga-cdemu.service >/dev/null 2>&1; then
    log "CDEmu host service is active; COD2 SP can use the virtual SCSI optical device"
  else
    log "WARNING: pcga-cdemu.service did not start; leaving it failed once (no restart storm) and retaining loop-backed SP media"
    systemctl --no-pager --full status pcga-cdemu.service 2>&1 | tail -n 60 >&2 || true
  fi
else
  systemctl disable pcga-cdemu.service >/dev/null 2>&1 || true
  log "WARNING: CDEmu userspace/VHBA is not ready; service remains disabled and SP retains loop-backed ISO media while MP remains on Wine 9"
fi

cat > /etc/udev/rules.d/52-pcga-media-rip.rules <<'PCGA_OPTICAL_UDEV'
# Every optical change event enters PCGA's media classifier first.
KERNEL=="sr[0-9]", ACTION=="change", SUBSYSTEM=="block", TAG+="systemd", ENV{SYSTEMD_WANTS}+="pcga-optical-dispatch@%k.service"
PCGA_OPTICAL_UDEV
udevadm control --reload-rules
if [[ ! -e /etc/pc-game-archive/game-metadata.env ]]; then
  cat > /etc/pc-game-archive/game-metadata.env <<'PCGA_GAME_METADATA_ENV'
# PCGA game profile enrichment. Steam Store needs no key and is conservative.
PCGA_STEAM_STORE_METADATA=1
PCGA_METADATA_LANGUAGE=english
PCGA_METADATA_COUNTRY=US
# PC-game compatibility knowledge. Provider pages/reports are cached locally;
# PlayOnLinux scripts are parsed as data and are never executed by PCGA.
PCGA_PROTONDB_ENABLED=1
PCGA_PROTONDB_COMMUNITY_REPORTS=1
PCGA_PROTONDB_REPORTS_URL=https://protondb.max-p.me/games/{appid}/reports/
PCGA_PLAYONLINUX_ENABLED=1
# User-driven canonical PC-game profile search. Get a personal key from
# https://rawg.io/apidocs; the portal never exposes the key back to the browser.
PCGA_GAME_DB_PROVIDER=rawg
RAWG_API_KEY=
# Additional provider credentials are reserved for future adapters:
IGDB_CLIENT_ID=
IGDB_CLIENT_SECRET=
STEAMGRIDDB_API_KEY=
PCGA_GAME_METADATA_ENV
  chmod 0600 /etc/pc-game-archive/game-metadata.env
fi
for kv in \
  'PCGA_PROTONDB_ENABLED=1' \
  'PCGA_PROTONDB_COMMUNITY_REPORTS=1' \
  'PCGA_PROTONDB_REPORTS_URL=https://protondb.max-p.me/games/{appid}/reports/' \
  'PCGA_PLAYONLINUX_ENABLED=1' \
  'PCGA_GAME_DB_PROVIDER=rawg' \
  'RAWG_API_KEY='; do
  key="${kv%%=*}"
  grep -qE "^${key}=" /etc/pc-game-archive/game-metadata.env 2>/dev/null || printf '%s\n' "$kv" >> /etc/pc-game-archive/game-metadata.env
done
chmod 0600 /etc/pc-game-archive/game-metadata.env
if [[ ! -e /etc/pc-game-archive/game-runtime.env ]]; then
  cat > /etc/pc-game-archive/game-runtime.env <<'PCGA_GAME_RUNTIME_ENV'
PCGA_GAME_RUNTIME_IMAGE=ghcr.io/games-on-whales/lutris:edge
PCGA_INSTALL_TIMEOUT_SECONDS=1800
# PCGA launches Wine directly rather than via Lutris' Wine runner. Auto selects
# pinned DXVK when Vulkan is usable and otherwise keeps WineD3D as a safe fallback.
PCGA_GRAPHICS_BACKEND=auto
PCGA_DXVK_WINETRICKS_VERB=dxvk2062
PCGA_DXVK_SETUP_SECONDS=600
PCGA_DXVK_HUD=0
PCGA_GAME_RUNTIME_ENV
  chmod 0600 /etc/pc-game-archive/game-runtime.env
fi
for kv in \
  'PCGA_GRAPHICS_BACKEND=auto' \
  'PCGA_DXVK_WINETRICKS_VERB=dxvk2062' \
  'PCGA_DXVK_SETUP_SECONDS=600' \
  'PCGA_DXVK_HUD=0'; do
  key="${kv%%=*}"
  grep -qE "^${key}=" /etc/pc-game-archive/game-runtime.env 2>/dev/null || printf '%s\n' "$kv" >> /etc/pc-game-archive/game-runtime.env
done
chmod 0600 /etc/pc-game-archive/game-runtime.env
install -m 0755 "$COMP/pcga-media-sort" /usr/local/sbin/pcga-media-sort
install -m 0755 "$COMP/pcga-ingest-reconcile" /usr/local/sbin/pcga-ingest-reconcile
install -d -m 0755 /var/lib/pc-game-archive/ingest-reconcile
install -m 0755 "$COMP/pcga-classify" /usr/local/sbin/pcga-classify
install -m 0755 "$COMP/pcga-metadata-classify" /usr/local/sbin/pcga-metadata-classify
install -m 0755 "$COMP/pcga-manual-review" /usr/local/sbin/pcga-manual-review
install -m 0755 "$COMP/pcga-public-media" /usr/local/sbin/pcga-public-media
install -d -m 0755 /var/lib/pc-game-archive/public-media
install -m 0755 "$COMP/pcga-dedupe" /usr/local/sbin/pcga-dedupe
install -m 0755 "$COMP/pcga-extra-prune" /usr/local/sbin/pcga-extra-prune
install -m 0755 "$COMP/pcga-stream-prune" /usr/local/sbin/pcga-stream-prune
install -d -m 0700 /var/lib/pc-game-archive/extra-prune
install -d -m 0755 /var/lib/pc-game-archive/dedupe
install -m 0755 "$COMP/pcga-steam-native" /usr/local/sbin/pcga-steam-native
# On an existing decode-only GPU, retain the working software-mode preference
# without interrupting Steam or modifying its auth/game/profile volumes.
# Recreating the Steam container (to update its Docker environment) is an
# explicit user action in Control Center, never an automatic upgrade step.
if ! /usr/local/sbin/pcga-steam-native reconcile >/dev/null; then
  log "Steam encoder preference probe unavailable; use Control Center to inspect and configure Steam"
fi

install -m 0755 "$COMP/pcga-control" /usr/local/sbin/pcga-control
install -m 0755 "$COMP/pcga-heroic-bootstrap" /usr/local/sbin/pcga-heroic-bootstrap
install -m 0755 "$COMP/pcga-heroic-sync" /usr/local/sbin/pcga-heroic-sync
install -m 0755 "$COMP/pcga-store-provider" /usr/local/sbin/pcga-store-provider
install -m 0755 "$COMP/pcga-store-bootstrap" /usr/local/sbin/pcga-store-bootstrap
install -m 0644 "$COMP/pcga-store-bootstrap.service" /etc/systemd/system/pcga-store-bootstrap.service
install -m 0755 "$COMP/pcga-store-compat" /usr/local/sbin/pcga-store-compat
install -m 0644 "$COMP/pcga-store-umu.service" /etc/systemd/system/pcga-store-umu.service
install -m 0755 "$COMP/pcga-store-ingest" /usr/local/sbin/pcga-store-ingest
install -m 0755 "$COMP/pcga-store-game-startup" /usr/local/sbin/pcga-store-game-startup
install -m 0644 "$COMP/pcga-store-ingest.service" /etc/systemd/system/pcga-store-ingest.service
install -m 0644 "$COMP/pcga-store-ingest.timer" /etc/systemd/system/pcga-store-ingest.timer
install -m 0755 "$COMP/pcga-store-jobs" /usr/local/sbin/pcga-store-jobs
install -m 0644 "$COMP/pcga-store-jobs.service" /etc/systemd/system/pcga-store-jobs.service
install -m 0644 "$COMP/pcga-heroic-bootstrap.service" /etc/systemd/system/pcga-heroic-bootstrap.service
install -m 0644 "$COMP/pcga-heroic-sync.service" /etc/systemd/system/pcga-heroic-sync.service
install -m 0644 "$COMP/pcga-heroic-sync.timer" /etc/systemd/system/pcga-heroic-sync.timer
install -m 0755 "$COMP/pcga-nas-storage" /usr/local/sbin/pcga-nas-storage
install -m 0755 "$COMP/pcga-nas-discover" /usr/local/sbin/pcga-nas-discover
install -m 0755 "$COMP/pcga-lan-dns" /usr/local/sbin/pcga-lan-dns
install -m 0644 "$COMP/pcga-lan-dns.service" /etc/systemd/system/pcga-lan-dns.service
install -m 0644 "$COMP/pcga-nas-mount.service" /etc/systemd/system/pcga-nas-mount.service
install -m 0644 "$COMP/pcga-nas-sync.service" /etc/systemd/system/pcga-nas-sync.service
install -m 0644 "$COMP/pcga-nas-sync.timer" /etc/systemd/system/pcga-nas-sync.timer
install -d -m 0755 /var/lib/pc-game-archive/control /var/lib/pc-game-archive/activity /var/lib/pc-game-archive/nas /var/lib/pc-game-archive/heroic /var/cache/pc-game-archive/heroic /mnt/pcga-nas /etc/pc-game-archive
install -d -m 0700 /var/lib/pc-game-archive/store-jobs /var/log/pc-game-archive/store-jobs /var/lib/pc-game-archive/store-umu
install -d -m 0755 "$ROOT/games/heroic/config" "$ROOT/games/heroic/library" "$ROOT/games/heroic/cache"
# v0.19.10 native store catalog/job roots. Preserve any credentials that were
# previously created by the v0.19.0 Heroic compatibility path, but never
# overwrite newer native-provider state.
STORE_UID="$(awk -F= '$1=="PUID"{gsub(/[[:space:]\r]/,"",$2);print $2}' "$STACK_DIR/.env" 2>/dev/null | tail -n1)"
STORE_GID="$(awk -F= '$1=="PGID"{gsub(/[[:space:]\r]/,"",$2);print $2}' "$STACK_DIR/.env" 2>/dev/null | tail -n1)"
STORE_UID="${STORE_UID:-$(stat -c '%u' "$ROOT" 2>/dev/null || echo 1000)}"
STORE_GID="${STORE_GID:-$(stat -c '%g' "$ROOT" 2>/dev/null || echo 1000)}"
install -d -m 0700 -o "$STORE_UID" -g "$STORE_GID" \
  "$ROOT/games/stores/config" "$ROOT/games/stores/config/legendary" \
  "$ROOT/games/stores/config/gog" "$ROOT/games/stores/config/gogdl" \
  "$ROOT/games/stores/config/nile" "$ROOT/games/stores/config/nile/nile" "$ROOT/games/stores/config/xdg" \
  "$ROOT/games/stores/cache" "$ROOT/games/stores/home"
install -d -m 0755 -o "$STORE_UID" -g "$STORE_GID" "$ROOT/games/stores/library"
install -d -m 0700 /var/lib/pc-game-archive/store-providers /var/lib/pc-game-archive/store-providers/catalogs
LEGACY_HEROIC="$ROOT/games/heroic/config"
if [[ -d "$LEGACY_HEROIC/legendaryConfig/legendary" ]] && ! find "$ROOT/games/stores/config/legendary" -mindepth 1 -print -quit | grep -q .; then
  cp -a "$LEGACY_HEROIC/legendaryConfig/legendary/." "$ROOT/games/stores/config/legendary/" 2>/dev/null || true
fi
if [[ -f "$LEGACY_HEROIC/gog_store/auth.json" && ! -s "$ROOT/games/stores/config/gog/auth.json" ]]; then
  install -m 0600 -o "$STORE_UID" -g "$STORE_GID" "$LEGACY_HEROIC/gog_store/auth.json" "$ROOT/games/stores/config/gog/auth.json"
fi
if [[ -d "$LEGACY_HEROIC/gogdlConfig" ]] && ! find "$ROOT/games/stores/config/gogdl" -mindepth 1 -print -quit | grep -q .; then
  cp -a "$LEGACY_HEROIC/gogdlConfig/." "$ROOT/games/stores/config/gogdl/" 2>/dev/null || true
fi
# NILE_CONFIG_PATH points at a base directory and Nile stores its files in a
# nested `nile/` directory beneath it. v0.19.1 could place migrated JSON one
# level too high; copy both legacy and misplaced evidence into the canonical
# nested directory without deleting the old source.
NILE_NATIVE="$ROOT/games/stores/config/nile/nile"
if ! find "$NILE_NATIVE" -mindepth 1 -print -quit | grep -q .; then
  if [[ -d "$LEGACY_HEROIC/nile_config/nile" ]]; then
    cp -a "$LEGACY_HEROIC/nile_config/nile/." "$NILE_NATIVE/" 2>/dev/null || true
  else
    find "$ROOT/games/stores/config/nile" -maxdepth 1 -type f -name '*.json' -exec cp -a -t "$NILE_NATIVE" {} + 2>/dev/null || true
  fi
fi
chown -R "$STORE_UID:$STORE_GID" "$ROOT/games/stores/config" "$ROOT/games/stores/cache" "$ROOT/games/stores/home" "$ROOT/games/stores/library" 2>/dev/null || true
chmod -R go-rwx "$ROOT/games/stores/config" "$ROOT/games/stores/cache" "$ROOT/games/stores/home" 2>/dev/null || true
if [[ ! -s /etc/pc-game-archive/control-token ]]; then
  umask 077
  openssl rand -hex 32 > /etc/pc-game-archive/control-token
fi
chmod 0600 /etc/pc-game-archive/control-token

# First control-plane migration: derive initial appliance state from the
# services already installed on this host. Subsequent releases preserve the
# server-side configuration rather than recomputing it.
if [[ ! -e /etc/pc-game-archive/appliance.json ]]; then
  ROMM_ENABLED=false; [[ -f "$STACK_DIR/compose.romm.yml" ]] && ROMM_ENABLED=true
  IMMICH_ENABLED=false; [[ -f "$STACK_DIR/compose.immich.yml" ]] && IMMICH_ENABLED=true
  JELLYFIN_ENABLED=false; grep -Eq '^[[:space:]]{2}jellyfin:' "$STACK_DIR/compose.yml" 2>/dev/null && JELLYFIN_ENABLED=true
  AUTO_RIP=false; { systemctl is-enabled --quiet pcga-optical-watch.service 2>/dev/null || systemctl is-enabled --quiet pcga-arm-watch.service 2>/dev/null; } && AUTO_RIP=true
  SORTER_ENABLED=false; systemctl is-enabled --quiet pcga-media-sort.timer 2>/dev/null && SORTER_ENABLED=true
  CLASSIFIER_ENABLED=false; systemctl is-enabled --quiet pcga-metadata-classify.timer 2>/dev/null && CLASSIFIER_ENABLED=true
  DEDUPE_ENABLED=false; systemctl is-enabled --quiet pcga-dedupe.timer 2>/dev/null && DEDUPE_ENABLED=true
  cat > /etc/pc-game-archive/appliance.json <<APPLIANCE_JSON
{
  "schema": 2,
  "version": "0.19.22",
  "libraries": {
    "movies": "/media/library/movies",
    "tv": "/media/library/tv",
    "music": "/media/library/music",
    "audio": "/media/library/audio",
    "photos": "/media/library/photos",
    "pc_games": "/ingest/inbox/pc-games",
    "console_games": "/media/library/console-games"
  },
  "ingest": {"auto_rip": $AUTO_RIP, "keep_raw": false},
  "review": {"auto_classify": $CLASSIFIER_ENABLED, "auto_threshold": 0.90},
  "games": {"romm_enabled": $ROMM_ENABLED, "filesystem_watch": true, "watch_debounce_seconds": 300, "scheduled_rescan": "25 3 * * *", "metadata_hasheous": true, "metadata_playmatch": true, "compat_protondb": true, "compat_playonlinux": true, "graphics_backend": "auto"},
  "photos": {"immich_enabled": $IMMICH_ENABLED, "shared_library": "/media/library/photos"},
  "media": {"jellyfin_enabled": $JELLYFIN_ENABLED, "background_video_max_width": 1920, "background_video_max_height": 1080, "background_video_bitrate": 8000000},
  "automation": {"sorter_enabled": $SORTER_ENABLED, "classifier_enabled": $CLASSIFIER_ENABLED, "dedupe_enabled": $DEDUPE_ENABLED},
  "remote_access": {"tailscale_enabled": false, "netbird_enabled": false, "zerotier_enabled": false, "zerotier_network_id": ""},
  "nas": {"enabled": false, "protocol": "smb", "host": "", "share": "", "username": "", "domain": "", "base_dir": "PCGA", "mode": "mirror", "libraries": ["movies", "tv", "music", "home-videos", "photos"], "local_reserve_gib": 100, "min_age_days": 30, "schedule_enabled": true}
}
APPLIANCE_JSON
  chmod 0644 /etc/pc-game-archive/appliance.json
fi

# v0.18.24: add managed NAS tiering defaults without disturbing existing appliance settings.
python3 - /etc/pc-game-archive/appliance.json <<'PY_NAS_CONFIG'
from pathlib import Path
import json,sys
p=Path(sys.argv[1])
try: data=json.loads(p.read_text())
except Exception: data={}
if not isinstance(data,dict): data={}
data['schema']=max(2,int(data.get('schema') or 1))
data['version']='0.19.22'
defaults={'enabled':False,'protocol':'smb','host':'','share':'','username':'','domain':'','base_dir':'PCGA','mode':'mirror','libraries':['movies','tv','music','home-videos','photos'],'local_reserve_gib':100,'min_age_days':30,'schedule_enabled':True}
nas=data.get('nas')
if not isinstance(nas,dict): nas={}
for k,v in defaults.items(): nas.setdefault(k,v)
data['nas']=nas
remote=data.get('remote_access')
if not isinstance(remote,dict): remote={}
remote.setdefault('tailscale_enabled',False)
remote.setdefault('netbird_enabled',False)
remote.setdefault('zerotier_enabled',False)
remote.setdefault('zerotier_network_id','')
data['remote_access']=remote
games=data.get('games')
if not isinstance(games,dict): games={}
games.setdefault('compat_protondb', True)
games.setdefault('compat_playonlinux', True)
games.setdefault('graphics_backend', 'auto')
data['games']=games
p.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
PY_NAS_CONFIG
chmod 0644 /etc/pc-game-archive/appliance.json
install -d -m 0700 /etc/pc-game-archive/secrets
install -d -m 0755 /var/lib/pc-game-archive/nas /mnt/pcga-nas

if [[ ! -e /etc/pc-game-archive/dedupe.conf ]]; then
  cat > /etc/pc-game-archive/dedupe.conf <<'DEDUPE_CONF'
# Minimum media file size considered by scheduled dedupe.
PCGA_DEDUPE_MIN_SIZE=16MiB
# Set to 1 only if you explicitly want scheduled runs to hardlink two final
# Jellyfin library paths together when their bytes are identical.
PCGA_DEDUPE_LIBRARY_DUPLICATES=0
# Optional colon-separated additional absolute roots to include. Empty by default.
PCGA_DEDUPE_EXTRA_ROOTS=
DEDUPE_CONF
  chmod 0644 /etc/pc-game-archive/dedupe.conf
fi

# Shared photo archive. Jellyfin and Immich both read this same directory;
# Immich continues to keep its database-managed upload store separate.
install -d -m 0755 "$ROOT/media/library/photos"
install -d -m 0755 "$ROOT/media/library/audio/podcasts" "$ROOT/media/library/audio/audiobooks/librivox" "$ROOT/media/library/audio/audiobooks/uploads" /var/lib/pc-game-archive/audio
python3 - "$STACK_DIR/compose.yml" <<'PY_PHOTO_COMPOSE'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
if '\n  jellyfin:\n' not in s:
    raise SystemExit(0)
mount='      - "${ARCHIVE_ROOT}/media/library/photos:/media/photos:ro"\n'
if '/media/library/photos:/media/photos:ro' not in s:
    needle='      - "${ARCHIVE_ROOT}/media/library/home-videos:/media/home-videos:ro"\n'
    if needle not in s:
        raise SystemExit('Could not locate Jellyfin volume list in compose.yml')
    s=s.replace(needle,needle+mount,1)
p.write_text(s)
PY_PHOTO_COMPOSE

# Extend the installed Jellyfin library synchronizer to own a Photos library.
if [[ -f /usr/local/sbin/pcga-jellyfin-configure ]]; then
python3 - /usr/local/sbin/pcga-jellyfin-configure <<'PY_PHOTO_JF'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
if 'Photos      -> /media/photos' not in s:
    s=s.replace('  Home Videos -> /media/home-videos\n','  Home Videos -> /media/home-videos\n  Photos      -> /media/photos\n',1)
if "$'Photos\\tphotos\\t/media/photos'" not in s:
    s=s.replace("  $'Home Videos\\thomevideos\\t/media/home-videos'\n)","  $'Home Videos\\thomevideos\\t/media/home-videos'\n  $'Photos\\tphotos\\t/media/photos'\n)",1)
p.write_text(s)
PY_PHOTO_JF
chmod 0755 /usr/local/sbin/pcga-jellyfin-configure
fi

if [[ -f /usr/local/sbin/pcga-jellyfin-configure ]]; then
python3 - /usr/local/sbin/pcga-jellyfin-configure <<'PY_SHARED_JF'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
old='DEFAULT_ADMIN_USER="${PCGA_JELLYFIN_ADMIN_USER:-admin}"\nDEFAULT_ADMIN_PASSWORD="${PCGA_JELLYFIN_ADMIN_PASSWORD:-pass}"'
new='''APPLIANCE_CREDS=/etc/pc-game-archive/secrets/appliance-admin.env
if [[ -x /usr/local/sbin/pcga-appliance-credentials ]]; then /usr/local/sbin/pcga-appliance-credentials >/dev/null; fi
if [[ -r "$APPLIANCE_CREDS" ]]; then
  # shellcheck disable=SC1090
  . "$APPLIANCE_CREDS"
fi
DEFAULT_ADMIN_USER="${PCGA_JELLYFIN_ADMIN_USER:-${PCGA_APPLIANCE_ADMIN_USER:-pcga-admin}}"
DEFAULT_ADMIN_PASSWORD="${PCGA_JELLYFIN_ADMIN_PASSWORD:-${PCGA_APPLIANCE_ADMIN_PASSWORD:-}}"'''
if old in s:
    s=s.replace(old,new,1)
s=s.replace("with admin user 'admin' and password 'pass' (overridable with the environment\nvariables PCGA_JELLYFIN_ADMIN_USER and PCGA_JELLYFIN_ADMIN_PASSWORD). Existing", "with the common PCGA appliance administrator. Existing")
s=s.replace("  warn \"The requested password 'pass' is weak. Keep Jellyfin LAN-only and change the password when convenient.\"\n", "")
s=s.replace("  warn \"The requested password 'pass' is weak. Keep Jellyfin LAN-only or change it after setup.\"\n", "")
p.write_text(s)
PY_SHARED_JF
chmod 0755 /usr/local/sbin/pcga-jellyfin-configure
fi


# Add conservative TV layout reconciliation aliases to an existing wrapper.
if [[ -f /usr/local/bin/game-archive ]]; then
python3 - /usr/local/bin/game-archive <<'PYWRAP'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
s=s.replace("    'pcga-arm-rip@*.service' 2>/dev/null | grep -q 'pcga-arm-rip@' && return 0", "    'pcga-arm-rip@*.service' 'pcga-pc-disc-rip@*.service' 2>/dev/null | grep -Eq 'pcga-(arm-rip|pc-disc-rip)@' && return 0")
s=s.replace("Refusing '$1': an ARM optical rip is active. Let pcga-arm-rip@<drive>.service finish first.", "Refusing '$1': an optical ingest is active. Let the per-drive ingest service finish first.")
s=s.replace('|recover-raw [DISC]|arm-test [DEV]|', '|recover-raw [DISC]|optical-identify [DEV]|optical-dispatch [DEV]|pc-disc-rip [DEV]|arm-test [DEV]|')
if '  optical-identify)' not in s and '  arm-test)' in s:
    block='''  optical-identify)
    dev="${2:-$(head -n1 /etc/pc-game-archive/media-drives 2>/dev/null || true)}"
    [[ -n "$dev" ]] || { echo "No optical media drive assigned" >&2; exit 1; }
    sudo /usr/local/sbin/pcga-optical-identify "$dev"
    ;;
  optical-dispatch)
    dev="${2:-$(head -n1 /etc/pc-game-archive/media-drives 2>/dev/null || true)}"
    [[ -n "$dev" ]] || { echo "No optical media drive assigned" >&2; exit 1; }
    sudo /usr/local/sbin/pcga-optical-dispatch "${dev#/dev/}"
    ;;
  pc-disc-rip)
    dev="${2:-$(head -n1 /etc/pc-game-archive/media-drives 2>/dev/null || true)}"
    [[ -n "$dev" ]] || { echo "No optical media drive assigned" >&2; exit 1; }
    sudo /usr/local/sbin/pcga-pc-disc-rip "${dev#/dev/}"
    ;;
'''
    s=s.replace('  arm-test)\n', block+'  arm-test)\n', 1)
if '  media-intake)' not in s and '  arm-test)' in s:
    block='''  media-intake)\n    shift || true\n    sudo /usr/local/sbin/pcga-media-intake \"$@\"\n    ;;\n'''
    s=s.replace('  arm-test)\n', block+'  arm-test)\n', 1)
if '  game-install)' not in s and '  arm-test)' in s:
    block='''  game-install)\n    shift || true\n    sudo /usr/local/sbin/pcga-game-orchestrator "$@"\n    ;;\n'''
    s=s.replace('  arm-test)\n', block+'  arm-test)\n', 1)
if '  game-compat-test)' not in s and '  arm-test)' in s:
    block='''  game-compat-test)\n    shift || true\n    sudo /usr/local/sbin/pcga-game-compat-test "$@"\n    ;;\n  game-compat-report)\n    shift || true\n    report=/var/lib/pc-game-archive/game-compat-tests/latest.json\n    [[ -r "$report" ]] || { echo "No compatibility report has been generated yet. Run: game-archive game-compat-test" >&2; exit 1; }\n    if [[ "${1:-}" == "--summary" ]]; then\n      /usr/local/sbin/pcga-game-compat-test --summary-report "$report"\n    else\n      python3 -m json.tool "$report"\n    fi\n    ;;\n'''
    s=s.replace('  arm-test)\n', block+'  arm-test)\n', 1)
# Upgrade the branch even when it was installed by an earlier release.
if '  game-compat-report)' in s:
    start=s.index('  game-compat-report)')
    end=s.index('    ;;\n', start)+len('    ;;\n')
    report_branch='''  game-compat-report)\n    shift || true\n    report=/var/lib/pc-game-archive/game-compat-tests/latest.json\n    [[ -r "$report" ]] || { echo "No compatibility report has been generated yet. Run: game-archive game-compat-test" >&2; exit 1; }\n    if [[ "${1:-}" == "--summary" ]]; then\n      /usr/local/sbin/pcga-game-compat-test --summary-report "$report"\n    else\n      python3 -m json.tool "$report"\n    fi\n    ;;\n'''
    s=s[:start]+report_branch+s[end:]
s=s.replace('|pc-disc-rip [DEV]|arm-test [DEV]|', '|pc-disc-rip [DEV]|media-intake <command>|game-install [--status|--set-id ID|--force]|game-compat-test [--set-id ID|--timeout SEC]|game-compat-report [--summary]|arm-test [DEV]|')
s=s.replace('|game-compat-report|arm-test [DEV]|', '|game-compat-report [--summary]|arm-test [DEV]|')
if '  credentials)' not in s and '  immich-status)' in s:
    s=s.replace('  immich-status)\n', '  credentials)\n    sudo /usr/local/sbin/pcga-appliance-credentials >/dev/null\n    sudo cat /etc/pc-game-archive/secrets/appliance-admin.env\n    ;;\n  immich-status)\n', 1)
s=s.replace('|jellyfin-forget-token|immich-status|', '|jellyfin-forget-token|credentials|immich-status|')
if '  tv-reconcile)' not in s and '  classification-status|metadata-status)' in s:
    marker='''  classification-status|metadata-status)
    systemctl --no-pager --full status pcga-metadata-classify.path pcga-metadata-classify.timer pcga-metadata-classify.service || true
    sudo /usr/local/sbin/pcga-classify --status || true
    journalctl -t PCGA-CLASSIFY -n 40 --no-pager 2>/dev/null || true
    ;;
'''
    block=marker+'''  tv-reconcile)
    sudo /usr/local/sbin/pcga-classify --repair-tv-layout
    ;;
  tv-reconcile-apply)
    sudo /usr/local/sbin/pcga-classify --repair-tv-layout --apply
    ;;
'''
    if marker in s:
        s=s.replace(marker,block,1)
if '  ingest-audit)' not in s and '  raw-review)' in s:
    block='''  ingest-audit)
    sudo /usr/local/sbin/pcga-ingest-reconcile audit
    ;;
  ingest-reconcile)
    sudo /usr/local/sbin/pcga-ingest-reconcile reconcile
    sudo /usr/local/sbin/pcga-media-sort
    ;;
'''
    s=s.replace('  raw-review)\n',block+'  raw-review)\n',1)
if '  dedupe-audit)' not in s and '  ingest-audit)' in s:
    block='''  dedupe-audit)
    shift || true
    sudo /usr/local/sbin/pcga-dedupe audit "$@"
    ;;
  dedupe-run)
    shift || true
    sudo /usr/local/sbin/pcga-dedupe run "$@"
    ;;
  dedupe-library)
    shift || true
    sudo /usr/local/sbin/pcga-dedupe run --include-library-duplicates "$@"
    ;;
  dedupe-status)
    systemctl --no-pager --full status pcga-dedupe.timer pcga-dedupe.service || true
    systemctl list-timers --all pcga-dedupe.timer --no-pager || true
    ;;
'''
    s=s.replace('  ingest-audit)\n',block+'  ingest-audit)\n',1)
s=s.replace('|classify|classification-status|metadata-classify|metadata-status|jellyfin-configure|',
            '|classify|classification-status|metadata-classify|metadata-status|tv-reconcile|tv-reconcile-apply|jellyfin-configure|')
s=s.replace('|pipeline-status|pipeline-status-url|pipeline-status-logs|raw-review [DISC]|',
            '|pipeline-status|pipeline-status-url|pipeline-status-logs|dedupe-audit|dedupe-run|dedupe-library|dedupe-status|ingest-audit|ingest-reconcile|raw-review [DISC]|')
s=s.replace('|pipeline-status|pipeline-status-url|pipeline-status-logs|ingest-audit|ingest-reconcile|raw-review [DISC]|',
            '|pipeline-status|pipeline-status-url|pipeline-status-logs|dedupe-audit|dedupe-run|dedupe-library|dedupe-status|ingest-audit|ingest-reconcile|raw-review [DISC]|')
if '[[ -f compose.immich.yml ]]' not in s:
    s=s.replace('[[ -f compose.jellyfin-gpu.yml ]] && FILES+=(-f compose.jellyfin-gpu.yml)\n', '[[ -f compose.jellyfin-gpu.yml ]] && FILES+=(-f compose.jellyfin-gpu.yml)\n[[ -f compose.immich.yml ]] && FILES+=(-f compose.immich.yml)\n',1)
if '[[ -f compose.romm.yml ]]' not in s:
    s=s.replace('[[ -f compose.immich.yml ]] && FILES+=(-f compose.immich.yml)\n', '[[ -f compose.immich.yml ]] && FILES+=(-f compose.immich.yml)\n[[ -f compose.romm.yml ]] && FILES+=(-f compose.romm.yml)\n',1)
if '  immich-status)' not in s and '  jellyfin-forget-token)' in s:
    marker='''  jellyfin-forget-token)
    sudo rm -f /etc/pc-game-archive/jellyfin-api-key
    echo "Removed the saved PC Game Archive Jellyfin API token."
    ;;
'''
    block=marker+'''  immich-status)
    "${DC[@]}" ps immich-server immich-machine-learning immich-redis immich-database
    port="$(awk -F= '$1=="IMMICH_PORT"{print $2}' .env | tail -n1)"; port="${port:-2283}"
    curl -fsS --max-time 3 "http://127.0.0.1:${port}/api/server/ping" || true
    echo
    ;;
  immich-logs)
    "${DC[@]}" logs --tail=200 immich-server immich-machine-learning immich-redis immich-database
    ;;
  immich-restart)
    "${DC[@]}" restart immich-server immich-machine-learning immich-redis immich-database
    ;;
'''
    if marker in s: s=s.replace(marker,block,1)
if '  romm-status)' not in s and '  immich-status)' in s:
    marker='''  immich-status)
    "${DC[@]}" ps immich-server immich-machine-learning immich-redis immich-database
    port="$(awk -F= '$1=="IMMICH_PORT"{print $2}' .env | tail -n1)"; port="${port:-2283}"
    curl -fsS --max-time 3 "http://127.0.0.1:${port}/api/server/ping" || true
    echo
    ;;
'''
    # Append RomM management commands immediately before the next case arm.
    block=marker+'''  romm-status)
    "${DC[@]}" ps romm romm-db
    port="$(awk -F= '$1=="ROMM_PORT"{print $2}' .env | tail -n1)"; port="${port:-8082}"
    curl -fsSI --max-time 3 "http://127.0.0.1:${port}/" | head -n1 || true
    ;;
  romm-logs)
    "${DC[@]}" logs --tail=200 romm romm-db
    ;;
  romm-restart)
    "${DC[@]}" restart romm-db romm
    ;;
'''
    if marker in s:
        s=s.replace(marker,block,1)
# Upgrade existing RomM status diagnostics from a TCP-only probe to the
# authoritative portal-native emulator pipeline health endpoint.
old_romm='''  romm-status)
    "${DC[@]}" ps romm romm-db
    port="$(awk -F= '$1=="ROMM_PORT"{print $2}' .env | tail -n1)"; port="${port:-8082}"
    curl -fsSI --max-time 3 "http://127.0.0.1:${port}/" | head -n1 || true
    ;;
'''
new_romm='''  romm-status)
    "${DC[@]}" ps romm romm-db
    port="$(awk -F= '$1=="ROMM_PORT"{print $2}' .env | tail -n1)"; port="${port:-8082}"
    status_port="$(awk -F= '$1=="PCGA_STATUS_PORT"{print $2}' .env | tail -n1)"; status_port="${status_port:-8098}"
    echo "RomM heartbeat:"
    curl -fsS --max-time 3 "http://127.0.0.1:${port}/api/heartbeat" 2>/dev/null | python3 -m json.tool 2>/dev/null || true
    echo "Portal emulator pipeline:"
    curl -sS --max-time 8 "http://127.0.0.1:${status_port}/api/games/health?refresh=1" 2>/dev/null | python3 -m json.tool 2>/dev/null || true
    ;;
'''
if old_romm in s:
    s=s.replace(old_romm,new_romm,1)
if '  control-status)' not in s and '  ingest-audit)' in s:
    block='''  control-status)\n    systemctl --no-pager --full status pcga-control.service || true\n    ;;\n  control-config)\n    sudo cat /etc/pc-game-archive/appliance.json\n    ;;\n'''
    s=s.replace('  ingest-audit)\n', block+'  ingest-audit)\n', 1)
s=s.replace('|jellyfin-forget-token|arm-metadata-configure', '|jellyfin-forget-token|immich-status|immich-logs|immich-restart|romm-status|romm-logs|romm-restart|control-status|control-config|arm-metadata-configure')
p.write_text(s)
PYWRAP
chmod 0755 /usr/local/bin/game-archive
fi
install -d -m 0755 "$STATUS_DIR"
install -m 0755 "$COMP/pcga-status-server.py" "$STATUS_DIR/server.py"
install -m 0755 "$COMP/pcga-appliance-credentials" /usr/local/sbin/pcga-appliance-credentials
install -m 0755 "$COMP/pcga-immich-bootstrap" /usr/local/sbin/pcga-immich-bootstrap
install -m 0755 "$COMP/pcga-jellyfin-appliance-user" /usr/local/sbin/pcga-jellyfin-appliance-user
install -m 0755 "$COMP/pcga-game-stack-start" /usr/local/sbin/pcga-game-stack-start
install -m 0644 "$COMP/pcga-game-stack.service" /etc/systemd/system/pcga-game-stack.service
install -m 0755 "$COMP/pcga-service-auth" /usr/local/sbin/pcga-service-auth
install -m 0755 "$COMP/pcga-secure-context-bootstrap" /usr/local/sbin/pcga-secure-context-bootstrap
install -m 0755 "$COMP/pcga-network-identity" /usr/local/sbin/pcga-network-identity
install -m 0644 "$COMP/pcga-network-identity.service" /etc/systemd/system/pcga-network-identity.service
install -m 0755 "$COMP/pcga-moonlight-web-bootstrap" /usr/local/sbin/pcga-moonlight-web-bootstrap
install -m 0755 "$COMP/pcga-tailscale-remote" /usr/local/sbin/pcga-tailscale-remote
install -m 0755 "$COMP/pcga-netbird-remote" /usr/local/sbin/pcga-netbird-remote
install -m 0755 "$COMP/pcga-zerotier-remote" /usr/local/sbin/pcga-zerotier-remote
install -m 0755 "$COMP/pcga-thin-client-bootstrap" /usr/local/sbin/pcga-thin-client-bootstrap
install -m 0644 "$COMP/pcga-thin-client-bootstrap.service" /etc/systemd/system/pcga-thin-client-bootstrap.service
install -m 0644 "$COMP/pcga-service-auth.service" /etc/systemd/system/pcga-service-auth.service
install -m 0644 "$COMP/pcga-service-auth.timer" /etc/systemd/system/pcga-service-auth.timer
/usr/local/sbin/pcga-appliance-credentials
install -m 0755 "$COMP/pcga-romm-bootstrap" /usr/local/sbin/pcga-romm-bootstrap
install -m 0755 "$COMP/pcga-native-emulators" /usr/local/sbin/pcga-native-emulators
install -d -m 0700 /etc/pc-game-archive/secrets
if [[ ! -e /etc/pc-game-archive/secrets/romm-bootstrap.env ]]; then
  install -m 0600 /dev/null /etc/pc-game-archive/secrets/romm-bootstrap.env
else
  chmod 0600 /etc/pc-game-archive/secrets/romm-bootstrap.env 2>/dev/null || true
fi
install -m 0755 "$COMP/pcga-lancommander-bootstrap" /usr/local/sbin/pcga-lancommander-bootstrap
install -m 0644 "$COMP/compose.game-lan.yml" "$STACK_DIR/compose.game-lan.yml"

install -m 0644 "$COMP/pcga-media-sort.service" /etc/systemd/system/pcga-media-sort.service
install -m 0644 "$COMP/pcga-media-sort.timer" /etc/systemd/system/pcga-media-sort.timer
install -m 0644 "$COMP/pcga-metadata-classify.service" /etc/systemd/system/pcga-metadata-classify.service
install -m 0644 "$COMP/pcga-metadata-classify.timer" /etc/systemd/system/pcga-metadata-classify.timer

python3 - "$COMP/pcga-media-sort.path" /etc/systemd/system/pcga-media-sort.path "$ROOT" <<'PY'
from pathlib import Path
import sys
src, dst, root = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
dst.write_text(src.read_text().replace('__ARCHIVE_ROOT__', root))
PY
python3 - "$COMP/pcga-metadata-classify.path" /etc/systemd/system/pcga-metadata-classify.path "$ROOT" <<'PY'
from pathlib import Path
import sys
src, dst, root = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
dst.write_text(src.read_text().replace('__ARCHIVE_ROOT__', root))
PY
chmod 0644 /etc/systemd/system/pcga-media-sort.path /etc/systemd/system/pcga-metadata-classify.path

# Manual Review is now a portal-native modal. The writable review service remains
# isolated on the host; pcga-status receives only its service credential so browser
# JavaScript never sees the token.
install -d -m 0755 /etc/pc-game-archive
if [[ ! -s /etc/pc-game-archive/manual-review-token ]]; then
  python3 - <<'PYREVIEWTOKEN'
from pathlib import Path
import secrets
p=Path('/etc/pc-game-archive/manual-review-token')
p.write_text(secrets.token_urlsafe(36)+'\n')
p.chmod(0o600)
PYREVIEWTOKEN
else
  chmod 0600 /etc/pc-game-archive/manual-review-token 2>/dev/null || true
fi

# Ensure the read-only portal can proxy the privileged control plane without
# exposing its bearer token to browser JavaScript.
python3 - "$STACK_DIR/compose.status.yml" <<'PYOPTICALDISPATCHMOUNT'
from pathlib import Path
import sys
p=Path(sys.argv[1]); lines=p.read_text().splitlines()
mount='      - "/var/lib/pc-game-archive/optical-dispatch:/pcga/status/optical-dispatch:ro"'
if 'optical-dispatch:/pcga/status/optical-dispatch:ro' not in '\n'.join(lines):
    out=[]; done=False
    for line in lines:
        out.append(line)
        if '/var/lib/pc-game-archive/optical-health:/pcga/status/optical-health:ro' in line:
            out.append(mount); done=True
    if not done: raise SystemExit('Could not locate optical-health mount anchor in compose.status.yml')
    p.write_text('\n'.join(out)+'\n')
PYOPTICALDISPATCHMOUNT

python3 - "$STACK_DIR/compose.status.yml" <<'PYBOOTSTRAPMOUNT'
from pathlib import Path
import sys
p=Path(sys.argv[1])
if p.exists():
    lines=p.read_text().splitlines()
    mount='/var/lib/pc-game-archive/bootstrap:/var/lib/pc-game-archive/bootstrap:ro'
    if not any(mount in x for x in lines):
        out=[]; inserted=False
        for x in lines:
            out.append(x)
            if '/app/server.py:ro' in x:
                indent=x[:len(x)-len(x.lstrip())]
                out.append(f'{indent}- "{mount}"')
                inserted=True
        if not inserted:
            raise SystemExit('Could not locate status server volume anchor for bootstrap state mount')
        p.write_text('\n'.join(out)+'\n')
PYBOOTSTRAPMOUNT

python3 - "$STACK_DIR/compose.status.yml" <<'PYREVIEWSTATUS'
from pathlib import Path
import sys
p=Path(sys.argv[1])
if not p.exists(): raise SystemExit(0)
lines=p.read_text().splitlines()
if not any('PCGA_REVIEW_TOKEN_FILE:' in x for x in lines):
    out=[]; inserted=False
    for line in lines:
        out.append(line)
        if 'PCGA_REVIEW_UPSTREAM:' in line:
            indent=line[:len(line)-len(line.lstrip())]
            out.append(f'{indent}PCGA_REVIEW_TOKEN_FILE: "/pcga/secrets/manual-review-token"')
            inserted=True
    if not inserted: raise SystemExit('Could not locate review upstream environment anchor in compose.status.yml')
    lines=out
mount='/etc/pc-game-archive/manual-review-token:/pcga/secrets/manual-review-token:ro'
if not any('/pcga/secrets/manual-review-token:ro' in x for x in lines):
    out=[]; inserted=False
    for line in lines:
        out.append(line)
        if '/etc/pc-game-archive/control-token:/pcga/secrets/control-token:ro' in line or '/etc/pc-game-archive/jellyfin-api-key:/pcga/secrets/jellyfin-api-key:ro' in line:
            if not inserted:
                indent=line[:len(line)-len(line.lstrip())]
                out.append(f'{indent}- "{mount}"')
                inserted=True
    if not inserted: raise SystemExit('Could not locate status volume anchor for manual-review token')
    lines=out
p.write_text('\n'.join(lines)+'\n')
PYREVIEWSTATUS

# Give the read-only portal direct access to LANCommander's catalog and
# package/media storage. The normal PC Games UI stays on the PCGA origin; the
# native LANCommander server is an Advanced administration surface only.
python3 - "$STACK_DIR/compose.status.yml" "$ROOT" <<'PYLANCOMMANDERPORTAL'
from pathlib import Path
import sys
p=Path(sys.argv[1]); root=sys.argv[2]
if not p.exists(): raise SystemExit(0)
lines=p.read_text().splitlines()
if not any('PCGA_LANCOMMANDER_DATA:' in x for x in lines):
    out=[]; inserted=False
    for line in lines:
        out.append(line)
        if 'PCGA_LANCOMMANDER_PORT:' in line:
            indent=line[:len(line)-len(line.lstrip())]
            out.append(f'{indent}PCGA_LANCOMMANDER_DATA: "/pcga/lancommander"')
            inserted=True
    if not inserted: raise SystemExit('Could not locate LANCommander port environment anchor in compose.status.yml')
    lines=out
mount=f'{root}/lancommander:/pcga/lancommander:ro'
if not any('/pcga/lancommander:ro' in x for x in lines):
    out=[]; inserted=False
    for line in lines:
        out.append(line)
        if '/var/lib/pc-game-archive/bootstrap:/var/lib/pc-game-archive/bootstrap:ro' in line:
            indent=line[:len(line)-len(line.lstrip())]
            out.append(f'{indent}- "{mount}"')
            inserted=True
    if not inserted: raise SystemExit('Could not locate portal volume anchor for LANCommander data mount')
    lines=out
p.write_text('\n'.join(lines)+'\n')
PYLANCOMMANDERPORTAL

python3 - "$STACK_DIR/compose.status.yml" <<'PYPCGAGAMEPORTAL'
from pathlib import Path
import sys
p=Path(sys.argv[1])
if not p.exists(): raise SystemExit(0)
lines=p.read_text().splitlines()
mounts=[
    '/var/lib/pc-game-archive/game-intake:/pcga/game-intake:ro',
    '/var/lib/pc-game-archive/game-installs:/pcga/game-installs:ro',
    '/var/lib/pc-game-archive/heroic:/pcga/heroic:ro',
]
for mount in mounts:
    if any(mount in x for x in lines): continue
    out=[]; inserted=False
    for line in lines:
        out.append(line)
        if '/pcga/lancommander:ro' in line and not inserted:
            indent=line[:len(line)-len(line.lstrip())]
            out.append(f'{indent}- "{mount}"'); inserted=True
    if not inserted: raise SystemExit('Could not locate LANCommander status mount anchor for PC-game state')
    lines=out
p.write_text('\n'.join(lines)+'\n')
PYPCGAGAMEPORTAL

python3 - "$STACK_DIR/compose.status.yml" <<'PYCONTROLSTATUS'
from pathlib import Path
import sys
p=Path(sys.argv[1])
if not p.exists(): raise SystemExit(0)
lines=p.read_text().splitlines()
if not any('PCGA_CONTROL_UPSTREAM:' in x for x in lines):
    out=[]
    for line in lines:
        out.append(line)
        if 'PCGA_PUBLIC_MEDIA_UPSTREAM:' in line:
            indent=line[:len(line)-len(line.lstrip())]
            out.append(f'{indent}PCGA_CONTROL_UPSTREAM: "http://host.docker.internal:8100"')
            out.append(f'{indent}PCGA_CONTROL_TOKEN_FILE: "/pcga/secrets/control-token"')
    lines=out
if not any('control-token:/pcga/secrets/control-token:ro' in x for x in lines):
    out=[]
    for line in lines:
        out.append(line)
        if 'jellyfin-api-key:/pcga/secrets/jellyfin-api-key:ro' in line:
            indent=line[:len(line)-len(line.lstrip())]
            out.append(indent+'- "/etc/pc-game-archive/control-token:/pcga/secrets/control-token:ro"')
    lines=out
p.write_text('\n'.join(lines)+'\n')
PYCONTROLSTATUS

status_network_gateway() {
  local gw="" net=""
  gw="$(docker inspect pcga-status --format '{{range .NetworkSettings.Networks}}{{println .Gateway}}{{end}}' 2>/dev/null | awk 'NF{print; exit}' || true)"
  if [[ -z "$gw" ]]; then
    net="$(docker network ls --filter label=com.docker.compose.project=pc-game-archive --format '{{.Name}}' 2>/dev/null | head -n1 || true)"
    [[ -n "$net" ]] && gw="$(docker network inspect "$net" --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)"
  fi
  if [[ -z "$gw" ]]; then
    gw="$(docker network inspect pc-game-archive_default --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)"
  fi
  if [[ -z "$gw" ]]; then
    gw="$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)"
  fi
  printf '%s' "$gw"
}

CONTROL_BIND="$(status_network_gateway)"
[[ -n "$CONTROL_BIND" ]] || die "Unable to determine the pcga-status Docker network gateway"
PUBLIC_MEDIA_BIND="$CONTROL_BIND"
log "Binding host control services to the pcga-status network gateway $CONTROL_BIND"

# Do not rely on Docker's host-gateway alias here. On Linux that alias normally
# points at docker0 even when pcga-status lives on a user-defined Compose bridge.
# Bind the host services and point the sidecar at the gateway of its *actual*
# network so diagnostics and importer traffic never cross an unrelated bridge.
python3 - "$STACK_DIR/compose.status.yml" "$CONTROL_BIND" "$JELLYFIN_CURRENT" <<'PYSTATUSGATEWAY'
from pathlib import Path
import re, sys
p=Path(sys.argv[1]); gateway=sys.argv[2]; jellyfin_port=sys.argv[3]
if not p.exists():
    raise SystemExit(0)
lines=p.read_text().splitlines()

# Locate the pcga-status service without assuming the rest of compose.status.yml
# came from a specific historical PCGA release.
svc=None
svc_indent=None
for i,line in enumerate(lines):
    if line.strip() == 'pcga-status:' and not line.lstrip().startswith('#'):
        svc=i; svc_indent=len(line)-len(line.lstrip()); break
if svc is None:
    raise SystemExit('compose.status.yml has no pcga-status service')
svc_end=len(lines)
for i in range(svc+1,len(lines)):
    stripped=lines[i].strip()
    indent=len(lines[i])-len(lines[i].lstrip())
    if stripped and not stripped.startswith('#') and indent <= svc_indent:
        svc_end=i; break

def reconcile_environment(lines, svc, svc_end):
    wanted={
        'PCGA_CONTROL_UPSTREAM': f'http://{gateway}:8100',
        'PCGA_TOOL_HOST': gateway,
        'PCGA_JELLYFIN_PORT': jellyfin_port,
        'PCGA_PUBLIC_MEDIA_UPSTREAM': f'http://{gateway}:8099',
        'PCGA_CONTROL_TOKEN_FILE': '/pcga/secrets/control-token',
    }
    env=None; env_indent=None; env_end=None
    for i in range(svc+1,svc_end):
        if lines[i].strip() == 'environment:':
            env=i; env_indent=len(lines[i])-len(lines[i].lstrip()); break
    if env is None:
        child=' '*(svc_indent+2)
        grand=' '*(svc_indent+4)
        block=[child+'environment:']+[grand+f'{k}: "{v}"' for k,v in wanted.items()]
        lines[svc+1:svc+1]=block
        return lines
    env_end=svc_end
    style='mapping'
    for i in range(env+1,svc_end):
        stripped=lines[i].strip(); indent=len(lines[i])-len(lines[i].lstrip())
        if stripped and not stripped.startswith('#') and indent <= env_indent:
            env_end=i; break
        if stripped and not stripped.startswith('#') and indent > env_indent and stripped.startswith('- '):
            style='list'
    body=[]
    for line in lines[env+1:env_end]:
        s=line.strip()
        if any(re.match(rf'^(?:-\s*)?{re.escape(k)}(?:\s*:|=)',s) for k in wanted):
            continue
        body.append(line)
    indent=' '*(env_indent+2)
    if style=='list':
        canonical=[indent+f'- {k}={v}' for k,v in wanted.items()]
    else:
        canonical=[indent+f'{k}: "{v}"' for k,v in wanted.items()]
    lines[env+1:env_end]=canonical+body
    return lines

lines=reconcile_environment(lines,svc,svc_end)

# Ensure the control token is mounted into the read-only portal sidecar.
text='\n'.join(lines)+'\n'
mount='/etc/pc-game-archive/control-token:/pcga/secrets/control-token:ro'
if mount not in text:
    lines=text.splitlines()
    svc=None; svc_indent=None
    for i,line in enumerate(lines):
        if line.strip()=='pcga-status:':
            svc=i; svc_indent=len(line)-len(line.lstrip()); break
    svc_end=len(lines)
    for i in range(svc+1,len(lines)):
        stripped=lines[i].strip(); indent=len(lines[i])-len(lines[i].lstrip())
        if stripped and not stripped.startswith('#') and indent <= svc_indent:
            svc_end=i; break
    vols=None; vols_indent=None; vols_end=svc_end
    for i in range(svc+1,svc_end):
        if lines[i].strip()=='volumes:':
            vols=i; vols_indent=len(lines[i])-len(lines[i].lstrip()); break
    if vols is None:
        child=' '*(svc_indent+2); grand=' '*(svc_indent+4)
        lines[svc_end:svc_end]=[child+'volumes:', grand+f'- "{mount}"']
    else:
        for i in range(vols+1,svc_end):
            stripped=lines[i].strip(); indent=len(lines[i])-len(lines[i].lstrip())
            if stripped and not stripped.startswith('#') and indent <= vols_indent:
                vols_end=i; break
        lines.insert(vols_end,' '*(vols_indent+2)+f'- "{mount}"')

p.write_text('\n'.join(lines)+'\n')
PYSTATUSGATEWAY

python3 - "$COMP/pcga-control.service" /etc/systemd/system/pcga-control.service "$CONTROL_BIND" "$ROOT" <<'PYCONTROLSVC'
from pathlib import Path
import sys
src,dst,bind,root=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],sys.argv[4]
text=src.read_text().replace('__PCGA_CONTROL_BIND__',bind).replace('__PCGA_ARCHIVE_ROOT__',root)
dst.write_text(text)
PYCONTROLSVC
chmod 0644 /etc/systemd/system/pcga-control.service
systemctl daemon-reload
systemctl enable pcga-control.service >/dev/null 2>&1 || true
systemctl enable pcga-network-identity.service >/dev/null 2>&1 || true
systemctl enable pcga-thin-client-bootstrap.service >/dev/null 2>&1 || true
systemctl enable pcga-lan-dns.service >/dev/null 2>&1 || true
systemctl enable pcga-nas-mount.service >/dev/null 2>&1 || true
systemctl enable --now pcga-nas-sync.timer >/dev/null 2>&1 || true
# Keep the writable control plane down while Compose definitions are being
# reconciled; a Settings apply can itself start/recreate RomM.
systemctl stop pcga-control.service >/dev/null 2>&1 || true

log "Binding public-media importer to pcga-status network gateway $PUBLIC_MEDIA_BIND:8099"

python3 - "$COMP/pcga-public-media.service" /etc/systemd/system/pcga-public-media.service "$ROOT" "$PUBLIC_MEDIA_BIND" <<'PYUNIT'
from pathlib import Path
import sys
src, dst, root, bind = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
text = src.read_text().replace('__ARCHIVE_ROOT__', root).replace('__PUBLIC_MEDIA_BIND__', bind)
dst.write_text(text)
PYUNIT
chmod 0644 /etc/systemd/system/pcga-public-media.service
install -m 0644 "$COMP/pcga-dedupe.service" /etc/systemd/system/pcga-dedupe.service
install -m 0644 "$COMP/pcga-dedupe.timer" /etc/systemd/system/pcga-dedupe.timer

# Install Immich as the appliance's standard photo/video handler. The managed
# upload tree is separate from PCGA's generic libraries; a read-only photo
# archive is mounted at /mnt/pcga-photos for optional Immich External Library use.
install -d -m 0755 "$ROOT/immich/library" "$ROOT/media/library/photos" \
  /var/lib/pc-game-archive/immich/postgres /var/cache/pc-game-archive/immich-model-cache \
  /etc/pc-game-archive
if [[ ! -e /etc/pc-game-archive/immich.env ]]; then
  IMMICH_DB_PASSWORD="$(python3 - <<'PYIMMICHSECRET'
import secrets,string
alphabet=string.ascii_letters+string.digits
print(''.join(secrets.choice(alphabet) for _ in range(40)))
PYIMMICHSECRET
)"
  cat > /etc/pc-game-archive/immich.env <<IMMICH_ENV
DB_HOSTNAME=immich-database
DB_USERNAME=postgres
DB_PASSWORD=$IMMICH_DB_PASSWORD
DB_DATABASE_NAME=immich
REDIS_HOSTNAME=immich-redis
TZ=$TZ_VALUE
POSTGRES_PASSWORD=$IMMICH_DB_PASSWORD
POSTGRES_USER=postgres
POSTGRES_DB=immich
POSTGRES_INITDB_ARGS=--data-checksums
IMMICH_ENV
  chmod 0600 /etc/pc-game-archive/immich.env
else
  chmod 0600 /etc/pc-game-archive/immich.env 2>/dev/null || true
fi

python3 - "$STACK_DIR/.env" "$IMMICH_PORT" <<'PYIMMICHENV'
from pathlib import Path
import sys
p=Path(sys.argv[1]); port=sys.argv[2]
lines=p.read_text().splitlines() if p.exists() else []
def setv(key,val):
    global lines
    for i,line in enumerate(lines):
        if line.startswith(key+'='):
            lines[i]=f'{key}={val}'; return
    lines.append(f'{key}={val}')
setv('IMMICH_PORT',port)
setv('IMMICH_VERSION','v3.2.0')
p.write_text('\n'.join(lines)+'\n')
PYIMMICHENV

cat > "$STACK_DIR/compose.immich.yml" <<'COMPOSE_IMMICH'
services:
  immich-server:
    image: ghcr.io/immich-app/immich-server:${IMMICH_VERSION:-v3.2.0}
    container_name: immich_server
    ports:
      - "${IMMICH_PORT}:2283/tcp"
    volumes:
      - "${ARCHIVE_ROOT}/immich/library:/data:rw"
      - "${ARCHIVE_ROOT}/media/library/photos:/mnt/pcga-photos:ro"
      - "/etc/localtime:/etc/localtime:ro"
    env_file:
      - /etc/pc-game-archive/immich.env
    depends_on:
      immich-redis:
        condition: service_healthy
      immich-database:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      disable: false

  immich-machine-learning:
    image: ghcr.io/immich-app/immich-machine-learning:${IMMICH_VERSION:-v3.2.0}
    container_name: immich_machine_learning
    volumes:
      - "/var/cache/pc-game-archive/immich-model-cache:/cache:rw"
    env_file:
      - /etc/pc-game-archive/immich.env
    restart: unless-stopped
    healthcheck:
      disable: false

  immich-redis:
    image: docker.io/valkey/valkey:9@sha256:70739f85ad2ee01a726a965584a0f94895f01b0c60b3cc8b0aeef11eaa6888cf
    container_name: immich_redis
    volumes:
      - immich-redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
    restart: unless-stopped

  immich-database:
    image: ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0@sha256:bcf63357191b76a916ae5eb93464d65c07511da41e3bf7a8416db519b40b1c23
    container_name: immich_postgres
    env_file:
      - /etc/pc-game-archive/immich.env
    volumes:
      - "/var/lib/pc-game-archive/immich/postgres:/var/lib/postgresql/data:rw"
    shm_size: 128mb
    healthcheck:
      test: ["CMD-SHELL", "pg_isready --dbname=$${POSTGRES_DB} --username=$${POSTGRES_USER} || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

volumes:
  immich-redis-data:
COMPOSE_IMMICH

# Ensure the status sidecar learns a custom Immich port too.
python3 - "$STACK_DIR/compose.status.yml" "$IMMICH_PORT" <<'PYIMMICHSTATUS'
from pathlib import Path
import sys
p=Path(sys.argv[1]); port=sys.argv[2]
if not p.exists(): raise SystemExit(0)
lines=p.read_text().splitlines()
if any('PCGA_IMMICH_PORT:' in x for x in lines):
    lines=[(x[:len(x)-len(x.lstrip())] + f'PCGA_IMMICH_PORT: "{port}"') if 'PCGA_IMMICH_PORT:' in x else x for x in lines]
else:
    out=[]; done=False
    for x in lines:
        out.append(x)
        if 'PCGA_JELLYFIN_PORT:' in x:
            indent=x[:len(x)-len(x.lstrip())]
            out.append(f'{indent}PCGA_IMMICH_PORT: "{port}"'); done=True
    lines=out
p.write_text('\n'.join(lines)+'\n')
PYIMMICHSTATUS

# RomM + EmulatorJS: browser-playable console library. The full RomM image
# bundles EmulatorJS runtimes so normal browser play does not depend on a CDN.
install -d -m 0755 \
  "$ROOT/media/library/console-games/roms" \
  "$ROOT/media/library/console-games/bios" \
  "$ROOT/romm/assets" "$ROOT/romm/config" "$ROOT/romm/resources" \
  /var/lib/pc-game-archive/romm/mariadb /var/lib/pc-game-archive/romm/redis-data \
  /etc/pc-game-archive

ROMM_PUID="$(awk -F= '$1=="PUID"{print $2}' "$STACK_DIR/.env" 2>/dev/null | tail -n1)"
ROMM_PGID="$(awk -F= '$1=="PGID"{print $2}' "$STACK_DIR/.env" 2>/dev/null | tail -n1)"
ROMM_PUID="${ROMM_PUID:-$(stat -c '%u' "$ROOT" 2>/dev/null || echo 1000)}"
ROMM_PGID="${ROMM_PGID:-$(stat -c '%g' "$ROOT" 2>/dev/null || echo 1000)}"
chown -R "$ROMM_PUID:$ROMM_PGID" "$ROOT/media/library/console-games" "$ROOT/romm"
chown "$ROMM_PUID:$ROMM_PGID" /var/lib/pc-game-archive/romm/redis-data

if [[ ! -e "$ROOT/romm/config/config.yml" ]]; then
  cat > "$ROOT/romm/config/config.yml" <<'ROMM_CONFIG'
# PCGA-managed RomM defaults. RomM's web UI reads this same file.
# The stable v5.2 layout keeps ROMs and firmware in the canonical PCGA tree.
filesystem:
  roms_folder: "roms"
  firmware_folder: "bios"
  skip_hash_calculation: false

system:
  platforms:
    psx: "ps"
    gc: "ngc"
    gamecube: "ngc"
ROMM_CONFIG
fi

python3 - "$ROOT/romm/config/config.yml" <<'PYROMMCFG'
from pathlib import Path
import sys
p=Path(sys.argv[1])
legacy='filesystem:\n  roms_folder: "roms"\n  firmware_folder: "bios"\n'
managed='# PCGA-managed RomM defaults. RomM\'s web UI reads this same file.\n# The stable v5.2 layout keeps ROMs and firmware in the canonical PCGA tree.\nfilesystem:\n  roms_folder: "roms"\n  firmware_folder: "bios"\n  skip_hash_calculation: false\n\nsystem:\n  platforms:\n    psx: "ps"\n    gc: "ngc"\n    gamecube: "ngc"\n'
if not p.exists():
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(managed)
else:
    current=p.read_text()
    # Upgrade only the exact v0.16.0 PCGA-generated minimal file. Never
    # overwrite a user-customized RomM config.
    if current.strip() == legacy.strip():
        p.write_text(managed)
PYROMMCFG

if [[ ! -e /etc/pc-game-archive/romm.env ]]; then
  ROMM_AUTH_SECRET="$(openssl rand -hex 32)"
  ROMM_DB_PASSWORD="$(python3 - <<'PYROMMSECRET'
import secrets,string
a=string.ascii_letters+string.digits
print(''.join(secrets.choice(a) for _ in range(40)))
PYROMMSECRET
)"
  ROMM_DB_ROOT_PASSWORD="$(python3 - <<'PYROMMROOT'
import secrets,string
a=string.ascii_letters+string.digits
print(''.join(secrets.choice(a) for _ in range(48)))
PYROMMROOT
)"
  cat > /etc/pc-game-archive/romm.env <<ROMM_ENV
ROMM_AUTH_SECRET_KEY=$ROMM_AUTH_SECRET
DB_NAME=romm
DB_USER=romm-user
DB_PASSWD=$ROMM_DB_PASSWORD
MARIADB_ROOT_PASSWORD=$ROMM_DB_ROOT_PASSWORD
MARIADB_DATABASE=romm
MARIADB_USER=romm-user
MARIADB_PASSWORD=$ROMM_DB_PASSWORD
HASHEOUS_API_ENABLED=true
PLAYMATCH_API_ENABLED=true
DISABLE_SETUP_WIZARD=false
DISABLE_EMULATOR_JS=false
DISABLE_RUFFLE_RS=false
ENABLE_RESCAN_ON_FILESYSTEM_CHANGE=true
RESCAN_ON_FILESYSTEM_CHANGE_DELAY=5
ENABLE_SCHEDULED_RESCAN=true
SCHEDULED_RESCAN_CRON=25 3 * * *
SCAN_TIMEOUT=21600
SEVEN_ZIP_TIMEOUT=120
SCAN_WORKERS=2
WEB_SERVER_CONCURRENCY=2
PUID=$ROMM_PUID
PGID=$ROMM_PGID
TZ=$TZ_VALUE
ROMM_ENV
  chmod 0600 /etc/pc-game-archive/romm.env
else
  chmod 0600 /etc/pc-game-archive/romm.env 2>/dev/null || true
fi

# Reconcile PCGA-owned RomM background defaults on every install/upgrade.
# Existing provider credentials and user-added variables are preserved.
python3 - /etc/pc-game-archive/romm.env /etc/pc-game-archive/appliance.json <<'PYROMMBG'
from pathlib import Path
import json, sys
p=Path(sys.argv[1]); cfgp=Path(sys.argv[2])
lines=p.read_text().splitlines() if p.exists() else []
# These values are appliance-owned.  Read the persisted Control Center config
# instead of assuming the factory defaults, so upgrades preserve supported
# user customization while still repairing stale/missing RomM environment keys.
games={}
try:
    raw=json.loads(cfgp.read_text()) if cfgp.exists() else {}
    if isinstance(raw, dict) and isinstance(raw.get('games'), dict):
        games=raw['games']
except Exception:
    games={}
def as_bool(value, default=True):
    return value if isinstance(value, bool) else default
def clamp_int(value, lo, hi, default):
    try: n=int(value)
    except (TypeError, ValueError): return default
    return max(lo, min(hi, n))
watch_seconds=clamp_int(games.get('watch_debounce_seconds'), 30, 3600, 300)
cron=str(games.get('scheduled_rescan') or '25 3 * * *').strip()
if len(cron)>80 or any(c in cron for c in '\n\r\0'):
    cron='25 3 * * *'
values={
    'HASHEOUS_API_ENABLED':'true' if as_bool(games.get('metadata_hasheous'), True) else 'false',
    'PLAYMATCH_API_ENABLED':'true' if as_bool(games.get('metadata_playmatch'), True) else 'false',
    'DISABLE_SETUP_WIZARD':'false',
    'DISABLE_EMULATOR_JS':'false',
    'DISABLE_RUFFLE_RS':'false',
    'ENABLE_RESCAN_ON_FILESYSTEM_CHANGE':'true' if as_bool(games.get('filesystem_watch'), True) else 'false',
    # RomM 5.2.0 expresses this setting in whole minutes.
    'RESCAN_ON_FILESYSTEM_CHANGE_DELAY':str(max(1, watch_seconds // 60)),
    'ENABLE_SCHEDULED_RESCAN':'true',
    'SCHEDULED_RESCAN_CRON':cron,
    'SCAN_TIMEOUT':'21600',
    'SEVEN_ZIP_TIMEOUT':'120',
}
remaining=dict(values)
out=[]
for line in lines:
    if '=' in line and not line.lstrip().startswith('#'):
        key=line.split('=',1)[0].strip()
        if key in remaining:
            out.append(f'{key}={remaining.pop(key)}')
            continue
    out.append(line)
if out and out[-1] != '': out.append('')
for key,val in remaining.items(): out.append(f'{key}={val}')
p.write_text('\n'.join(out).rstrip()+'\n')
PYROMMBG
chmod 0600 /etc/pc-game-archive/romm.env

python3 - "$STACK_DIR/.env" "$ROMM_PORT" <<'PYROMMENV'
from pathlib import Path
import sys
p=Path(sys.argv[1]); port=sys.argv[2]
lines=p.read_text().splitlines() if p.exists() else []
def setv(k,v):
    for i,x in enumerate(lines):
        if x.startswith(k+'='):
            lines[i]=f'{k}={v}'; return
    lines.append(f'{k}={v}')
setv('ROMM_PORT',port)
setv('ROMM_VERSION','5.2.0')
p.write_text('\n'.join(lines)+'\n')
PYROMMENV

cat > "$STACK_DIR/compose.romm.yml" <<'COMPOSE_ROMM'
services:
  romm:
    image: rommapp/romm:${ROMM_VERSION:-5.2.0}
    container_name: romm
    env_file:
      - /etc/pc-game-archive/romm.env
    environment:
      DB_HOST: romm-db
    ports:
      - "${ROMM_PORT}:8080/tcp"
    volumes:
      - "${ARCHIVE_ROOT}/media/library/console-games:/romm/library:rw"
      - "${ARCHIVE_ROOT}/romm/assets:/romm/assets:rw"
      - "${ARCHIVE_ROOT}/romm/config:/romm/config:rw"
      - "${ARCHIVE_ROOT}/romm/resources:/romm/resources:rw"
      - "/var/lib/pc-game-archive/romm/redis-data:/redis-data:rw"
    depends_on:
      romm-db:
        condition: service_healthy
        restart: true
    restart: unless-stopped

  romm-db:
    image: mariadb:11
    container_name: romm-db
    env_file:
      - /etc/pc-game-archive/romm.env
    volumes:
      - "/var/lib/pc-game-archive/romm/mariadb:/var/lib/mysql:rw"
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      start_period: 30s
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped
COMPOSE_ROMM

# Let the portal advertise the configured RomM host port.
python3 - "$STACK_DIR/compose.status.yml" "$ROMM_PORT" <<'PYROMMSTATUS'
from pathlib import Path
import sys
p=Path(sys.argv[1]); port=sys.argv[2]
if not p.exists(): raise SystemExit(0)
lines=p.read_text().splitlines()
if any('PCGA_ROMM_PORT:' in x for x in lines):
    lines=[(x[:len(x)-len(x.lstrip())]+f'PCGA_ROMM_PORT: "{port}"') if 'PCGA_ROMM_PORT:' in x else x for x in lines]
else:
    out=[]; done=False
    for x in lines:
        out.append(x)
        if 'PCGA_IMMICH_PORT:' in x:
            indent=x[:len(x)-len(x.lstrip())]
            out.append(f'{indent}PCGA_ROMM_PORT: "{port}"'); done=True
    lines=out
if not any('PCGA_ROMM_CREDS_FILE:' in x for x in lines):
    out=[]; done=False
    for x in lines:
        out.append(x)
        if 'PCGA_ROMM_PORT:' in x:
            indent=x[:len(x)-len(x.lstrip())]
            out.append(f'{indent}PCGA_ROMM_CREDS_FILE: "/pcga/secrets/romm-bootstrap.env"'); done=True
    lines=out
mount='/etc/pc-game-archive/secrets/romm-bootstrap.env:/pcga/secrets/romm-bootstrap.env:ro'
if not any(mount in x for x in lines):
    out=[]; done=False
    for x in lines:
        out.append(x)
        if '/pcga/secrets/jellyfin-api-key:ro' in x:
            indent=x[:len(x)-len(x.lstrip())]
            out.append(f'{indent}- "{mount}"'); done=True
    lines=out
p.write_text('\n'.join(lines)+'\n')
PYROMMSTATUS

# v0.17.36 retires the old always-retain-raw preservation profile. Previous
# releases exposed keep_raw as a disabled UI control and defaulted it on, so
# there was no supported portal path for choosing that behavior. Migrate once
# to the normal appliance policy: source-quality final MKV, cleanup of successful
# ARM intermediates, and recovery retention only for failed/incomplete jobs.
python3 - /etc/pc-game-archive/appliance.json <<'PYARMMIGRATE'
import json, os, sys, tempfile
from pathlib import Path
p=Path(sys.argv[1])
try:
    data=json.loads(p.read_text()) if p.exists() else {}
except Exception:
    data={}
ingest=data.setdefault('ingest',{})
ingest['keep_raw']=False
data['version']='0.19.22'
p.parent.mkdir(parents=True, exist_ok=True)
fd,tmp=tempfile.mkstemp(prefix=p.name+'.',dir=str(p.parent))
with os.fdopen(fd,'w') as f:
    json.dump(data,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.chmod(tmp,0o644); os.replace(tmp,p)
PYARMMIGRATE

# Reconcile ARM once while idle. It is no longer blindly rewritten immediately
# before every disc; settings changed during an active job are reconciled after
# that job finishes.
set +e
/usr/local/sbin/pcga-arm-configure --ensure >/tmp/pcga-arm-configure-v01713.log 2>&1
cfg_rc=$?
set -e
if [[ $cfg_rc -eq 0 ]]; then
  log "Synchronized ARM ingest policy (source-quality MKV; successful intermediates cleaned)."
elif [[ $cfg_rc -eq 75 ]]; then
  log "ARM rip is active; ingest-policy reconciliation deferred until that job finishes."
else
  cat /tmp/pcga-arm-configure-v01713.log >&2 || true
  die "Unable to reconcile ARM ingest policy (exit $cfg_rc)"
fi
rm -f /tmp/pcga-arm-configure-v01713.log

systemctl daemon-reload
systemctl reset-failed pcga-media-sort.service pcga-metadata-classify.service pcga-public-media.service 2>/dev/null || true
systemctl reset-failed pcga-dedupe.service 2>/dev/null || true
systemctl enable --now \
  pcga-media-sort.path pcga-media-sort.timer \
  pcga-metadata-classify.path pcga-metadata-classify.timer >/dev/null
systemctl enable --now pcga-dedupe.timer >/dev/null

# Safety: published optical reconciliation is now an explicit operator action.
# Auto-scanning historical rips during each upgrade could reintroduce a title
# deliberately separated from an incorrectly grouped movie. No library content
# is rewritten by the upgrader.
log "Skipping automatic published-title reconciliation; use Manual Review only when needed."

# Restart review UI and portal code. These operations do not touch arm-rippers.
systemctl restart pcga-manual-review.service 2>/dev/null || die "Unable to restart pcga-manual-review.service"
systemctl enable pcga-public-media.service >/dev/null || die "Unable to enable pcga-public-media.service"
# The unit file may have changed its --bind address while an older importer is
# already running. enable --now does not restart an active service, so force a
# restart to make the running process consume the freshly rendered ExecStart.
systemctl restart pcga-public-media.service || die "Unable to restart pcga-public-media.service with current Docker gateway bind"

# Pin LANCommander before bootstrap so the identity schema contract cannot drift.
python3 - "$STACK_DIR/.env" "$STACK_DIR/compose.yml" <<'PYLANPIN'
from pathlib import Path
import sys
env,compose=map(Path,sys.argv[1:])
lines=env.read_text().splitlines() if env.exists() else []
for i,x in enumerate(lines):
    if x.startswith('LANCOMMANDER_VERSION='): lines[i]='LANCOMMANDER_VERSION=v2.1.16'; break
else: lines.append('LANCOMMANDER_VERSION=v2.1.16')
managed={'PCGA_GAME_LAN_NETWORK':'legacy-games','PCGA_GAME_LAN_SUBNET':'10.40.0.0/16'}
for key,value in managed.items():
    for i,x in enumerate(lines):
        if x.startswith(key+'='):
            lines[i]=f'{key}={value}'
            break
    else:
        lines.append(f'{key}={value}')
env.write_text('\n'.join(lines)+'\n')
if compose.exists():
    text=compose.read_text().replace('lancommander/lancommander:latest','lancommander/lancommander:${LANCOMMANDER_VERSION:-v2.1.16}')
    compose.write_text(text)
PYLANPIN

# Streamed Wine desktops and LANCommander share one appliance-local L2 segment.
# Preserve an existing network so upgrades never renumber live game prefixes;
# create it only when this appliance predates the reserved game-LAN bridge.
GAME_LAN_NETWORK="legacy-games"
GAME_LAN_SUBNET="10.40.0.0/16"
if docker network inspect "$GAME_LAN_NETWORK" >/dev/null 2>&1; then
  GAME_LAN_SUBNET_ACTUAL="$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}' "$GAME_LAN_NETWORK" 2>/dev/null || true)"
  [[ -n "$GAME_LAN_SUBNET_ACTUAL" ]] && GAME_LAN_SUBNET="$GAME_LAN_SUBNET_ACTUAL"
else
  docker network create --driver bridge --attachable --subnet "$GAME_LAN_SUBNET" "$GAME_LAN_NETWORK" >/dev/null || die "Unable to create shared PC-game LAN $GAME_LAN_NETWORK ($GAME_LAN_SUBNET)"
fi
python3 - "$STACK_DIR/.env" "$GAME_LAN_SUBNET" <<'PYGAMELANENV'
from pathlib import Path
import sys
p=Path(sys.argv[1]); subnet=sys.argv[2]
lines=p.read_text().splitlines() if p.exists() else []
vals={'PCGA_GAME_LAN_NETWORK':'legacy-games','PCGA_GAME_LAN_SUBNET':subnet}
out=[]; seen=set()
for line in lines:
    key=line.split('=',1)[0] if '=' in line else ''
    if key in vals:
        if key not in seen: out.append(f'{key}={vals[key]}'); seen.add(key)
    else: out.append(line)
for key,value in vals.items():
    if key not in seen: out.append(f'{key}={value}')
p.write_text('\n'.join(out)+'\n')
PYGAMELANENV
log "Shared PC-game LAN: $GAME_LAN_NETWORK ($GAME_LAN_SUBNET)"

# Prefer the conventional HTTPS port for the friendly LAN name. Keep 8443
# available in all cases for compatibility. If another host service already owns
# 443, PCGA leaves it alone and advertises https://pcga.portal:8443/ instead.
install -d -m 0755 /etc/pc-game-archive
PCGA_LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
[[ -n "$PCGA_LAN_IP" ]] || PCGA_LAN_IP="$(hostname -I 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ && $i !~ /^127\./ && $i !~ /^172\.(1[6-9]|2[0-9]|3[0-1])\./){print $i; exit}}')"
[[ -n "$PCGA_LAN_IP" ]] || die "Unable to determine LAN address for friendly portal DNS"
LAN_HTTPS_PORT=443
port443_busy=0
if ss -H -ltn 2>/dev/null | awk '{print $4}' | grep -Eq '(^|\]):443$|:443$'; then
  if docker inspect pcga-status >/dev/null 2>&1 && docker port pcga-status 8443/tcp 2>/dev/null | grep -Eq '(^|:)443$'; then
    port443_busy=0
  else
    port443_busy=1
  fi
fi
if [[ $port443_busy -eq 1 ]]; then
  LAN_HTTPS_PORT=8443
  log "TCP 443 is already in use; LAN alias will use https://pcga.portal:8443/"
else
  log "TCP 443 is available; LAN alias will use https://pcga.portal/"
fi
printf '%s\n' "$LAN_HTTPS_PORT" > /etc/pc-game-archive/lan-https-port
chmod 0644 /etc/pc-game-archive/lan-https-port

# Install the browser-native Moonlight-compatible client only when Wolf exists.
if [[ -f "$STACK_DIR/compose.wolf.yml" ]]; then
  install -m 0644 "$COMP/compose.moonlight-web.yml" "$STACK_DIR/compose.moonlight-web.yml"
  PCGA_LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
  [[ -n "$PCGA_LAN_IP" ]] || PCGA_LAN_IP="$(hostname -I 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ && $i !~ /^127\./ && $i !~ /^172\.(1[6-9]|2[0-9]|3[0-1])\./){print $i; exit}}')"
  [[ -n "$PCGA_LAN_IP" ]] || die "Unable to determine LAN address for browser game streaming"
  python3 - "$STACK_DIR/.env" "$PCGA_LAN_IP" <<'PYMOONENV'
from pathlib import Path
import sys
p=Path(sys.argv[1]); vals={'PCGA_MOONLIGHT_WEB_PORT':'8101','PCGA_MOONLIGHT_WEB_PORT_2':'8102','PCGA_MOONLIGHT_WEB_PORT_3':'8103','PCGA_MOONLIGHT_WEB_PORT_4':'8104','PCGA_MOONLIGHT_WEB_LANES':'4','PCGA_STATUS_TLS_PORT':'8443','PCGA_PORTAL_DNS_NAME':'pcga.portal','PCGA_LAN_HTTPS_PORT':str(__import__('pathlib').Path('/etc/pc-game-archive/lan-https-port').read_text().strip() or '8443'),'PCGA_LAN_IP':sys.argv[2]}
lines=p.read_text().splitlines() if p.exists() else []; out=[]; seen=set()
for line in lines:
    k=line.split('=',1)[0] if '=' in line else ''
    if k in vals:
        if k not in seen: out.append(f'{k}={vals[k]}'); seen.add(k)
    else: out.append(line)
for k,v in vals.items():
    if k not in seen: out.append(f'{k}={v}')
p.write_text('\n'.join(out)+'\n')
PYMOONENV
  # Wolf is multi-homed on a PCGA appliance (LAN + Docker bridges + loopback).
  # Moonlight rejects a stream if Wolf's media originates from a different IP
  # than the GameStream endpoint it contacted. Pin both sides to the appliance
  # LAN address so control, RTSP, video and audio all agree on one identity.
  repair_wolf_compose
  PCGA_LAN_IP="$PCGA_LAN_IP" PCGA_STATUS_TLS_PORT=8443 PCGA_MOONLIGHT_WEB_PORT=8101 PCGA_PORTAL_DNS_NAME=pcga.portal /usr/local/sbin/pcga-secure-context-bootstrap
else
  rm -f "$STACK_DIR/compose.moonlight-web.yml"
fi
# The friendly LAN identity is useful even on appliances without Wolf/Moonlight.
# Re-run certificate reconciliation unconditionally so pcga.portal is always a
# valid SAN on the portal certificate.
PCGA_STATUS_TLS_PORT=8443 PCGA_MOONLIGHT_WEB_PORT=8101 PCGA_PORTAL_DNS_NAME=pcga.portal /usr/local/sbin/pcga-secure-context-bootstrap

# Reconcile the read-only portal's browser-stream upstream and TLS settings.
if [[ -f "$STACK_DIR/compose.status.yml" ]]; then
python3 - "$STACK_DIR/compose.status.yml" "$LAN_HTTPS_PORT" <<'PYMOONSTATUS'
from pathlib import Path
import sys
p=Path(sys.argv[1]); lines=p.read_text().splitlines()
# Update/insert environment values.
vals={
 'PCGA_MOONLIGHT_WEB_PORT:':'PCGA_MOONLIGHT_WEB_PORT: "8101"',
 'PCGA_MOONLIGHT_WEB_LANES:':'PCGA_MOONLIGHT_WEB_LANES: "4"',
 'PCGA_MOONLIGHT_WEB_UPSTREAM:':'PCGA_MOONLIGHT_WEB_UPSTREAM: "https://host.docker.internal:8101"',
 'PCGA_TLS_CA_FILE:':'PCGA_TLS_CA_FILE: "/pcga/tls/pcga-ca.crt"',
 'PCGA_STATUS_TLS_PORT:':'PCGA_STATUS_TLS_PORT: "8443"',
 'PCGA_STATUS_TLS_CERT:':'PCGA_STATUS_TLS_CERT: "/pcga/tls/pcga-server.crt"',
 'PCGA_STATUS_TLS_KEY:':'PCGA_STATUS_TLS_KEY: "/pcga/tls/pcga-server.key"',
 'PCGA_PORTAL_DNS_NAME:':'PCGA_PORTAL_DNS_NAME: "pcga.portal"',
 'PCGA_LAN_HTTPS_PORT:':f'PCGA_LAN_HTTPS_PORT: "{sys.argv[2]}"',
}
for key,value in vals.items():
    found=False
    for i,line in enumerate(lines):
        if key in line:
            indent=line[:len(line)-len(line.lstrip())]
            lines[i]=indent+value; found=True; break
    if found: continue
    out=[]; inserted=False
    for line in lines:
        out.append(line)
        if 'PCGA_WOLFDEN_PORT:' in line and not inserted:
            indent=line[:len(line)-len(line.lstrip())]; out.append(indent+value); inserted=True
    if not inserted: raise SystemExit('Could not locate PCGA_WOLFDEN_PORT in compose.status.yml')
    lines=out
# Publish HTTPS portal port immediately after existing 8098 mapping.
if not any('8443:8443' in line for line in lines):
    out=[]; inserted=False
    for line in lines:
        out.append(line)
        if '8098/tcp' in line and not inserted:
            indent=line[:len(line)-len(line.lstrip())]; out.append(indent+'- "8443:8443/tcp"'); inserted=True
    if not inserted: raise SystemExit('Could not locate status port mapping in compose.status.yml')
    lines=out
# Publish the friendly LAN URL on standard HTTPS when port 443 is available.
lan_https_port=int(sys.argv[2])
lines=[line for line in lines if '"443:8443/tcp"' not in line and "'443:8443/tcp'" not in line]
if lan_https_port == 443:
    out=[]; inserted=False
    for line in lines:
        out.append(line)
        if '8443:8443' in line and not inserted:
            indent=line[:len(line)-len(line.lstrip())]; out.append(indent+'- "443:8443/tcp"'); inserted=True
    if not inserted: raise SystemExit('Could not locate HTTPS status port mapping for LAN alias')
    lines=out
# Mount appliance TLS material into the read-only status sidecar.
if not any('/etc/pc-game-archive/tls:/pcga/tls:ro' in line for line in lines):
    out=[]; inserted=False
    for line in lines:
        out.append(line)
        if '$STACK_DIR/status/server.py:/app/server.py:ro' in line and not inserted:
            indent=line[:len(line)-len(line.lstrip())]; out.append(indent+'- "/etc/pc-game-archive/tls:/pcga/tls:ro"'); inserted=True
    if not inserted:
        # Installed compose contains the expanded stack path.
        out=[]
        for line in lines:
            out.append(line)
            if '/status/server.py:/app/server.py:ro' in line and not inserted:
                indent=line[:len(line)-len(line.lstrip())]; out.append(indent+'- "/etc/pc-game-archive/tls:/pcga/tls:ro"'); inserted=True
    if not inserted: raise SystemExit('Could not locate status server volume in compose.status.yml')
    lines=out
p.write_text('\n'.join(lines)+'\n')
PYMOONSTATUS
fi

# Reconcile the NAS before the stack Compose transaction. Mirror mode mounts only
# the backup target; offload mode also generates the read-only active-media overlay.
/usr/local/sbin/pcga-nas-storage reconcile >/var/lib/pc-game-archive/nas/upgrade-reconcile.json 2>/var/lib/pc-game-archive/nas/upgrade-reconcile.err || log "NAS tier is configured but unavailable; local media remains authoritative"

cd "$STACK_DIR"
FILES=(-f compose.yml)
[[ -f compose.jellyfin-gpu.yml ]] && FILES+=(-f compose.jellyfin-gpu.yml)
[[ -f compose.immich.yml ]] && FILES+=(-f compose.immich.yml)
[[ -f compose.romm.yml ]] && FILES+=(-f compose.romm.yml)
[[ -f compose.arm.yml ]] && FILES+=(-f compose.arm.yml)
[[ -f compose.status.yml ]] && FILES+=(-f compose.status.yml)
[[ -f compose.wolf.yml ]] && FILES+=(-f compose.wolf.yml)
[[ -f compose.moonlight-web.yml ]] && FILES+=(-f compose.moonlight-web.yml)
[[ -f compose.game-lan.yml ]] && FILES+=(-f compose.game-lan.yml)
[[ -f compose.nas.yml ]] && FILES+=(-f compose.nas.yml)

# Serialize the complete upgrade-side container transaction with the same lock
# used by pcga-game-stack-start/service-auth. The inherited flag lets bootstrap
# helpers run inside this transaction without deadlocking on their own lock.
GAME_STACK_LOCK=/run/pcga-game-stack-start.lock
exec 8>"$GAME_STACK_LOCK"
if ! flock -w 180 8; then
  die "Timed out waiting for another PCGA game-stack reconciliation to finish"
fi
export PCGA_GAME_STACK_LOCK_HELD=1

compose_up_retry(){
  local out rc attempt
  for attempt in 1 2 3 4 5 6; do
    out="$(mktemp)"
    if docker compose "${FILES[@]}" up "$@" >"$out" 2>&1; then
      rm -f "$out"
      return 0
    else
      rc=$?
    fi
    if grep -Fq 'removal of container' "$out" && grep -Fq 'already in progress' "$out"; then
      log "Docker is still finishing a prior container removal; retrying Compose (${attempt}/6)"
      rm -f "$out"
      sleep $((attempt * 2))
      continue
    fi
    cat "$out" >&2
    rm -f "$out"
    return "$rc"
  done
  die "Docker did not finish the prior container removal after bounded retries"
}

docker compose "${FILES[@]}" config >/dev/null
log "Pulling RomM 5.2.0 + MariaDB images"
docker compose "${FILES[@]}" pull romm romm-db >/dev/null
log "Starting RomM console services"
compose_up_retry -d romm-db romm
log "Reconciling common PCGA appliance credentials"
/usr/local/sbin/pcga-appliance-credentials
if [[ -f compose.moonlight-web.yml ]]; then
  log "Pulling Moonlight Web v3 and starting four independent browser-stream lanes"
  docker compose "${FILES[@]}" pull moonlight-web moonlight-web-2 moonlight-web-3 moonlight-web-4 >/dev/null
  compose_up_retry -d --no-deps --force-recreate pcga-status
  compose_up_retry -d wolf wolf-den moonlight-web moonlight-web-2 moonlight-web-3 moonlight-web-4
  # Lane 1 keeps the existing persistent identity. Lanes 2-4 receive their own
  # volumes/certificates so one portal client can hold several Wolf sessions.
  log "Resetting Moonlight Web streamer workers and reconciling the client pool"
  for lane in 1 2 3 4; do
    container=pcga-moonlight-web
    [[ "$lane" -gt 1 ]] && container="pcga-moonlight-web-$lane"
    docker restart "$container" >/dev/null || die "Unable to restart Moonlight Web lane $lane"
  done
  PCGA_MOONLIGHT_WEB_LANES=4 /usr/local/sbin/pcga-moonlight-web-bootstrap || die "Moonlight Web pool bootstrap failed; inspect: docker logs --tail 150 pcga-moonlight-web"
  for lane in 1 2 3 4; do
    port=$((8100 + lane))
    container=pcga-moonlight-web
    [[ "$lane" -gt 1 ]] && container="pcga-moonlight-web-$lane"
    moon_net="$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$container" 2>/dev/null || true)"
    [[ "$moon_net" == host ]] || die "Moonlight Web lane $lane network mode is '$moon_net', expected host"
    moon_image="$(docker inspect -f '{{.Config.Image}}' "$container" 2>/dev/null || true)"
    [[ "$moon_image" == "mrcreativ3001/moonlight-web-stream:v3.0.0-prerelease.6" ]] || die "Moonlight Web lane $lane image is '$moon_image', expected v3.0.0-prerelease.6"
    moon_bind="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$container" 2>/dev/null | awk -F= '$1=="BIND_ADDRESS"{print $2; exit}')"
    [[ "$moon_bind" == "0.0.0.0:$port" ]] || die "Moonlight Web lane $lane bind address is '$moon_bind', expected 0.0.0.0:$port"
    moon_ssl="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$container" 2>/dev/null | awk -F= '$1=="SSL_CERTIFICATE"{print $2; exit}')"
    [[ "$moon_ssl" == "/pcga-tls/pcga-server.crt" ]] || die "Moonlight Web lane $lane TLS certificate is not configured"
  done
  wolf_internal="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' wolf 2>/dev/null | awk -F= '$1=="WOLF_INTERNAL_IP"{print $2; exit}')"
  [[ "$wolf_internal" == "$PCGA_LAN_IP" ]] || die "Wolf internal IP is '$wolf_internal', expected '$PCGA_LAN_IP'"
  wolf_zero_copy="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' wolf 2>/dev/null | awk -F= '$1=="WOLF_USE_ZERO_COPY"{print $2; exit}')"
  [[ "$wolf_zero_copy" == "FALSE" ]] || die "Wolf zero-copy mode is '$wolf_zero_copy', expected FALSE for the compatibility pipeline"
fi
log "Starting pinned LANCommander and completing game-library bootstrap"
docker compose "${FILES[@]}" pull lancommander >/dev/null
compose_up_retry -d lancommander
if ! /usr/local/sbin/pcga-lancommander-bootstrap; then
  die "LANCommander appliance bootstrap failed; PCGA will not leave PC Games in a half-configured state. Inspect: docker logs --tail 150 lancommander"
fi
if /usr/local/sbin/pcga-romm-bootstrap; then
  compose_up_retry -d --no-deps --force-recreate romm
else
  die "RomM appliance credential reconciliation failed; PCGA will not leave Console Games in a half-configured state. Inspect: docker logs --tail 150 romm"
fi
log "Pulling Immich v3.2.0 images"
docker compose "${FILES[@]}" pull immich-server immich-machine-learning immich-redis immich-database >/dev/null
log "Starting Immich photo services"
compose_up_retry -d immich-database immich-redis immich-machine-learning immich-server
# v0.19.36: an enabled Jellyfin service must not be silently skipped if the
# container has disappeared. Preserve a healthy running instance (and any
# active playback) rather than force-recreating it on every portal upgrade.
JELLYFIN_APP_ENABLED="$(python3 - <<'PY_JF_ENABLED'
import json
from pathlib import Path
path=Path('/etc/pc-game-archive/appliance.json')
try:
    config=json.loads(path.read_text(encoding='utf-8'))
    enabled=config.get('media',{}).get('jellyfin_enabled',True)
except (OSError,ValueError,AttributeError):
    enabled=True
print('true' if enabled is not False else 'false')
PY_JF_ENABLED
)"
JELLYFIN_COMPOSE_DEFINED=false
JELLYFIN_COMPOSE_SERVICES="$(docker compose "${FILES[@]}" config --services)" || die "Unable to list Compose services for Jellyfin startup verification"
if grep -Fxq jellyfin <<<"$JELLYFIN_COMPOSE_SERVICES"; then
  JELLYFIN_COMPOSE_DEFINED=true
fi
if [[ "$JELLYFIN_APP_ENABLED" == true ]]; then
  [[ "$JELLYFIN_COMPOSE_DEFINED" == true ]] || die "Jellyfin is enabled but absent from the installed compose.yml; no media data was changed. Restore the Jellyfin service definition before retrying."
  if [[ "$(docker inspect -f '{{.State.Running}}' jellyfin 2>/dev/null || true)" != true ]]; then
    log "Jellyfin is missing/stopped; reconciling enabled service from Compose"
    compose_up_retry -d --no-deps jellyfin || die "Unable to start Jellyfin; inspect: docker compose logs --tail 100 jellyfin"
  else
    log "Jellyfin is already running; leaving its playback session intact"
  fi
  jellyfin_ready=0
  for ((jf_tries=0;jf_tries<40;jf_tries++)); do
    if [[ "$(docker inspect -f '{{.State.Running}}' jellyfin 2>/dev/null || true)" == true ]] && \
       curl --noproxy '*' -fsS --max-time 3 "http://127.0.0.1:${JELLYFIN_CURRENT}/health" >/dev/null 2>&1; then
      jellyfin_ready=1; break
    fi
    sleep 2
  done
  [[ "$jellyfin_ready" -eq 1 ]] || die "Jellyfin failed its HTTP health check on port $JELLYFIN_CURRENT. Run: docker logs --tail 100 jellyfin; docker compose ps jellyfin"
else
  log "Jellyfin intentionally disabled in appliance settings; no automatic start requested"
fi
if [[ -x /usr/local/sbin/pcga-jellyfin-configure ]]; then
  /usr/local/sbin/pcga-jellyfin-configure --non-interactive --no-restart || log "Jellyfin Photos library will be created on the next authenticated jellyfin-configure run"
  /usr/local/sbin/pcga-jellyfin-appliance-user || log "Jellyfin common PCGA account will retry in the background"
fi
/usr/local/sbin/pcga-immich-bootstrap || log "Immich common PCGA account will retry in the background"
if [[ "$(docker inspect -f '{{.State.Running}}' arm-rippers 2>/dev/null || true)" != true ]]; then
  log "Starting arm-rippers so pcga-status can join its PID namespace"
  docker start arm-rippers >/dev/null || die "Unable to start arm-rippers"
fi
compose_up_retry -d --no-deps --force-recreate pcga-status

# Re-read the exact gateway from the newly recreated status container. If the
# Compose network was created or changed during this upgrade, reconcile both
# host listeners and the status-side upstream URLs, then recreate the sidecar
# once more so the live environment matches the files on disk.
ACTUAL_STATUS_GATEWAY="$(status_network_gateway)"
if [[ -n "$ACTUAL_STATUS_GATEWAY" && "$ACTUAL_STATUS_GATEWAY" != "$CONTROL_BIND" ]]; then
  log "pcga-status network gateway changed to $ACTUAL_STATUS_GATEWAY; reconciling host control routes"
  CONTROL_BIND="$ACTUAL_STATUS_GATEWAY"
  PUBLIC_MEDIA_BIND="$ACTUAL_STATUS_GATEWAY"
  sed -i -E "s/--bind [^ ]+ --port 8100/--bind ${CONTROL_BIND} --port 8100/" /etc/systemd/system/pcga-control.service
  sed -i -E "s/--bind [^ ]+ --port 8099/--bind ${PUBLIC_MEDIA_BIND} --port 8099/" /etc/systemd/system/pcga-public-media.service
  python3 - "$STACK_DIR/compose.status.yml" "$CONTROL_BIND" "$JELLYFIN_CURRENT" <<'PYSTATUSGATEWAY2'
from pathlib import Path
import re, sys
p=Path(sys.argv[1]); gateway=sys.argv[2]; jellyfin_port=sys.argv[3]
lines=p.read_text().splitlines()
svc=None; svc_indent=None
for i,line in enumerate(lines):
    if line.strip()=='pcga-status:':
        svc=i; svc_indent=len(line)-len(line.lstrip()); break
if svc is None: raise SystemExit('compose.status.yml has no pcga-status service')
svc_end=len(lines)
for i in range(svc+1,len(lines)):
    s=lines[i].strip(); ind=len(lines[i])-len(lines[i].lstrip())
    if s and not s.startswith('#') and ind <= svc_indent:
        svc_end=i; break
env=None; env_indent=None; env_end=svc_end
for i in range(svc+1,svc_end):
    if lines[i].strip()=='environment:':
        env=i; env_indent=len(lines[i])-len(lines[i].lstrip()); break
wanted={'PCGA_CONTROL_UPSTREAM':f'http://{gateway}:8100','PCGA_TOOL_HOST':gateway,'PCGA_JELLYFIN_PORT':jellyfin_port,'PCGA_PUBLIC_MEDIA_UPSTREAM':f'http://{gateway}:8099','PCGA_CONTROL_TOKEN_FILE':'/pcga/secrets/control-token'}
if env is None:
    child=' '*(svc_indent+2); grand=' '*(svc_indent+4)
    lines[svc+1:svc+1]=[child+'environment:']+[grand+f'{k}: "{v}"' for k,v in wanted.items()]
else:
    style='mapping'
    for i in range(env+1,svc_end):
        s=lines[i].strip(); ind=len(lines[i])-len(lines[i].lstrip())
        if s and not s.startswith('#') and ind <= env_indent:
            env_end=i; break
        if s and ind > env_indent and s.startswith('- '): style='list'
    body=[line for line in lines[env+1:env_end] if not any(re.match(rf'^(?:-\s*)?{re.escape(k)}(?:\s*:|=)',line.strip()) for k in wanted)]
    indent=' '*(env_indent+2)
    canon=[indent+(f'- {k}={v}' if style=='list' else f'{k}: "{v}"') for k,v in wanted.items()]
    lines[env+1:env_end]=canon+body
p.write_text('\n'.join(lines)+'\n')
PYSTATUSGATEWAY2
  systemctl daemon-reload
  systemctl restart pcga-control.service pcga-public-media.service
  compose_up_retry -d --no-deps --force-recreate pcga-status
fi

# The direct Compose/bootstrap transaction is complete. Release the cross-process
# lock before starting systemd reconciliation, which will acquire the same lock.
unset PCGA_GAME_STACK_LOCK_HELD
flock -u 8 || true
exec 8>&-

systemctl daemon-reload
# Reconcile DHCP-derived identity before any secure/browser/DNS service starts.
# This updates .env atomically, rotates only the leaf certificate when needed,
# reloads already-running TLS containers, and preserves the trusted local CA.
systemctl stop pcga-network-identity.service >/dev/null 2>&1 || true
systemctl start pcga-network-identity.service || die "Dynamic LAN identity reconciliation failed; inspect: journalctl -u pcga-network-identity.service -n 100 --no-pager"
PCGA_LAN_IP="$(awk -F= '$1=="PCGA_LAN_IP"{print substr($0,index($0,"=")+1)}' "$STACK_DIR/.env" | tail -n1)"
systemctl restart pcga-control.service || die "Unable to restart PCGA control plane"
systemctl restart pcga-thin-client-bootstrap.service || die "Unable to start LAN-only thin-client bootstrap service"
# Publish pcga.local through mDNS and pcga.portal through a LAN-bound DNS
# forwarder. Never install or enable a DHCP server; LAN DHCP remains router-owned.
/usr/local/sbin/pcga-lan-dns configure >/dev/null
systemctl enable --now avahi-daemon.service >/dev/null 2>&1 || log "Avahi could not be enabled; pcga.local fallback may be unavailable"
systemctl restart avahi-daemon.service >/dev/null 2>&1 || true
if systemctl restart pcga-lan-dns.service >/dev/null 2>&1; then
  log "LAN DNS service is answering pcga.portal"
else
  log "LAN DNS service could not bind port 53. If this host already runs DNS, add a local record pcga.portal -> $PCGA_LAN_IP there instead."
fi
LAN_IFACE="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')"
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active' && [[ -n "$LAN_IFACE" ]]; then
  ufw allow in on "$LAN_IFACE" to any port 53 proto udp comment 'PCGA LAN DNS' >/dev/null 2>&1 || true
  ufw allow in on "$LAN_IFACE" to any port 53 proto tcp comment 'PCGA LAN DNS' >/dev/null 2>&1 || true
  if [[ "$LAN_HTTPS_PORT" == 443 ]]; then ufw allow in on "$LAN_IFACE" to any port 443 proto tcp comment 'PCGA portal' >/dev/null 2>&1 || true; fi
fi
systemctl enable pcga-game-stack.service >/dev/null 2>&1 || true
# Reset the oneshot active state on upgrade so the new startup sequence runs now.
systemctl stop pcga-game-stack.service >/dev/null 2>&1 || true
systemctl start pcga-game-stack.service || die "Game stack startup sequence failed; inspect: journalctl -u pcga-game-stack.service -n 150 --no-pager"
systemctl enable --now pcga-service-auth.timer >/dev/null 2>&1 || true
systemctl start pcga-service-auth.service >/dev/null 2>&1 || true
systemctl enable --now pcga-game-orchestrator.timer >/dev/null 2>&1 || true
systemctl enable --now pcga-heroic-sync.timer >/dev/null 2>&1 || true
systemctl enable --now pcga-store-ingest.timer >/dev/null 2>&1 || log "Store-ingest timer could not be enabled"
systemctl start --no-block pcga-store-ingest.service >/dev/null 2>&1 || true
systemctl enable --now pcga-store-jobs.service >/dev/null 2>&1 || die "Unable to start persistent PC-store acquisition queue"
# Index any existing Heroic data without downloading the launcher during upgrade.
/usr/local/sbin/pcga-heroic-sync --reconcile-wolf >/dev/null 2>&1 || log "Heroic integration staged; launcher will be prepared on first use"
log "PC-store accounts remain available for all three providers; Epic + GOG acquisition queues staged; backends stay lazy until requested"

# A terminally failed pre-v0.18.53 Wolf child can remain alive only because its
# compositor/grace shell is still running.  Such a disposable desktop blocks the
# canonical Wolf reload for every game.  Remove only containers whose own logs
# prove that the Wine launcher has already entered a terminal failure path.
if command -v docker >/dev/null 2>&1; then
  while IFS= read -r cid; do
    [[ -n "$cid" ]] || continue
    runtime_log="$(docker logs --tail 120 "$cid" 2>&1 || true)"
    if grep -Eq 'installer failed; terminating stale Wine helpers|installer failed; exiting transient setup container|primary Wine launch failed; terminating stale prefix helpers|Wine debugger detected after an unhandled game exception|detached Wine process crashed; debugger detected|Wine stayed alive without mapping a game window|no game window appeared after launcher hand-off' <<<"$runtime_log"; then
      name="$(docker inspect -f '{{.Name}}' "$cid" 2>/dev/null | sed 's#^/##' || true)"
      log "Removing terminally failed transient PCGA runtime ${name:-$cid}"
      docker rm -f "$cid" >/dev/null 2>&1 || true
    fi
  done < <(docker ps -q --filter 'name=PCGA-' 2>/dev/null || true)
fi

# v0.19.3 does not change the COD2/Wine/CDEmu runtime.  Keep generated game
# images, prefixes and Wolf registrations intact; the general local reconciliation
# below remains safe for catalog/permission repair without forcing a COD2 rebuild.

# Repair logical identity on already-ingested images synchronously before the
# portal is validated.  This is bounded/local-only; installation and network
# metadata enrichment continue asynchronously through the service.
/usr/local/sbin/pcga-game-orchestrator --metadata-only --no-network --force >/dev/null 2>&1 || true

# v0.18.38 could leave root-copied optical payload directories unreadable to
# Wolf's uid 1000 even though the catalog itself was READY. Repair only mutable
# installed templates here; preserved disc images/inbox artifacts remain untouched.
INSTALLED_ROOT="$ROOT/games/installed"
if [[ -d "$INSTALLED_ROOT" ]]; then
  find "$INSTALLED_ROOT" -type d -exec chmod a+rx {} + 2>/dev/null || true
  find "$INSTALLED_ROOT" -type f -exec chmod a+r {} + 2>/dev/null || true
fi

# Run one local/no-network orchestration pass synchronously so executable
# re-selection, duplicate-canonical repair, setup-root restaging and runtime
# permission normalization are complete before the user reopens PC Games.
if ! /usr/local/sbin/pcga-game-orchestrator --no-network --force; then
  log "Local PC-game repair pass reported one or more unresolved titles; preserved media was retained and the periodic orchestrator will retry"
fi
systemctl --no-block start pcga-game-orchestrator.service >/dev/null 2>&1 || true
[[ -x /usr/local/sbin/pcga-extra-prune ]] || die "Installed extras pruning helper is missing"
[[ -x /usr/local/sbin/pcga-stream-prune ]] || die "Installed stream-aware pruning helper is missing"
python3 -W error::SyntaxWarning -m py_compile /usr/local/sbin/pcga-stream-prune || die "Installed stream-aware pruning helper failed syntax verification"
python3 -W error::SyntaxWarning -m py_compile /usr/local/sbin/pcga-extra-prune || die "Installed extras pruning helper failed syntax verification"
log "Running v$VERSION validation"
bash -n /usr/local/sbin/pcga-arm-configure
python3 -W error::SyntaxWarning -m py_compile /usr/local/sbin/pcga-disc-structure
bash -n /usr/local/sbin/pcga-arm-rip
bash -n /usr/local/sbin/pcga-optical-dispatch
bash -n /usr/local/sbin/pcga-optical-watch
bash -n /usr/local/sbin/pcga-pc-disc-rip
bash -n /usr/local/sbin/pcga-optical-health
python3 -W error::SyntaxWarning -m py_compile /usr/local/sbin/pcga-optical-identify /usr/local/sbin/pcga-game-disc-metadata /usr/local/sbin/pcga-game-intake /usr/local/sbin/pcga-game-orchestrator /usr/local/sbin/pcga-game-compat-resolver /usr/local/sbin/pcga-media-disc-metadata /usr/local/sbin/pcga-media-intake
bash -n /usr/local/sbin/pcga-appliance-credentials
bash -n /usr/local/sbin/pcga-romm-bootstrap
bash -n /usr/local/sbin/pcga-immich-bootstrap
bash -n /usr/local/sbin/pcga-jellyfin-appliance-user
bash -n /usr/local/sbin/pcga-game-stack-start
bash -n /usr/local/sbin/pcga-service-auth
bash -n /usr/local/sbin/pcga-secure-context-bootstrap
bash -n /usr/local/sbin/pcga-network-identity
bash -n /usr/local/sbin/pcga-tailscale-remote
python3 -m py_compile /usr/local/sbin/pcga-netbird-remote /usr/local/sbin/pcga-zerotier-remote
bash -n /usr/local/sbin/pcga-lan-dns
python3 -W error::SyntaxWarning -m py_compile /usr/local/sbin/pcga-store-compat
python3 -m py_compile /usr/local/sbin/pcga-low-loss-tier /usr/local/sbin/pcga-low-loss-encode
python3 -W error::SyntaxWarning -m py_compile /usr/local/sbin/pcga-nas-discover /usr/local/sbin/pcga-steam-native /usr/local/sbin/pcga-thin-client-bootstrap /usr/local/sbin/pcga-nas-storage /usr/local/sbin/pcga-control /usr/local/sbin/pcga-heroic-sync /usr/local/sbin/pcga-store-provider /usr/local/sbin/pcga-store-jobs /usr/local/sbin/pcga-store-ingest
systemd-analyze verify /etc/systemd/system/pcga-network-identity.service /etc/systemd/system/pcga-game-stack.service /etc/systemd/system/pcga-thin-client-bootstrap.service /etc/systemd/system/pcga-nas-mount.service /etc/systemd/system/pcga-nas-sync.service /etc/systemd/system/pcga-nas-sync.timer /etc/systemd/system/pcga-lan-dns.service /etc/systemd/system/pcga-store-bootstrap.service /etc/systemd/system/pcga-store-jobs.service /etc/systemd/system/pcga-store-ingest.service /etc/systemd/system/pcga-store-umu.service /etc/systemd/system/pcga-store-ingest.timer >/dev/null 2>&1 || true
# The CA is public material. Host users must be able to traverse the TLS directory
# and read it without gaining access to either private key.
[[ -r /etc/pc-game-archive/tls/pcga-ca.crt ]] || die "PCGA CA certificate is missing"
[[ "$(stat -c '%a' /etc/pc-game-archive/tls)" == 751 ]] || die "PCGA TLS directory must be mode 0751"
[[ "$(stat -c '%a' /etc/pc-game-archive/tls/pcga-ca.crt)" == 644 ]] || die "PCGA CA certificate must be mode 0644"
[[ "$(stat -c '%a' /etc/pc-game-archive/tls/pcga-ca.key)" == 600 ]] || die "PCGA CA private key must remain mode 0600"
if [[ -r "$BACKUP/etc/pc-game-archive/tls/pcga-ca.crt" ]] && openssl x509 -in "$BACKUP/etc/pc-game-archive/tls/pcga-ca.crt" -noout -text 2>/dev/null | grep -q 'CA:TRUE'; then
  old_ca_fp="$(openssl x509 -in "$BACKUP/etc/pc-game-archive/tls/pcga-ca.crt" -noout -fingerprint -sha256 | sed 's/.*=//;s/://g')"
  new_ca_fp="$(openssl x509 -in /etc/pc-game-archive/tls/pcga-ca.crt -noout -fingerprint -sha256 | sed 's/.*=//;s/://g')"
  [[ "$old_ca_fp" == "$new_ca_fp" ]] || die "PCGA trusted local CA changed unexpectedly; refusing to invalidate already-trusted secure clients"
fi
openssl x509 -in /etc/pc-game-archive/tls/pcga-server.crt -noout -ext subjectAltName 2>/dev/null | grep -Fq 'DNS:pcga.portal' || die "PCGA portal certificate is missing the pcga.portal DNS SAN"
CURRENT_LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
[[ -n "$CURRENT_LAN_IP" ]] || CURRENT_LAN_IP="$PCGA_LAN_IP"
[[ "$PCGA_LAN_IP" == "$CURRENT_LAN_IP" ]] || die "Persisted PCGA_LAN_IP is '$PCGA_LAN_IP', current DHCP address is '$CURRENT_LAN_IP'"
openssl x509 -in /etc/pc-game-archive/tls/pcga-server.crt -noout -ext subjectAltName 2>/dev/null | grep -Fq "IP Address:${CURRENT_LAN_IP}" || die "PCGA portal certificate is missing current DHCP address ${CURRENT_LAN_IP}"
if systemctl is-active --quiet pcga-lan-dns.service; then
  /usr/local/sbin/pcga-lan-dns test >/dev/null || die "PCGA LAN DNS service is active but pcga.portal did not resolve"
fi
if [[ "$LAN_HTTPS_PORT" == 443 ]]; then
  curl --resolve "pcga.portal:443:${PCGA_LAN_IP}" --cacert /etc/pc-game-archive/tls/pcga-ca.crt -fsS --max-time 8 https://pcga.portal/health >/dev/null || die "Friendly HTTPS portal is not reachable as https://pcga.portal/"
fi
bash -n /usr/local/sbin/pcga-moonlight-web-bootstrap
bash -n /usr/local/sbin/pcga-jellyfin-appliance-user
bash -n /usr/local/sbin/pcga-lancommander-bootstrap
[[ -s /etc/pc-game-archive/secrets/appliance-admin.env ]] || die "Common appliance credential was not created"
python3 - /etc/pc-game-archive/secrets/appliance-admin.env /etc/pc-game-archive/secrets/romm-bootstrap.env /etc/pc-game-archive/secrets/lancommander-bootstrap.env <<'PY_COMMON_CREDS'
from pathlib import Path
import sys
def read(p):
    out={}
    for line in Path(p).read_text().splitlines():
        if '=' in line:
            k,v=line.split('=',1); out[k]=v
    return out
common,romm,lan=map(read,sys.argv[1:])
assert common.get('PCGA_APPLIANCE_ADMIN_USER')
assert common.get('PCGA_APPLIANCE_ADMIN_PASSWORD')
assert romm.get('PCGA_ROMM_ADMIN_USER') == common['PCGA_APPLIANCE_ADMIN_USER']
assert romm.get('PCGA_ROMM_ADMIN_PASSWORD') == common['PCGA_APPLIANCE_ADMIN_PASSWORD']
assert lan.get('PCGA_LANCOMMANDER_ADMIN_USER') == common['PCGA_APPLIANCE_ADMIN_USER']
assert lan.get('PCGA_LANCOMMANDER_ADMIN_PASSWORD') == common['PCGA_APPLIANCE_ADMIN_PASSWORD']
PY_COMMON_CREDS
grep -Fq 'mapfile -t secure_identity_fields' /usr/local/sbin/pcga-network-identity || die "Dynamic LAN identity parser hotfix is missing"
systemctl is-enabled pcga-network-identity.service >/dev/null 2>&1 || die "PCGA dynamic LAN identity service is not enabled"
systemctl is-active pcga-network-identity.service >/dev/null 2>&1 || die "PCGA dynamic LAN identity service did not complete successfully"
systemctl is-enabled pcga-game-stack.service >/dev/null 2>&1 || die "PCGA game-stack startup service is not enabled"
systemctl is-enabled pcga-thin-client-bootstrap.service >/dev/null 2>&1 || die "PCGA thin-client bootstrap service is not enabled"
systemctl is-active pcga-thin-client-bootstrap.service >/dev/null 2>&1 || die "PCGA thin-client bootstrap service is not active"
systemctl is-active pcga-game-stack.service >/dev/null 2>&1 || die "PCGA game-stack startup service did not complete successfully"
[[ "$(cat /var/lib/pc-game-archive/bootstrap/lancommander.state 2>/dev/null || true)" == ready ]] || die "LANCommander bootstrap state is not ready after reconciliation"
LC_GAME_LAN_IP="$(docker inspect -f '{{with index .NetworkSettings.Networks "legacy-games"}}{{.IPAddress}}{{end}}' lancommander 2>/dev/null || true)"
[[ -n "$LC_GAME_LAN_IP" ]] || die "LANCommander is not attached to the shared legacy-games network"
grep -Eq '"NetworkMode"[[:space:]]*:[[:space:]]*"legacy-games"' /usr/local/sbin/pcga-game-orchestrator || die "Wolf PC-game runners are not configured for the shared legacy-games network"
grep -Fq 'PCGA_IPX_RELAY_HOST=lancommander' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runners are missing LANCommander IPX relay discovery variables"
systemctl is-enabled pcga-service-auth.timer >/dev/null 2>&1 || die "PCGA service authentication timer is not enabled"
if [[ -f "$STACK_DIR/compose.moonlight-web.yml" ]]; then
  lane=0
  for port in 8101 8102 8103 8104; do
    lane=$((lane+1))
    curl --cacert /etc/pc-game-archive/tls/pcga-ca.crt -fsS --max-time 5 "https://127.0.0.1:${port}/" >/dev/null || die "Moonlight Web browser client is not HTTPS-ready on port $port"
    container=pcga-moonlight-web; [[ $lane -gt 1 ]] && container="pcga-moonlight-web-$lane"
    nat_ip="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$container" 2>/dev/null | awk -F= '$1=="WEBRTC_NAT_1TO1_HOST"{print $2; exit}')"
    [[ "$nat_ip" == "$CURRENT_LAN_IP" ]] || die "Moonlight Web lane $lane advertises stale WebRTC address '$nat_ip', expected '$CURRENT_LAN_IP'"
  done
  curl --cacert /etc/pc-game-archive/tls/pcga-ca.crt -fsS --max-time 5 https://127.0.0.1:8443/health >/dev/null || die "PCGA secure portal is not HTTPS-ready on port 8443"
  moon_state="$(python3 - <<'PY'
import json
try: print(json.load(open('/var/lib/pc-game-archive/bootstrap/moonlight-web.json')).get('state',''))
except Exception: print('')
PY
)"
  [[ "$moon_state" == ready ]] || die "Moonlight Web automatic Wolf pairing did not become ready (state: '$moon_state'). Inspect: sudo /usr/local/sbin/pcga-moonlight-web-bootstrap"
fi
bash -n /usr/local/sbin/pcga-arm-rip
bash -n /usr/local/sbin/pcga-media-sort
python3 -W error::SyntaxWarning -m py_compile /usr/local/sbin/pcga-ingest-reconcile
bash -n /usr/local/sbin/pcga-metadata-classify
python3 -W error::SyntaxWarning -m py_compile /usr/local/sbin/pcga-classify
python3 -W error::SyntaxWarning -m py_compile /usr/local/sbin/pcga-manual-review
python3 -W error::SyntaxWarning -m py_compile /usr/local/sbin/pcga-public-media

romm_ok=0
for _ in $(seq 1 60); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:${ROMM_PORT}/" || true)"
  case "$code" in 200|301|302|303|307|308) romm_ok=1; break;; esac
  sleep 2
done
[[ $romm_ok -eq 1 ]] || die "RomM did not become reachable on port $ROMM_PORT; inspect: docker logs --tail 150 romm"
python3 - /etc/pc-game-archive/romm.env /etc/pc-game-archive/appliance.json <<'PYROMMVALIDATE'
from pathlib import Path
import json, sys
envp=Path(sys.argv[1]); cfgp=Path(sys.argv[2])
actual={}
for raw in envp.read_text().splitlines():
    line=raw.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    key,val=line.split('=',1)
    actual[key.strip()]=val
games={}
try:
    raw=json.loads(cfgp.read_text()) if cfgp.exists() else {}
    if isinstance(raw, dict) and isinstance(raw.get('games'), dict): games=raw['games']
except Exception:
    games={}
def as_bool(value, default=True):
    return value if isinstance(value, bool) else default
def clamp_int(value, lo, hi, default):
    try: n=int(value)
    except (TypeError, ValueError): return default
    return max(lo, min(hi, n))
watch_seconds=clamp_int(games.get('watch_debounce_seconds'),30,3600,300)
cron=str(games.get('scheduled_rescan') or '25 3 * * *').strip()
if len(cron)>80 or any(c in cron for c in '\n\r\0'): cron='25 3 * * *'
expected={
    'HASHEOUS_API_ENABLED':'true' if as_bool(games.get('metadata_hasheous'),True) else 'false',
    'PLAYMATCH_API_ENABLED':'true' if as_bool(games.get('metadata_playmatch'),True) else 'false',
    'DISABLE_EMULATOR_JS':'false',
    'DISABLE_RUFFLE_RS':'false',
    'ENABLE_RESCAN_ON_FILESYSTEM_CHANGE':'true' if as_bool(games.get('filesystem_watch'),True) else 'false',
    'RESCAN_ON_FILESYSTEM_CHANGE_DELAY':str(max(1,watch_seconds//60)),
    'ENABLE_SCHEDULED_RESCAN':'true',
    'SCHEDULED_RESCAN_CRON':cron,
}
wrong=[]
for key,val in expected.items():
    got=actual.get(key)
    if got != val: wrong.append(f'{key}: expected {val!r}, got {got!r}')
if wrong:
    raise SystemExit('RomM appliance configuration mismatch: '+'; '.join(wrong))
print(f"RomM filesystem rescan delay validated at {expected['RESCAN_ON_FILESYSTEM_CHANGE_DELAY']} minute(s)")
PYROMMVALIDATE
grep -Fq 'roms_folder: "roms"' "$ROOT/romm/config/config.yml" || die "RomM config is missing PCGA ROM folder mapping"
grep -Fq 'firmware_folder: "bios"' "$ROOT/romm/config/config.yml" || die "RomM config is missing PCGA firmware folder mapping"

immich_ok=0
for _ in $(seq 1 60); do
  if curl -fsS --max-time 3 "http://127.0.0.1:${IMMICH_PORT}/api/server/ping" 2>/dev/null | grep -q 'pong'; then immich_ok=1; break; fi
  sleep 2
done
[[ $immich_ok -eq 1 ]] || die "Immich did not become healthy on port $IMMICH_PORT; inspect: docker logs --tail 100 immich_server"
python3 -W error::SyntaxWarning -m py_compile "$STATUS_DIR/server.py"
systemd-analyze verify \
  /etc/systemd/system/pcga-media-sort.service \
  /etc/systemd/system/pcga-media-sort.path \
  /etc/systemd/system/pcga-media-sort.timer \
  /etc/systemd/system/pcga-metadata-classify.service \
  /etc/systemd/system/pcga-metadata-classify.path \
  /etc/systemd/system/pcga-metadata-classify.timer \
  /etc/systemd/system/pcga-public-media.service \
  /etc/systemd/system/pcga-optical-watch.service \
  /etc/systemd/system/pcga-optical-dispatch@.service \
  /etc/systemd/system/pcga-pc-disc-rip@.service >/dev/null 2>&1 || true

systemctl daemon-reload
systemctl disable --now pcga-arm-watch.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/multi-user.target.wants/pcga-arm-watch.service /etc/systemd/system/pcga-arm-watch.service 2>/dev/null || true
systemctl daemon-reload
if python3 - <<'PY_AUTORIP'
import json
try:
    d=json.load(open('/etc/pc-game-archive/appliance.json'))
    raise SystemExit(0 if bool((d.get('ingest') or {}).get('auto_rip',True)) else 1)
except Exception:
    raise SystemExit(0)
PY_AUTORIP
then
  systemctl enable --now pcga-optical-watch.service >/dev/null
else
  systemctl disable --now pcga-optical-watch.service >/dev/null 2>&1 || true
fi
[[ ! -e /etc/systemd/system/pcga-arm-watch.service ]] || die "Legacy pcga-arm-watch.service still exists after optical-dispatch migration"
if python3 - <<'PY_AUTORIP_VALIDATE'
import json
try:
    d=json.load(open('/etc/pc-game-archive/appliance.json'))
    raise SystemExit(0 if bool((d.get('ingest') or {}).get('auto_rip',True)) else 1)
except Exception:
    raise SystemExit(0)
PY_AUTORIP_VALIDATE
then
  systemctl is-enabled --quiet pcga-optical-watch.service || die "Auto ingest is enabled but pcga-optical-watch.service is not enabled"
  systemctl is-active --quiet pcga-optical-watch.service || die "Auto ingest is enabled but pcga-optical-watch.service is not active"
else
  if systemctl is-enabled --quiet pcga-optical-watch.service 2>/dev/null; then
    die "Auto ingest is disabled but pcga-optical-watch.service is still enabled"
  fi
fi

for unit in pcga-media-sort.path pcga-media-sort.timer pcga-metadata-classify.path pcga-metadata-classify.timer; do
  systemctl is-enabled --quiet "$unit" || die "$unit is not enabled"
  systemctl is-active --quiet "$unit" || die "$unit is not active"
done

# Catch up immediately. If an optical rip is active, media-sort safely leaves
# shared ARM staging alone but still kicks classification for isolated pending
# items. The recurring timer will retry staging after ARM becomes idle.
systemctl start pcga-media-sort.service || true
systemctl start pcga-metadata-classify.service || true
/usr/local/sbin/pcga-ingest-reconcile audit || true

ok=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS --max-time 2 http://127.0.0.1:8098/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
[[ $ok -eq 1 ]] || die "Portal did not return healthy after v$VERSION upgrade; inspect: docker logs --tail 100 pcga-status"
curl -fsS --max-time 3 http://127.0.0.1:8093/health >/dev/null || die "Thin-client bootstrap health check failed on :8093"
api_ver="$(curl -fsS --max-time 3 http://127.0.0.1:8098/api/status | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))')"
[[ "$api_ver" == "$VERSION" ]] || die "Portal API version is '$api_ver', expected '$VERSION'"
portal_html="$(curl -fsS --max-time 5 http://127.0.0.1:8098/ || true)"
grep -Fq "const PORTAL_BUILD_VERSION='$VERSION'" <<<"$portal_html" || die "Portal HTML is stale after recreate; expected build $VERSION. Inspect pcga-status mount/container."
# Validate stable PC Games browser hooks rather than incidental display copy.
# v0.19.18 renamed the description while retaining the actual UI.
for game_ui_marker in 'function renderPcGameBrowser(' 'id="pcga-combined-game-grid"' 'id="pcga-steam-source-filters"'; do
  grep -Fq "$game_ui_marker" <<<"$portal_html" || die "Portal HTML is missing PC Games UI hook: $game_ui_marker"
done
docker exec pcga-status grep -Fq "VERSION = \"$VERSION\"" /app/server.py 2>/dev/null || die "pcga-status container is not executing v$VERSION server.py"

# Validate the exact LANCommander path used by the portal, not merely the host
# bootstrap state.  v0.17.20 could finish with lancommander.state=ready while
# pcga-status still could not discover/read the catalog database.
lc_health="$(mktemp)"
lc_ok=0
for _ in $(seq 1 15); do
  code="$(curl -sS --max-time 5 -o "$lc_health" -w '%{http_code}' http://127.0.0.1:8098/api/pc-games/health 2>/dev/null || true)"
  if [[ "$code" == "200" ]] && python3 - "$lc_health" <<'PYLCHEALTH' >/dev/null 2>&1
import json,sys
with open(sys.argv[1], encoding='utf-8') as fh:
    d=json.load(fh)
raise SystemExit(0 if d.get('service_ready') is True and d.get('catalog_db_readable') is True else 1)
PYLCHEALTH
  then
    lc_ok=1
    break
  fi
  sleep 1
done
if [[ $lc_ok -ne 1 ]]; then
  lc_detail="$(python3 - "$lc_health" <<'PYLCDETAIL' 2>/dev/null || true
import json,sys
try:
    with open(sys.argv[1], encoding='utf-8') as fh: d=json.load(fh)
    print(d.get('detail') or 'LANCommander portal health endpoint did not report a catalog')
    disc=d.get('discovery') or {}
    if disc.get('candidates'):
        print('candidates='+json.dumps(disc.get('candidates'), separators=(',',':')))
except Exception:
    print('LANCommander portal health endpoint did not return valid JSON')
PYLCDETAIL
)"
  rm -f "$lc_health"
  die "PC Games portal bridge is not healthy: ${lc_detail}. Check: curl -sS http://127.0.0.1:8098/api/pc-games/health ; docker logs --tail 150 lancommander ; docker logs --tail 150 pcga-status"
fi
rm -f "$lc_health"
log "PC Games LANCommander catalog bridge validated end-to-end"

# A listening RomM port is not sufficient for Console Games.  If PCGA owns the
# RomM service identity, require the complete portal-native emulation path before
# calling the upgrade healthy: heartbeat -> EmulatorJS enabled -> OAuth ->
# platforms API -> EmulatorJS loader asset.
ROMM_BOOTSTRAP_STATE="$(cat /var/lib/pc-game-archive/bootstrap/romm.state 2>/dev/null || true)"
if [[ "$ROMM_BOOTSTRAP_STATE" == "ready" ]]; then
  emulator_health="$(mktemp)"
  emulator_ok=0
  for _ in $(seq 1 30); do
    code="$(curl -sS --max-time 6 -o "$emulator_health" -w '%{http_code}' 'http://127.0.0.1:8098/api/games/health?refresh=1' 2>/dev/null || true)"
    if [[ "$code" == "200" ]] && python3 - "$emulator_health" <<'PYHEALTH' >/dev/null 2>&1
import json, sys
with open(sys.argv[1], encoding='utf-8') as fh:
    data=json.load(fh)
raise SystemExit(0 if data.get('available') is True else 1)
PYHEALTH
    then
      emulator_ok=1
      break
    fi
    sleep 2
  done
  if [[ $emulator_ok -ne 1 ]]; then
    emulator_detail="$(python3 - "$emulator_health" <<'PYDETAIL' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1], encoding='utf-8') as fh:
        data=json.load(fh)
    print(data.get('detail') or 'unknown emulator pipeline failure')
except Exception:
    print('portal emulator health endpoint did not return valid JSON')
PYDETAIL
)"
    rm -f "$emulator_health"
    die "Console Games emulator pipeline is not healthy: ${emulator_detail}. Check: curl -sS http://127.0.0.1:8098/api/games/health?refresh=1 ; docker logs --tail 150 romm ; docker logs --tail 150 pcga-status"
  fi
  rm -f "$emulator_health"
  log "Console Games emulator pipeline validated end-to-end"
else
  die "RomM bootstrap state is '${ROMM_BOOTSTRAP_STATE:-missing}', expected 'ready'. PCGA must own a verified appliance identity before Console Games can be considered healthy."
fi
curl -fsS --max-time 3 http://127.0.0.1:8098/review/health >/dev/null || die "Manual review proxy health check failed"
curl -fsS --max-time 5 http://127.0.0.1:8098/api/review/items | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("ok") is True and isinstance(d.get("items"),list)' || die "Portal-native Manual Review API is unavailable"
log "Portal-native Manual Review bridge validated"
curl -fsS --max-time 5 "http://${PUBLIC_MEDIA_BIND}:8099/health" >/dev/null || die "Public media importer is not reachable on Docker host gateway ${PUBLIC_MEDIA_BIND}:8099"
docker exec pcga-status python3 -c "import urllib.request; print(urllib.request.urlopen('http://${PUBLIC_MEDIA_BIND}:8099/health', timeout=3).read().decode())" >/dev/null || die "pcga-status cannot reach public-media on ${PUBLIC_MEDIA_BIND}:8099"
docker exec pcga-status python3 -c "import urllib.request; print(urllib.request.urlopen('http://${CONTROL_BIND}:8100/health', timeout=3).read().decode())" >/dev/null || die "pcga-status cannot reach pcga-control on ${CONTROL_BIND}:8100"
STATUS_CONTROL_UPSTREAM="$(docker inspect pcga-status --format '{{range .Config.Env}}{{println .}}{{end}}' | awk -F= '$1=="PCGA_CONTROL_UPSTREAM"{print $2; exit}')"
[[ "$STATUS_CONTROL_UPSTREAM" == "http://${CONTROL_BIND}:8100" ]] || die "pcga-status runtime PCGA_CONTROL_UPSTREAM is '${STATUS_CONTROL_UPSTREAM:-missing}', expected http://${CONTROL_BIND}:8100"
docker exec pcga-status test -r /pcga/secrets/control-token || die "pcga-status cannot read the mounted control token"
STATUS_JELLYFIN_HOST="$(docker inspect pcga-status --format '{{range .Config.Env}}{{println .}}{{end}}' | awk -F= '$1=="PCGA_TOOL_HOST"{print $2; exit}')"
[[ "$STATUS_JELLYFIN_HOST" == "$CONTROL_BIND" ]] || die "pcga-status Jellyfin upstream host is '${STATUS_JELLYFIN_HOST:-missing}', expected $CONTROL_BIND"
STATUS_JELLYFIN_PORT="$(docker inspect pcga-status --format '{{range .Config.Env}}{{println .}}{{end}}' | awk -F= '$1=="PCGA_JELLYFIN_PORT"{print $2; exit}')"
[[ "$STATUS_JELLYFIN_PORT" == "$JELLYFIN_CURRENT" ]] || die "pcga-status Jellyfin port is '${STATUS_JELLYFIN_PORT:-missing}', expected $JELLYFIN_CURRENT"
curl -fsS --max-time 3 http://127.0.0.1:8098/api/control/state >/dev/null || die "Portal cannot proxy the PCGA control plane"
curl -fsS --max-time 4 'http://127.0.0.1:8098/api/control/game-activity?limit=1' | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("ok") is True and isinstance(d.get("items"),list)' || die "Portal cannot read persistent game activity history"
# Diagnostics intentionally requires HTTPS (the HTTP endpoint responds 426).
# Check it exactly once over the secure portal; validate the Jellyfin profile
# from that same response, not an insecure request to port 8098.
diagnostics_response="$(mktemp)"
if ! diagnostics_code="$(curl --cacert /etc/pc-game-archive/tls/pcga-ca.crt -sS --connect-timeout 4 --max-time 12 \
  -o "$diagnostics_response" -w '%{http_code}' https://127.0.0.1:8443/api/diagnostics/catalog)"; then
  rm -f "$diagnostics_response"
  die "Unable to fetch HTTPS Diagnostics catalog. Verify PCGA CA and https://127.0.0.1:8443/health (do not use HTTP port 8098 for Diagnostics)."
fi
if [[ "$diagnostics_code" != 200 ]]; then
  diagnostics_detail="$(python3 - "$diagnostics_response" <<'PY_DIAGNOSTICS_ERROR'
import json,sys
try:
    with open(sys.argv[1],encoding='utf-8') as fh: data=json.load(fh)
    print(str(data.get('detail') or data.get('error') or 'no error detail')[:240] if isinstance(data,dict) else 'unexpected response body')
except (OSError,ValueError):
    print('non-JSON response')
PY_DIAGNOSTICS_ERROR
)"
  rm -f "$diagnostics_response"
  die "HTTPS Diagnostics catalog returned HTTP $diagnostics_code: $diagnostics_detail"
fi
if ! python3 "$COMP/pcga-upgrade-diagnostics-check" "$diagnostics_response" "$JELLYFIN_APP_ENABLED"; then
  rm -f "$diagnostics_response"
  die "HTTPS Diagnostics catalog is invalid or missing required services; inspect secure portal Diagnostics and pcga-control logs"
fi
rm -f "$diagnostics_response"
log "HTTPS Diagnostics catalog and Media profile validated"
# The host Jellyfin health probe is insufficient if status-sidecar networking
# cannot reach the host-mapped Jellyfin endpoint (Movies & TV would still fail).
if [[ "$JELLYFIN_APP_ENABLED" == true ]]; then
  curl -fsS --max-time 7 http://127.0.0.1:8098/api/jellyfin/health | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("reachable") is True, d.get("detail")' || die "Movies & TV portal cannot reach Jellyfin even though the host port responds; check pcga-status PCGA_TOOL_HOST and PCGA_JELLYFIN_PORT"
fi
grep -Fq 'service_log(service_id' /usr/local/sbin/pcga-control || die "PCGA control plane is missing bounded service-log retrieval"
grep -Fq '_redact_log_text' /usr/local/sbin/pcga-control || die "PCGA control plane is missing browser-log credential redaction"
curl -fsS --max-time 5 http://127.0.0.1:8098/public-media/health >/dev/null || die "Public media proxy health check failed"
curl -fsS --max-time 5 http://127.0.0.1:8098/api/games/collection/platforms | python3 -c 'import json,sys; d=json.load(sys.stdin); assert any(x.get("slug")=="nes" for x in d.get("items",[]))' || die "Portal ROM Collection platform endpoint is unavailable"
portal_check="$(mktemp)"
trap 'rm -f "$portal_check"' EXIT
curl -fsS --max-time 3 http://127.0.0.1:8098/ >"$portal_check" || die "Unable to fetch portal UI"
grep -Fq 'id="setting-clock-face"' "$portal_check" || die "Portal UI is missing analog clock-face selector"
grep -Fq '<option value="roman">Roman</option>' "$portal_check" || die "Portal UI is missing Roman clock face"
grep -Fq '<option value="railway">Railway</option>' "$portal_check" || die "Portal UI is missing Railway clock face"
grep -Eq '\.background-video(,\.background-photo)?\{position:fixed;inset:0;width:100%;height:100%;object-fit:cover;z-index:0' "$portal_check" || die "Portal UI is missing repaired background stacking"
grep -Fq 'browser-compatible H.264/AAC MP4 stream' "$portal_check" || die "Portal UI is missing compatible-video background messaging"
grep -Fq 'stream.mp4?' "$STATUS_DIR/server.py" || die "Portal server is missing Jellyfin MP4 compatibility stream"
grep -Fq '"static": "false"' "$STATUS_DIR/server.py" || die "Portal server is not configured for Jellyfin transcoding/remux"
grep -Fq '"videoCodec": "h264"' "$STATUS_DIR/server.py" || die "Portal server is missing H.264 compatibility request"
grep -Fq '"audioCodec": "aac"' "$STATUS_DIR/server.py" || die "Portal server is missing AAC compatibility request"
grep -Fq 'id="library-browser"' "$portal_check" || die "Portal UI is missing Jellyfin Library browser"
grep -Fq 'library-sections' "$portal_check" || die "Portal UI is missing categorized media overview"
grep -Fq "musicNavButton('albums','Albums')" "$portal_check" || die "Portal UI is missing structured music navigation"
grep -Fq 'music-section-head' "$portal_check" || die "Portal UI is missing music sections"
grep -Fq 'id="jellyfin-video-player"' "$portal_check" || die "Portal UI is missing in-portal Jellyfin video player"
grep -Fq 'id="photo-browser"' "$portal_check" || die "Portal UI is missing shared photo browser"
grep -Fq 'PCGA Control Center' "$portal_check" || die "Portal UI is missing PCGA Control Center"
grep -Fq 'data-control-tab="diagnostics"' "$portal_check" || die "Portal UI is missing Diagnostics tab"
for diag_id in diag-grid diag-summary diag-profile diag-window diag-lines diag-refresh diag-download diag-auto; do
  grep -Fq "id=\"${diag_id}\"" "$portal_check" || die "Portal UI is missing diagnostics component: ${diag_id}"
done
grep -Fq 'data-control-section="diagnostics"' "$portal_check" || die "Portal UI is missing Diagnostics settings section"
grep -Fq '.diag-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))' "$portal_check" || die "Portal UI is missing side-by-side diagnostic log layout"
grep -Fq '/api/diagnostics/logs' "$STATUS_DIR/server.py" || die "Portal server is missing diagnostics log API proxy"
grep -Fq '"action":"pc-game-retry"' "$STATUS_DIR/server.py" || die "Portal PC-game retry is not delegated to the host control plane"
grep -Fq 'name == "pc-game-retry"' /usr/local/sbin/pcga-control || die "PCGA control plane is missing host-side PC-game retry action"
grep -Fq 'name == "pc-game-reinstall"' /usr/local/sbin/pcga-control || die "PCGA control plane is missing host-side PC-game reinstall action"
grep -Fq 'install_patch_from_stream' /usr/local/sbin/pcga-control || die "PCGA control plane is missing signed/validated ZIP patch ingestion"
grep -Fq 'id="patch-drop"' "$portal_check" || die "Portal UI is missing drag-and-drop patch installer"
grep -Fq '/api/control/patch' "$STATUS_DIR/server.py" || die "Portal server is missing patch-upload proxy"
grep -Fq 'data-pc-reinstall' "$portal_check" || die "Portal UI is missing PC-game reinstall button"
grep -Fq '/reinstall"' "$STATUS_DIR/server.py" || die "Portal server is missing PC-game reinstall endpoint"
[[ -x /usr/local/sbin/pcga-game-orchestrator ]] || die "PC game orchestrator host executable is missing"
[[ -x /usr/local/sbin/pcga-game-compat-resolver ]] || die "PC game compatibility resolver host executable is missing"
grep -Fq 'id="review-browser"' "$portal_check" || die "Portal UI is missing portal-native Manual Review modal"
grep -Fq 'data-open-review' "$portal_check" || die "Control Center still navigates away for Manual Review"
grep -Fq 'path":"#review"' "$STATUS_DIR/server.py" || die "Review Queue launcher still aliases to the standalone review page"
grep -Fq '/api/review/items' "$STATUS_DIR/server.py" || die "Portal server is missing Manual Review JSON bridge"
grep -Fq '/api/review/preview/' "$STATUS_DIR/server.py" || die "Portal server is missing Manual Review media preview"
grep -Fq 'pcgaTextEditing' "$portal_check" || die "Portal UI is missing text-input focus protection"
grep -Fq 'id="video-seek"' "$portal_check" || die "Portal UI is missing fixed-runtime Jellyfin video timeline"
grep -Fq 'id="video-quality"' "$portal_check" || die "Portal UI is missing Jellyfin quality selector"
grep -Fq 'id="video-audio-track"' "$portal_check" || die "Portal UI is missing Jellyfin audio-track selector"
grep -Fq 'id="video-subtitle-track"' "$portal_check" || die "Portal UI is missing Jellyfin subtitle selector"
grep -Fq 'id="video-speed"' "$portal_check" || die "Portal UI is missing Jellyfin playback-speed selector"
grep -Fq 'id="video-fit"' "$portal_check" || die "Portal UI is missing Jellyfin Fit/Fill control"
grep -Fq 'function toggleVideoFullscreen()' "$portal_check" || die "Portal UI is missing player-only fullscreen handler"
grep -Fq '.video-player-panel:fullscreen' "$portal_check" || die "Portal UI is missing fullscreen theater-player layout"
grep -Fq 'VIDEO_QUALITY_PROFILES' "$STATUS_DIR/server.py" || die "Portal server is missing Jellyfin quality profiles"
grep -Fq 'def jellyfin_video_stream_params' "$STATUS_DIR/server.py" || die "Portal server is missing Jellyfin stream parameter builder"
grep -Fq 'subtitleMethod' "$STATUS_DIR/server.py" || die "Portal server is missing Jellyfin subtitle delivery configuration"
grep -Fq 'PCGA_REVIEW_TOKEN_FILE' "$STACK_DIR/compose.status.yml" || die "Portal status sidecar is missing Manual Review credential configuration"
grep -Fq '/pcga/secrets/manual-review-token:ro' "$STACK_DIR/compose.status.yml" || die "Portal status sidecar is missing read-only Manual Review credential mount"
grep -Fq 'data-control-tab="games"' "$portal_check" || die "Portal UI is missing Games & Emulation settings"
grep -Fq 'id="system-strip"' "$portal_check" || die "Portal UI is missing appliance status strip"
grep -Fq 'PCGA_NAV_SELECTOR' "$portal_check" || die "Portal UI is missing unified navigation engine"
grep -Fq "document.addEventListener('pointerover'" "$portal_check" || die "Portal UI is missing hover-to-selection synchronization"
grep -Fq 'pcga-nav-selected' "$portal_check" || die "Portal UI is missing shared selection styling"
grep -Fq 'option value="slideshow"' "$portal_check" || die "Portal UI is missing photo slideshow background mode"
grep -Fq 'id="setting-background-motion"' "$portal_check" || die "Portal UI is missing background motion selector"
grep -Fq '<option value="parallax">Reactive parallax</option>' "$portal_check" || die "Portal UI is missing reactive parallax mode"
grep -Fq 'setting-parallax-ambient' "$portal_check" || die "Portal UI is missing ambient parallax depth control"
grep -Fq 'setting-parallax-pattern' "$portal_check" || die "Portal UI is missing pattern parallax depth control"
grep -Fq 'setting-parallax-media' "$portal_check" || die "Portal UI is missing media parallax depth control"
grep -Fq 'function setParallaxFromPoint' "$portal_check" || die "Portal UI is missing reactive parallax engine"
grep -Fq 'prefers-reduced-motion' "$portal_check" || die "Portal UI is missing reduced-motion handling"
grep -Fq "'wii-aero':{name:'Aero Channels'" "$portal_check" || die "Portal UI is missing Aero Channels theme"
grep -Fq "'couch-grid':{name:'Couch Grid'" "$portal_check" || die "Portal UI is missing Couch Grid theme"
grep -Fq "'desk-compact':{name:'Desk Compact'" "$portal_check" || die "Portal UI is missing Desk Compact theme"
grep -Fq "'arcade-crt':{name:'Arcade CRT'" "$portal_check" || die "Portal UI is missing Arcade CRT theme"
grep -Fq "'high-contrast':{name:'High Contrast'" "$portal_check" || die "Portal UI is missing High Contrast theme"
grep -Fq -- '--panel-rgb' "$portal_check" || die "Portal UI is missing semantic panel palette token"
grep -Fq -- '--focus-ring' "$portal_check" || die "Portal UI is missing semantic focus palette token"
grep -Fq "setVar('--bg-deep-rgb'" "$portal_check" || die "Portal palette does not propagate background RGB tokens"
grep -Fq "setVar('--theme-glass'" "$portal_check" || die "Portal palette does not propagate theme glass tokens"
grep -Fq "id=\"setting-appearance-mode\"" "$portal_check" || die "Portal UI is missing Light/Dark appearance selector"
grep -Fq "id=\"setting-surface-style\"" "$portal_check" || die "Portal UI is missing surface treatment selector"
grep -Fq "surfaceStyle:'theme'" "$portal_check" || die "Portal UI is missing persisted surface-style default"
grep -Fq 'id="setting-font-style"' "$portal_check" || die "Portal UI is missing interface-font selector"
grep -Fq "fontStyle:'theme'" "$portal_check" || die "Portal UI is missing persisted interface-font default"
grep -Fq 'const PORTAL_FONTS=' "$portal_check" || die "Portal UI is missing interface-font registry"
grep -Fq "setVar('--ui-font-family'" "$portal_check" || die "Portal UI is missing typography propagation token"
grep -Fq '.control-path,.diag-log,code,pre' "$portal_check" || die "Portal UI is missing monospace diagnostic/path protection"
grep -Fq 'data-surface-style="frosted"' "$portal_check" || die "Portal UI is missing Frosted glass treatment"
grep -Fq 'data-surface-style="crystal"' "$portal_check" || die "Portal UI is missing Crystal glass treatment"
grep -Fq 'orthogonal surface-material system' "$portal_check" || die "Portal UI is missing v0.18.6 surface-material layer"
grep -Fq "function resolvedAppearanceMode()" "$portal_check" || die "Portal UI is missing automatic Light/Dark resolver"
grep -Fq "data-color-mode=\"dark\"" "$portal_check" || die "Portal UI is missing dark appearance state"
grep -Fq "responsive modal headers + independent light/dark appearance" "$portal_check" || die "Portal UI is missing v0.18.4 overlap/layout hardening"
grep -Fq "function openSettings(section='display')" "$portal_check" || die "Portal UI is missing v0.18.5 Control Center open handler"
grep -Fq "function closeSettings()" "$portal_check" || die "Portal UI is missing v0.18.5 Control Center close handler"
grep -Fq 'PCGA_PLATFORM_PLACEHOLDERS' "$portal_check" || die "Portal UI is missing v0.18.9 platform placeholder registry"
grep -Fq "snes:['SNES','Super Nintendo'" "$portal_check" || die "Portal UI is missing SNES fallback artwork"
grep -Fq "n64:['N64','Nintendo 64'" "$portal_check" || die "Portal UI is missing N64 fallback artwork"
grep -Fq 'function artStack(' "$portal_check" || die "Portal UI is missing artwork failure fallback stack"
grep -Fq 'platform-fallback' "$portal_check" || die "Portal UI is missing platform placeholder styling"
grep -Fq 'id="setting-home-media"' "$portal_check" || die "Portal UI is missing Continue & Recent master toggle"
grep -Fq 'id="setting-home-media-games"' "$portal_check" || die "Portal UI is missing game inclusion toggle for Continue & Recent"
grep -Fq 'id="setting-home-media-continue"' "$portal_check" || die "Portal UI is missing Continue shelf toggle"
grep -Fq 'id="setting-home-media-recent"' "$portal_check" || die "Portal UI is missing Recently Accessed shelf toggle"
grep -Fq 'id="setting-home-media-added"' "$portal_check" || die "Portal UI is missing Recently Added shelf toggle"
grep -Fq 'id="home-media-surface"' "$portal_check" || die "Portal UI is missing secondary home-media surface"
grep -Fq 'function openHomeMediaSurface()' "$portal_check" || die "Portal UI is missing home-media sweep navigation"
grep -Fq 'function closeHomeMediaSurface(' "$portal_check" || die "Portal UI is missing home-media return navigation"
grep -Fq '/api/jellyfin/home-media' "$STATUS_DIR/server.py" || die "Portal server is missing Jellyfin home-media endpoint"
grep -Fq 'def jellyfin_home_media_items' "$STATUS_DIR/server.py" || die "Portal server is missing home-media aggregation"
grep -Fq '_game_activity_home_items' "$STATUS_DIR/server.py" || die "Portal server is missing unified game activity shelves"
grep -Fq 'GAME_ACTIVITY_PATH' /usr/local/sbin/pcga-control || die "Control plane is missing persistent game activity history"
grep -Fq 'game_activity_record' /usr/local/sbin/pcga-control || die "Control plane is missing game launch recording"
! grep -Fq -- '--wii-cyan:#' "$portal_check" || die "Aero Channels still forces a fixed cyan palette"
grep -Fq '/api/photos/library' "$STATUS_DIR/server.py" || die "Portal server is missing photo library endpoint"
grep -Fq '/media/library/photos:/media/photos:ro' "$STACK_DIR/compose.yml" || die "Jellyfin is missing shared photo mount"
rm -f "$portal_check"
trap - EXIT

grep -Fq "'GET_VIDEO_TITLE': 'false'" /usr/local/sbin/pcga-arm-configure || die "ARM profile still enables synchronous video-title lookup"
grep -Fq "'MINLENGTH': '\"30\"'" /usr/local/sbin/pcga-arm-configure || die "ARM profile is not configured to retain short optical bonus features (MINLENGTH=30)"
grep -Fq -- "--minlength=30" /usr/local/sbin/pcga-makemkv-preflight || die "MakeMKV preflight is not scanning 30-second bonus titles"
grep -Fq -- "--minlength=30" /usr/local/sbin/pcga-media-disc-metadata || die "Optical metadata scan is not scanning 30-second bonus titles"
grep -Fq "'DELRAWFILES': 'false' if keep_raw else 'true'" /usr/local/sbin/pcga-arm-configure || die "ARM work-file retention is not controlled by the PCGA keep_raw setting"
grep -Fq '"keep_raw": False' /usr/local/sbin/pcga-control || die "Control-plane default still retains successful ARM work files"
grep -Fq "['cc-keep-raw','ingest','keep_raw']" "$STATUS_DIR/server.py" || die "Portal keep_raw control is not wired to the control plane"
if grep -Fq 'pcga-arm-configure >/dev/null' /usr/local/sbin/pcga-arm-rip; then
  die "ARM rip trigger still applies the old pre-rip configuration profile"
fi
grep -Eq '\"?\$RECONCILE_BIN\"?[[:space:]]+reconcile([[:space:]]|$)' /usr/local/sbin/pcga-media-sort || die "Sorter is missing staging reconciliation path"
grep -Fq 'transcode' /usr/local/sbin/pcga-ingest-reconcile || die "Reconciler is missing transcode-stage inventory"
grep -Fq 'source category hint' /usr/local/sbin/pcga-classify || die "Classifier is missing unified source-hint logic"
grep -Fq 'optical dispatcher:' /usr/local/sbin/pcga-classify || die "Classifier is missing optical-disc manifest integration"
grep -Fq 'pcga-optical-identify --field route' /usr/local/sbin/pcga-arm-rip || die "ARM trigger is missing the optical media-type gate"
grep -Fq 'pcga-optical-dispatch@%k.service' /etc/udev/rules.d/52-pcga-media-rip.rules || die "udev still bypasses the optical dispatcher"
grep -Fq 'pc-data|pc-mixed' /usr/local/sbin/pcga-optical-dispatch || die "Optical dispatcher is missing PC/data routes"
grep -Fq 'pcga-game-disc-metadata --record' /usr/local/sbin/pcga-optical-dispatch || die "Optical dispatcher is missing pre-rip game metadata collection"
[[ -d /var/lib/pc-game-archive/game-intake/collections ]] || die "Game intake collection registry is missing"
grep -Fq 'add-game-to-disc' /usr/local/sbin/pcga-game-intake || die "Game intake is missing compilation membership management"
grep -Fq "layout':'compilation" /usr/local/sbin/pcga-game-disc-metadata || die "Pre-rip metadata collector is missing compilation detection"
grep -Fq 'pcga-media-disc-metadata --record' /usr/local/sbin/pcga-optical-dispatch || die "Optical dispatcher is missing pre-rip movie/TV metadata collection"
grep -Fq 'multi-title-candidate' /usr/local/sbin/pcga-media-disc-metadata || die "Movie/TV metadata collector is missing multi-title detection"
grep -Fq 'add-item-to-disc' /usr/local/sbin/pcga-media-intake || die "Movie/TV intake is missing multi-title membership management"
grep -Fq 'attach-artifact' /usr/local/sbin/pcga-media-sort || die "ARM sorter is not carrying optical media relationships into classification"
grep -Fq 'optical-multi-title' /usr/local/sbin/pcga-classify || die "Classifier is missing optical multi-title review protection"
grep -Fq 'def promote_optical_movie_multititle' /usr/local/sbin/pcga-manual-review || die "Manual Review is missing movie main-feature/extras promotion"
grep -Fq 'def reclassify_library_optical' /usr/local/sbin/pcga-manual-review || die "Manual Review is missing existing optical-title reclassification"
grep -Fq 'def reconcile_existing_optical' /usr/local/sbin/pcga-manual-review || die "Manual Review is missing current-rip bonus-feature reconciliation"
grep -Fq '/api/library-optical-items' /usr/local/sbin/pcga-manual-review || die "Manual Review is missing promoted optical library API"
grep -Fq 'This optical source contains multiple independent logical titles' /usr/local/sbin/pcga-manual-review || die "Manual Review no longer protects true anthology/collection sources"
grep -Fq 'multi-title-candidate' /usr/local/sbin/pcga-media-disc-metadata || die "Movie/TV metadata collector is missing multi-title candidate classification"
grep -Fq 'preserved-game-compilation' /usr/local/sbin/pcga-classify || die "Classifier is missing preserved compilation handling"
grep -Fq '.pcga-game.json' /usr/local/sbin/pcga-pc-disc-rip || die "PC/data preservation is not carrying game metadata into the rip artifact"
grep -Fq 'progress_percent' /usr/local/sbin/pcga-pc-disc-rip || die "PC/data preservation is missing portal progress state"
grep -Fq 'preserved_at' /usr/local/sbin/pcga-pc-disc-rip || die "PC/data preservation is missing preserved lifecycle state"
grep -Fq 'pc-disc-verifying' /usr/local/sbin/pcga-pc-disc-rip || die "PC/data preservation is missing verifying lifecycle state"
grep -Fq 'def optical_game_signal' /usr/local/sbin/pcga-classify || die "Classifier is missing strong local Windows-game evidence scoring"
grep -Fq 'retire_consumed_pending' /usr/local/sbin/pcga-classify || die "Classifier is missing consumed optical-source reconciliation"
grep -Fq 'already-published-optical-fingerprint' /usr/local/sbin/pcga-classify || die "Classifier is missing durable duplicate retirement receipts"
grep -Fq '_pcga_pending_review_rows' "$STATUS_DIR/server.py" || die "PC Games UI is missing preserved review-required candidates"
grep -Fq 'cdrdao read-cd --read-raw' /usr/local/sbin/pcga-pc-disc-rip || die "Mixed-mode preservation backend is missing"
grep -Fq 'ddrescue -b 2048' /usr/local/sbin/pcga-pc-disc-rip || die "Data-disc preservation backend is missing"
grep -Fq 'held-auto-ingest-disabled' /usr/local/sbin/pcga-optical-dispatch || die "Optical identification is still coupled to automatic backend execution"
grep -Fq '/var/lib/pc-game-archive/optical-dispatch:/pcga/status/optical-dispatch:ro' "$STACK_DIR/compose.status.yml" || die "Portal status sidecar is missing optical dispatcher state mount"
grep -Fq 'dispatch_status' "$STATUS_DIR/server.py" || die "Portal status server is missing optical dispatcher diagnostics"
grep -Fq 'parse_episode_identity' /usr/local/sbin/pcga-classify || die "Classifier is missing episode identity parsing"
grep -Fq 'Season {season:02d}' /usr/local/sbin/pcga-classify || die "Classifier is missing canonical TV season layout"
grep -Fq '/Items/RemoteSearch/{endpoint}' /usr/local/sbin/pcga-manual-review || die "Manual Review is missing Jellyfin remote metadata search"
grep -Fq 'metadata-apply' /usr/local/sbin/pcga-manual-review || die "Manual Review is missing metadata selection flow"
grep -Fq '/api/items' /usr/local/sbin/pcga-manual-review || die "Manual Review service is missing portal JSON API"
grep -Fq 'X-PCGA-Review-Token' /usr/local/sbin/pcga-manual-review || die "Manual Review service is missing private portal authentication"
grep -Fq 'def delete_review_item' /usr/local/sbin/pcga-manual-review || die "Manual Review is missing permanent delete support"
grep -Fq '/api/delete' /usr/local/sbin/pcga-manual-review || die "Manual Review is missing authenticated delete API"
grep -Fq 'review-deletions' /usr/local/sbin/pcga-manual-review || die "Manual Review delete audit receipts are missing"
grep -Fq 'media/quarantine/duplicates' /usr/local/sbin/pcga-manual-review || die "Manual Review is not exposing duplicate quarantine for cleanup"
grep -Fq 'data-review-delete' "$STATUS_DIR/server.py" || die "Portal Manual Review is missing Delete permanently control"
grep -Fq '"quarantine", "delete"' "$STATUS_DIR/server.py" || die "Portal Manual Review proxy is not allowing delete requests"
grep -Fq 'episode-plan sequential' /usr/local/sbin/pcga-manual-review || die "Manual Review is missing sequential episode assignment preview"
grep -Fq "data['episode_assignment']='sequential'" /usr/local/sbin/pcga-manual-review || die "Manual Review does not prepare unnumbered TV tracks after metadata selection"
grep -Fq -- '--repair-tv-layout' /usr/local/sbin/pcga-classify || die "Classifier is missing TV reconciliation command"
grep -Fq 'advancedsearch.php' /usr/local/sbin/pcga-public-media || die "Public media importer is missing Internet Archive search API"
grep -Fq '/api/user-upload/session' /usr/local/sbin/pcga-public-media || die "Content intake service is missing upload-session API"
grep -Fq 'receive_user_upload' /usr/local/sbin/pcga-public-media || die "Content intake service is missing streamed upload receiver"
grep -Fq 'pc_game_changed' /usr/local/sbin/pcga-public-media || die "PC-game browser uploads do not trigger runtime reconciliation"
grep -Fq "pcga-game-orchestrator.service" /usr/local/sbin/pcga-public-media || die "PC-game browser uploads are missing orchestrator wake-up"
grep -Fq 'infer_rom_platform' /usr/local/sbin/pcga-public-media || die "Content intake service is missing ROM platform inference"
grep -Fq 'route_console_artwork_unit' /usr/local/sbin/pcga-public-media || die "ROM uploads are missing artwork separation"
grep -Fq 'route_bios_unit' /usr/local/sbin/pcga-public-media || die "Content intake service is missing BIOS routing"
grep -Fq 'Upload BIOS' "$STATUS_DIR/server.py" || die "Portal is missing the BIOS upload UI"
grep -Fq "Decision('photo'" /usr/local/sbin/pcga-classify || die "Classifier is missing photo categorization"
grep -Fq '/api/uploads/file' "$STATUS_DIR/server.py" || die "Portal server is missing streamed upload endpoint"
grep -Fq 'Upload & organize' "$STATUS_DIR/server.py" || die "Portal UI is missing unified upload workflow"
for kind in movie tv music home-video photos pc-game software disc-image rom; do
  grep -Fq "<option value=\"$kind\">" "$STATUS_DIR/server.py" || die "Portal Add Media is missing upload type $kind"
done
grep -Fq 'data-upload-kind="pc-game"' "$STATUS_DIR/server.py" || die "PC Games UI is missing contextual upload action"
grep -Fq 'data-upload-kind="rom"' "$STATUS_DIR/server.py" || die "Console Games UI is missing contextual upload action"
grep -Fq 'data-upload-kind="music"' "$STATUS_DIR/server.py" || die "Music UI is missing contextual upload action"
grep -Fq 'data-upload-kind="photos"' "$STATUS_DIR/server.py" || die "Photos UI is missing contextual upload action"
grep -Fq "ReadWritePaths=$ROOT " /etc/systemd/system/pcga-public-media.service || die "Content intake service does not have archive write access"
grep -Fq 'Public Media' "$STATUS_DIR/server.py" || die "Portal is missing Public Media launcher tile"
grep -Fq '"title":"Movies & TV"' "$STATUS_DIR/server.py" || die "Portal is missing Movies & TV launcher tile"
grep -Fq 'Console Games' "$STATUS_DIR/server.py" || die "Portal is missing RomM Console Games launcher tile"
grep -Fq 'PCGA_ROMM_PORT' "$STACK_DIR/compose.status.yml" || die "Portal status sidecar is missing RomM port configuration"
grep -Fq 'PCGA_ROMM_CREDS_FILE' "$STACK_DIR/compose.status.yml" || die "Portal status sidecar is missing RomM appliance credential configuration"
grep -Fq '/api/games/library' "$STATUS_DIR/server.py" || die "Portal server is missing portal-native console library endpoint"
grep -Fq '/api/games/collection/search' "$STATUS_DIR/server.py" || die "Portal server is missing ROM Collection search endpoint"
grep -Fq '/api/games/collection/import' "$STATUS_DIR/server.py" || die "Portal server is missing ROM Collection import endpoint"
grep -Fq '/api/games/rescan' "$STATUS_DIR/server.py" || die "Portal server is missing immediate RomM rescan endpoint"
grep -Fq 'tasks.run' "$STATUS_DIR/server.py" || die "Portal RomM OAuth scope is missing tasks.run for collection rescans"
grep -Fq 'Find ROMs' "$STATUS_DIR/server.py" || die "Console Games UI is missing ROM Collection discovery"
grep -Fq '/api/rom/search' /usr/local/sbin/pcga-public-media || die "Public media importer is missing ROM Collection search API"
grep -Fq 'abandonware-review' /usr/local/sbin/pcga-public-media || die "ROM Collection is missing abandonware rights-review classification"
grep -Fq '.pcga-source' /usr/local/sbin/pcga-public-media || die "ROM Collection is missing source provenance storage"
grep -Fq '/api/pc-games/health' "$STATUS_DIR/server.py" || die "Portal server is missing LANCommander catalog health endpoint"
grep -Fq '/api/pc-games/library' "$STATUS_DIR/server.py" || die "Portal server is missing portal-native PC game library endpoint"
grep -Fq '#pc-games' "$STATUS_DIR/server.py" || die "PC Games launcher is not portal-native"
grep -Fq '{"id":"lancommander","title":"PC Games","subtitle":lc_subtitle,"same_origin":True,"path":"#pc-games"' "$STATUS_DIR/server.py" || die "PC Games primary tile still aliases to LANCommander or bypasses health diagnostics"
grep -Fq '{"id":"lancommander-native","title":"LANCommander"' "$STATUS_DIR/server.py" || die "Advanced LANCommander administration tile is missing"
grep -Fq 'PCGA_LANCOMMANDER_DATA' "$STACK_DIR/compose.status.yml" || die "Portal status sidecar is missing LANCommander catalog mount configuration"
grep -Fq '/pcga/lancommander:ro' "$STACK_DIR/compose.status.yml" || die "Portal status sidecar is missing read-only LANCommander data mount"
grep -Fq '/pcga/game-intake:ro' "$STACK_DIR/compose.status.yml" || die "Portal status sidecar is missing game metadata mount"
grep -Fq '/pcga/game-installs:ro' "$STACK_DIR/compose.status.yml" || die "Portal status sidecar is missing game install state mount"
systemctl is-enabled pcga-game-orchestrator.timer >/dev/null 2>&1 || die "PC game orchestrator timer is not enabled"
systemctl is-enabled pcga-heroic-sync.timer >/dev/null 2>&1 || die "Heroic library synchronization timer is not enabled"
[[ -x /usr/local/sbin/pcga-heroic-bootstrap ]] || die "Heroic runtime bootstrap helper is missing"
[[ -x /usr/local/sbin/pcga-heroic-sync ]] || die "Heroic library synchronization helper is missing"
[[ -x /usr/local/sbin/pcga-store-provider ]] || die "Native PC-store provider helper is missing"
[[ -x /usr/local/sbin/pcga-store-bootstrap ]] || die "Headless PC-store backend bootstrap helper is missing"
[[ -f /etc/systemd/system/pcga-store-bootstrap.service ]] || die "PC-store backend bootstrap unit is missing"
[[ -x /usr/local/sbin/pcga-store-jobs ]] || die "Persistent PC-store job helper is missing"
[[ -f /etc/systemd/system/pcga-store-jobs.service ]] || die "Persistent PC-store job service is missing"
[[ -x /usr/local/sbin/pcga-store-ingest ]] || die "Store-to-PCGA game ingestion helper is missing"
[[ -x /usr/local/sbin/pcga-store-game-startup ]] || die "Store game streaming startup helper is missing"
[[ -f /etc/systemd/system/pcga-store-ingest.timer ]] || die "Store game reconciliation timer is missing"
systemctl is-enabled pcga-store-ingest.timer >/dev/null 2>&1 || die "Store game reconciliation timer is not enabled"
systemctl is-enabled pcga-store-jobs.service >/dev/null 2>&1 || die "Persistent PC-store job service is not enabled"
systemctl is-active pcga-store-jobs.service >/dev/null 2>&1 || die "Persistent PC-store job service is not active"
grep -Fq 'ALLOWED_OPERATIONS = ("install", "update", "verify", "uninstall")' /usr/local/sbin/pcga-store-jobs || die "Epic/GOG maintenance queue operations are missing"
grep -Fq 'PROVIDERS = ("epic", "gog")' /usr/local/sbin/pcga-store-jobs || die "v0.19.13 must limit game maintenance to Epic and GOG"
grep -Fq 'queue_position' /usr/local/sbin/pcga-store-jobs || die "PC-store download queue positions are unavailable"
grep -Fq 'store-jobs-search' "$STATUS_DIR/server.py" || die "Native Downloads search is missing"
grep -Fq 'one_active_per_provider' /usr/local/sbin/pcga-store-jobs || die "PC-store job queue is missing per-provider concurrency reporting"
grep -Fq 'Direct provider execution refuses game-mutating operations' /usr/local/sbin/pcga-store-provider || die "PC-store direct-execution game-mutation safety boundary is missing"
grep -Fq 'HEROIC_VERSION="2.22.3"' /usr/local/sbin/pcga-store-bootstrap || die "PC-store backend bootstrap is not pinned to Heroic 2.22.3"
grep -Fq 'ASSET="Heroic-${HEROIC_VERSION}-linux-x64.tar.xz"' /usr/local/sbin/pcga-store-bootstrap || die "PC-store backend bootstrap asset naming is unexpected"
grep -Fq 'HEROIC_VERSION="2.22.3"' /usr/local/sbin/pcga-heroic-bootstrap || die "Heroic runtime bootstrap is not pinned to the v2.22.3 Linux release"
grep -Fq 'HEROIC_ASSET="Heroic-${HEROIC_VERSION}-linux-x64.tar.xz"' /usr/local/sbin/pcga-heroic-bootstrap || die "Heroic runtime bootstrap asset naming is unexpected"
grep -Fq '/var/lib/pc-game-archive/heroic:/pcga/heroic:ro' "$STACK_DIR/compose.status.yml" || die "Portal status sidecar is missing Heroic catalog state mount"
grep -Fq 'data-store-backends' "$STATUS_DIR/server.py" || die "PC Games UI is missing the native PC-store backend entry point"
grep -Fq 'data-store-library' "$STATUS_DIR/server.py" || die "PC Games UI is missing the native Store Library entry point"
grep -Fq 'store-jobs-modal' "$STATUS_DIR/server.py" || die "PC Games UI is missing the persistent Store Downloads monitor"
grep -Fq 'path == "/store/jobs"' /usr/local/sbin/pcga-control || die "Control plane is missing the persistent Store Downloads endpoint"
grep -Fq 'store-job-enqueue' /usr/local/sbin/pcga-control || die "Control plane is missing durable store job enqueue support"
grep -Fq 'def store_maintenance_preflight' /usr/local/sbin/pcga-control || die "Store maintenance preflight is missing"
grep -Fq 'store-maintain-modal' "$STATUS_DIR/server.py" || die "Store maintenance dialog is missing"
grep -Fq 'def library_payload' /usr/local/sbin/pcga-store-provider || die "PC-store provider is missing the normalized library contract"
grep -Fq 'def account_login_start' /usr/local/sbin/pcga-store-provider || die "PC-store provider is missing account login start"
grep -Fq 'def account_login_complete' /usr/local/sbin/pcga-store-provider || die "PC-store provider is missing account login completion"
grep -Fq -- '--code-stdin' /usr/local/sbin/pcga-store-provider || die "PC-store login codes are not using stdin transport"
grep -Fq 'store-account-login-start' /usr/local/sbin/pcga-control || die "PCGA control plane is missing store account actions"
grep -Fq 'path == "/store/backends"' /usr/local/sbin/pcga-control || die "PCGA control plane is missing store backend readiness endpoint"
grep -Fq 'storeBackendsReadyForLogin' "$STATUS_DIR/server.py" || die "Portal login is missing on-demand backend preparation"

grep -Fq 'path == "/store/library"' /usr/local/sbin/pcga-control || die "Control plane is missing the read-only store library endpoint"
grep -Fq 'cc-store-epic' "$STATUS_DIR/server.py" || die "Control Center is missing PC-store provider diagnostics"
grep -Fq 'def heroic_stream_info' "$STATUS_DIR/server.py" || die "Portal server is missing Heroic-to-Wolf stream integration"
grep -Fq 'heroic-session-active' /usr/local/sbin/pcga-control || die "Control plane is missing Heroic single-session protection"
grep -Fq 'PCGA_NATIVE_EMULATORS' "$STATUS_DIR/server.py" || die "Portal is missing native console emulator mapping"
grep -Fq 'id="cc-native-emulators"' "$STATUS_DIR/server.py" || die "Portal is missing native emulator installation panel"
grep -Fq 'nativeEmulatorRequest' "$STATUS_DIR/server.py" || die "Portal is missing native emulator installation actions"
grep -Fq 'native-emulators-install' /usr/local/sbin/pcga-control || die "Control plane is missing native emulator install dispatch"
[[ -x /usr/local/sbin/pcga-native-emulators ]] || die "Native console emulator manager is missing"
grep -Fq '/api/games/ejs/' "$STATUS_DIR/server.py" || die "Portal server is missing EmulatorJS asset proxy endpoint"
grep -Fq '/api/games/health' "$STATUS_DIR/server.py" || die "Portal server is missing emulator pipeline health endpoint"
grep -Fq 'ROMM_OAUTH_SCOPES' "$STATUS_DIR/server.py" || die "Portal server is missing scoped RomM OAuth authentication"
grep -Fq '/games/play/' "$STATUS_DIR/server.py" || die "Portal server is missing portal-native emulator player route"
grep -Fq '/api/jellyfin/library' "$STATUS_DIR/server.py" || die "Portal server is missing unified Jellyfin library endpoint"
grep -Fq '"tv": "Series"' "$STATUS_DIR/server.py" || die "Movies & TV browser still maps the TV filter to episodes instead of series"
grep -Fq '("tv", "TV Series", "Series")' "$STATUS_DIR/server.py" || die "Movies & TV overview is missing the TV Series shelf"
grep -Fq 'function renderJellyfinSeries' "$STATUS_DIR/server.py" || die "Movies & TV browser is missing series episode drill-down"
grep -Fq 'data-library-series-back' "$STATUS_DIR/server.py" || die "Series episode browser is missing return navigation"
grep -Fq '/api/jellyfin/video/prepare' "$STATUS_DIR/server.py" || die "Portal server is missing foreground Jellyfin video preparation"

grep -Fq 'PROTONDB_SUMMARY' /usr/local/sbin/pcga-game-compat-resolver || die "Compatibility resolver is missing ProtonDB support"
grep -Fq 'POL_GAMES_CATALOG' /usr/local/sbin/pcga-game-compat-resolver || die "Compatibility resolver is missing PlayOnLinux support"
grep -Fq 'SAFE_WINETRICKS' /usr/local/sbin/pcga-game-compat-resolver || die "Compatibility resolver is missing the allow-listed component policy"
grep -Fq 'execute_provider_scripts' /usr/local/sbin/pcga-game-compat-resolver || die "Compatibility resolver is missing provider-script non-execution policy"
grep -Fq 'provider_settings' /usr/local/sbin/pcga-game-compat-resolver || die "Compatibility resolver is missing provider-policy cache invalidation"
grep -Fq 'idtech3-legacy-opengl-extension-string' /usr/local/sbin/pcga-game-compat-resolver || die "Compatibility resolver is missing Jedi/id Tech 3 known-good rule"
grep -Fq 'MESA_EXTENSION_MAX_YEAR' /usr/local/sbin/pcga-game-compat-resolver || die "Compatibility resolver is missing Mesa extension-string compatibility"
grep -Fq '__GL_ExtensionStringVersion' /usr/local/sbin/pcga-game-compat-resolver || die "Compatibility resolver is missing NVIDIA extension-string compatibility"
grep -Fq '"virtual_cd"' /usr/local/sbin/pcga-game-compat-resolver || die "Compatibility resolver is missing appliance-owned virtual CD recipes"
grep -Fq '.windows-label' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing Wine virtual CD volume-label presentation"
grep -Fq '.pcga-install-complete' /usr/local/sbin/pcga-game-orchestrator || die "PC game setup is missing persistent completion finalization"
grep -Fq 'compatibility_preferred_executables' /usr/local/sbin/pcga-game-orchestrator || die "PC game launcher is missing ordered direct-executable preference"
grep -Fq '"finalized": finalized' /usr/local/sbin/pcga-control || die "Control plane is missing immediate setup-session finalization"
grep -Fq 'resolve_compatibility' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing compatibility resolution"
grep -Fq 'PCGA_COMPAT_WINETRICKS_SECONDS' /usr/local/sbin/pcga-game-orchestrator || die "PC game compatibility setup is missing a bounded Winetricks window"
grep -Fq 'pcga_configure_graphics_backend' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing explicit DXVK/WineD3D graphics backend selection"
grep -Fq 'PCGA_DXVK_WINETRICKS_VERB' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing pinned DXVK provisioning"
grep -Fq 'compatibility_shell_prelude' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing compatibility profile application"
grep -Fq 'RUNTIME_MEDIA_ROOT = Path("/run/pcga-game-media")' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing preserved optical-media staging"
grep -Fq 'loop,ro,nosuid,nodev,noexec' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing read-only ISO loop mounting"
grep -Fq 'dosdevices/{letter}::' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing raw Wine optical-device mapping"
grep -Fq 'wine cmd /c vol' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing optical volume-label diagnostics"
grep -Fq 'PrivateTmp=false' /etc/systemd/system/pcga-game-orchestrator.service || die "PC game orchestrator still hides runtime media mounts from Docker"
grep -Fq 'OnBootSec=15s' /etc/systemd/system/pcga-game-orchestrator.timer || die "PC game orchestrator does not recreate optical runtime mounts promptly at boot"
grep -Fq 'Refresh compatibility' "$STATUS_DIR/server.py" || die "Portal PC-game profile is missing compatibility refresh UI"
grep -Fq 'ProtonDB compatibility knowledge' "$STATUS_DIR/server.py" || die "Portal settings are missing compatibility provider controls"
grep -Fq 'pc-game-compat-refresh' /usr/local/sbin/pcga-control || die "Control plane is missing compatibility refresh action"
grep -Fq '"iexplore.exe"' /usr/local/sbin/pcga-game-orchestrator || die "PC game launcher is missing Wine built-in executable rejection"
grep -Fq 'Repaired false Wine runtime launch target' /usr/local/sbin/pcga-game-orchestrator || die "PC game launcher is missing false-ready state repair"
grep -Fq 'wolf_remove_superseded_apps' /usr/local/sbin/pcga-game-orchestrator || die "Wolf app reconciliation is missing legacy duplicate cleanup"
grep -Fq 'cd "$(dirname "$TARGET")"' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing executable working-directory launch"
! grep -Fq '"RUN_GAMESCOPE=0"' /usr/local/sbin/pcga-game-orchestrator || die "PC game Wolf app still enables nested Gamescope with RUN_GAMESCOPE=0"
grep -Fq '"RUN_GAMESCOPE="' /usr/local/sbin/pcga-game-orchestrator || die "PC game Wolf app is missing explicit empty Gamescope disable"
grep -Fq 'export RUN_GAMESCOPE=""' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing nounset-safe Gamescope normalization"
grep -Fq 'RUN_GAMESCOPE=${{RUN_GAMESCOPE-<unset>}}' /usr/local/sbin/pcga-game-orchestrator || die "PC game setup diagnostics are missing compositor environment logging"
grep -Fq -- '--reinstall' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing reinstall mode"
grep -Fq 'reset_install_for_reinstall' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing preserved-source reinstall reset"
grep -Fq 'runtime-logs/session.log' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing persistent runtime logging"
grep -Fq 'install_generation' /usr/local/sbin/pcga-game-orchestrator || die "PC game reinstall is missing per-player template generation refresh"
grep -Fq 'battlefrontii.exe' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing Battlefront II compatibility hook"
grep -Fq 'file:pcga-runtime:' /usr/local/sbin/pcga-control || die "Diagnostics catalog is missing persistent PC game runtime logs"
grep -Fq '"ok": returncode == 0' /usr/local/sbin/pcga-control || die "Persisted PC-game diagnostics still reference an unbound subprocess result"
grep -Fq '_wolf_reconcile_batched_restart' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing batched Wolf reload handling"
grep -Fq 'Reconcile the canonical managed block in place' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing idempotent Wolf app reconciliation"
grep -Fq 'launch(?:bfii|eaw)' /usr/local/sbin/pcga-game-orchestrator || die "PC game identity repair is missing launcher-wrapper rejection"
grep -Fq 'pc-game-stream-reconcile' /usr/local/sbin/pcga-control || die "PCGA control plane is missing stream-only Wolf reconciliation"
grep -Fq 'name == "pc-game-session-list"' /usr/local/sbin/pcga-control || die "PCGA control plane is missing PC-game session discovery"
grep -Fq 'name == "pc-game-session-stop"' /usr/local/sbin/pcga-control || die "PCGA control plane is missing PC-game session termination"
grep -Fq 'name == "pc-game-session-reserve"' /usr/local/sbin/pcga-control || die "PCGA control plane is missing client-owned stream reservations"
grep -Fq '"resumable": bool(owner.get("reservation_id") and owner.get("lane"))' /usr/local/sbin/pcga-control || die "PCGA control plane is missing resumable session metadata"
grep -Fq 'data-pc-session-resume' "$STATUS_DIR/server.py" || die "Portal UI is missing active PC-game session Resume actions"
grep -Fq 'Reconnect video' "$STATUS_DIR/server.py" || die "Portal UI is missing non-destructive stream reconnect action"
grep -Fq 'Resuming active session' "$STATUS_DIR/server.py" || die "Portal UI does not prefer resume over duplicate same-title launches"
grep -Fq 'PC_GAME_SESSION_OWNER_PATH' /usr/local/sbin/pcga-control || die "PCGA control plane is missing durable PC-game session ownership"
grep -Fq 'PCGA_MOONLIGHT_WEB_LANES' "$STATUS_DIR/server.py" || die "Portal is missing Moonlight Web lane support"
grep -Fq 'data-pc-session-end-all' "$STATUS_DIR/server.py" || die "Portal is missing the active PC-game session manager"
grep -Fq 'id="pc-game-stream-discs"' "$STATUS_DIR/server.py" || die "Portal is missing streamed multi-disc controls"
grep -Fq "action:'pc-game-disc-switch'" "$STATUS_DIR/server.py" || die "Portal is missing session-scoped disc switch requests"
grep -Fq 'selected PC game session is no longer active or is not owned by this portal client' /usr/local/sbin/pcga-control || die "PCGA control plane is missing client-scoped disc switching"
grep -Fq 'data-pc-stream-end' "$STATUS_DIR/server.py" || die "Portal stream overlay is missing End session control"
grep -Fq 'pcGamePendingMessage' "$STATUS_DIR/server.py" || die "Portal is missing actionable pending-Wolf stream handling"
grep -Fq 'pre-v0.18.16 app-block ordering bug' "$STATUS_DIR/server.py" || die "Portal stream API is missing stale pending-restart recovery"
grep -Fq 'WOLF_RESTART_STATE' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing persistent deferred Wolf reload state"
grep -Fq 'managed runtime container active:' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing active runtime-container restart protection"
grep -Fq '"AutoRemove": true' /usr/local/sbin/pcga-game-orchestrator || die "Wolf child runtimes are not configured for automatic container removal"
grep -Fq '_prune_stopped_managed_runtime_containers' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing stopped runtime-container cleanup"
grep -Fq 'terminating black-screen session' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing black-screen launch watchdog"
grep -Fq 'game window has been gone for 15s' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing post-window stale-helper cleanup"
grep -Fq 'stopped-and-removed' /usr/local/sbin/pcga-control || die "PC game session stop does not remove the transient Docker container"
grep -Fq '_pc_game_metadata_target' /usr/local/sbin/pcga-control || die "PC game metadata application is missing working-runtime target resolution"
grep -Fq '_merge_duplicate_user_metadata' /usr/local/sbin/pcga-game-orchestrator || die "PC game duplicate convergence is missing metadata-to-runtime migration"
grep -Fq 'catalog_identity_aliases' /usr/local/sbin/pcga-game-orchestrator || die "PC game duplicate convergence is missing conservative acronym/title aliases"
grep -Fq '_pc_game_identity_aliases' /usr/local/sbin/pcga-control || die "PC game metadata application is missing acronym-linked runtime resolution"
! grep -Fq '>Streaming status</button>' "$STATUS_DIR/server.py" || die "Portal still renders misleading Streaming status action buttons"
grep -Fq 'PREPARING STREAM' "$STATUS_DIR/server.py" || die "Portal is missing non-streaming pending-state labeling"
[[ $(grep -c 'async function pcGameMetadataApply' "$STATUS_DIR/server.py") -eq 1 ]] || die "Portal metadata selection has duplicate/overriding apply handlers"
grep -Fq 'received signal=$1' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing external-termination signal logging"
grep -Fq 'gpu access ok:' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing render-node permission diagnostics"
grep -Fq 'def logical_disc_count' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing logical-disc deduplication"
grep -Fq 'ignoring duplicate preserved ISO for logical disc' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing duplicate-preservation suppression"
grep -Fq 'Wine prefix preflight: existing prefix is unusable' /usr/local/sbin/pcga-game-orchestrator || die "Interactive PC-game setup is missing Wine-prefix recovery"
grep -Fq 'pcga_launch_installer()' /usr/local/sbin/pcga-game-orchestrator || die "PC-game setup is missing the legacy-installer launch wrapper"
grep -Fq 'PCGA_SETUP_VIRTUAL_DESKTOP' /usr/local/sbin/pcga-game-orchestrator || die "PC-game setup is missing Wine virtual-desktop containment"
grep -Fq '/desktop=PCGASetup,$desktop_size' /usr/local/sbin/pcga-game-orchestrator || die "PC-game setup is missing the stable PCGASetup desktop launch"
grep -Fq 'esync/fsync disabled for legacy setup' /usr/local/sbin/pcga-game-orchestrator || die "PC-game setup is missing legacy installer synchronization defaults"
grep -Fq 'PCGA_SETUP_SOFTWARE_CURSOR' /usr/local/sbin/pcga-game-orchestrator || die "PC-game setup is missing nested-Sway software-cursor hardening"
grep -Fq 'PCGA_ARGV=/tmp/pcga-runtime.argv' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing NUL-delimited argv handoff"
grep -Fq "printf '%s\\\\0' \"\$TARGET\"" /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime argv handoff is missing the double-escaped NUL separator"
grep -Fq 'pcga_wait_for_xwayland()' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing the Xwayland readiness barrier"
grep -Fq 'Xwayland did not become ready' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing bounded Xwayland timeout diagnostics"
grep -Fq 'resetting pre-compositor Wine helpers before GUI launch' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing pre-compositor wineserver reset"
grep -Fq 'Wine GUI launch boundary ready' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing Wine GUI-boundary diagnostics"
grep -Fq 'def _runtime_media_source_device' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing host optical loop-device discovery"
grep -Fq '/dev/pcga-media-disc' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing raw optical block-device presentation"
grep -Fq 'COD2 SP ISO-backed optical D:' /usr/local/sbin/pcga-game-orchestrator || die "COD2 SP runtime is missing explicit ISO-backed D: mapping"
grep -Fq 'COD2CD1 CDEmu virtual-CD read probe: PASS' /usr/local/sbin/pcga-game-orchestrator || die "COD2 SP runtime is missing CDEmu virtual-CD readability validation"
grep -Fq 'CDEmu virtual CD-ROM' /usr/local/sbin/pcga-game-orchestrator || die "COD2 SP runtime is missing CDEmu virtual optical presentation"
! grep -Fq '/dev/pcga-physical-auth' /usr/local/sbin/pcga-game-orchestrator || die "COD2 runtime still contains physical optical-device passthrough"
! grep -Fq 'physical authentication is unavailable' /usr/local/sbin/pcga-game-orchestrator || die "COD2 SP still fails on missing physical media"
grep -Fq 'pcga-cdemu.service' /usr/local/sbin/pcga-game-orchestrator || die "COD2 host reconciliation is missing the CDEmu appliance service"
grep -Fq 'CDEMU_CONTAINER_DEVICE = "/dev/pcga-cdemu-cod2"' /usr/local/sbin/pcga-game-orchestrator || die "COD2 SP is missing the CDEmu container device"
grep -Fq 'COD2 multiplayer profile: preserved win32 install • base Wine runtime • preserved optical media' /usr/local/sbin/pcga-game-orchestrator || die "COD2 MP base-Wine isolation was removed"
grep -Fq 'COD2 single-player: skipping legacy intro movie to avoid Wine startup hang' /usr/local/sbin/pcga-game-orchestrator || die "COD2 SP is missing the legacy intro-movie startup workaround"
grep -Fq 'pcga_args+=(+set com_introplayed 1)' /usr/local/sbin/pcga-game-orchestrator || die "COD2 SP intro skip is missing the expected command-line argument"
[[ -f /etc/systemd/system/pcga-cdemu.service ]] || die "CDEmu appliance service was not installed"
[[ -x /usr/local/sbin/pcga-cdemu-bootstrap ]] || die "CDEmu VHBA bootstrap helper was not installed"
[[ -x /usr/local/sbin/pcga-cdemu-userspace-bootstrap ]] || die "CDEmu userspace bootstrap helper was not installed"
grep -Fq 'Restart=no' /etc/systemd/system/pcga-cdemu.service || die "CDEmu service can still enter a restart storm"
grep -Fq 'CDEmu userspace packages are not published' "$0" || die "Noble-safe CDEmu source fallback is missing from the upgrader"
grep -Fq 'libsndfile1-dev libsamplerate0-dev' "$0" || die "Noble-safe libMirage build dependencies are missing from the upgrader"
grep -Fq 'MIRAGE_VERSION="3.3.3"' /usr/local/sbin/pcga-cdemu-userspace-bootstrap || die "CDEmu userspace bootstrap is missing pinned libMirage source build"
grep -Fq 'COD2CD1 ISO loop-device fallback read probe: PASS' /usr/local/sbin/pcga-game-orchestrator || die "COD2 SP is missing non-destructive loop-media fallback when CDEmu is unavailable"
! grep -Fq 'exit 90' /usr/local/sbin/pcga-game-orchestrator || die "COD2 SP still tears down the stream when CDEmu is unavailable"
grep -Fq '"pcga-cdemu.service": "CDEmu Optical"' /usr/local/sbin/pcga-control || die "Streaming diagnostics do not include the CDEmu service"
grep -Fq 'devices_toml' /usr/local/sbin/pcga-game-orchestrator || die "Wolf app generation is missing dynamic optical device passthrough"
grep -Fq '/reg:32' /usr/local/sbin/pcga-game-orchestrator || die "Wine optical mapping is missing 32-bit drive-type registration"
grep -Fq '/reg:64' /usr/local/sbin/pcga-game-orchestrator || die "Wine optical mapping is missing 64-bit drive-type registration"
grep -Fq 'ln -s "$PCGA_VCD" "$WINEPREFIX/dosdevices/{letter}:"' /usr/local/sbin/pcga-game-orchestrator || die "Compatibility CD is missing overlay dosdevice mapping"
grep -Fq 'Win32 drive probe:' /usr/local/sbin/pcga-game-orchestrator || die "Compatibility CD is missing Win32 drive-type diagnostics"
grep -Fq 'DRIVE_CDROM (5)' /usr/local/sbin/pcga-game-orchestrator || die "Compatibility CD is missing DRIVE_CDROM validation"
grep -Fq 'optical-disc-set' /usr/local/sbin/pcga-game-disc-metadata || die "Game metadata collector is missing title-owned disc inventory"
grep -Fq '/tmp/pcga-disc-switch' /usr/local/sbin/pcga-game-orchestrator || die "Game runtime is missing live multi-disc switching"
grep -Fq 'COD2 synthetic optical setup source:' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup is missing synthetic optical six-disc presentation"
grep -Fq '_flatten_cod2_msi_media_table' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup is missing MSI logical-media flattening"
grep -Fq 'setup_source_msi_media_flattened_v01858' /usr/local/sbin/pcga-game-orchestrator || die "COD2 v0.18.69 MSI media-flatten migration marker is missing"
grep -Fq 'setup_source_multidisc_optical_v01866' /usr/local/sbin/pcga-game-orchestrator || die "COD2 v0.18.69 synthetic optical-source marker is missing"
grep -Fq 'authoritative-Media.idt-import-v01866-optical' /usr/local/sbin/pcga-game-orchestrator || die "COD2 v0.18.69 authoritative Media.idt optical rewrite is missing"
grep -Fq 'validated COD2DVD synthetic optical source is unavailable' /usr/local/sbin/pcga-game-orchestrator || die "COD2 v0.18.69 fail-closed synthetic optical guard is missing"
grep -Fq '.pcga-msi-media-flattened-v01866.json' /usr/local/sbin/pcga-game-orchestrator || die "COD2 v0.18.69 Media audit marker is missing"
grep -Fq '/dev/pcga-setup-media' /usr/local/sbin/pcga-game-orchestrator || die "COD2 synthetic D: mapping is missing the raw optical loop device"
grep -Fq 'COD2 MSI Media single-volume flatten marker v0.18.72 present' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup diagnostics are missing v0.18.69 MSI single-volume marker"
grep -Fq 'refreshing wineserver before COD2 D: optical mapping' /usr/local/sbin/pcga-game-orchestrator || die "COD2 v0.18.69 pre-D wineserver refresh is missing"
grep -Fq 'DOS-device symlink payload probe found D:/Setup/Data/main/iw_02.iwd' /usr/local/sbin/pcga-game-orchestrator || die "COD2 v0.18.69 direct DOS-device payload probe is missing"
grep -Fq 'restarting wineserver after COD2 D: optical registration' /usr/local/sbin/pcga-game-orchestrator || die "COD2 v0.18.69 post-registration wineserver refresh is missing"
grep -Fq 'setup_reason="setup-source-busy"' /usr/local/sbin/pcga-game-orchestrator || die "Mount-safe setup-source busy handling is missing"
grep -Fq 'recovered COD2 mounted setup-source failure before generic installer staging' /usr/local/sbin/pcga-game-orchestrator || die "COD2 v0.18.67 EROFS-state recovery is missing"
grep -Fq 'COD2 synthetic optical setup source is authoritative; skipped generic setup-source restaging' /usr/local/sbin/pcga-game-orchestrator || die "COD2 authoritative optical-source isolation is missing"
grep -Fq '_cod2_synthetic_setup_source_ready' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup source exact-mount validation is missing"
grep -Fq 'COD2 setup source lost its MSI media marker before launch' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup launch-time source guard is missing"
grep -Fq 'orchestrator traceback:' /usr/local/sbin/pcga-game-orchestrator || die "Per-game orchestrator traceback logging is missing"
grep -Fq 'COD2 MSI Media audit:' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup diagnostics are missing Media-table audit output"
grep -Fq 'PCGA_SETUP_WINDOWS_TARGET' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup is missing explicit Windows source-drive launch support"
grep -Fq 'Windows installer source forced to $app_win' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup is missing D-drive SourceDir diagnostics"
grep -Fq 'Windows installer-source probe found' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup is missing D-drive installer visibility probe"
grep -Fq "setup.exe command line remains unmodified" /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup is missing 1629-safe MSI logging policy"
grep -Fq "PCGA_SETUP_WINEDEBUG:-+msi,+msiexec" /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup is missing Wine MSI trace fallback"
grep -Fq "voicewarmupx" /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup is missing Windows Installer policy logging"
grep -Fq 'setup_launch_drive_repaired_v01860' /usr/local/sbin/pcga-game-orchestrator || die "COD2 v0.18.69 source-drive migration marker is missing"
grep -Fq 'setup_active = _setup_container_active_for_set(set_id)' /usr/local/sbin/pcga-game-orchestrator || die "Interactive setup promotion is missing live-container guard"
grep -Fq 'pcga_cod2_direct_payload_complete()' /usr/local/sbin/pcga-game-orchestrator || die "COD2 v0.18.72 direct-payload completion probe is missing"
grep -Fq 'd27cdb6e-ae6d-11cf-96b8-444553540000' /usr/local/sbin/pcga-game-orchestrator || die "COD2 v0.18.72 obsolete Shockwave Flash bypass signature is missing"
grep -Fq 'cod2_flash_launcher_bypassed_v01870' /usr/local/sbin/pcga-game-orchestrator || die "COD2 v0.18.72 host-side Flash-launcher recovery marker is missing"
grep -Fq 'def discover_launch_variants' /usr/local/sbin/pcga-game-orchestrator || die "v0.18.72 executable-role launch variant discovery is missing"
grep -Fq 'launch_variant_detection_v01871' /usr/local/sbin/pcga-game-orchestrator || die "v0.18.72 launch variant migration marker is missing"
grep -Fq 'PCGA_LAUNCH_VARIANT' /usr/local/sbin/pcga-game-orchestrator || die "v0.18.72 runtime launch-variant selector is missing"
grep -Fq 'def wolf_launch_variant_apps' /usr/local/sbin/pcga-game-orchestrator || die "v0.18.72 Wolf launch-variant app generation is missing"
grep -Fq 'stream_variant_apps' /usr/local/sbin/pcga-game-orchestrator || die "v0.18.72 Wolf variant-app state tracking is missing"
grep -Fq 'cod2-retail-safedisc-win32-prefix' /usr/local/sbin/pcga-game-compat-resolver || die "COD2 retail win32 SafeDisc compatibility rule is missing"
grep -Fq 'def compatibility_wine_arch' /usr/local/sbin/pcga-game-orchestrator || die "PC-game orchestrator is missing authoritative Wine-prefix architecture resolution"
grep -Fq 'def ensure_appliance_compatibility_rules' /usr/local/sbin/pcga-game-orchestrator || die "PC-game orchestrator is missing offline appliance compatibility persistence"
grep -Fq 'cod2_win32_prefix_migration_v01872' /usr/local/sbin/pcga-game-orchestrator || die "COD2 win64-to-win32 prefix migration is missing"
grep -Fq 'Wine prefix architecture mismatch: existing=' /usr/local/sbin/pcga-game-orchestrator || die "Interactive setup is missing Wine-prefix architecture validation"
grep -Fq 'COD2 single-player profile: preserved win32 install' /usr/local/sbin/pcga-game-orchestrator || die "COD2 runtime is missing isolated single-player startup diagnostics"
grep -Fq 'COD2 single-player hit the SafeDisc/SecDrv kernel-driver boundary' /usr/local/sbin/pcga-game-orchestrator || die "COD2 runtime is missing generalized SecDrv failure diagnostics"
grep -Fq 'COD2_WINE_RUNNER_VERSION = "11.19"' /usr/local/sbin/pcga-game-orchestrator || die "COD2 portable Wine runner is not pinned to 11.19"
grep -Fq '/opt/wine-11.19-amd64-wow64/bin/wine' /usr/local/sbin/pcga-game-orchestrator || die "COD2 portable Wine runner path is missing"
grep -Fq 'runtime_wine_runner_fallback_v01877' /usr/local/sbin/pcga-game-orchestrator || die "COD2 isolated Wine runner is missing non-destructive base-Wine fallback"
grep -Fq 'wine-11.19-amd64-wow64.tar.xz' /usr/local/sbin/pcga-game-orchestrator || die "COD2 portable Wine runner archive is missing"
grep -Fq 'a1fe858b45d12c9b16b91c7601d9b934f68430f7b6b95e240212ab6e2a198d8a' /usr/local/sbin/pcga-game-orchestrator || die "COD2 portable Wine runner checksum pin is missing"
grep -Fq 'runner-prefixes/${{PCGA_WINE_RUNNER}}' /usr/local/sbin/pcga-game-orchestrator || die "COD2 SP is missing runner-owned WoW64 prefix isolation"
grep -Fq "find /pcga-media -maxdepth 5 -type f -iname 'secdrv.sys'" /usr/local/sbin/pcga-game-orchestrator || die "COD2 SP is missing original-media SecDrv staging"
grep -Fq 'CoD2SP_s.exe Windows-version override: winxp' /usr/local/sbin/pcga-game-orchestrator || die "COD2 SP is missing scoped Wine XP compatibility override"
grep -Fq 'suppressing obsolete post-install Flash/OLE shell' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup is missing post-install OLE suppression"
grep -Fq '0x80040154' /usr/local/sbin/pcga-game-orchestrator || die "COD2 OLE recovery is missing generic class-not-registered detection"
grep -Fq 'last-failure.json' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing persisted launch-failure detail"
grep -Fq 'known legacy-DRM launch failure; closing compositor immediately' /usr/local/sbin/pcga-game-orchestrator || die "Known DRM failures still hold a black compositor grace screen"
grep -Fq '"runtime_failure":runtime_failure or None' "$STATUS_DIR/server.py" || die "Portal stream API is missing persisted runtime-failure exposure"
grep -Fq 'launch_variant' /usr/local/sbin/pcga-control || die "v0.18.72 control-plane launch-variant session ownership is missing"
grep -Fq 'launch_variant_default' "$STATUS_DIR/server.py" || die "v0.18.72 portal API launch-variant metadata is missing"
grep -Fq 'Choose mode' "$STATUS_DIR/server.py" || die "v0.18.72 portal library mode chooser is missing"
grep -Fq 'data-pc-stream-variant' "$STATUS_DIR/server.py" || die "v0.18.72 portal per-mode launch controls are missing"
command -v msiinfo >/dev/null 2>&1 || die "msiinfo is unavailable after msitools dependency installation"
command -v msibuild >/dev/null 2>&1 || die "msibuild is unavailable after msitools dependency installation"
command -v xorriso >/dev/null 2>&1 || die "xorriso is unavailable after synthetic-media dependency installation"
grep -Fq 'genuine synthetic COD2DVD ISO' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup is missing genuine synthetic optical-volume presentation"
grep -Fq 'Wine does not see COD2DVD as the D: volume label' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup is missing strict Wine volume-label validation"
grep -Fq 'synthetic COD2 D: is not DRIVE_CDROM (5)' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup is missing strict Win32 CD-ROM drive-type validation"
grep -Fq 'D: optical-media probe found' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup is missing synthetic optical payload verification"
grep -Fq 'Automatic synthetic setup media:' "$STATUS_DIR/server.py" || die "Portal stream toolbar is missing COD2 synthetic-media state"
grep -Fq 'def _disc_number_from_volume_label' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup is missing physical disc-number recovery from volume labels"
grep -Fq 'def _autorun_installer_target' /usr/local/sbin/pcga-game-orchestrator || die "PC game installer selection is missing autorun bootstrapper preference"
grep -Fq 'bundled_component_dirs' /usr/local/sbin/pcga-game-orchestrator || die "PC game installer selection is missing bundled prerequisite filtering"
grep -Fq 'portable_multidisc_repaired_v01841' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing multi-disc portable-state repair"
grep -Fq 'portable_multidisc_repaired_v01844' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing forced legacy multi-disc portable migration"
grep -Fq '_precanonicalize_local_identities' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing pre-deduplication identity normalization"
grep -Fq '_expand_duplicate_candidates' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing metadata/runtime sibling convergence"
grep -Fq 'def _ensure_portable_prefix_template' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing portable Wine-prefix seeding"
grep -Fq 'installer_selection_repaired_v01845' /usr/local/sbin/pcga-game-orchestrator || die "PC game installer selection is missing stale staged-target repair"
grep -Fq 'use the streamed disc controls when the installer requests another disc' /usr/local/sbin/pcga-game-orchestrator || die "Multi-disc installer staging is missing interactive disc-control guidance"
grep -Fq 'canonicalize_duplicate_source_mapping' /usr/local/sbin/pcga-game-orchestrator || die "PC-game orchestrator is missing duplicate title canonicalization"
grep -Fq 'recovered stale canonical catalog visibility' /usr/local/sbin/pcga-game-orchestrator || die "PC-game orchestrator is missing canonical visibility self-heal"
grep -Fq 'Set metadata owns canonical visibility' "$STATUS_DIR/server.py" || die "Portal PC-game library is missing stale hidden-state recovery"
grep -Fq 'wolf_remove_superseded_apps' /usr/local/sbin/pcga-game-orchestrator || die "PC-game orchestrator is missing superseded Wolf app cleanup"
grep -Fq 'normalize_install_template_permissions' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing ISO-template permission normalization"
grep -Fq 'chmod","-R","a+rX"' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing hardened installed-template permission repair"
grep -Fq 'idriver.exe' /usr/local/sbin/pcga-game-orchestrator || die "PC-game launcher is missing InstallShield helper rejection"
grep -Fq 'cdkey.exe' /usr/local/sbin/pcga-game-orchestrator || die "PC-game launcher is missing CD-key utility rejection"
grep -Fq 'fpupdate.exe' /usr/local/sbin/pcga-game-orchestrator || die "PC-game launcher is missing update-helper rejection"
grep -Fq 'repair_noncompilation_setup_scope' /usr/local/sbin/pcga-game-orchestrator || die "PC-game setup is missing single-title disc-root restaging"
grep -Fq 'setup_source_scope_verified_v01845' /usr/local/sbin/pcga-game-orchestrator || die "PC-game setup is missing v0.18.53 disc-root target verification"
grep -Fq 'def _bundled_payload_title' /usr/local/sbin/pcga-game-orchestrator || die "PC-game identity resolver is missing bundled payload-title rejection"
grep -Fq 'adberdr|adobereader|acrobatreader|acroread' /usr/local/sbin/pcga-game-orchestrator || die "PC-game identity resolver is missing Adobe Reader package-name rejection"
grep -Fq 'managed installer detected without CLR' /usr/local/sbin/pcga-game-orchestrator || die "PC-game setup is missing managed-installer runtime recovery"
grep -Fq '/run/pcga-game-disc-metadata.lock' /usr/local/sbin/pcga-game-disc-metadata || die "PC-game optical metadata collector is missing concurrent registry serialization"
grep -Fq 'compact mastering-label form' "$STATUS_DIR/server.py" || die "PC-game portal is missing canonical duplicate-card consolidation"
grep -Fq 'pc-game-disc-switch' /usr/local/sbin/pcga-control || die "Control plane is missing multi-disc switch action"
grep -Fq 'pc-game-disc-library' /usr/local/sbin/pcga-control || die "Control plane is missing preserved PC-game disc inventory action"
grep -Fq 'pc-game-disc-assign' /usr/local/sbin/pcga-control || die "Control plane is missing manual PC-game disc assignment action"
grep -Fq 'pc-game-title-create' /usr/local/sbin/pcga-control || die "Control plane is missing manual PC-game title creation action"
grep -Fq 'pc-game-metadata-search' /usr/local/sbin/pcga-control || die "Control plane is missing PC-game database search action"
grep -Fq 'pc-game-metadata-apply' /usr/local/sbin/pcga-control || die "Control plane is missing selected metadata profile application"
grep -Fq 'RAWG_API_KEY' /usr/local/sbin/pcga-control || die "Control plane is missing RAWG secret-backed metadata provider"
grep -Fq 'locked_by_user' /usr/local/sbin/pcga-game-orchestrator || die "PC-game orchestrator can overwrite a user-selected database profile"
grep -Fq 'Game Database' "$STATUS_DIR/server.py" || die "Portal UI is missing PC-game database search"
grep -Fq 'Search game database' "$STATUS_DIR/server.py" || die "Preserved disc workflow is missing database-profile creation"
grep -Fq 'RAWG ↗' "$STATUS_DIR/server.py" || die "Portal UI is missing RAWG attribution links"
grep -Fq 'snapshot_schema:2' "$STATUS_DIR/server.py" || die "Streaming diagnostics are missing compact snapshot schema"
grep -Fq 'historical duplicates' /usr/local/sbin/pcga-control || die "Streaming diagnostics are missing canonical current-log filtering"
grep -Fq 'sync_preserved_sidecars' /usr/local/sbin/pcga-game-intake || die "Game intake is missing preservation-sidecar ownership synchronization"
grep -Fq 'Preserved PC Game Discs' "$STATUS_DIR/server.py" || die "Portal UI is missing preserved PC-game disc browser"
grep -Fq "letter=chr(ord('e')+pos)" /usr/local/sbin/pcga-game-orchestrator || die "Game runtime is missing stable all-disc mappings"
grep -Fq 'resetting pre-compositor Wine helpers before installer GUI launch' /usr/local/sbin/pcga-game-orchestrator || die "PC-game setup runtime is missing pre-compositor wineserver reset"
grep -Fq 'compatibility_runtime_environment' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing normalized compatibility environment application"
grep -Fq 'known-good launch arguments' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing normalized compatibility launch arguments"
grep -Fq 'compatibility_runtime_environment_prelude' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing scoped compatibility environment support"
grep -Fq 'include_runtime_environment=False' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime may leak game graphics environment into Sway"
grep -Fq 'applying game-process environment' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing scoped compatibility diagnostics"
grep -Fq 'waiting for detached Wine installer processes' /usr/local/sbin/pcga-game-orchestrator || die "Interactive PC-game setup is missing detached-installer supervision"
grep -Fq 'monitoring detached Wine child processes' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing detached-child/window supervision"
grep -Fq 'pcga_wine_debugger_active()' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing Wine crash/debugger detection"
python3 -W error::SyntaxWarning -m py_compile /usr/local/sbin/pcga-game-compat-test
grep -Fq 'clean_wolf_children' /usr/local/sbin/pcga-game-compat-test || die "PC-game compatibility sweep is missing transient Wolf cleanup"
grep -Fq 'failure_traceback' /usr/local/sbin/pcga-game-compat-test || die "PC-game compatibility sweep is missing per-game failure tracebacks"
grep -Fq 'x11-unix' /usr/local/sbin/pcga-game-compat-test || die "PC-game compatibility sweep is missing Wolf X11 runtime emulation"
grep -Fq 'ignored_records' /usr/local/sbin/pcga-game-compat-test || die "PC-game compatibility sweep is missing source-only record classification"
grep -Fq '_wolf_reconcile_all_launchable_apps' /usr/local/sbin/pcga-game-orchestrator || die "PC-game orchestrator is missing registry-wide Wolf app reconciliation"
grep -Fq 'isolated-wolf-equivalent-runtime' /usr/local/sbin/pcga-game-compat-test || die "PC-game compatibility sweep is missing Wolf-equivalent runtime probes"
grep -Fq 'XDG_RUNTIME_DIR=/run/user/wolf' /usr/local/sbin/pcga-game-compat-test || die "PC-game compatibility sweep is missing private Wolf XDG runtime emulation"
grep -Fq 'GOW_REQUIRED_DEVICES=/dev/input/event* /dev/dri/* /dev/snd/* /dev/nvidia* /dev/pcga-media-disc*' /usr/local/sbin/pcga-game-compat-test || die "PC-game compatibility sweep is missing production-equivalent device group discovery"
grep -Fq 'base_required_devices = "/dev/input/event* /dev/dri/* /dev/snd/* /dev/nvidia* /dev/pcga-media-disc*"' /usr/local/sbin/pcga-game-orchestrator || die "Wolf game profiles are missing optical/render device group discovery"
grep -Fq 'Wolf reload dropped' /usr/local/sbin/pcga-game-orchestrator || die "Wolf post-reload managed app verification is missing"
grep -Fq 'wolf_registration_quarantined_v01869' /usr/local/sbin/pcga-game-orchestrator || die "Wolf per-title rejection quarantine is missing"
grep -Fq 'quarantined without further automatic daemon reloads' /usr/local/sbin/pcga-game-orchestrator || die "Wolf reload-storm breaker is missing"
grep -Fq '"--metadata-only", "--no-network", "--force"' /usr/local/sbin/pcga-control || die "Portal Retry stream does not force a quarantined Wolf registration retry"
grep -Fq 'portable_multidisc_repaired_v01849' /usr/local/sbin/pcga-game-orchestrator || die "Multi-disc portable runtime-media repair is missing"
grep -Fq 'persisted_media_isos' /usr/local/sbin/pcga-game-orchestrator || die "Persisted optical-media recovery helper is missing"
grep -Fq 'recover_related_preserved_sources' /usr/local/sbin/pcga-game-orchestrator || die "Canonical titles cannot recover title-linked preserved source rows"
grep -Fq 'stage_multidisc_installer_from_isos' /usr/local/sbin/pcga-game-orchestrator || die "Multi-disc all-media installer staging is missing"
grep -Fq 'repair_cod2_multidisc_setup_source' /usr/local/sbin/pcga-game-orchestrator || die "COD2 host-side multi-disc SourceDir restaging is missing"
grep -Fq 'def _copy_cod2_disc_payload' /usr/local/sbin/pcga-game-orchestrator || die "COD2 byte-only disc overlay helper is missing"
grep -Fq 'COD2 staging ignored non-payload source marker' /usr/local/sbin/pcga-game-orchestrator || die "COD2 pseudo-file staging guard is missing"
grep -Fq 'setup_source_multidisc_merged_v01858' /usr/local/sbin/pcga-game-orchestrator || die "COD2 v0.18.69 merged-source migration marker is missing"
grep -Fq 'D: optical-media probe found' /usr/local/sbin/pcga-game-orchestrator || die "COD2 setup runtime is missing optical SourceDir verification"
grep -Fq 'setup_bootstrap_disc' /usr/local/sbin/pcga-game-orchestrator || die "Multi-disc setup bootstrap slot tracking is missing"
grep -Fq 'pcga.compat.probe=1' /usr/local/sbin/pcga-game-compat-test || die "Compatibility probes are not isolated from production transient cleanup"
grep -Fq 'AUXILIARY_GAME_WINDOW_RE' /usr/local/sbin/pcga-game-compat-test || die "Compatibility sweep is missing auxiliary-window classification"
grep -Fq '"schema": 4' /usr/local/sbin/pcga-game-compat-test || die "Compatibility report schema 4 is missing"
grep -Fq 'PORTAL MANUAL TEST CANDIDATES' /usr/local/sbin/pcga-game-compat-test || die "Compatibility sweep is missing portal manual-test summary output"
grep -Fq 'portal_test_candidates' /usr/local/sbin/pcga-game-compat-test || die "Compatibility report is missing portal test candidate records"
grep -Fq 'game-compat-report [--summary]' /usr/local/bin/game-archive || die "game-archive wrapper is missing compatibility report summary mode"
grep -Fq 'def wolf_internal_app_title' /usr/local/sbin/pcga-game-orchestrator || die "PC-game Wolf registration is missing immutable runtime application identifiers"
grep -Fq 'removed terminally failed transient runtime container' /usr/local/sbin/pcga-game-orchestrator || die "PC-game orchestrator is missing failed transient-container reaping"
grep -Fq 'OnUnitActiveSec=1min' /etc/systemd/system/pcga-game-orchestrator.timer || die "PC-game orchestrator recovery timer is not using the one-minute stabilization cadence"
grep -Fq 'launchable' "$STATUS_DIR/server.py" || die "PC-game portal is missing retryable launch-state controls"
grep -Fq 'detached Wine process crashed; debugger detected' /usr/local/sbin/pcga-game-orchestrator || die "PC-game runtime is missing detached crash teardown"
grep -Fq 'Selected direct known-good game executable' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing legacy launcher-target repair"
grep -Fq 'Empire at War windowed compatibility' /usr/local/sbin/pcga-game-orchestrator || die "PC game runtime is missing Empire at War compositor compatibility"
grep -Fq 'PREVIEW_CLIP_SECONDS = 20' /usr/local/sbin/pcga-manual-review || die "Manual Review is missing FFmpeg short-preview support"
grep -Fq 'proxy_review_preview' "$STATUS_DIR/server.py" || die "Portal status server is missing Manual Review preview proxy"
grep -Fq 'autorun-product-evidence' /usr/local/sbin/pcga-game-disc-metadata || die "PC game metadata collector is missing autorun product-identity evidence"
grep -Fq '_autorun_product_hints' /usr/local/sbin/pcga-game-orchestrator || die "PC game orchestrator is missing autorun product-identity reconciliation"
grep -Fq 'bundled demo executables' /usr/local/sbin/pcga-game-orchestrator || die "PC game identity resolver is missing stale/demo evidence isolation"

python3 -W error::SyntaxWarning -m py_compile /usr/local/sbin/pcga-dedupe
systemd-analyze verify /etc/systemd/system/pcga-dedupe.service /etc/systemd/system/pcga-dedupe.timer >/dev/null 2>&1 || true
systemctl is-enabled pcga-dedupe.timer >/dev/null || die "Dedupe timer is not enabled"
DEDUPE_SMOKE="$(mktemp -d /tmp/pcga-dedupe-smoke.XXXXXX)"
mkdir -p "$DEDUPE_SMOKE/media/library"
if ! PCGA_ROOT_OVERRIDE="$DEDUPE_SMOKE" PCGA_DEDUPE_IGNORE_ARM=1 /usr/local/sbin/pcga-dedupe audit --min-size 1TiB --scheduled >/dev/null; then
  rm -rf "$DEDUPE_SMOKE"
  die "Dedupe audit sanity check failed"
fi
rm -rf "$DEDUPE_SMOKE"
nas_json="$(/usr/local/sbin/pcga-nas-storage status)" || die "NAS storage helper status failed"
python3 - "$nas_json" <<'PY_NAS_VALIDATE'
import json,sys
x=json.loads(sys.argv[1])
assert x.get('version') == '0.19.0'
assert x.get('mount_point') == '/mnt/pcga-nas'
assert x.get('mode') in {'mirror','offload'}
assert isinstance(x.get('libraries'),list)
PY_NAS_VALIDATE
systemctl is-enabled pcga-nas-sync.timer >/dev/null || die "NAS maintenance timer is not enabled"

grep -Fq 'NAS storage tier' "$STATUS_DIR/server.py" || die "Portal UI is missing NAS storage controls"
grep -Fq 'nas-configure' /usr/local/sbin/pcga-control || die "Control plane is missing NAS configuration action"
[[ -x /usr/local/sbin/pcga-nas-discover ]] || die "NAS discovery helper was not installed"
grep -Fq 'cc-nas-discovery-results' "$STATUS_DIR/server.py" || die "Portal is missing NAS discovery results UI"
grep -Fq 'nas-discover-start' /usr/local/sbin/pcga-control || die "Control plane is missing NAS discovery start action"
/usr/local/sbin/pcga-nas-discover status >/dev/null || die "NAS discovery status helper failed"


grep -Fq 'podcast_search' /usr/local/sbin/pcga-control || die "Audio control plane is missing podcast search"
grep -Fq 'https://gpodder.net/search.json' /usr/local/sbin/pcga-control || die "Podcast discovery is missing the open gPodder directory"
! grep -Fq 'itunes.apple.com' /usr/local/sbin/pcga-control || die "Podcast discovery still depends on the Apple Search API"
grep -Fq 'gpodder_update_episode_actions' /usr/local/sbin/pcga-control || die "Audio control plane is missing AntennaPod/gPodder episode synchronization"
grep -Fq 'gpodder_subscription_changes' /usr/local/sbin/pcga-control || die "Audio control plane is missing AntennaPod/gPodder subscription synchronization"
grep -Fq 'proxy_gpodder' "$STATUS_DIR/server.py" || die "Portal proxy is missing AntennaPod/gPodder routes"
grep -Fq '/api/2/auth/' "$STATUS_DIR/server.py" || die "Portal proxy is missing AntennaPod login routes"
grep -Fq 'open_podcast_subscriptions' /usr/local/sbin/pcga-control || die "Legacy Open Podcast compatibility endpoint is missing"
grep -Fq 'librivox_collect' /usr/local/sbin/pcga-control || die "Audio control plane is missing LibriVox collection"
grep -Fq 'https://librivox.org/api/feed/audiobooks/' /usr/local/sbin/pcga-control || die "Audiobook search is missing the canonical LibriVox API URL"
grep -Fq 'path_url = LIBRIVOX_API_URL' /usr/local/sbin/pcga-control || die "Audiobook search is missing LibriVox path-style fallback"
grep -Fq 'https://archive.org/advancedsearch.php' /usr/local/sbin/pcga-control || die "Audiobook search is missing Internet Archive fallback"
grep -Fq 'if exc.code not in {403,429}' /usr/local/sbin/pcga-control || die "Audiobook search is missing LibriVox 403/429 fallback gating"
grep -Fq 'def _internet_archive_detail' /usr/local/sbin/pcga-control || die "Audiobook fallback is missing Internet Archive chapter/detail support"
grep -Fq 'Internet Archive collection' "$STATUS_DIR/server.py" || die "Portal audiobook UI is missing fallback-provider guidance"
grep -Fq '/api/audio/remote' "$STATUS_DIR/server.py" || die "Portal is missing signed remote-audio proxy"
grep -Fq 'openPodcastBrowser' "$STATUS_DIR/server.py" || die "Portal is missing podcast UI"
grep -Fq 'openAudiobookBrowser' "$STATUS_DIR/server.py" || die "Portal is missing audiobook UI"
grep -Fq 'data-upload-kind="audiobook"' "$STATUS_DIR/server.py" || die "Portal audiobook UI is missing dedicated upload button"
grep -Fq "UPLOAD_HINTS={'auto','movie','tv','music','audiobook'" /usr/local/sbin/pcga-public-media || die "Content intake service is missing audiobook upload hint"
grep -Fq 'def route_audiobook_session' /usr/local/sbin/pcga-public-media || die "Content intake service is missing audiobook batch/ZIP routing"
grep -Fq "'.m4b'" /usr/local/sbin/pcga-public-media || die "Audiobook upload path is missing M4B support"
grep -Fq 'def _local_audiobook_detail' /usr/local/sbin/pcga-control || die "Audio control plane is missing uploaded-audiobook detail support"
grep -Fq 'PCGA local upload' /usr/local/sbin/pcga-control || die "Audio control plane is missing local audiobook provider"
grep -Fq 'def audiobook_search' /usr/local/sbin/pcga-control || die "Audio control plane is missing unified local + online audiobook search"
grep -Fq '/audio/audiobooks/search' /usr/local/sbin/pcga-control || die "Audio control plane is missing unified audiobook search route"
grep -Fq 'recent_uploaded' /usr/local/sbin/pcga-control || die "Audio collection API is missing recently uploaded books"
grep -Fq 'def _local_audiobook_art_rel' /usr/local/sbin/pcga-control || die "Local audiobook cover fallback scan is missing"
grep -Fq 'Search local library + LibriVox' "$STATUS_DIR/server.py" || die "Portal audiobook search does not expose local + LibriVox search"
grep -Fq 'Recently uploaded' "$STATUS_DIR/server.py" || die "Portal audiobook UI is missing the recently uploaded shelf"
grep -Fq 'def _search_cached' "$STATUS_DIR/server.py" || die "Portal search cache helper is missing"
grep -Fq 'def portal_global_search' "$STATUS_DIR/server.py" || die "Portal global-search backend is missing"
grep -Fq '/api/search/global' "$STATUS_DIR/server.py" || die "Portal global-search endpoint is missing"
grep -Fq 'id="global-search-open"' "$STATUS_DIR/server.py" || die "Portal landing page is missing the Global Search button"
grep -Fq 'id="global-search-modal"' "$STATUS_DIR/server.py" || die "Portal global-search modal is missing"
grep -Fq 'id="setting-layout-mode"' "$STATUS_DIR/server.py" || die "Portal Display settings are missing the adaptive layout selector"
grep -Fq 'function detectDeviceLayout()' "$STATUS_DIR/server.py" || die "Portal is missing automatic TV/desktop/ultrawide/tablet/mobile detection"
grep -Fq 'data-device-layout="tv"' "$STATUS_DIR/server.py" || die "Portal is missing its TV-safe initial layout marker"
grep -Fq 'body[data-device-layout="ultrawide"]' "$STATUS_DIR/server.py" || die "Portal is missing ultrawide responsive geometry"
grep -Fq 'body[data-device-layout="mobile"]' "$STATUS_DIR/server.py" || die "Portal is missing mobile responsive geometry"
grep -Fq 'def audio_local_global_search' /usr/local/sbin/pcga-control || die "Audio control plane is missing network-free local Global Search"
grep -Fq '/audio/local-search' /usr/local/sbin/pcga-control || die "Audio control plane is missing local Global Search route"
[[ -d "$ROOT/media/library/audio/audiobooks/uploads" ]] || die "Uploaded-audiobook library directory missing"
[[ -d "$ROOT/media/library/audio/audiobooks/librivox" ]] || die "Audio library directory missing"
log "PCGA v$VERSION Control Center and appliance control plane installed successfully."
if [[ "$LAN_HTTPS_PORT" == 443 ]]; then
  log "Friendly LAN portal: https://pcga.portal/"
  log "mDNS fallback: https://pcga.local/"
else
  log "Friendly LAN portal: https://pcga.portal:${LAN_HTTPS_PORT}/"
  log "mDNS fallback: https://pcga.local:${LAN_HTTPS_PORT}/"
fi
log "LAN DNS server: ${PCGA_LAN_IP}:53. Configure your router's local DNS/host override or LAN clients to use it for pcga.portal."
log "Backup: $BACKUP"
log "Sorter timer: $(systemctl list-timers --all --no-legend pcga-media-sort.timer 2>/dev/null | head -n1 | xargs || true)"
log "Classifier timer: $(systemctl list-timers --all --no-legend pcga-metadata-classify.timer 2>/dev/null | head -n1 | xargs || true)"
log "Optical insertion now passes through media identification before ARM or PC/data-disc preservation is selected."

# v0.19.11 compatibility management smoke-check; UMU remains user-initiated.
[[ -x /usr/local/sbin/pcga-store-compat ]] || die "Store Proton/UMU helper missing"
[[ -f /etc/systemd/system/pcga-store-umu.service ]] || die "UMU preparation unit missing"
grep -Fq 'store-compat-modal' "$STATUS_DIR/server.py" || die "Store compatibility UI missing"
grep -Fq 'PCGA_STORE_COMPAT_RUNNER' /usr/local/sbin/pcga-store-game-startup || die "Store compatibility launch wiring missing"
