#!/usr/bin/env python3
"""PC Game Archive pipeline status and manual-classification portal.

Runs as a hardened read-only sidecar. Manual classification is exposed through
portal-owned JSON endpoints backed by pcga-manual-review, so the container retains
no archive write access and the browser never receives the review service token.
Only the Python standard library is required.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import ipaddress
import datetime as dt
import difflib
import html
import http.client
import json
import mimetypes
import os
import re
from pathlib import Path
import shutil
import socket
import ssl
import sqlite3
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, quote, urlencode, parse_qs, unquote
import urllib.error
import urllib.request
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed

VERSION = "0.19.13"
ARM_DB = Path("/home/arm/db/arm.db")
ARM_LOGS = Path("/home/arm/logs")
PROGRESS_DIR = ARM_LOGS / "progress"
RAW = Path("/home/arm/media/raw")
TRANSCODE = Path("/home/arm/media/transcode")
COMPLETED = Path("/home/arm/media/completed")
MUSIC = Path("/home/arm/music")
STATUS_ROOT = Path("/pcga/status")
PENDING = STATUS_ROOT / "metadata-pending"
QUAR_UNIDENTIFIED = STATUS_ROOT / "quarantine" / "unidentified"
LIBRARY = STATUS_ROOT / "library"
PHOTOS = LIBRARY / "photos"
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp"}
INGEST = STATUS_ROOT / "ingest"
DRIVES_FILE = STATUS_ROOT / "media-drives"
ROLES_FILE = STATUS_ROOT / "optical-drive-roles.tsv"
OPTICAL_HEALTH_DIR = STATUS_ROOT / "optical-health"
OPTICAL_DISPATCH_DIR = STATUS_ROOT / "optical-dispatch"
CONFIG_FILE = Path("/etc/arm/config/arm.yaml")

def _container_default_gateway() -> str:
    """Return this container network namespace's IPv4 default gateway.

    host.docker.internal normally resolves to docker0 on Linux, which is wrong
    when pcga-status is attached to a user-defined Compose bridge. Reading the
    kernel route table makes the portal resilient even when older compose files
    are missing the explicit PCGA_*_UPSTREAM environment entries.
    """
    try:
        rows = Path("/proc/net/route").read_text(encoding="utf-8", errors="replace").splitlines()[1:]
        for row in rows:
            fields = row.split()
            if len(fields) < 3 or fields[1] != "00000000":
                continue
            raw = bytes.fromhex(fields[2])
            if len(raw) == 4:
                return socket.inet_ntoa(raw[::-1])
    except Exception:
        pass
    return "host.docker.internal"

_CONTAINER_GATEWAY = _container_default_gateway()
REVIEW_UPSTREAM = os.environ.get("PCGA_REVIEW_UPSTREAM", "http://host.docker.internal:8097").rstrip("/")
REVIEW_TOKEN_FILE = Path(os.environ.get("PCGA_REVIEW_TOKEN_FILE", "/pcga/secrets/manual-review-token"))
PUBLIC_MEDIA_UPSTREAM = os.environ.get("PCGA_PUBLIC_MEDIA_UPSTREAM", f"http://{_CONTAINER_GATEWAY}:8099").rstrip("/")
CONTROL_UPSTREAM = os.environ.get("PCGA_CONTROL_UPSTREAM", f"http://{_CONTAINER_GATEWAY}:8100").rstrip("/")
CONTROL_TOKEN_FILE = Path(os.environ.get("PCGA_CONTROL_TOKEN_FILE", "/pcga/secrets/control-token"))
TOOL_HOST = os.environ.get("PCGA_TOOL_HOST", "host.docker.internal")
JELLYFIN_PORT = int(os.environ.get("PCGA_JELLYFIN_PORT", "8096"))
IMMICH_PORT = int(os.environ.get("PCGA_IMMICH_PORT", "2283"))
ROMM_PORT = int(os.environ.get("PCGA_ROMM_PORT", "8082"))
ARM_PORT = int(os.environ.get("PCGA_ARM_PORT", "8081"))
LANCOMMANDER_PORT = int(os.environ.get("PCGA_LANCOMMANDER_PORT", "1337"))
LANCOMMANDER_DATA = Path(os.environ.get("PCGA_LANCOMMANDER_DATA", "/pcga/lancommander"))
PCGA_GAME_INTAKE = Path(os.environ.get("PCGA_GAME_INTAKE", "/pcga/game-intake"))
PCGA_GAME_INSTALLS = Path(os.environ.get("PCGA_GAME_INSTALLS", "/pcga/game-installs"))
PCGA_HEROIC = Path(os.environ.get("PCGA_HEROIC_STATE", "/pcga/heroic"))
PCGA_HEROIC_CATALOG = PCGA_HEROIC / "catalog.json"
PCGA_STORE_GAMES = PCGA_HEROIC / "store-games.json"
PCGA_HEROIC_STATUS = PCGA_HEROIC / "status.json"
HEROIC_LAUNCHER_SID = "heroic-library-manager"
WOLFDEN_PORT = int(os.environ.get("PCGA_WOLFDEN_PORT", "8080"))
MOONLIGHT_WEB_PORT = int(os.environ.get("PCGA_MOONLIGHT_WEB_PORT", "8101"))
MOONLIGHT_WEB_LANES = max(1, min(8, int(os.environ.get("PCGA_MOONLIGHT_WEB_LANES", "4"))))
MOONLIGHT_WEB_UPSTREAM = os.environ.get("PCGA_MOONLIGHT_WEB_UPSTREAM", f"https://host.docker.internal:{MOONLIGHT_WEB_PORT}").rstrip("/")
MOONLIGHT_WEB_STATE = Path(os.environ.get("PCGA_MOONLIGHT_WEB_STATE", "/var/lib/pc-game-archive/bootstrap/moonlight-web.json"))
TLS_CA_FILE = Path(os.environ.get("PCGA_TLS_CA_FILE", "/pcga/tls/pcga-ca.crt"))
STATUS_TLS_PORT = int(os.environ.get("PCGA_STATUS_TLS_PORT", "8443"))
PORTAL_DNS_NAME = os.environ.get("PCGA_PORTAL_DNS_NAME", "pcga.portal").strip() or "pcga.portal"
LAN_HTTPS_PORT = int(os.environ.get("PCGA_LAN_HTTPS_PORT", "8443"))
STATUS_TLS_CERT = Path(os.environ.get("PCGA_STATUS_TLS_CERT", "/pcga/tls/pcga-server.crt"))
STATUS_TLS_KEY = Path(os.environ.get("PCGA_STATUS_TLS_KEY", "/pcga/tls/pcga-server.key"))
JELLYFIN_TOKEN_FILE = Path(os.environ.get("PCGA_JELLYFIN_TOKEN_FILE", "/pcga/secrets/jellyfin-api-key"))
ROMM_CREDS_FILE = Path(os.environ.get("PCGA_ROMM_CREDS_FILE", "/pcga/secrets/romm-bootstrap.env"))
JELLYFIN_USER_ID = os.environ.get("PCGA_JELLYFIN_USER_ID", "").strip()
JELLYFIN_DEVICE_ID = os.environ.get("PCGA_JELLYFIN_DEVICE_ID", "pcga-tv-portal").strip() or "pcga-tv-portal"

VIDEO_QUALITY_PROFILES = {
    "best": {"label": "Best available", "max_width": None, "max_height": None, "bitrate": 50_000_000},
    "auto": {"label": "Auto", "max_width": None, "max_height": None, "bitrate": 12_000_000},
    "2160p": {"label": "4K / 2160p", "max_width": 3840, "max_height": 2160, "bitrate": 25_000_000},
    "1080p": {"label": "1080p", "max_width": 1920, "max_height": 1080, "bitrate": 10_000_000},
    "720p": {"label": "720p", "max_width": 1280, "max_height": 720, "bitrate": 5_000_000},
    "480p": {"label": "480p", "max_width": 854, "max_height": 480, "bitrate": 2_500_000},
    "360p": {"label": "360p", "max_width": 640, "max_height": 360, "bitrate": 1_200_000},
}

def jellyfin_video_quality(name: str) -> tuple[str, dict]:
    key = str(name or "auto").strip().lower()
    if key not in VIDEO_QUALITY_PROFILES:
        key = "auto"
    return key, VIDEO_QUALITY_PROFILES[key]

def _stream_index(value, default=None):
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _jellyfin_stream_label(stream: dict, kind: str) -> str:
    index = _stream_index(stream.get("Index"), 0) or 0
    display = str(stream.get("DisplayTitle") or stream.get("Title") or "").strip()
    language = str(stream.get("Language") or "").strip()
    codec = str(stream.get("Codec") or "").upper().strip()
    parts = []
    if display:
        parts.append(display)
    elif language:
        parts.append(language.upper())
    else:
        parts.append(f"{kind.title()} {index}")
    if kind == "audio":
        channels = _stream_index(stream.get("Channels"), 0) or 0
        detail = " / ".join(x for x in (codec, f"{channels}ch" if channels else "") if x)
        if detail and detail.lower() not in parts[0].lower():
            parts.append(detail)
    elif codec and codec.lower() not in parts[0].lower():
        parts.append(codec)
    flags = []
    if stream.get("IsDefault"):
        flags.append("default")
    if stream.get("IsForced"):
        flags.append("forced")
    if flags:
        parts.append(", ".join(flags))
    return " • ".join(parts)

def jellyfin_media_streams(source: dict) -> dict:
    streams = source.get("MediaStreams") or []
    audio = []
    subtitles = []
    video = None
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        kind = str(stream.get("Type") or "").lower()
        idx = _stream_index(stream.get("Index"))
        if idx is None:
            continue
        entry = {
            "index": idx,
            "label": _jellyfin_stream_label(stream, kind or "stream"),
            "language": stream.get("Language") or None,
            "codec": stream.get("Codec") or None,
            "title": stream.get("Title") or stream.get("DisplayTitle") or None,
            "default": bool(stream.get("IsDefault")),
            "forced": bool(stream.get("IsForced")),
        }
        if kind == "audio":
            entry["channels"] = _stream_index(stream.get("Channels"), 0) or 0
            audio.append(entry)
        elif kind == "subtitle":
            entry["external"] = bool(stream.get("IsExternal") or stream.get("SupportsExternalStream"))
            subtitles.append(entry)
        elif kind == "video" and video is None:
            video = {
                **entry,
                "width": _stream_index(stream.get("Width"), 0) or 0,
                "height": _stream_index(stream.get("Height"), 0) or 0,
                "bitrate": _stream_index(stream.get("BitRate"), 0) or 0,
                "bit_depth": _stream_index(stream.get("BitDepth"), 0) or 0,
                "hdr_type": stream.get("VideoRangeType") or stream.get("VideoRange") or None,
            }
    return {"audio": audio, "subtitles": subtitles, "video": video}

def jellyfin_video_stream_params(*, media_source_id: str = "", play_session_id: str = "", start_ticks: int = 0, quality: str = "auto", audio_stream_index=None, subtitle_stream_index=None) -> dict[str, str]:
    quality_key, profile = jellyfin_video_quality(quality)
    params = {
        "static": "false",
        "deviceId": JELLYFIN_DEVICE_ID,
        "videoCodec": "h264",
        "audioCodec": "aac",
        "maxAudioChannels": "6",
        "audioBitRate": "192000",
        "videoBitRate": str(profile["bitrate"]),
        "requireAvc": "true",
        "enableAutoStreamCopy": "true",
        "allowVideoStreamCopy": "true",
        "allowAudioStreamCopy": "true",
        "transcodingMaxAudioChannels": "6",
        "context": "Streaming",
    }
    if profile.get("max_width"):
        params["maxWidth"] = str(profile["max_width"])
    if profile.get("max_height"):
        params["maxHeight"] = str(profile["max_height"])
    if media_source_id:
        params["mediaSourceId"] = media_source_id
    if play_session_id:
        params["playSessionId"] = play_session_id
    if start_ticks:
        params["startTimeTicks"] = str(max(0, int(start_ticks)))
    ai = _stream_index(audio_stream_index)
    if ai is not None and ai >= 0:
        params["audioStreamIndex"] = str(ai)
    si = _stream_index(subtitle_stream_index)
    if si is not None and si >= 0:
        params["subtitleStreamIndex"] = str(si)
        # Encode is the compatibility-first path: text, styled ASS/SSA and image
        # subtitles all remain selectable at the cost of a video transcode.
        params["subtitleMethod"] = "Encode"
    return params



def review_token() -> str | None:
    try:
        token = REVIEW_TOKEN_FILE.read_text(encoding="utf-8", errors="replace").strip()
        return token or None
    except OSError:
        return None


def review_api(path: str, payload: dict | None = None) -> tuple[int, dict]:
    token = review_token()
    if not token:
        return HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": "review-token-unavailable", "detail": "PCGA cannot read the manual-review service credential"}
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Accept": "application/json", "X-PCGA-Review-Token": token, "User-Agent": f"PCGameArchive/{VERSION}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(REVIEW_UPSTREAM + path, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8", "replace") or "{}")
            return response.status, body if isinstance(body, dict) else {"ok": False, "error": "invalid-review-response"}
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8", "replace") or "{}")
        except Exception:
            body = {"ok": False, "error": "review-http-error", "detail": f"HTTP {exc.code}"}
        return exc.code, body if isinstance(body, dict) else {"ok": False, "error": "invalid-review-response"}
    except Exception as exc:
        return HTTPStatus.BAD_GATEWAY, {"ok": False, "error": "review-unavailable", "detail": type(exc).__name__}



def jellyfin_token() -> str | None:
    try:
        token = JELLYFIN_TOKEN_FILE.read_text(encoding="utf-8", errors="replace").strip()
        return token or None
    except OSError:
        return None


def jellyfin_headers() -> dict[str, str]:
    token = jellyfin_token()
    if not token:
        return {}
    return {
        "Accept": "application/json",
        "Authorization": (
            'MediaBrowser Client="PCGA TV Portal", Device="media-stripe1", '
            'DeviceId="pcga-tv-portal", Version="0.19.0", Token="' + token + '"'
        ),
    }


def jellyfin_request(path: str, method: str = "GET", body: bytes | None = None, timeout: float = 3.0):
    headers = jellyfin_headers()
    if not headers:
        raise RuntimeError("Jellyfin token unavailable")
    if body is not None:
        headers["Content-Type"] = "application/json"
    url = f"http://{TOOL_HOST}:{JELLYFIN_PORT}{path}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def jellyfin_sessions() -> list[dict]:
    status, _, raw = jellyfin_request("/Sessions", timeout=3.0)
    if status < 200 or status >= 300:
        raise RuntimeError(f"Jellyfin /Sessions returned HTTP {status}")
    data = json.loads(raw.decode("utf-8", "replace") or "[]")
    return data if isinstance(data, list) else []


def active_audio_session(sessions: list[dict] | None = None) -> dict | None:
    sessions = sessions if sessions is not None else jellyfin_sessions()
    candidates = []
    for session in sessions:
        item = session.get("NowPlayingItem") or {}
        media_type = str(item.get("MediaType") or "").lower()
        item_type = str(item.get("Type") or "").lower()
        if media_type != "audio" and item_type != "audio":
            continue
        play = session.get("PlayState") or {}
        score = (
            1 if session.get("IsActive") else 0,
            1 if not play.get("IsPaused") else 0,
            str(session.get("LastPlaybackCheckIn") or session.get("LastActivityDate") or ""),
        )
        candidates.append((score, session))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def jellyfin_now_playing() -> dict:
    if not jellyfin_token():
        return {"available": False, "reason": "token-unavailable", "playing": False}
    try:
        session = active_audio_session()
    except Exception as exc:
        return {"available": False, "reason": type(exc).__name__, "playing": False}
    if not session:
        return {"available": True, "playing": False}
    item = session.get("NowPlayingItem") or {}
    play = session.get("PlayState") or {}
    artists = item.get("Artists") or []
    if isinstance(artists, str):
        artists = [artists]
    runtime = int(item.get("RunTimeTicks") or 0)
    position = int(play.get("PositionTicks") or 0)
    image_id = item.get("AlbumId") or item.get("Id")
    supported = session.get("SupportedCommands") or []
    controllable = bool(session.get("SupportsMediaControl"))
    supported_set = {str(x) for x in supported}
    def can(*commands: str) -> bool:
        return controllable and (not supported_set or any(c in supported_set for c in commands))
    capabilities = {
        "previous": can("PreviousTrack"),
        "playpause": can("PlayPause", "Pause", "Unpause", "Play"),
        "next": can("NextTrack", "PlayNext"),
        "volume_down": can("VolumeDown", "SetVolume"),
        "volume_up": can("VolumeUp", "SetVolume"),
        "mute": can("ToggleMute", "Mute", "Unmute"),
    }
    return {
        "available": True,
        "playing": True,
        "source": "jellyfin-session",
        "session_id": session.get("Id"),
        "device": session.get("DeviceName") or session.get("Client"),
        "client": session.get("Client"),
        "user": session.get("UserName"),
        "item_id": item.get("Id"),
        "image_id": image_id,
        "title": item.get("Name") or "Unknown track",
        "artists": artists,
        "artist": ", ".join(str(x) for x in artists if x),
        "album": item.get("Album") or "",
        "paused": bool(play.get("IsPaused")),
        "muted": bool(play.get("IsMuted")),
        "volume": play.get("VolumeLevel"),
        "position_ticks": position,
        "runtime_ticks": runtime,
        "position_seconds": round(position / 10_000_000, 1) if position else 0,
        "runtime_seconds": round(runtime / 10_000_000, 1) if runtime else 0,
        "progress_percent": round((position / runtime) * 100, 2) if runtime > 0 else 0,
        "controllable": controllable,
        "supports_remote_control": bool(session.get("SupportsRemoteControl")),
        "supported_commands": supported,
        "capabilities": capabilities,
        "art_url": f"/api/jellyfin/art/{quote(str(image_id), safe='')}" if image_id else None,
        "queue": [str((q or {}).get("Id") or (q or {}).get("ItemId") or "") for q in (session.get("NowPlayingQueue") or []) if str((q or {}).get("Id") or (q or {}).get("ItemId") or "")],
    }



def _search_norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _fuzzy_threshold(query: object) -> float:
    q = _search_norm(query)
    compact = q.replace(" ", "")
    if len(compact) <= 3:
        return 0.88
    if len(compact) <= 5:
        return 0.80
    return 0.70 if " " not in q else 0.67


def _fuzzy_score(query: object, candidate: object) -> float:
    q = _search_norm(query); text = _search_norm(candidate)
    if not q or not text:
        return 0.0
    if q == text:
        return 1.30
    if q in text:
        return 1.18
    q_tokens = q.split(); text_tokens = text.split()
    if not q_tokens or not text_tokens:
        return 0.0
    token_scores=[]
    for token in q_tokens:
        if token in text_tokens:
            token_scores.append(1.0); continue
        if len(token) <= 2:
            token_scores.append(1.0 if any(t.startswith(token) for t in text_tokens) else 0.0); continue
        best=max((difflib.SequenceMatcher(None, token, t).ratio() for t in text_tokens), default=0.0)
        token_scores.append(best)
    token_score=sum(token_scores)/len(token_scores)
    whole=difflib.SequenceMatcher(None, q, text).ratio()
    joined=difflib.SequenceMatcher(None, q.replace(" ", ""), text.replace(" ", "")).ratio()
    coverage=sum(1 for score in token_scores if score >= 0.72)/len(token_scores)
    score=max(token_score*0.96, whole*0.90, joined*0.92)
    if coverage < 1.0:
        score *= 0.72 + 0.28*coverage
    return score


def _fuzzy_rank(items: list[dict], query: object, text_fn, limit: int | None = None) -> list[dict]:
    if not _search_norm(query):
        return list(items[:limit] if limit else items)
    threshold=_fuzzy_threshold(query); scored=[]
    for index,item in enumerate(items):
        score=_fuzzy_score(query,text_fn(item))
        if score >= threshold:
            scored.append((score,index,item))
    scored.sort(key=lambda row:(-row[0],row[1]))
    ranked=[row[2] for row in scored]
    return ranked[:limit] if limit else ranked


_SEARCH_CACHE_LOCK = threading.RLock()
_SEARCH_CACHE: dict[str, tuple[float, object]] = {}

def _search_cached(key: str, ttl: float, loader):
    """Small in-process cache for search catalogs and filesystem indexes."""
    now=time.monotonic()
    with _SEARCH_CACHE_LOCK:
        row=_SEARCH_CACHE.get(key)
        if row and now-row[0] < ttl:
            return row[1]
    value=loader()
    with _SEARCH_CACHE_LOCK:
        _SEARCH_CACHE[key]=(time.monotonic(),value)
        if len(_SEARCH_CACHE)>128:
            oldest=sorted(_SEARCH_CACHE.items(),key=lambda kv:kv[1][0])[:32]
            for stale,_ in oldest: _SEARCH_CACHE.pop(stale,None)
    return value


def _control_audio_local_search(query: str, limit: int = 8) -> dict:
    """Query only PCGA-owned audio metadata; never waits on public providers."""
    try:
        token=CONTROL_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if not token: return {"audiobooks":[],"podcasts":[]}
        target=CONTROL_UPSTREAM+"/audio/local-search?"+urlencode({"q":query,"limit":str(limit)})
        req=urllib.request.Request(target,headers={"Authorization":f"Bearer {token}","Accept":"application/json","User-Agent":f"PCGameArchive/{VERSION}"})
        with urllib.request.urlopen(req,timeout=2.5) as response:
            if int(response.status)<200 or int(response.status)>=300: return {"audiobooks":[],"podcasts":[]}
            data=json.loads(response.read().decode("utf-8","replace") or "{}")
        return data if isinstance(data,dict) else {"audiobooks":[],"podcasts":[]}
    except Exception:
        return {"audiobooks":[],"podcasts":[]}


def valid_jellyfin_id(value: str) -> bool:
    return bool(value) and len(value) <= 160 and all(c.isalnum() or c in "-_" for c in value)


def jellyfin_users() -> list[dict]:
    status, _, raw = jellyfin_request("/Users", timeout=4.0)
    if status < 200 or status >= 300:
        raise RuntimeError(f"Jellyfin /Users returned HTTP {status}")
    data = json.loads(raw.decode("utf-8", "replace") or "[]")
    return data if isinstance(data, list) else []


def jellyfin_playback_user() -> tuple[str, str]:
    if JELLYFIN_USER_ID and valid_jellyfin_id(JELLYFIN_USER_ID):
        return JELLYFIN_USER_ID, "Configured user"
    try:
        session = active_audio_session()
        sid = str((session or {}).get("UserId") or "")
        if valid_jellyfin_id(sid):
            return sid, str((session or {}).get("UserName") or "Jellyfin user")
    except Exception:
        pass
    users = jellyfin_users()
    enabled = [u for u in users if not ((u.get("Policy") or {}).get("IsDisabled")) and valid_jellyfin_id(str(u.get("Id") or ""))]
    if not enabled:
        raise RuntimeError("No enabled Jellyfin user is available for portal music playback")
    # Prefer an administrator on appliance-style single-user installs; otherwise
    # use the first enabled user returned by Jellyfin. PCGA_JELLYFIN_USER_ID can
    # override this deterministically on multi-user servers.
    enabled.sort(key=lambda u: (not bool((u.get("Policy") or {}).get("IsAdministrator")), str(u.get("Name") or "").lower()))
    user = enabled[0]
    return str(user.get("Id")), str(user.get("Name") or "Jellyfin user")


def jellyfin_music_items(search: str = "", limit: int = 24, view: str = "home", parent_id: str = "") -> dict:
    """Return a structured music hub instead of a single flat track list."""
    user_id, user_name = jellyfin_playback_user()
    limit = max(1, min(80, int(limit or 24)))
    search = str(search or "").strip()[:120]
    view = str(view or "home").strip().lower()
    parent_id = str(parent_id or "").strip()
    if parent_id and not valid_jellyfin_id(parent_id):
        raise ValueError("invalid-parent-id")

    fields = "PrimaryImageAspectRatio,PrimaryImageItemId,Album,AlbumArtist,Artists,AlbumArtists,AlbumId,RunTimeTicks,MediaSources,DateCreated,ChildCount,IndexNumber,ParentIndexNumber"

    def query_items(item_type: str, item_limit: int, *, term: str = "", sort_by: str = "SortName", sort_order: str = "Ascending", parent: str = "") -> list[dict]:
        params = {
            "IncludeItemTypes": item_type,
            "Recursive": "true",
            "Limit": str(max(1, min(100, item_limit))),
            "Fields": fields,
            "SortBy": sort_by,
            "SortOrder": sort_order,
        }
        if term:
            params["SearchTerm"] = term
        if parent:
            params["ParentId"] = parent
        if item_type == "MusicArtist":
            artist_params = {"UserId": user_id, "Limit": params["Limit"], "Fields": fields, "SortBy": sort_by, "SortOrder": sort_order}
            if term:
                artist_params["SearchTerm"] = term
            path = f"/Artists?{urlencode(artist_params)}"
        else:
            path = f"/Users/{quote(user_id, safe='')}/Items?{urlencode(params)}"
        status, _, raw = jellyfin_request(path, timeout=8.0)
        if status < 200 or status >= 300:
            raise RuntimeError(f"Jellyfin music items returned HTTP {status}")
        data = json.loads(raw.decode("utf-8", "replace") or "{}")
        out = []
        for item in data.get("Items") or []:
            iid = str(item.get("Id") or "")
            if not valid_jellyfin_id(iid):
                continue
            item_type_name = str(item.get("Type") or item_type)
            artists = item.get("Artists") or []
            if isinstance(artists, str):
                artists = [artists]
            album_artists = item.get("AlbumArtists") or []
            if isinstance(album_artists, dict):
                album_artists = [album_artists]
            album_artist_names = []
            for a in album_artists:
                if isinstance(a, dict) and a.get("Name"):
                    album_artist_names.append(str(a.get("Name")))
                elif isinstance(a, str):
                    album_artist_names.append(a)
            artist = ", ".join(str(x) for x in artists if x) or str(item.get("AlbumArtist") or "") or ", ".join(album_artist_names)
            runtime = int(item.get("RunTimeTicks") or 0)
            image_id = str(item.get("AlbumId") or item.get("PrimaryImageItemId") or iid)
            entity_kind = "track" if item_type_name == "Audio" else ("album" if item_type_name == "MusicAlbum" else "artist")
            out.append({
                "id": iid,
                "name": item.get("Name") or ("Unknown track" if entity_kind == "track" else "Untitled"),
                "entity_kind": entity_kind,
                "type": item_type_name,
                "album": item.get("Album") or (item.get("Name") if entity_kind == "album" else ""),
                "artist": artist,
                "artists": artists,
                "runtime_ticks": runtime,
                "runtime_seconds": round(runtime / 10_000_000, 1) if runtime else 0,
                "child_count": int(item.get("ChildCount") or 0),
                "track_number": item.get("IndexNumber"),
                "disc_number": item.get("ParentIndexNumber"),
                "art_url": f"/api/jellyfin/art/{quote(image_id, safe='')}" if valid_jellyfin_id(image_id) else None,
            })
        return out

    sections: list[dict] = []
    active_view = view
    if parent_id:
        active_view = "album"
        tracks = query_items("Audio", limit, sort_by="ParentIndexNumber,IndexNumber,SortName", parent=parent_id)
        sections.append({"id": "tracks", "title": "Tracks", "kind": "tracks", "items": tracks})
    elif search:
        active_view = "search"
        def fuzzy_music(item_type: str, out_limit: int) -> list[dict]:
            exact_key=f"jellyfin:music:{user_id}:{item_type}:q:{_search_norm(search)}"
            with ThreadPoolExecutor(max_workers=2,thread_name_prefix="pcga-jf-music") as pool:
                exact_future=pool.submit(
                    _search_cached,exact_key,15.0,
                    lambda: query_items(item_type,min(100,out_limit*3),term=search),
                )
                broad_future=pool.submit(
                    _search_cached,f"jellyfin:music:{user_id}:{item_type}:all",45.0,
                    lambda: query_items(item_type,300,term=""),
                )
                exact=exact_future.result(); broad=broad_future.result()
            merged=[]; seen=set()
            for item in exact+broad:
                iid=str(item.get("id") or "")
                if iid in seen: continue
                seen.add(iid); merged.append(item)
            return _fuzzy_rank(merged,search,lambda x:" ".join(str(x.get(k) or "") for k in ("name","artist","album")),out_limit)
        with ThreadPoolExecutor(max_workers=3,thread_name_prefix="pcga-jf-music-kind") as pool:
            artist_future=pool.submit(fuzzy_music,"MusicArtist",min(limit,16))
            album_future=pool.submit(fuzzy_music,"MusicAlbum",min(limit,18))
            track_future=pool.submit(fuzzy_music,"Audio",min(max(limit,24),60))
            artists=artist_future.result(); albums=album_future.result(); tracks=track_future.result()
        if artists:
            sections.append({"id": "artists", "title": "Artists", "kind": "artists", "items": artists})
        if albums:
            sections.append({"id": "albums", "title": "Albums", "kind": "albums", "items": albums})
        if tracks:
            sections.append({"id": "tracks", "title": "Tracks", "kind": "tracks", "items": tracks})
    elif view == "albums":
        sections.append({"id": "albums", "title": "Albums", "kind": "albums", "items": query_items("MusicAlbum", limit, sort_by="SortName")})
    elif view == "artists":
        sections.append({"id": "artists", "title": "Artists", "kind": "artists", "items": query_items("MusicArtist", limit, sort_by="SortName")})
    elif view == "tracks":
        sections.append({"id": "tracks", "title": "Tracks", "kind": "tracks", "items": query_items("Audio", limit, sort_by="SortName")})
    else:
        active_view = "home"
        recent = query_items("Audio", min(limit, 16), sort_by="DateCreated,SortName", sort_order="Descending")
        albums = query_items("MusicAlbum", min(limit, 14), sort_by="DateCreated,SortName", sort_order="Descending")
        artists = query_items("MusicArtist", min(limit, 14), sort_by="SortName")
        if recent:
            sections.append({"id": "recent", "title": "Recently Added", "kind": "tracks", "items": recent})
        if albums:
            sections.append({"id": "albums", "title": "Albums", "kind": "albums", "items": albums})
        if artists:
            sections.append({"id": "artists", "title": "Artists", "kind": "artists", "items": artists})

    tracks = [x for section in sections if section.get("kind") == "tracks" for x in section.get("items") or []]
    return {
        "available": True,
        "user_id": user_id,
        "user_name": user_name,
        "view": active_view,
        "search": search,
        "parent_id": parent_id or None,
        "sections": sections,
        "items": tracks,
    }


def photo_token(relative_path: str) -> str:
    raw = relative_path.encode("utf-8", "surrogateescape")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def photo_path_from_token(token: str) -> Path:
    if not token or len(token) > 4096 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise ValueError("invalid-photo-token")
    padded = token + "=" * ((4 - len(token) % 4) % 4)
    try:
        rel = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", "surrogateescape")
    except Exception as exc:
        raise ValueError("invalid-photo-token") from exc
    root = PHOTOS.resolve()
    candidate = (PHOTOS / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("invalid-photo-path") from exc
    if not candidate.is_file() or candidate.suffix.lower() not in PHOTO_EXTS:
        raise FileNotFoundError(rel)
    return candidate


def _photo_search_index() -> list[tuple[int,str,int]]:
    def load():
        rows=[]; scanned=0
        if not PHOTOS.exists(): return rows
        for path in PHOTOS.rglob("*"):
            if scanned>=20000: break
            if not path.is_file() or path.suffix.lower() not in PHOTO_EXTS: continue
            scanned+=1
            try: st=path.stat()
            except OSError: continue
            rows.append((st.st_mtime_ns,path.relative_to(PHOTOS).as_posix(),st.st_size))
        return rows
    # Photo uploads are visible within at most 12 seconds while repeated searches
    # avoid walking the archive filesystem again and again.
    return _search_cached("photos:index",12.0,load)

def photo_library_items(search: str = "", limit: int = 80) -> dict:
    limit = max(1, min(200, int(limit or 80)))
    search_l = str(search or "").strip().lower()[:120]
    rows=_photo_search_index()
    candidates=[]
    for mtime_ns,rel,size in rows:
        score=_fuzzy_score(search_l,f"{rel} {Path(rel).stem}") if search_l else 0.0
        if search_l and score<_fuzzy_threshold(search_l): continue
        candidates.append((score,mtime_ns,rel,size))
    if search_l: candidates.sort(key=lambda x:(-x[0],-x[1],x[2].lower()))
    else: candidates.sort(key=lambda x:(-x[1],x[2].lower()))
    out=[]
    for _score,mtime_ns,rel,size in candidates[:limit]:
        token=photo_token(rel); parent=str(Path(rel).parent).replace('.', '', 1).strip('/')
        out.append({"id":token,"name":Path(rel).name,"title":Path(rel).stem,"relative_path":rel,"folder":parent,"size":size,"mtime":round(mtime_ns/1_000_000_000,3),"url":f"/api/photos/file/{token}"})
    return {"available":True,"root":"/media/photos","count":len(candidates),"scanned":len(rows),"items":out,"index_cached":True}


def jellyfin_background_items(search: str = "", limit: int = 30) -> dict:
    """Return video items suitable for a silent portal background browser."""
    user_id, user_name = jellyfin_playback_user()
    limit = max(1, min(60, int(limit or 30)))
    fields = "PrimaryImageAspectRatio,PrimaryImageItemId,RunTimeTicks,MediaSources,MediaStreams,SeriesName,ProductionYear,IndexNumber,ParentIndexNumber,DateCreated"
    def fetch(term: str="", item_limit: int=60) -> list[dict]:
        params = {
            "IncludeItemTypes": "Movie,Episode,Video,MusicVideo,Trailer",
            "Recursive": "true", "Limit": str(max(1,min(300,item_limit))), "Fields": fields,
            "SortBy": "SortName" if term else "DateCreated,SortName",
            "SortOrder": "Ascending" if term else "Descending",
        }
        if term: params["SearchTerm"] = term[:120]
        path = f"/Users/{quote(user_id, safe='')}/Items?{urlencode(params)}"
        status, _, raw = jellyfin_request(path, timeout=8.0)
        if status < 200 or status >= 300: raise RuntimeError(f"Jellyfin video items returned HTTP {status}")
        data = json.loads(raw.decode("utf-8", "replace") or "{}")
        return [x for x in (data.get("Items") or []) if isinstance(x,dict)]
    if search:
        with ThreadPoolExecutor(max_workers=2,thread_name_prefix="pcga-jf-background") as pool:
            exact_future=pool.submit(
                _search_cached,f"jellyfin:background:{user_id}:q:{_search_norm(search)}",15.0,
                lambda: fetch(search,limit*2),
            )
            broad_future=pool.submit(_search_cached,f"jellyfin:background:{user_id}:all",60.0,lambda:fetch("",300))
            rows=exact_future.result(); broad=broad_future.result()
        seen=set(); merged=[]
        for item in rows+broad:
            iid=str(item.get("Id") or "")
            if iid in seen: continue
            seen.add(iid); merged.append(item)
        rows=_fuzzy_rank(merged,search,lambda x:" ".join(str(x.get(k) or "") for k in ("Name","SeriesName","ProductionYear","Type")),limit)
    out = []
    for item in rows[:limit]:
        iid = str(item.get("Id") or "")
        if not valid_jellyfin_id(iid): continue
        item_type = str(item.get("Type") or "Video"); runtime = int(item.get("RunTimeTicks") or 0)
        sources = item.get("MediaSources") or []; source = sources[0] if sources else {}
        media_source_id = str(source.get("Id") or "")
        if media_source_id and not valid_jellyfin_id(media_source_id): media_source_id = ""
        streams = source.get("MediaStreams") or item.get("MediaStreams") or []
        video_stream = next((x for x in streams if str(x.get("Type") or "").lower() == "video"), {})
        codec = str(video_stream.get("Codec") or ""); container = str(source.get("Container") or "")
        series = str(item.get("SeriesName") or "").strip(); season=item.get("ParentIndexNumber"); episode=item.get("IndexNumber"); subtitle=""
        if series:
            ep=""
            if season is not None and episode is not None:
                try: ep=f"S{int(season):02d}E{int(episode):02d}"
                except (TypeError,ValueError): ep=""
            subtitle=" • ".join(x for x in (series,ep) if x)
        elif item.get("ProductionYear"): subtitle=str(item.get("ProductionYear"))
        else: subtitle=item_type
        image_id=str(item.get("PrimaryImageItemId") or iid); query={"media_source_id":media_source_id} if media_source_id else {}
        out.append({"id":iid,"name":item.get("Name") or "Untitled video","subtitle":subtitle,"type":item_type,"runtime_ticks":runtime,"runtime_seconds":round(runtime/10_000_000,1) if runtime else 0,"media_source_id":media_source_id or None,"container":container or None,"video_codec":codec or None,"art_url":f"/api/jellyfin/art/{quote(image_id,safe='')}" if valid_jellyfin_id(image_id) else None,"stream_url":f"/api/jellyfin/video/{quote(iid,safe='')}"+(f"?{urlencode(query)}" if query else "")})
    return {"available": True, "user_id": user_id, "user_name": user_name, "items": out}

def jellyfin_library_items(search: str = "", media_filter: str = "all", limit: int = 48, parent_id: str = "") -> dict:
    """Return video media with a categorized overview for the portal."""
    user_id, user_name = jellyfin_playback_user()
    limit = max(1, min(300, int(limit or 48)))
    media_filter = str(media_filter or "all").strip().lower()
    search = str(search or "").strip()[:120]
    parent_id = str(parent_id or "").strip()
    if parent_id and not valid_jellyfin_id(parent_id):
        parent_id = ""
    type_map = {
        "movies": "Movie",
        "tv": "Series",
        "episodes": "Episode",
        "videos": "Video,MusicVideo,Trailer",
        "video": "Video,MusicVideo,Trailer",  # compatibility with older portal state
    }
    fields = "PrimaryImageAspectRatio,PrimaryImageItemId,RunTimeTicks,MediaSources,MediaStreams,SeriesName,ProductionYear,IndexNumber,ParentIndexNumber,DateCreated,Album,Artists,AlbumId,UserData,ChildCount"

    def normalize(item: dict) -> dict | None:
        iid = str(item.get("Id") or "")
        if not valid_jellyfin_id(iid):
            return None
        item_type = str(item.get("Type") or "Video")
        runtime = int(item.get("RunTimeTicks") or 0)
        sources = item.get("MediaSources") or []
        source = sources[0] if sources else {}
        media_source_id = str(source.get("Id") or "")
        if media_source_id and not valid_jellyfin_id(media_source_id):
            media_source_id = ""
        series = str(item.get("SeriesName") or "").strip()
        season = item.get("ParentIndexNumber")
        episode = item.get("IndexNumber")
        meta = []
        if item_type == "Series":
            if item.get("ProductionYear"):
                meta.append(str(item.get("ProductionYear")))
            meta.append("TV Series")
        elif series:
            meta.append(series)
            if season is not None and episode is not None:
                try:
                    meta.append(f"S{int(season):02d}E{int(episode):02d}")
                except (TypeError, ValueError):
                    pass
        elif item.get("ProductionYear"):
            meta.append(str(item.get("ProductionYear")))
        if not meta:
            meta.append(item_type)
        user_data = item.get("UserData") or {}
        resume_ticks = max(0, int(user_data.get("PlaybackPositionTicks") or 0))
        played_pct = 0.0
        if runtime > 0 and resume_ticks > 0:
            played_pct = max(0.0, min(100.0, resume_ticks / runtime * 100.0))
        image_id = str(item.get("PrimaryImageItemId") or iid)
        return {
            "id": iid,
            "name": item.get("Name") or "Untitled video",
            "kind": "series" if item_type == "Series" else "video",
            "type": item_type,
            "subtitle": " • ".join(meta),
            "runtime_ticks": runtime,
            "runtime_seconds": round(runtime / 10_000_000, 1) if runtime else 0,
            "resume_ticks": resume_ticks,
            "resume_seconds": round(resume_ticks / 10_000_000, 1) if resume_ticks else 0,
            "played_percent": round(played_pct, 1),
            "media_source_id": media_source_id or None,
            "art_url": f"/api/jellyfin/art/{quote(image_id, safe='')}" if valid_jellyfin_id(image_id) else None,
        }

    def query_items(include_types: str, item_limit: int, *, term: str = "", sort_by: str | None = None, sort_order: str | None = None, parent_id: str = "") -> list[dict]:
        params = {
            "IncludeItemTypes": include_types,
            "Recursive": "true",
            "Limit": str(max(1, min(300, item_limit))),
            "Fields": fields,
            "SortBy": sort_by or ("SortName" if term else "DateCreated,SortName"),
            "SortOrder": sort_order or ("Ascending" if term else "Descending"),
        }
        if term:
            params["SearchTerm"] = term
        if parent_id and valid_jellyfin_id(parent_id):
            params["ParentId"] = parent_id
        path = f"/Users/{quote(user_id, safe='')}/Items?{urlencode(params)}"
        status, _, raw = jellyfin_request(path, timeout=10.0)
        if status < 200 or status >= 300:
            raise RuntimeError(f"Jellyfin library items returned HTTP {status}")
        data = json.loads(raw.decode("utf-8", "replace") or "{}")
        return [x for x in (normalize(item) for item in (data.get("Items") or [])) if x]

    def search_items(include_types: str, item_limit: int, *, parent_id: str = "", sort_by: str | None = None, sort_order: str | None = None) -> list[dict]:
        if not search:
            return query_items(include_types,item_limit,parent_id=parent_id,sort_by=sort_by,sort_order=sort_order)
        exact_key=f"jellyfin:library:{user_id}:{include_types}:{parent_id or '-'}:q:{_search_norm(search)}"
        with ThreadPoolExecutor(max_workers=2,thread_name_prefix="pcga-jf-library") as pool:
            exact_future=pool.submit(
                _search_cached,exact_key,15.0,
                lambda: query_items(include_types,min(300,max(item_limit*2,60)),term=search,parent_id=parent_id,sort_by=sort_by,sort_order=sort_order),
            )
            broad_future=pool.submit(
                _search_cached,f"jellyfin:library:{user_id}:{include_types}:{parent_id or '-'}:all",45.0,
                lambda: query_items(include_types,300,term="",parent_id=parent_id,sort_by=sort_by,sort_order=sort_order),
            )
            exact=exact_future.result(); broad=broad_future.result()
        merged=[]; seen=set()
        for item in exact+broad:
            iid=str(item.get("id") or "")
            if iid in seen: continue
            seen.add(iid); merged.append(item)
        return _fuzzy_rank(merged,search,lambda x:" ".join(str(x.get(k) or "") for k in ("name","subtitle","type")),item_limit)

    def resume_items(item_limit: int) -> list[dict]:
        params = {
            "Limit": str(max(1, min(50, item_limit))),
            "MediaTypes": "Video",
            "IncludeItemTypes": "Movie,Episode,Video,MusicVideo",
            "Fields": fields,
            "EnableUserData": "true",
        }
        path = f"/Users/{quote(user_id, safe='')}/Items/Resume?{urlencode(params)}"
        status, _, raw = jellyfin_request(path, timeout=8.0)
        if status < 200 or status >= 300:
            return []
        data = json.loads(raw.decode("utf-8", "replace") or "{}")
        return [x for x in (normalize(item) for item in (data.get("Items") or [])) if x]

    if media_filter == "all":
        per = max(8, min(18, limit // 3 or 12))
        sections = []
        if not search:
            resume = resume_items(min(12, per))
            if resume:
                sections.append({"id": "continue", "title": "Continue Watching", "filter": "all", "items": resume})
        categories=(
            ("movies", "Movies", "Movie"),
            ("tv", "TV Series", "Series"),
            ("videos", "Other Video", "Video,MusicVideo,Trailer"),
        )
        # Independent Jellyfin categories should not serialize three network
        # round trips on the common All/Search view.
        with ThreadPoolExecutor(max_workers=3,thread_name_prefix="pcga-jf-media-kind") as pool:
            futures={sid:pool.submit(search_items,types,per) for sid,_title,types in categories}
            category_items={sid:futures[sid].result() for sid,_title,_types in categories}
        for sid,title,_types in categories:
            items=category_items.get(sid) or []
            if items:
                sections.append({"id":sid,"title":title,"filter":sid,"items":items})
        flat = [item for section in sections for item in section.get("items") or []]
        return {"available": True, "user_id": user_id, "user_name": user_name, "filter": "all", "search": search, "sections": sections, "items": flat}

    include_types = type_map.get(media_filter, "Movie,Series,Video,MusicVideo,Trailer")
    if media_filter == "episodes":
        out = search_items(
            "Episode", limit,
            sort_by="ParentIndexNumber,IndexNumber,SortName", sort_order="Ascending",
            parent_id=parent_id,
        )
    else:
        out = search_items(include_types, limit, parent_id=parent_id)
    return {"available": True, "user_id": user_id, "user_name": user_name, "filter": media_filter, "search": search, "parent_id": parent_id or None, "items": out, "sections": []}




def _home_parse_time(value) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _control_game_activity(limit: int = 48) -> list[dict]:
    try:
        token = CONTROL_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if not token:
            return []
        req = urllib.request.Request(
            CONTROL_UPSTREAM + "/game-activity?" + urlencode({"limit": str(max(1, min(300, int(limit or 48))))}),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": f"PCGameArchive/{VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=4.0) as response:
            if int(response.status) < 200 or int(response.status) >= 300:
                return []
            data = json.loads(response.read().decode("utf-8", "replace") or "{}")
        return [dict(x) for x in (data.get("items") or []) if isinstance(x, dict)]
    except Exception:
        return []


def _game_home_catalog(limit: int = 24) -> tuple[dict[str, dict], list[dict]]:
    """Return current game metadata lookup plus recently-added game cards.

    Each backend is isolated so a temporarily unavailable RomM or PC-game stack
    cannot make the Jellyfin shelves disappear.
    """
    lookup: dict[str, dict] = {}
    added: list[dict] = []
    try:
        consoles = romm_library("", "", 160, 0).get("items") or []
    except Exception:
        consoles = []
    for game in consoles:
        if not isinstance(game, dict) or not game.get("id"):
            continue
        gid = str(game.get("id"))
        item = {
            "id": gid,
            "name": game.get("name") or "Console Game",
            "title": game.get("name") or "Console Game",
            "kind": "console-game",
            "type": "Console Game",
            "subtitle": str(game.get("platform") or game.get("platform_slug") or "Console Game"),
            "platform": game.get("platform"),
            "platform_slug": game.get("platform_slug"),
            "art_url": game.get("cover_url") if game.get("metadata_state") == "identified" else None,
            "date_created": game.get("date_created"),
            "last_played": "",
            "played_percent": 0,
        }
        lookup["console-game:" + gid] = item
        if _home_parse_time(item.get("date_created")) > 0:
            added.append(item)
    try:
        pc_rows = _pcga_game_rows("")
    except Exception:
        pc_rows = []
    for game in pc_rows:
        if not isinstance(game, dict) or not game.get("id"):
            continue
        gid = str(game.get("id"))
        if gid.startswith("review:"):
            continue
        meta = [str(game.get("developer") or "").strip(), str(game.get("year") or "").strip()]
        if not game.get("playable") and game.get("install_status"):
            meta.append(str(game.get("install_status")).replace("-", " ").title())
        item = {
            "id": gid,
            "name": game.get("title") or "PC Game",
            "title": game.get("title") or "PC Game",
            "kind": "pc-game",
            "type": "PC Game",
            "subtitle": " • ".join(x for x in meta if x) or "PC Game",
            "art_url": game.get("cover_url"),
            "stream_id": game.get("stream_id") or gid,
            "metadata_source_url": game.get("metadata_source_url"),
            "metadata_attribution": game.get("metadata_attribution"),
            "date_created": game.get("date_created"),
            "last_played": "",
            "played_percent": 0,
        }
        lookup["pc-game:" + gid] = item
        if _home_parse_time(item.get("date_created")) > 0:
            added.append(item)
    added.sort(key=lambda x: _home_parse_time(x.get("date_created")), reverse=True)
    return lookup, added[:max(1, int(limit or 24))]


def _game_activity_home_items(limit: int = 24) -> tuple[list[dict], list[dict]]:
    lookup, added = _game_home_catalog(limit * 3)
    recent: list[dict] = []
    for row in _control_game_activity(limit * 4):
        kind = str(row.get("kind") or "")
        gid = str(row.get("id") or "")
        if kind not in {"console-game", "pc-game"} or not gid:
            continue
        current = dict(lookup.get(kind + ":" + gid) or {})
        current.update({k: v for k, v in {
            "id": gid,
            "kind": kind,
            "type": "Console Game" if kind == "console-game" else "PC Game",
            "name": row.get("title") or row.get("name"),
            "title": row.get("title") or row.get("name"),
            "subtitle": row.get("subtitle") or row.get("platform"),
            "art_url": row.get("art_url"),
            "platform": row.get("platform"),
            "platform_slug": row.get("platform_slug"),
            "stream_id": row.get("stream_id"),
        }.items() if v not in (None, "")})
        current["name"] = current.get("name") or ("Console Game" if kind == "console-game" else "PC Game")
        current["title"] = current.get("title") or current["name"]
        current["subtitle"] = current.get("subtitle") or current.get("type")
        stamp = float(row.get("launched_at") or 0)
        current["last_played"] = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat(timespec="milliseconds") if stamp > 0 else ""
        current["launched_at"] = stamp
        current["launch_count"] = int(row.get("launch_count") or 0)
        current["played_percent"] = 0
        recent.append(current)
    recent.sort(key=lambda x: _home_parse_time(x.get("last_played")), reverse=True)
    return recent[:max(1, int(limit or 24))], added


def _home_item_identity(item: dict) -> str:
    return f"{item.get('kind') or item.get('type') or 'item'}:{item.get('id') or ''}"


def jellyfin_home_media_items(limit: int = 12, include_games: bool = True) -> dict:
    """Return compact shelves for the optional secondary home activity surface.

    Jellyfin contributes resumable/recent media, while PCGA contributes a small
    launch-history ledger for console and PC games. Newly added games are derived
    from RomM and the PC-game ingest registry so the surface remains useful even
    when Jellyfin is temporarily unavailable.
    """
    try:
        user_id, user_name = jellyfin_playback_user()
        jellyfin_available = True
    except Exception:
        user_id, user_name = "", ""
        jellyfin_available = False
    limit = max(4, min(24, int(limit or 12)))
    fields = (
        "PrimaryImageAspectRatio,PrimaryImageItemId,RunTimeTicks,MediaSources,"
        "MediaStreams,SeriesName,ProductionYear,IndexNumber,ParentIndexNumber,"
        "DateCreated,Album,Artists,AlbumId,UserData"
    )

    def normalize(item: dict) -> dict | None:
        iid = str(item.get("Id") or "")
        if not valid_jellyfin_id(iid):
            return None
        item_type = str(item.get("Type") or "Video")
        lower_type = item_type.lower()
        kind = "audio" if lower_type == "audio" else "video"
        runtime = max(0, int(item.get("RunTimeTicks") or 0))
        user_data = item.get("UserData") or {}
        resume_ticks = max(0, int(user_data.get("PlaybackPositionTicks") or 0))
        played_pct = 0.0
        if runtime > 0 and resume_ticks > 0:
            played_pct = max(0.0, min(100.0, resume_ticks / runtime * 100.0))
        sources = item.get("MediaSources") or []
        source = sources[0] if sources else {}
        media_source_id = str(source.get("Id") or "")
        if media_source_id and not valid_jellyfin_id(media_source_id):
            media_source_id = ""
        artists = item.get("Artists") or []
        if isinstance(artists, str):
            artists = [artists]
        subtitle = ""
        if kind == "audio":
            subtitle = " • ".join(x for x in (", ".join(str(a) for a in artists if a), str(item.get("Album") or "").strip()) if x)
            if not subtitle:
                subtitle = "Music"
            image_id = str(item.get("AlbumId") or item.get("PrimaryImageItemId") or iid)
        else:
            series = str(item.get("SeriesName") or "").strip()
            season = item.get("ParentIndexNumber")
            episode = item.get("IndexNumber")
            meta = []
            if series:
                meta.append(series)
                if season is not None and episode is not None:
                    try:
                        meta.append(f"S{int(season):02d}E{int(episode):02d}")
                    except (TypeError, ValueError):
                        pass
            elif item.get("ProductionYear"):
                meta.append(str(item.get("ProductionYear")))
            subtitle = " • ".join(meta) or item_type
            image_id = str(item.get("PrimaryImageItemId") or iid)
        return {
            "id": iid,
            "name": item.get("Name") or ("Untitled audio" if kind == "audio" else "Untitled video"),
            "kind": kind,
            "type": item_type,
            "subtitle": subtitle,
            "runtime_ticks": runtime,
            "runtime_seconds": round(runtime / 10_000_000, 1) if runtime else 0,
            "resume_ticks": resume_ticks,
            "resume_seconds": round(resume_ticks / 10_000_000, 1) if resume_ticks else 0,
            "played_percent": round(played_pct, 1),
            "media_source_id": media_source_id or None,
            "art_url": f"/api/jellyfin/art/{quote(image_id, safe='')}" if valid_jellyfin_id(image_id) else None,
            "last_played": str(user_data.get("LastPlayedDate") or ""),
            "date_created": str(item.get("DateCreated") or ""),
        }

    def request_items(params: dict, timeout: float = 8.0) -> list[dict]:
        if not jellyfin_available or not user_id:
            return []
        params = {k: str(v) for k, v in params.items() if v is not None and v != ""}
        path = f"/Users/{quote(user_id, safe='')}/Items?{urlencode(params)}"
        status, _, raw = jellyfin_request(path, timeout=timeout)
        if status < 200 or status >= 300:
            return []
        data = json.loads(raw.decode("utf-8", "replace") or "{}")
        return [x for x in (normalize(item) for item in (data.get("Items") or [])) if x]

    # Continue Watching is Jellyfin's own resume list so its semantics match the
    # Movies & TV browser exactly.
    resume_params = {
        "Limit": str(limit),
        "MediaTypes": "Video",
        "IncludeItemTypes": "Movie,Episode,Video,MusicVideo",
        "Fields": fields,
        "EnableUserData": "true",
    }
    resume_path = f"/Users/{quote(user_id, safe='')}/Items/Resume?{urlencode(resume_params)}"
    continue_items: list[dict] = []
    if jellyfin_available and user_id:
        status, _, raw = jellyfin_request(resume_path, timeout=8.0)
        if 200 <= status < 300:
            data = json.loads(raw.decode("utf-8", "replace") or "{}")
            continue_items = [x for x in (normalize(item) for item in (data.get("Items") or [])) if x]

    common = {
        "IncludeItemTypes": "Movie,Episode,Video,MusicVideo,Audio",
        "Recursive": "true",
        "Limit": str(limit),
        "Fields": fields,
        "EnableUserData": "true",
    }
    recently_accessed = request_items({
        **common,
        "SortBy": "DatePlayed",
        "SortOrder": "Descending",
    })
    # Some Jellyfin versions return never-played items at the tail of a DatePlayed
    # sort.  Keep only records that actually carry a LastPlayedDate.
    recently_accessed = [x for x in recently_accessed if x.get("last_played")][:limit]
    recently_added = request_items({
        **common,
        "SortBy": "DateCreated,SortName",
        "SortOrder": "Descending",
    })[:limit]

    if include_games:
        game_recent, game_added = _game_activity_home_items(limit * 2)
        # Games have launch history rather than a universal media-style resume
        # percentage. Keep at most half of Continue as game launches so a recent
        # gaming session cannot crowd every resumable movie/episode off the row.
        game_continue = game_recent[:max(1, min(6, limit // 2))]
        continue_items = sorted(
            list(continue_items) + list(game_continue),
            key=lambda x: _home_parse_time(x.get("last_played") or x.get("launched_at")),
            reverse=True,
        )[:limit]
        recently_accessed = sorted(
            list(recently_accessed) + list(game_recent),
            key=lambda x: _home_parse_time(x.get("last_played") or x.get("launched_at")),
            reverse=True,
        )
        recently_added = sorted(
            list(recently_added) + list(game_added),
            key=lambda x: _home_parse_time(x.get("date_created")),
            reverse=True,
        )[:limit]

    continue_ids = {_home_item_identity(x) for x in continue_items}
    recently_accessed = [x for x in recently_accessed if _home_item_identity(x) not in continue_ids][:limit]
    return {
        "available": True,
        "jellyfin_available": jellyfin_available,
        "user_id": user_id or None,
        "user_name": user_name or None,
        "games_included": bool(include_games),
        "sections": [
            {"id": "continue", "title": "Continue", "items": continue_items[:limit]},
            {"id": "recent", "title": "Recently Accessed", "items": recently_accessed[:limit]},
            {"id": "added", "title": "Recently Added", "items": recently_added[:limit]},
        ],
    }


def jellyfin_item(item_id: str) -> dict:
    if not valid_jellyfin_id(item_id):
        raise ValueError("invalid-item")
    user_id, _ = jellyfin_playback_user()
    status, _, raw = jellyfin_request(f"/Users/{quote(user_id, safe='')}/Items/{quote(item_id, safe='')}", timeout=4.0)
    if status < 200 or status >= 300:
        raise RuntimeError(f"Jellyfin item returned HTTP {status}")
    item = json.loads(raw.decode("utf-8", "replace") or "{}")
    artists = item.get("Artists") or []
    if isinstance(artists, str):
        artists = [artists]
    runtime = int(item.get("RunTimeTicks") or 0)
    item_type = str(item.get("Type") or "Audio")
    kind = "audio" if item_type.lower() == "audio" else "video"
    series = str(item.get("SeriesName") or "").strip()
    subtitle = str(item.get("Album") or "").strip() if kind == "audio" else series
    if kind == "video" and not subtitle and item.get("ProductionYear"):
        subtitle = str(item.get("ProductionYear"))
    if not subtitle:
        subtitle = item_type
    image_id = item.get("AlbumId") or item.get("PrimaryImageItemId") or item.get("Id")
    return {
        "id": str(item.get("Id") or item_id),
        "name": item.get("Name") or ("Unknown track" if kind == "audio" else "Untitled video"),
        "kind": kind,
        "type": item_type,
        "subtitle": subtitle,
        "album": item.get("Album") or "",
        "artist": ", ".join(str(x) for x in artists if x),
        "artists": artists,
        "runtime_ticks": runtime,
        "runtime_seconds": round(runtime / 10_000_000, 1) if runtime else 0,
        "art_url": f"/api/jellyfin/art/{quote(str(image_id), safe='')}" if image_id else None,
    }


def jellyfin_prepare_audio(item_id: str, start_ticks: int = 0) -> dict:
    if not valid_jellyfin_id(item_id):
        raise ValueError("invalid-item")
    user_id, user_name = jellyfin_playback_user()
    start_ticks = max(0, int(start_ticks or 0))
    request_body = {
        "UserId": user_id,
        "StartTimeTicks": start_ticks,
        "EnableDirectPlay": True,
        "EnableDirectStream": True,
        "EnableTranscoding": True,
        "AllowAudioStreamCopy": True,
        "MaxAudioChannels": 8,
    }
    status, _, raw = jellyfin_request(
        f"/Items/{quote(item_id, safe='')}/PlaybackInfo",
        method="POST",
        body=json.dumps(request_body, separators=(",", ":")).encode(),
        timeout=8.0,
    )
    if status < 200 or status >= 300:
        raise RuntimeError(f"Jellyfin PlaybackInfo returned HTTP {status}")
    info = json.loads(raw.decode("utf-8", "replace") or "{}")
    sources = info.get("MediaSources") or []
    source = sources[0] if sources else {}
    media_source_id = str(source.get("Id") or "")
    play_session_id = str(info.get("PlaySessionId") or "")
    if not play_session_id:
        raise RuntimeError("Jellyfin did not return a PlaySessionId")
    item = jellyfin_item(item_id)
    query = {"play_session_id": play_session_id}
    if media_source_id:
        query["media_source_id"] = media_source_id
    return {
        "ok": True,
        "user_id": user_id,
        "user_name": user_name,
        "item": item,
        "play_session_id": play_session_id,
        "media_source_id": media_source_id,
        "start_ticks": start_ticks,
        "stream_url": f"/api/jellyfin/audio/{quote(item_id, safe='')}?{urlencode(query)}",
    }


def jellyfin_prepare_video(
    item_id: str,
    start_ticks: int = 0,
    *,
    media_source_id: str = "",
    quality: str = "auto",
    audio_stream_index=None,
    subtitle_stream_index=None,
) -> dict:
    if not valid_jellyfin_id(item_id):
        raise ValueError("invalid-item")
    if media_source_id and not valid_jellyfin_id(media_source_id):
        raise ValueError("invalid-media-source")
    user_id, user_name = jellyfin_playback_user()
    start_ticks = max(0, int(start_ticks or 0))
    quality_key, quality_profile = jellyfin_video_quality(quality)
    requested_audio = _stream_index(audio_stream_index)
    requested_subtitle = _stream_index(subtitle_stream_index)
    request_body = {
        "UserId": user_id,
        "StartTimeTicks": start_ticks,
        "EnableDirectPlay": True,
        "EnableDirectStream": True,
        "EnableTranscoding": True,
        "AllowVideoStreamCopy": True,
        "AllowAudioStreamCopy": True,
        "MaxAudioChannels": 6,
        "MaxStreamingBitrate": int(quality_profile["bitrate"]),
    }
    if media_source_id:
        request_body["MediaSourceId"] = media_source_id
    if requested_audio is not None and requested_audio >= 0:
        request_body["AudioStreamIndex"] = requested_audio
    if requested_subtitle is not None and requested_subtitle >= 0:
        request_body["SubtitleStreamIndex"] = requested_subtitle
        request_body["AlwaysBurnInSubtitleWhenTranscoding"] = True
    status, _, raw = jellyfin_request(
        f"/Items/{quote(item_id, safe='')}/PlaybackInfo",
        method="POST",
        body=json.dumps(request_body, separators=(",", ":")).encode(),
        timeout=10.0,
    )
    if status < 200 or status >= 300:
        raise RuntimeError(f"Jellyfin PlaybackInfo returned HTTP {status}")
    info = json.loads(raw.decode("utf-8", "replace") or "{}")
    sources = info.get("MediaSources") or []
    source = {}
    if media_source_id:
        source = next((x for x in sources if str(x.get("Id") or "") == media_source_id), {})
    if not source:
        source = sources[0] if sources else {}
    selected_source_id = str(source.get("Id") or media_source_id or "")
    if selected_source_id and not valid_jellyfin_id(selected_source_id):
        selected_source_id = ""
    play_session_id = str(info.get("PlaySessionId") or "")
    if not play_session_id:
        raise RuntimeError("Jellyfin did not return a PlaySessionId")
    tracks = jellyfin_media_streams(source)
    if requested_audio is None:
        selected_audio = _stream_index(source.get("DefaultAudioStreamIndex"))
        if selected_audio is None and tracks["audio"]:
            selected_audio = next((x["index"] for x in tracks["audio"] if x.get("default")), tracks["audio"][0]["index"])
    else:
        selected_audio = requested_audio
    if requested_subtitle is None:
        selected_subtitle = _stream_index(source.get("DefaultSubtitleStreamIndex"), -1)
        if selected_subtitle is None:
            selected_subtitle = -1
    else:
        selected_subtitle = requested_subtitle
    item_data = jellyfin_item(item_id)
    item_data["kind"] = "video"
    item_data["media_source_id"] = selected_source_id or None
    item_data["resume_ticks"] = start_ticks
    item_data["resume_seconds"] = round(start_ticks / 10_000_000, 1) if start_ticks else 0
    video_stream = tracks.get("video") or {}
    item_data["source_width"] = int(video_stream.get("width") or 0)
    item_data["source_height"] = int(video_stream.get("height") or 0)
    item_data["source_codec"] = video_stream.get("codec") or None
    item_data["source_container"] = source.get("Container") or None
    query = {
        "play_session_id": play_session_id,
        "start_ticks": str(start_ticks),
        "quality": quality_key,
    }
    if selected_source_id:
        query["media_source_id"] = selected_source_id
    if selected_audio is not None and selected_audio >= 0:
        query["audio_stream_index"] = str(selected_audio)
    if selected_subtitle is not None:
        query["subtitle_stream_index"] = str(selected_subtitle)
    return {
        "ok": True,
        "user_id": user_id,
        "user_name": user_name,
        "item": item_data,
        "play_session_id": play_session_id,
        "media_source_id": selected_source_id,
        "start_ticks": start_ticks,
        "quality": quality_key,
        "quality_options": [{"id": key, **value} for key, value in VIDEO_QUALITY_PROFILES.items()],
        "audio_stream_index": selected_audio,
        "subtitle_stream_index": selected_subtitle,
        "audio_streams": tracks["audio"],
        "subtitle_streams": tracks["subtitles"],
        "video_stream": video_stream,
        "stream_url": f"/api/jellyfin/video/{quote(item_id, safe='')}?{urlencode(query)}",
    }


def jellyfin_report_portal_playback(event: str, payload: dict) -> tuple[int, dict]:
    if event not in {"start", "progress", "stopped"}:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid-event"}
    item_id = str(payload.get("item_id") or "")
    play_session_id = str(payload.get("play_session_id") or "")
    media_source_id = str(payload.get("media_source_id") or "")
    if not valid_jellyfin_id(item_id) or not play_session_id or len(play_session_id) > 200:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid-session-data"}
    try:
        position_ticks = max(0, int(payload.get("position_ticks") or 0))
        volume = max(0, min(100, int(payload.get("volume") if payload.get("volume") is not None else 100)))
    except (TypeError, ValueError):
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid-playback-values"}
    play_method = str(payload.get("play_method") or "DirectPlay")
    if play_method not in {"DirectPlay", "DirectStream", "Transcode"}:
        play_method = "DirectPlay"
    body = {
        "ItemId": item_id,
        "PlaySessionId": play_session_id,
        "PositionTicks": position_ticks,
        "CanSeek": True,
        "IsPaused": bool(payload.get("paused")),
        "IsMuted": bool(payload.get("muted")),
        "VolumeLevel": volume,
        "PlayMethod": play_method,
    }
    if media_source_id:
        body["MediaSourceId"] = media_source_id
    if event == "start":
        path = "/Sessions/Playing"
    elif event == "progress":
        path = "/Sessions/Playing/Progress"
    else:
        path = "/Sessions/Playing/Stopped"
        body = {k: body[k] for k in ("ItemId", "PlaySessionId", "PositionTicks", "MediaSourceId") if k in body}
        body["Failed"] = bool(payload.get("failed"))
    try:
        status, _, raw = jellyfin_request(path, method="POST", body=json.dumps(body, separators=(",", ":")).encode(), timeout=4.0)
    except Exception as exc:
        return HTTPStatus.BAD_GATEWAY, {"ok": False, "error": type(exc).__name__}
    if status < 200 or status >= 300:
        return HTTPStatus.BAD_GATEWAY, {"ok": False, "error": f"jellyfin-http-{status}", "detail": raw.decode("utf-8", "replace")[:240]}
    return HTTPStatus.OK, {"ok": True, "event": event}

def jellyfin_control(session_id: str, action: str) -> tuple[int, dict]:
    allowed = {"previous", "playpause", "next", "volume_down", "volume_up", "mute"}
    if action not in allowed:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "unsupported-action"}
    if not session_id or len(session_id) > 160 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in session_id):
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid-session"}
    try:
        session = active_audio_session()
    except Exception as exc:
        return HTTPStatus.BAD_GATEWAY, {"ok": False, "error": type(exc).__name__}
    if not session or session.get("Id") != session_id:
        return HTTPStatus.CONFLICT, {"ok": False, "error": "session-changed"}
    if not session.get("SupportsMediaControl"):
        return HTTPStatus.CONFLICT, {"ok": False, "error": "session-not-controllable"}

    play = session.get("PlayState") or {}
    if action == "playpause":
        command = "Unpause" if play.get("IsPaused") else "Pause"
        path = f"/Sessions/{quote(session_id, safe='')}/Playing/{command}"
    elif action == "previous":
        path = f"/Sessions/{quote(session_id, safe='')}/Playing/PreviousTrack"
    elif action == "next":
        path = f"/Sessions/{quote(session_id, safe='')}/Playing/NextTrack"
    elif action == "volume_down":
        path = f"/Sessions/{quote(session_id, safe='')}/Command/VolumeDown"
    elif action == "volume_up":
        path = f"/Sessions/{quote(session_id, safe='')}/Command/VolumeUp"
    else:
        path = f"/Sessions/{quote(session_id, safe='')}/Command/ToggleMute"
    try:
        status, _, _ = jellyfin_request(path, method="POST", body=b"", timeout=3.0)
    except Exception as exc:
        return HTTPStatus.BAD_GATEWAY, {"ok": False, "error": type(exc).__name__}
    if status < 200 or status >= 300:
        return HTTPStatus.BAD_GATEWAY, {"ok": False, "error": f"jellyfin-http-{status}"}
    return HTTPStatus.OK, {"ok": True, "action": action}

MEDIA_SUFFIXES = {
    ".mkv", ".mp4", ".m4v", ".avi", ".mov", ".mpg", ".mpeg", ".ts",
    ".m2ts", ".vob", ".webm", ".flac", ".mp3", ".m4a", ".aac", ".ogg",
    ".opus", ".wav", ".wma", ".alac", ".ape",
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def safe_run(argv: list[str], timeout: float = 2.0) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, (p.stdout or "").strip()
    except Exception:
        return 127, ""


def human_bytes(value: int) -> str:
    value = int(value or 0)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    num = float(value)
    for unit in units:
        if abs(num) < 1024.0 or unit == units[-1]:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{value} B"


def human_duration(seconds: int | float | None) -> str | None:
    if seconds is None:
        return None
    try:
        seconds = max(0, int(float(seconds)))
    except Exception:
        return None
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def tree_stats(path: Path) -> dict:
    total = 0
    files = 0
    newest = None
    if not path.exists():
        return {"exists": False, "bytes": 0, "human": "0 B", "files": 0, "newest_mtime": None}
    try:
        for base, _, names in os.walk(path):
            for name in names:
                p = Path(base) / name
                try:
                    st = p.stat()
                except OSError:
                    continue
                if not p.is_file():
                    continue
                files += 1
                total += st.st_size
                if newest is None or st.st_mtime > newest:
                    newest = st.st_mtime
    except OSError:
        pass
    return {
        "exists": True,
        "bytes": total,
        "human": human_bytes(total),
        "files": files,
        "newest_mtime": dt.datetime.fromtimestamp(newest, dt.timezone.utc).isoformat(timespec="seconds") if newest else None,
    }


def count_top_level(path: Path) -> int:
    try:
        return sum(1 for p in path.iterdir() if not p.name.startswith(".") and not p.name.endswith(".pcga-classification.json"))
    except OSError:
        return 0


def count_media(path: Path) -> int:
    count = 0
    if not path.exists():
        return 0
    try:
        for base, _, names in os.walk(path):
            for name in names:
                if Path(name).suffix.lower() in MEDIA_SUFFIXES:
                    count += 1
    except OSError:
        pass
    return count


def process_status() -> dict:
    # The sidecar shares ARM's PID namespace (pid: service:arm-rippers), so we
    # can inspect /proc directly without mounting the Docker socket or requiring
    # procps in the status image.
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
            if not raw:
                continue
            elapsed = None
            try:
                stat = (entry / "stat").read_text().split()
                start_ticks = int(stat[21])
                hz = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
                uptime = float(Path("/proc/uptime").read_text().split()[0])
                elapsed = max(0, int(uptime - (start_ticks / hz)))
            except Exception:
                pass
            low = raw.lower()
            kind = None
            if "makemkvcon" in low:
                kind = "makemkv"
            elif "handbrakecli" in low:
                kind = "handbrake"
            elif "python3 /opt/arm/arm/ripper/main.py" in low:
                kind = "arm"
            elif "abcde" in low or "cdparanoia" in low:
                kind = "audio-rip"
            if kind:
                found.append({
                    "kind": kind,
                    "pid": int(entry.name),
                    "elapsed_seconds": elapsed,
                    "elapsed": human_duration(elapsed),
                    "command": raw,
                })
        except (OSError, PermissionError):
            continue
    kinds = {p["kind"] for p in found}
    if "handbrake" in kinds:
        phase = "transcoding"
    elif "makemkv" in kinds:
        phase = "ripping"
    elif "audio-rip" in kinds:
        phase = "audio-ripping"
    elif "arm" in kinds:
        phase = "identifying"
    else:
        phase = "idle"
    active_ingests = active_ingest_status(found)
    return {
        "phase": phase,
        "processes": found,
        "progress": live_makemkv_progress(found),
        "active_ingests": active_ingests,
    }


def _drive_from_command(command: str) -> str | None:
    """Infer the optical block device represented by an ARM child command."""
    import re
    patterns = (
        r"dev:/dev/(sr\d+)",
        r"(?:^|\s)/dev/(sr\d+)(?:\s|$)",
        r"(?:^|\s)-d\s+(sr\d+)(?:\s|$)",
    )
    for pattern in patterns:
        m = re.search(pattern, command)
        if m:
            return "/dev/" + m.group(1)
    return None


def _display_title(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("_", " ")
    if not text:
        return None
    return text.title() if text.upper() == text else text


def _current_arm_jobs() -> dict[str, dict]:
    """Return ARM's current DB job for each drive without taking a write lock."""
    if not ARM_DB.exists():
        return {}
    try:
        uri = f"file:{ARM_DB}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=0.15)
        conn.row_factory = sqlite3.Row
        tables = _sqlite_tables(conn)
        jobs_table = next((t for t in tables if t.lower() in {"job", "jobs"}), None)
        drives_table = next((t for t in tables if "drive" in t.lower()), None)
        if not jobs_table or not drives_table:
            conn.close()
            return {}
        jcols = [r[1] for r in conn.execute(f'PRAGMA table_info("{jobs_table}")').fetchall()]
        dcols = [r[1] for r in conn.execute(f'PRAGMA table_info("{drives_table}")').fetchall()]
        job_id_col = next((c for c in ("job_id", "id") if c in jcols), None)
        if not job_id_col or "mount" not in dcols or "job_id_current" not in dcols:
            conn.close()
            return {}
        result: dict[str, dict] = {}
        drive_rows = conn.execute(
            f'SELECT "mount", "job_id_current" FROM "{drives_table}" '
            'WHERE "job_id_current" IS NOT NULL'
        ).fetchall()
        wanted = [c for c in (job_id_col, "status", "title", "year", "disctype", "video_type", "start_time", "devpath", "logfile") if c in jcols]
        projection = ", ".join('"' + c + '"' for c in wanted)
        track_table = next((t for t in tables if t.lower() in {"track", "tracks"}), None)
        track_cols = []
        if track_table:
            track_cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{track_table}")').fetchall()]
        for drow in drive_rows:
            mount = str(drow["mount"] or "")
            current = drow["job_id_current"]
            if not mount or current is None:
                continue
            jrow = conn.execute(
                f'SELECT {projection} FROM "{jobs_table}" WHERE "{job_id_col}"=? LIMIT 1',
                (current,),
            ).fetchone()
            if jrow:
                item = {k: jrow[k] for k in jrow.keys()}
                item["job_id"] = item.get(job_id_col)
                item["tracks"] = []
                if track_table and {"job_id", "track_number", "length"}.issubset(track_cols):
                    try:
                        rows = conn.execute(
                            f'SELECT "track_number", "length" FROM "{track_table}" WHERE "job_id"=?',
                            (current,),
                        ).fetchall()
                        for row in rows:
                            try:
                                number = int(str(row["track_number"]).strip())
                                length = int(row["length"] or 0)
                            except (TypeError, ValueError):
                                continue
                            if number > 0 and length > 0:
                                item["tracks"].append({"number": number, "length": length})
                        item["tracks"].sort(key=lambda x: x["number"])
                    except sqlite3.Error:
                        item["tracks"] = []
                result[mount] = item
        conn.close()
        return result
    except Exception:
        return {}


def _makemkv_output_dir(command: str) -> Path | None:
    import re
    # ARM uses paths without shell quoting in /proc/cmdline reconstruction and
    # its generated raw directory names are whitespace-free. Keep this parser
    # conservative; absence merely disables the byte-based estimate.
    m = re.search(r"(?:^|\s)all\s+(\S+)(?:\s|$)", command)
    if not m:
        return None
    try:
        path = Path(m.group(1))
        root = RAW.resolve(strict=False)
        resolved = path.resolve(strict=False)
        if resolved != root and root not in resolved.parents:
            return None
        return path
    except Exception:
        return None


def _tree_bytes(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        if path.is_file():
            return path.stat().st_size
        if not path.exists():
            return 0
        total = 0
        for base, _, names in os.walk(path):
            for name in names:
                try:
                    total += (Path(base) / name).stat().st_size
                except OSError:
                    pass
        return total
    except OSError:
        return None


def _drive_capacity_bytes(drive: str | None) -> int | None:
    if not drive:
        return None
    try:
        name = Path(drive).name
        sectors = int((Path("/host-sys/class/block") / name / "size").read_text().strip())
        size = sectors * 512
        return size if size > 0 else None
    except Exception:
        return None


def _makemkv_progress_for_process(proc: dict) -> dict | None:
    """Read progress for one live MakeMKV process only."""
    import re
    command = str(proc.get("command") or "")
    m = re.search(r"--progress=(?:\"([^\"]+)\"|(\S+))", command)
    if not m:
        return None
    raw_path = m.group(1) or m.group(2)
    try:
        path = Path(raw_path)
        resolved = path.resolve(strict=False)
        root = PROGRESS_DIR.resolve(strict=False)
        if resolved != root and root not in resolved.parents:
            return None
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    title = None
    operation = None
    values = None
    for line in lines[-400:]:
        if line.startswith("PRGT:"):
            mm = re.match(r'PRGT:\d+,\d+,"(.*)"$', line)
            if mm:
                title = mm.group(1)
        elif line.startswith("PRGC:"):
            mm = re.match(r'PRGC:\d+,\d+,"(.*)"$', line)
            if mm:
                operation = mm.group(1)
        elif line.startswith("PRGV:"):
            mm = re.match(r"PRGV:(\d+),(\d+),(\d+)$", line)
            if mm:
                values = tuple(int(x) for x in mm.groups())
    percent = None
    if values and values[2] > 0:
        percent = round(min(100.0, 100.0 * max(values[0], values[1]) / values[2]), 1)
    drive = _drive_from_command(command)
    output_dir = _makemkv_output_dir(command)
    output_bytes = _tree_bytes(output_dir)
    source_bytes = _drive_capacity_bytes(drive)
    estimated_percent = None
    if output_bytes is not None and source_bytes:
        # Output size is an estimate: extras, duplicate seamless segments, and
        # unused sectors mean it is not an exact optical-disc completion ratio.
        estimated_percent = round(min(99.0, 100.0 * output_bytes / source_bytes), 1)
    return {
        "live": True,
        "pid": proc.get("pid"),
        "drive": drive,
        "file": path.name,
        "title": title,
        "operation": operation,
        "values": list(values) if values else None,
        "percent": percent,
        "estimated_percent": estimated_percent,
        "output_bytes": output_bytes,
        "source_bytes": source_bytes,
        "elapsed_seconds": proc.get("elapsed_seconds"),
        "elapsed": proc.get("elapsed"),
    }


def live_makemkv_progress(processes: list[dict]) -> dict | None:
    """Backward-compatible single progress record for the first live rip."""
    for proc in processes:
        if proc.get("kind") != "makemkv":
            continue
        progress = _makemkv_progress_for_process(proc)
        if progress:
            return progress
    return None


def _arm_job_log_path(job: dict) -> Path | None:
    """Resolve one ARM job log while keeping reads inside the mounted log root."""
    raw = str(job.get("logfile") or "").strip()
    if not raw:
        return None
    candidates = [Path(raw)]
    if not Path(raw).is_absolute():
        candidates += [ARM_LOGS / raw, ARM_LOGS / Path(raw).name]
    root = ARM_LOGS.resolve(strict=False)
    for path in candidates:
        try:
            resolved = path.resolve(strict=False)
            if resolved != root and root not in resolved.parents:
                continue
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def _tail_text(path: Path, limit: int = 2 * 1024 * 1024) -> str:
    """Read a bounded tail; splitlines() later handles cdparanoia CR updates."""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - limit), os.SEEK_SET)
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _audio_progress_for_job(job: dict, processes: list[dict]) -> dict | None:
    """Derive live abcde/cdparanoia progress from ARM's per-job log.

    cdparanoia reports absolute CD sectors.  ARM already stores audio-track
    lengths in its Track rows, so we can weight the current track accurately
    and fall back to equal track weighting when those rows are unavailable.
    """
    import re

    path = _arm_job_log_path(job)
    if path is None:
        return None
    text = _tail_text(path)
    if not text:
        return None
    lines = text.splitlines()

    track_count = 0
    db_tracks = []
    for row in job.get("tracks") or []:
        try:
            number = int(row.get("number") or 0)
            length = int(row.get("length") or 0)
        except (TypeError, ValueError):
            continue
        if number > 0 and length > 0:
            db_tracks.append((number, length))
    db_tracks.sort()
    if db_tracks:
        track_count = len(db_tracks)

    # Track count is also printed by abcde before it starts reading.
    for line in lines:
        m = re.search(r"Grabbing entire CD\s*-\s*tracks:\s*(.*)$", line, re.I)
        if m:
            nums = [int(x) for x in re.findall(r"\b\d+\b", m.group(1))]
            if nums:
                track_count = max(track_count, len(nums), max(nums))
        m = re.search(r"(?:Encoding|Tagging|Moving) track\s+\d+\s+of\s+(\d+)", line, re.I)
        if m:
            track_count = max(track_count, int(m.group(1)))

    grab_index = None
    track_number = None
    track_title = None
    for i, line in enumerate(lines):
        m = re.search(r"Grabbing track\s+(\d+)\s*:\s*(.*?)\s*\.{3}\s*$", line, re.I)
        if m:
            grab_index = i
            track_number = int(m.group(1))
            track_title = m.group(2).strip() or None
    if grab_index is None or track_number is None:
        return {
            "percent": None,
            "track_percent": None,
            "track_number": None,
            "track_count": track_count or None,
            "track_title": None,
            "operation": "Preparing audio CD",
            "source": "abcde-log",
            "log_file": path.name,
        }

    segment = lines[grab_index:]
    start_sector = end_sector = current_sector = None
    for line in segment:
        m = re.search(r"Ripping from sector\s+(\d+)\s+\(track\s+(\d+)", line, re.I)
        if m and int(m.group(2)) == track_number:
            start_sector = int(m.group(1))
        m = re.search(r"to sector\s+(\d+)\s+\(track\s+(\d+)", line, re.I)
        if m and int(m.group(2)) == track_number:
            end_sector = int(m.group(1))
        # cdparanoia writes this progress display repeatedly with carriage
        # returns; splitlines() exposes each update as a logical line.
        m = re.search(r"\|\s*(\d+)\s+\d+\s*\]", line)
        if m:
            current_sector = int(m.group(1))

    done = any(line.strip() == "Done." for line in segment)
    failed = any("commands failed to run" in line.lower() or "readtrack-" in line.lower() and "returned code" in line.lower() for line in segment)
    fraction = None
    if start_sector is not None and end_sector is not None and end_sector >= start_sector:
        if current_sector is not None:
            fraction = (current_sector - start_sector) / max(1, end_sector - start_sector + 1)
            fraction = max(0.0, min(1.0, fraction))
        elif done and not failed:
            fraction = 1.0
    elif done and not failed:
        fraction = 1.0

    percent = None
    source = "abcde-log"
    if fraction is not None and db_tracks and (not track_count or len(db_tracks) >= track_count):
        ordered = [x for x in db_tracks if x[0] <= track_count or not track_count]
        index = next((i for i, (n, _) in enumerate(ordered) if n == track_number), None)
        if index is not None:
            total = sum(length for _, length in ordered)
            before = sum(length for _, length in ordered[:index])
            current_length = ordered[index][1]
            if total > 0:
                percent = 100.0 * (before + current_length * fraction) / total
                source = "abcde-log+arm-track-lengths"
    if percent is None and fraction is not None and track_count:
        position = max(0, min(track_count - 1, track_number - 1))
        percent = 100.0 * (position + fraction) / track_count
        source = "abcde-log+track-count"

    if percent is not None:
        percent = round(max(0.0, min(100.0, percent)), 1)
    track_percent = round(fraction * 100.0, 1) if fraction is not None else None

    cdparanoia_live = any("cdparanoia" in str(p.get("command") or "").lower() for p in processes)
    if failed:
        operation = f"Audio read error on track {track_number}"
    elif cdparanoia_live or fraction is not None and fraction < 1.0:
        operation = f"Ripping track {track_number}" + (f" of {track_count}" if track_count else "")
    elif track_count and track_number >= track_count and done:
        operation = "Finalizing audio files"
        if percent is None:
            percent = 100.0
    else:
        operation = f"Preparing track {min(track_number + 1, track_count) if track_count else track_number + 1}"

    return {
        "percent": percent,
        "track_percent": track_percent,
        "track_number": track_number,
        "track_count": track_count or None,
        "track_title": track_title,
        "start_sector": start_sector,
        "end_sector": end_sector,
        "current_sector": current_sector,
        "operation": operation,
        "source": source,
        "log_file": path.name,
    }


def active_ingest_status(processes: list[dict]) -> list[dict]:
    """Build persistent UI cards for every genuinely-live optical ingest lane."""
    jobs = _current_arm_jobs()
    by_drive: dict[str, list[dict]] = {}
    for proc in processes:
        drive = _drive_from_command(str(proc.get("command") or ""))
        if drive:
            by_drive.setdefault(drive, []).append(proc)

    tasks: list[dict] = []
    drives = sorted(set(jobs) | set(by_drive))
    for drive in drives:
        procs = by_drive.get(drive, [])
        # A DB row without a live process is stale and must never create a modal.
        if not procs:
            continue
        job = jobs.get(drive, {})
        makemkv = next((p for p in procs if p.get("kind") == "makemkv"), None)
        handbrake = next((p for p in procs if p.get("kind") == "handbrake"), None)
        audio_procs = [p for p in procs if p.get("kind") == "audio-rip"]
        audio = next((p for p in audio_procs if "abcde" in str(p.get("command") or "").lower()), None) or (audio_procs[0] if audio_procs else None)
        arm = next((p for p in procs if p.get("kind") == "arm"), None)
        chosen = makemkv or handbrake or audio or arm or procs[0]

        progress = _makemkv_progress_for_process(makemkv) if makemkv else None
        audio_progress = _audio_progress_for_job(job, procs) if audio else None
        if makemkv:
            phase = "ripping"
            operation = (progress or {}).get("operation") or "Ripping disc"
        elif audio:
            phase = "audio-ripping"
            operation = (audio_progress or {}).get("operation") or "Ripping audio disc"
        elif handbrake:
            phase = "transcoding"
            operation = "Transcoding media"
        else:
            phase = "identifying"
            operation = "Preparing disc"

        dispatch_state = optical_dispatch(Path(drive).name)
        media_meta = dispatch_state.get("media_metadata") if isinstance(dispatch_state.get("media_metadata"), dict) else {}
        title = _display_title(job.get("title"))
        if not title or title in {"Optical Media", "Unknown", "Unknown Title"}:
            title = _display_title(media_meta.get("collection_title")) or _display_title(media_meta.get("title")) or (progress or {}).get("title") or ("Audio CD" if audio else "Optical media")

        reported = (audio_progress or {}).get("percent") if audio else (progress or {}).get("percent")
        estimated = None if audio else (progress or {}).get("estimated_percent")
        use_estimate = estimated is not None and (reported is None or estimated > reported + 3.0)
        display_percent = estimated if use_estimate else reported
        tasks.append({
            "live": True,
            "drive": drive,
            "job_id": job.get("job_id"),
            "title": title,
            "disctype": job.get("disctype"),
            "phase": phase,
            "operation": operation,
            "percent": display_percent,
            "percent_estimated": bool(use_estimate),
            "reported_percent": reported,
            "estimated_percent": estimated,
            "progress_source": (audio_progress or {}).get("source") if audio else ("makemkv" if progress else None),
            "track_number": (audio_progress or {}).get("track_number") if audio else media_meta.get("disc_number"),
            "track_count": (audio_progress or {}).get("track_count") if audio else media_meta.get("disc_count"),
            "track_percent": (audio_progress or {}).get("track_percent") if audio else None,
            "track_title": (audio_progress or {}).get("track_title") if audio else (media_meta.get("layout") or media_meta.get("disc_role")),
            "elapsed_seconds": chosen.get("elapsed_seconds"),
            "elapsed": chosen.get("elapsed"),
            "pid": chosen.get("pid"),
        })

    # MakeMKV can briefly exist before ARM's DB row becomes readable. Preserve
    # visibility rather than dropping the activity modal during that window.
    known = {t["drive"] for t in tasks}
    for proc in processes:
        if proc.get("kind") != "makemkv":
            continue
        drive = _drive_from_command(str(proc.get("command") or ""))
        if not drive or drive in known:
            continue
        progress = _makemkv_progress_for_process(proc) or {}
        tasks.append({
            "live": True,
            "drive": drive,
            "job_id": None,
            "title": progress.get("title") or "Optical media",
            "disctype": None,
            "phase": "ripping",
            "operation": progress.get("operation") or "Ripping disc",
            "percent": progress.get("estimated_percent") if progress.get("estimated_percent") is not None and (progress.get("percent") is None or progress.get("estimated_percent") > progress.get("percent") + 3.0) else progress.get("percent"),
            "percent_estimated": bool(progress.get("estimated_percent") is not None and (progress.get("percent") is None or progress.get("estimated_percent") > progress.get("percent") + 3.0)),
            "reported_percent": progress.get("percent"),
            "estimated_percent": progress.get("estimated_percent"),
            "elapsed_seconds": proc.get("elapsed_seconds"),
            "elapsed": proc.get("elapsed"),
            "pid": proc.get("pid"),
        })
    # PC/data-disc preservation runs on the host rather than inside ARM's PID
    # namespace, so expose its persistent dispatcher state as the same optical
    # ingest card used by movie and music rips.
    known = {str(t.get("drive") or "") for t in tasks}
    now = dt.datetime.now(dt.timezone.utc)
    for dev in configured_drives():
        name = Path(dev).name
        state = optical_dispatch(name)
        status = str(state.get("dispatch_status") or "")
        if status not in {"ripping", "retrying", "verifying"} or dev in known:
            continue
        updated = state.get("updated_at")
        try:
            freshness = (now - dt.datetime.fromisoformat(str(updated).replace("Z", "+00:00"))).total_seconds()
        except Exception:
            freshness = 9999
        if freshness > 20:
            continue
        started = state.get("started_at")
        elapsed_seconds = None
        try:
            elapsed_seconds = max(0, int((now - dt.datetime.fromisoformat(str(started).replace("Z", "+00:00"))).total_seconds()))
        except Exception:
            pass
        meta = state.get("game_metadata") if isinstance(state.get("game_metadata"), dict) else {}
        title = _display_title(meta.get("collection_title")) or _display_title(meta.get("title")) or _display_title((state.get("filesystem") or {}).get("label")) or "PC/Data disc"
        tasks.append({
            "live": True, "drive": dev, "job_id": None, "title": title,
            "disctype": state.get("kind"), "phase": "pc-disc-imaging",
            "operation": state.get("operation") or "Preserving PC/data disc",
            "percent": state.get("progress_percent"), "percent_estimated": False,
            "reported_percent": state.get("progress_percent"), "estimated_percent": None,
            "progress_source": "pcga-preservation", "track_number": meta.get("disc_number"),
            "track_count": meta.get("disc_count"), "track_title": meta.get("disc_role"),
            "elapsed_seconds": elapsed_seconds, "elapsed": human_duration(elapsed_seconds), "pid": None,
        })
    return sorted(tasks, key=lambda x: str(x.get("drive") or ""))


def configured_drives() -> list[str]:
    try:
        rows = [x.strip() for x in DRIVES_FILE.read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        rows = []
    if not rows:
        rows = sorted(str(p) for p in Path("/dev").glob("sr[0-9]*"))
    return rows


def drive_role(dev: str) -> str | None:
    try:
        for raw in ROLES_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            if not raw or raw.startswith("#"):
                continue
            cols = raw.split("\t")
            if cols and cols[0] == dev:
                return cols[1] if len(cols) > 1 else None
    except OSError:
        pass
    return None


def optical_health(name: str) -> dict:
    p = OPTICAL_HEALTH_DIR / f"{name}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def optical_dispatch(name: str) -> dict:
    p = OPTICAL_DISPATCH_DIR / f"{name}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def tcp_open(port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((TOOL_HOST, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def lancommander_tcp_target(timeout: float = 0.35) -> str | None:
    # LANCommander shares the Compose network with pcga-status, so service DNS is
    # the most direct health path.  Retain the host-gateway mapping as a fallback
    # for upgraded stacks whose network attachment differs from the clean install.
    for host in ("lancommander", TOOL_HOST):
        try:
            with socket.create_connection((host, LANCOMMANDER_PORT), timeout=timeout):
                return host
        except OSError:
            continue
    return None


# PCGA owns the public console-game API. RomM remains an internal metadata and
# storage service; its bootstrap credentials are never returned to the browser.
EJS_CORES = {
    "3do":["opera"], "acpc":["cap32","crocods"], "amiga":["puae"], "amiga-cd32":["puae"],
    "arcade":["mame2003","mame2003_plus","fbneo","fbalpha2012_cps1","fbalpha2012_cps2"],
    "neogeoaes":["fbneo"], "neogeomvs":["fbneo"], "atari2600":["stella2014"],
    "atari-2600-plus":["stella2014"], "atari5200":["a5200"], "atari7800":["prosystem"],
    "c-plus-4":["vice_xplus4"], "c64":["vice_x64sc","vice_x64"], "cpet":["vice_xpet"],
    "commodore-64c":["vice_x64sc","vice_x64"], "c128":["vice_x128"], "commmodore-128":["vice_x128"],
    "colecovision":["gearcoleco"], "doom":["prboom"], "dos":["dosbox_pure"], "jaguar":["virtualjaguar"],
    "lynx":["handy"], "atari-lynx-mkii":["handy"], "neo-geo-pocket":["mednafen_ngp"],
    "neo-geo-pocket-color":["mednafen_ngp"], "nes":["fceumm","nestopia"], "famicom":["fceumm","nestopia"],
    "fds":["fceumm","nestopia"], "game-televisison":["fceumm"], "new-style-nes":["fceumm"],
    "n64":["mupen64plus_next","parallel_n64"], "ique-player":["mupen64plus_next"],
    "nds":["melonds","desmume","desmume2015"], "nintendo-ds-lite":["melonds","desmume","desmume2015"],
    "nintendo-dsi":["melonds","desmume","desmume2015"], "nintendo-dsi-xl":["melonds","desmume","desmume2015"],
    "gb":["gambatte","mgba"], "game-boy-pocket":["gambatte","mgba"], "game-boy-light":["gambatte","mgba"],
    "gba":["mgba"], "game-boy-adavance-sp":["mgba"], "game-boy-micro":["mgba"], "gbc":["gambatte","mgba"],
    "pc-fx":["mednafen_pcfx"], "psx":["pcsx_rearmed","mednafen_psx_hw"], "philips-cd-i":["same_cdi"],
    "psp":["ppsspp"], "segacd":["genesis_plus_gx","picodrive"], "sega32":["picodrive"],
    "gamegear":["genesis_plus_gx"], "sms":["genesis_plus_gx"], "sega-mark-iii":["genesis_plus_gx"],
    "sega-game-box-9":["genesis_plus_gx"], "sega-master-system-ii":["genesis_plus_gx","smsplus"],
    "master-system-super-compact":["genesis_plus_gx"], "master-system-girl":["genesis_plus_gx"],
    "genesis":["genesis_plus_gx"], "sega-mega-drive-2-slash-genesis":["genesis_plus_gx"],
    "sega-mega-jet":["genesis_plus_gx"], "mega-pc":["genesis_plus_gx"], "tera-drive":["genesis_plus_gx"],
    "sega-nomad":["genesis_plus_gx"], "saturn":["yabause"], "snes":["snes9x"], "sfam":["snes9x"],
    "super-nintendo-original-european-version":["snes9x"], "super-famicom-shvc-001":["snes9x"],
    "super-famicom-jr-model-shvc-101":["snes9x"], "new-style-super-nes-model-sns-101":["snes9x"],
    "tg16":["mednafen_pce"], "turbografx-cd":["mednafen_pce"], "supergrafx":["mednafen_pce"],
    "vic-20":["vice_xvic"], "virtualboy":["beetle_vb"], "wonderswan":["mednafen_wswan"],
    "swancrystal":["mednafen_wswan"], "wonderswan-color":["mednafen_wswan"], "zxs":["fuse"],
}
EJS_THREAD_CORES = {"dosbox_pure", "ppsspp", "azahar"}
EJS_CONTROL_SCHEMES = {
    "segacd":"segaCD", "sega32":"sega32x", "gamegear":"segaGG", "sms":"segaMS",
    "sega-mark-iii":"segaMS", "sega-game-box-9":"segaMS", "sega-master-system-ii":"segaMS",
    "master-system-super-compact":"segaMS", "master-system-girl":"segaMS", "genesis":"segaMD",
    "sega-mega-drive-2-slash-genesis":"segaMD", "sega-mega-jet":"segaMD", "mega-pc":"segaMD",
    "tera-drive":"segaMD", "sega-nomad":"segaMD", "saturn":"segaSaturn",
}


def _read_env_file(path: Path) -> dict[str, str]:
    out = {}
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def romm_credentials() -> tuple[str, str] | None:
    env = _read_env_file(ROMM_CREDS_FILE)
    user = env.get("PCGA_ROMM_ADMIN_USER", "").strip()
    password = env.get("PCGA_ROMM_ADMIN_PASSWORD", "").strip()
    return (user, password) if user and password else None


ROMM_OAUTH_SCOPES = "roms.read platforms.read assets.read firmware.read tasks.run"
_ROMM_TOKEN_CACHE: dict[str, object] = {"access_token": "", "expires_at": 0.0}
_ROMM_TOKEN_LOCK = threading.Lock()
_ROMM_PIPELINE_CACHE: dict[str, object] = {"expires_at": 0.0, "value": None}
_ROMM_PIPELINE_LOCK = threading.Lock()


def romm_public_request(path: str, method: str = "GET", body: bytes | None = None, timeout: float = 8.0,
                        extra_headers: dict[str, str] | None = None):
    headers = {"Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(f"http://{TOOL_HOST}:{ROMM_PORT}{path}", data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def romm_access_token(force: bool = False) -> str:
    now = time.monotonic()
    cached = str(_ROMM_TOKEN_CACHE.get("access_token") or "")
    expires_at = float(_ROMM_TOKEN_CACHE.get("expires_at") or 0.0)
    if not force and cached and now < expires_at - 30:
        return cached
    with _ROMM_TOKEN_LOCK:
        now = time.monotonic()
        cached = str(_ROMM_TOKEN_CACHE.get("access_token") or "")
        expires_at = float(_ROMM_TOKEN_CACHE.get("expires_at") or 0.0)
        if not force and cached and now < expires_at - 30:
            return cached
        creds = romm_credentials()
        if not creds:
            raise RuntimeError("RomM appliance credentials unavailable")
        form = urlencode({
            "grant_type": "password",
            "username": creds[0],
            "password": creds[1],
            "scope": ROMM_OAUTH_SCOPES,
        }).encode()
        status, _, raw = romm_public_request(
            "/api/token", method="POST", body=form, timeout=8.0,
            extra_headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if status < 200 or status >= 300:
            detail = raw.decode("utf-8", "replace")[:240]
            raise RuntimeError(f"RomM token endpoint returned HTTP {status}: {detail}")
        try:
            data = json.loads(raw.decode("utf-8", "replace") or "{}")
            token = str(data.get("access_token") or "").strip()
            expires = max(60, int(data.get("expires") or 900))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("RomM token endpoint returned invalid JSON") from exc
        if not token:
            raise RuntimeError("RomM token endpoint returned no access token")
        _ROMM_TOKEN_CACHE["access_token"] = token
        _ROMM_TOKEN_CACHE["expires_at"] = time.monotonic() + expires
        return token


def romm_headers(force_token: bool = False) -> dict[str, str]:
    token = romm_access_token(force=force_token)
    return {"Accept": "application/json", "Authorization": f"Bearer {token}"}


def romm_request(path: str, method: str = "GET", body: bytes | None = None, timeout: float = 8.0,
                 extra_headers: dict[str, str] | None = None):
    for attempt in range(2):
        headers = romm_headers(force_token=bool(attempt))
        if body is not None:
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(f"http://{TOOL_HOST}:{ROMM_PORT}{path}", data=body, headers=headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            if exc.code == HTTPStatus.UNAUTHORIZED and attempt == 0:
                try:
                    exc.close()
                except Exception:
                    pass
                continue
            return exc.code, exc.headers, raw
    raise RuntimeError("RomM authentication retry exhausted")


def romm_json(path: str, timeout: float = 8.0):
    status, _, raw = romm_request(path, timeout=timeout)
    if status < 200 or status >= 300:
        detail = raw.decode("utf-8", "replace")[:240]
        raise RuntimeError(f"RomM returned HTTP {status}: {detail}")
    return json.loads(raw.decode("utf-8", "replace") or "null")


def romm_trigger_scan() -> dict:
    status, _, raw = romm_request(
        "/api/tasks/run/scan_library", method="POST", body=b"{}", timeout=12.0,
        extra_headers={"Content-Type": "application/json"},
    )
    if status < 200 or status >= 300:
        detail = raw.decode("utf-8", "replace")[:320]
        raise RuntimeError(f"RomM scan task returned HTTP {status}: {detail}")
    try:
        data = json.loads(raw.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        data = {}
    task_id = ""
    if isinstance(data, dict):
        task_id = str(data.get("id") or data.get("task_id") or data.get("job_id") or "")
    return {"ok": True, "state": "queued", "detail": "RomM library scan queued", "task_id": task_id}


def _romm_bootstrap_state() -> str:
    try:
        return Path("/var/lib/pc-game-archive/bootstrap/romm.state").read_text().strip() or "missing"
    except OSError:
        return "missing"


def romm_pipeline_health(force: bool = False) -> dict:
    now = time.monotonic()
    cached_value = _ROMM_PIPELINE_CACHE.get("value")
    expires_at = float(_ROMM_PIPELINE_CACHE.get("expires_at") or 0.0)
    if not force and isinstance(cached_value, dict) and now < expires_at:
        return dict(cached_value)
    with _ROMM_PIPELINE_LOCK:
        now = time.monotonic()
        cached_value = _ROMM_PIPELINE_CACHE.get("value")
        expires_at = float(_ROMM_PIPELINE_CACHE.get("expires_at") or 0.0)
        if not force and isinstance(cached_value, dict) and now < expires_at:
            return dict(cached_value)
        result = {
            "available": False,
            "state": _romm_bootstrap_state(),
            "stages": {
                "bootstrap": False,
                "credentials": False,
                "tcp": False,
                "heartbeat": False,
                "emulatorjs": False,
                "oauth": False,
                "platforms": False,
                "assets": False,
            },
            "detail": "",
        }
        stages = result["stages"]
        try:
            if result["state"] != "ready":
                raise RuntimeError(f"RomM bootstrap state is {result['state']}")
            stages["bootstrap"] = True
            if not romm_credentials():
                raise RuntimeError("RomM appliance credentials are missing")
            stages["credentials"] = True
            if not tcp_open(ROMM_PORT, timeout=0.5):
                raise RuntimeError("RomM TCP endpoint is not reachable")
            stages["tcp"] = True
            status, _, raw = romm_public_request("/api/heartbeat", timeout=5.0)
            if status < 200 or status >= 300:
                raise RuntimeError(f"RomM heartbeat returned HTTP {status}")
            heartbeat = json.loads(raw.decode("utf-8", "replace") or "{}")
            stages["heartbeat"] = True
            disabled = bool(((heartbeat.get("EMULATION") or {}).get("DISABLE_EMULATOR_JS"))) if isinstance(heartbeat, dict) else True
            if disabled:
                raise RuntimeError("RomM reports EmulatorJS disabled")
            stages["emulatorjs"] = True
            romm_access_token(force=False)
            stages["oauth"] = True
            status, _, raw = romm_request("/api/platforms", timeout=8.0)
            if status < 200 or status >= 300:
                detail = raw.decode("utf-8", "replace")[:160]
                raise RuntimeError(f"RomM platforms API returned HTTP {status}: {detail}")
            stages["platforms"] = True
            status, _, raw = romm_public_request("/assets/emulatorjs/data/loader.js", timeout=8.0)
            if status < 200 or status >= 300 or len(raw) < 64:
                raise RuntimeError(f"RomM EmulatorJS loader returned HTTP {status}")
            stages["assets"] = True
            result["available"] = True
            result["detail"] = "Emulator pipeline ready"
            if isinstance(heartbeat, dict):
                result["romm_version"] = str(((heartbeat.get("SYSTEM") or {}).get("VERSION")) or "")
        except Exception as exc:
            result["detail"] = str(exc)[:240]
        result["checked_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _ROMM_PIPELINE_CACHE["value"] = dict(result)
        _ROMM_PIPELINE_CACHE["expires_at"] = time.monotonic() + (20.0 if result["available"] else 15.0)
        return result


def romm_portal_ready() -> bool:
    return bool(romm_pipeline_health().get("available"))

def _pick(d: dict, *keys, default=None):
    for key in keys:
        value = d.get(key)
        if value not in (None, ""):
            return value
    return default


def _platform_parts(item: dict) -> tuple[int | None, str, str]:
    p = item.get("platform") if isinstance(item.get("platform"), dict) else {}
    pid = _pick(item, "platform_id", default=_pick(p, "id"))
    try:
        pid = int(pid) if pid is not None else None
    except (TypeError, ValueError):
        pid = None
    slug = str(_pick(item, "platform_slug", default=_pick(p, "fs_slug", "slug", default="")) or "").strip().lower()
    name = str(_pick(item, "platform_name", default=_pick(p, "name", "display_name", default=slug)) or slug)
    return pid, slug, name


def normalize_romm_platform(item: dict) -> dict:
    try:
        pid = int(item.get("id"))
    except (TypeError, ValueError):
        pid = 0
    slug = str(_pick(item, "fs_slug", "slug", default="") or "").strip().lower()
    cores = list(EJS_CORES.get(slug, []))
    return {
        "id": pid,
        "name": str(_pick(item, "name", "display_name", default=slug or f"Platform {pid}")),
        "slug": slug,
        "rom_count": int(_pick(item, "rom_count", "roms_count", "count", default=0) or 0),
        "engine": "emulatorjs" if cores else None,
        "cores": cores,
        "playable": bool(cores),
    }


def _cover_present(item: dict) -> bool:
    return bool(_pick(item, "path_cover_small", "path_cover_large", "path_cover_s", "path_cover_l", "url_cover"))


def _romm_provider_blocks(item: dict):
    # RomM keeps normalized fields at the top level and provider-specific detail
    # in *_metadata objects.  Prefer normalized values, then fall back to the
    # provider blocks so PCGA remains useful across small RomM schema changes.
    for key in (
        "igdb_metadata", "ss_metadata", "moby_metadata", "launchbox_metadata",
        "hasheous_metadata", "ra_metadata", "tgdb_metadata", "flashpoint_metadata",
        "hltb_metadata", "steam_metadata", "gamelist_metadata",
    ):
        value = item.get(key)
        if isinstance(value, dict) and value:
            yield key.removesuffix("_metadata"), value


def _romm_meta_value(item: dict, *keys, default=None):
    value = _pick(item, *keys, default=None)
    if value not in (None, "", [], {}):
        return value
    for _, block in _romm_provider_blocks(item):
        value = _pick(block, *keys, default=None)
        if value not in (None, "", [], {}):
            return value
    return default


def _romm_text_list(item: dict, *keys, limit: int = 24) -> list[str]:
    raw = _romm_meta_value(item, *keys, default=[])
    if not isinstance(raw, (list, tuple, set)):
        raw = [raw] if raw not in (None, "") else []
    out = []
    for value in raw:
        if isinstance(value, dict):
            nested = value.get("company") if isinstance(value.get("company"), dict) else None
            if nested:
                value = _pick(nested, "name", "title", "display_name", "identifier", default="")
            else:
                value = _pick(value, "name", "title", "display_name", "identifier", default="")
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _romm_image_url(value) -> str | None:
    if isinstance(value, dict):
        value = _pick(value, "url", "image_url", "cover_url", "src", default="")
    raw = str(value or "").strip()
    if raw.startswith("//"):
        return "https:" + raw
    if raw.startswith(("http://", "https://", "/assets/")):
        return raw
    return None


def _romm_screenshots(item: dict, limit: int = 6) -> list[str]:
    candidates = []
    for key in ("screenshots", "artworks"):
        raw = item.get(key)
        if isinstance(raw, list):
            candidates.extend(raw)
    for _, block in _romm_provider_blocks(item):
        for key in ("screenshots", "artworks"):
            raw = block.get(key)
            if isinstance(raw, list):
                candidates.extend(raw)
    out = []
    for value in candidates:
        url = _romm_image_url(value)
        if url and url not in out:
            out.append(url)
        if len(out) >= limit:
            break
    return out


def _romm_cover_url(item: dict, rid: int) -> str | None:
    local = _pick(item, "path_cover_small", "path_cover_large", "path_cover_s", "path_cover_l", default="")
    if rid and local:
        return f"/api/games/cover/{rid}"
    # A newly identified ROM can have provider artwork before RomM finishes
    # caching the resource locally.  Use the provider URL until the local copy
    # exists rather than presenting a broken internal image endpoint.
    return _romm_image_url(_pick(item, "url_cover", "cover_url", default=""))


def normalize_romm_rom(item: dict) -> dict:
    try:
        rid = int(item.get("id"))
    except (TypeError, ValueError):
        rid = 0
    pid, slug, platform_name = _platform_parts(item)
    cores = list(EJS_CORES.get(slug, []))
    fs_name = str(_pick(item, "fs_name", default="") or "")
    name = str(_pick(item, "name", "fs_name_no_tags", "fs_name_no_ext", default=fs_name or f"ROM {rid}"))
    core = cores[0] if cores else ""
    summary = str(_romm_meta_value(item, "summary", "description", default="") or "")[:5000]
    providers = [name for name, _ in _romm_provider_blocks(item)]
    for provider, key in (("igdb", "igdb_id"), ("hasheous", "hasheous_id"), ("screenscraper", "ss_id"), ("moby", "moby_id"), ("retroachievements", "ra_id"), ("launchbox", "launchbox_id"), ("thegamesdb", "tgdb_id")):
        if item.get(key) not in (None, "", 0, "0") and provider not in providers:
            providers.append(provider)
    identified = bool(item.get("is_identified")) or bool(providers)
    return {
        "id": rid,
        "name": name,
        "fs_name": fs_name,
        "platform_id": pid,
        "platform": platform_name,
        "platform_slug": slug,
        "summary": summary,
        "release_date": _romm_meta_value(item, "first_release_date", "release_date"),
        "date_created": _romm_meta_value(item, "created_at", "createdAt", "created"),
        "cover_url": _romm_cover_url(item, rid),
        "screenshots": _romm_screenshots(item),
        "genres": _romm_text_list(item, "genres"),
        "companies": _romm_text_list(item, "companies", "involved_companies"),
        "franchises": _romm_text_list(item, "franchises", "franchise"),
        "game_modes": _romm_text_list(item, "game_modes"),
        "regions": _romm_text_list(item, "regions"),
        "languages": _romm_text_list(item, "languages"),
        "alternative_names": _romm_text_list(item, "alternative_names"),
        "rating": _romm_meta_value(item, "total_rating", "rating", "aggregated_rating"),
        "metadata_providers": providers,
        "metadata_state": "identified" if identified else ("identifying" if item.get("is_identifying") else "unidentified"),
        "engine": "emulatorjs" if cores else None,
        "cores": cores,
        "default_core": core or None,
        "threads_required": core in EJS_THREAD_CORES,
        "control_scheme": EJS_CONTROL_SCHEMES.get(slug),
        "playable": bool(rid and fs_name and cores),
        "player_url": f"/games/play/{rid}" if rid and fs_name and cores else None,
        "content_url": f"/api/games/rom/{rid}/content/{quote(fs_name, safe='')}" if rid and fs_name else None,
    }


def emulator_capabilities() -> dict:
    platforms = []
    for slug, cores in sorted(EJS_CORES.items()):
        platforms.append({"platform_slug": slug, "cores": list(cores), "default_core": cores[0] if cores else None})
    health = romm_pipeline_health()
    return {
        "available": bool(health.get("available")),
        "health": health,
        "engines": [{"id": "emulatorjs", "source": "romm-bundled", "asset_base": "/api/games/ejs/", "player": "/games/play/{rom_id}"}],
        "threaded_cores": sorted(EJS_THREAD_CORES),
        "platforms": platforms,
    }


def romm_platforms() -> dict:
    data = romm_json("/api/platforms")
    rows = data if isinstance(data, list) else (data.get("items") or data.get("platforms") or []) if isinstance(data, dict) else []
    items = [normalize_romm_platform(x) for x in rows if isinstance(x, dict)]
    items.sort(key=lambda x: x["name"].lower())
    return {"available": True, "items": items, "playable": sum(1 for x in items if x["playable"])}


def romm_library(search: str = "", platform_id: str = "", limit: int = 80, offset: int = 0) -> dict:
    limit = max(1, min(int(limit), 160)); offset = max(0, int(offset)); search=str(search or "").strip()[:120]
    def fetch(term: str="", item_limit: int=160, item_offset: int=0):
        q={"limit":str(max(1,min(500,item_limit))),"offset":str(max(0,item_offset)),"with_char_index":"false","with_filter_values":"false","with_rom_id_index":"false"}
        if term: q["search_term"]=term
        if platform_id and platform_id.isdigit(): q["platform_ids"]=platform_id
        data=romm_json("/api/roms?"+urlencode(q),timeout=15.0)
        rows=data if isinstance(data,list) else (data.get("items") or data.get("roms") or data.get("results") or []) if isinstance(data,dict) else []
        return data,[normalize_romm_rom(x) for x in rows if isinstance(x,dict)]
    if not search:
        data,items=fetch("",limit,offset); playable=[x for x in items if x["playable"]]
        total=data.get("total",data.get("total_count",len(items))) if isinstance(data,dict) else len(items)
        return {"available":True,"items":playable,"returned":len(playable),"upstream_returned":len(items),"total":total}
    with ThreadPoolExecutor(max_workers=2,thread_name_prefix="pcga-romm-search") as pool:
        exact_future=pool.submit(
            _search_cached,f"romm:library:{platform_id or '-'}:q:{_search_norm(search)}",15.0,
            lambda: fetch(search,min(200,max(80,limit*2)),0),
        )
        broad_future=pool.submit(_search_cached,f"romm:library:{platform_id or '-'}:all",45.0,lambda:fetch("",500,0))
        _data,exact=exact_future.result(); _broad_data,broad=broad_future.result()
    merged=[]; seen=set()
    for item in exact+broad:
        rid=str(item.get("id") or "")
        if rid in seen: continue
        seen.add(rid); merged.append(item)
    playable=[x for x in merged if x.get("playable")]
    ranked=_fuzzy_rank(playable,search,lambda x:" ".join([str(x.get("name") or ""),str(x.get("fs_name") or ""),str(x.get("platform") or ""),str(x.get("summary") or "")," ".join(x.get("alternative_names") or [])," ".join(x.get("companies") or [])," ".join(x.get("genres") or [])]))
    page=ranked[offset:offset+limit]
    return {"available":True,"items":page,"returned":len(page),"upstream_returned":len(merged),"total":len(ranked),"fuzzy":True}

def romm_firmware(platform_id: int) -> dict:
    data = romm_json("/api/firmware?" + urlencode({"platform_id": str(int(platform_id))}))
    rows = data if isinstance(data, list) else (data.get("items") or data.get("firmware") or data.get("results") or []) if isinstance(data, dict) else []
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            fid = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        file_name = str(_pick(row, "file_name", "fs_name", "name", default="") or "")
        if not file_name:
            continue
        items.append({
            "id": fid,
            "file_name": file_name,
            "name": str(_pick(row, "name", "file_name", default=file_name)),
            "content_url": f"/api/games/firmware/{fid}/content/{quote(file_name, safe='')}",
        })
    return {"available": True, "items": items}


def romm_rom(rom_id: int) -> dict:
    data = romm_json(f"/api/roms/{int(rom_id)}")
    if not isinstance(data, dict):
        raise RuntimeError("RomM returned an invalid ROM record")
    out = normalize_romm_rom(data)
    out["files"] = data.get("files") if isinstance(data.get("files"), list) else []
    return out


def romm_cover_target(rom_id: int) -> str | None:
    data = romm_json(f"/api/roms/{int(rom_id)}")
    if not isinstance(data, dict):
        return None
    raw = str(_pick(data, "path_cover_small", "path_cover_large", "path_cover_s", "path_cover_l", default="") or "").strip()
    if not raw or raw.startswith(("http://", "https://", "//")):
        return None
    if raw.startswith("/assets/"):
        return raw
    raw = raw.lstrip("/")
    if raw.startswith("romm/resources/"):
        return "/assets/" + raw
    if raw.startswith("resources/"):
        return "/assets/romm/" + raw
    return "/assets/romm/resources/" + raw


def emulator_player_html(rom_id: int) -> bytes:
    rid = int(rom_id)
    # The player intentionally lives on a distinct route so COOP/COEP can be
    # enabled only while EmulatorJS is active.
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>PCGA Emulator</title><style>
*{{box-sizing:border-box}}html,body{{margin:0;width:100%;height:100%;background:#050403;color:#fff4e6;font:16px system-ui,-apple-system,Segoe UI,sans-serif}}body{{display:flex;flex-direction:column}}header{{height:62px;display:flex;align-items:center;gap:14px;padding:8px 14px;background:#17100b;border-bottom:1px solid rgba(255,207,156,.2);z-index:5}}header a,header button,header select{{border:1px solid rgba(255,207,156,.24);background:#2a190e;color:#fff4e6;border-radius:12px;min-height:42px;padding:0 14px;font:inherit;font-weight:800}}#title{{min-width:0;flex:1;font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}#meta{{font-size:.78em;color:#d7bfa5}}#stage{{position:relative;flex:1;min-height:0;background:#000}}#game{{position:absolute;inset:0}}#loading{{position:absolute;inset:0;display:grid;place-items:center;background:#050403;color:#d7bfa5;z-index:3}}#error{{display:none;padding:18px;color:#ffd0c9;background:#38140f}}@media(max-width:720px){{header{{height:auto;flex-wrap:wrap}}#title{{order:-1;flex-basis:100%}}}}


</style></head><body>
<header><a href="/#games">← Console Games</a><div id="title">Loading game…<div id="meta"></div></div><select id="core" aria-label="Emulator core"></select><select id="bios" aria-label="Firmware"><option value="">No BIOS</option></select><button id="start" type="button" disabled>Start</button></header><div id="error"></div><main id="stage"><div id="loading">Preparing PCGA emulator…</div><div id="game"></div></main>
<script>
const ROM_ID={rid};let info=null;let started=false;const title=document.getElementById('title'),meta=document.getElementById('meta'),core=document.getElementById('core'),bios=document.getElementById('bios'),start=document.getElementById('start'),loading=document.getElementById('loading'),err=document.getElementById('error');
function fail(m){{loading.style.display='none';err.style.display='block';err.textContent=m;start.disabled=true}}
async function init(){{try{{const r=await fetch(`/api/games/rom/${{ROM_ID}}`,{{cache:'no-store'}});const d=await r.json();if(!r.ok)throw Error(d.detail||d.error||r.status);info=d;if(!d.playable||!d.content_url||!d.cores?.length)throw Error('This platform does not yet have a PCGA browser-emulator mapping.');title.firstChild.textContent=d.name||'Console Game';meta.textContent=d.platform||d.platform_slug||'';core.innerHTML=d.cores.map(x=>`<option value="${{x}}">${{x}}</option>`).join('');let firmwareCount=0;if(d.platform_id){{const fr=await fetch(`/api/games/firmware?platform_id=${{encodeURIComponent(d.platform_id)}}`,{{cache:'no-store'}});if(fr.ok){{const fd=await fr.json();const fw=fd.items||[];firmwareCount=fw.length;bios.innerHTML='<option value="">No BIOS</option>'+fw.map(x=>`<option value="${{x.content_url}}">${{x.name||x.file_name}}</option>`).join('');if(firmwareCount)bios.selectedIndex=1}}}}start.disabled=false;if(d.cores.length===1&&!firmwareCount){{loading.textContent='Loading emulator…';startEmulator()}}else{{loading.textContent='Choose emulator options, then press Start'}}}}catch(e){{fail('Unable to prepare emulator: '+(e.message||e))}}}}
async function startEmulator(){{if(started||!info)return;started=true;start.disabled=true;core.disabled=true;bios.disabled=true;loading.textContent='Checking emulator pipeline…';try{{const hr=await fetch('/api/games/health?refresh=1',{{cache:'no-store'}});const hd=await hr.json().catch(()=>({{}}));if(!hr.ok||!hd.available)throw Error(hd.detail||'emulator pipeline unavailable')}}catch(e){{started=false;fail('Emulator pipeline is not ready: '+(e.message||e));return}}const selected=core.value||info.default_core;if(['dosbox_pure','ppsspp','azahar'].includes(selected)&&!crossOriginIsolated){{started=false;fail('This emulator core requires cross-origin isolation, but the browser did not enable it for this page.');return}}loading.textContent='Loading EmulatorJS…';window.EJS_player='#game';window.EJS_core=selected;window.EJS_pathtodata='/api/games/ejs/';window.EJS_gameUrl=info.content_url;window.EJS_gameID=info.id;window.EJS_gameName=info.name;window.EJS_biosUrl=bios.value||'';window.EJS_color='#e8a15e';window.EJS_backgroundColor='#050403';window.EJS_alignStartButton='center';window.EJS_startOnLoaded=true;window.EJS_fullscreenOnLoaded=false;window.EJS_threads=['dosbox_pure','ppsspp','azahar'].includes(selected);window.EJS_controlScheme=info.control_scheme||null;window.EJS_defaultOptions={{'save-state-location':'browser',rewindEnabled:'enabled'}};window.EJS_netplayServer='';window.EJS_disableAutoLang=true;let timer=setTimeout(()=>fail('EmulatorJS loaded but the game did not start within 30 seconds. Check /api/games/health and the browser console.'),30000);window.EJS_onGameStart=()=>{{clearTimeout(timer);loading.style.display='none';fetch('/api/control/game-activity',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{kind:'console-game',id:String(info.id),title:info.name||'Console Game',subtitle:info.platform||info.platform_slug||'Console Game',platform:info.platform||'',platform_slug:info.platform_slug||'',art_url:info.metadata_state==='identified'?(info.cover_url||''):''}})}}).catch(()=>{{}})}};const script=document.createElement('script');script.src='/api/games/ejs/loader.js';script.onerror=()=>{{clearTimeout(timer);fail('The EmulatorJS runtime could not be loaded from the PCGA endpoint.')}};document.body.appendChild(script)}}
start.addEventListener('click',()=>{{started=false;startEmulator()}});core.addEventListener('change',()=>{{if(!started)return}});init();
</script></body></html>'''.encode()


def bootstrap_ready(name):
    try:
        state=Path(f"/var/lib/pc-game-archive/bootstrap/{name}.state")
        return state.read_text().strip() == "ready"
    except Exception:
        return False

def tool_status() -> list[dict]:
    # The normal launcher exposes appliance capabilities. Native application UIs
    # remain available under Control Center -> Advanced for deep administration.
    romm_health = romm_pipeline_health()
    romm_ready = bool(romm_health.get("available"))
    romm_subtitle = "Browse and play through the PCGA portal" if romm_ready else f"Emulator offline: {str(romm_health.get('detail') or 'pipeline unavailable')[:120]}"
    lc_health = lancommander_health()
    lc_service_ready = bool(lc_health.get("service_ready"))
    lc_catalog_ready = bool(lc_health.get("catalog_db_readable"))
    local_pc_games = False
    try: local_pc_games = any(PCGA_GAME_INSTALLS.glob("*.json"))
    except OSError: pass
    if local_pc_games:
        lc_subtitle = "Installed games, rich profiles and Wolf/Moonlight streaming"
    elif lc_catalog_ready:
        lc_subtitle = "Browse PC game packages through the PCGA portal"
    elif lc_service_ready:
        lc_subtitle = "LANCommander is running; insert or upload a PC game to begin"
    else:
        lc_subtitle = str(lc_health.get("detail") or "PC game services are unavailable")[:140]
    return [
        {"id":"jellyfinlibrary","title":"Movies & TV","subtitle":"Search and play the video library","same_origin":True,"path":"#library","available":bool(jellyfin_token()) and tcp_open(JELLYFIN_PORT),"primary":True},
        {"id":"musicplayer","title":"Audio","subtitle":"Music, podcasts and public-domain audiobooks","same_origin":True,"path":"#audio","available":True,"primary":True},
        {"id":"photos","title":"Photos","subtitle":"Browse photos, wallpapers and slideshows","same_origin":True,"path":"#photos","available":PHOTOS.exists(),"primary":True},
        {"id":"romm","title":"Console Games","subtitle":romm_subtitle,"same_origin":True,"path":"#games","available":romm_ready,"primary":True},
        {"id":"lancommander","title":"PC Games","subtitle":lc_subtitle,"same_origin":True,"path":"#pc-games","available":bool(lc_service_ready or local_pc_games),"catalog_available":lc_catalog_ready,"primary":True},
        {"id":"addmedia","title":"Add Media","subtitle":"Upload files/folders, rip discs, or import public media","same_origin":True,"path":"#control-ingest","available":True,"primary":True},
        {"id":"review","title":"Review Queue","subtitle":"Resolve unidentified or ambiguous media","same_origin":True,"path":"#review","available":True},
        {"id":"jellyfin","title":"Jellyfin","subtitle":"Native media-server interface","port":JELLYFIN_PORT,"path":"/","available":tcp_open(JELLYFIN_PORT),"advanced":True},
        {"id":"immich","title":"Immich","subtitle":"Native photo-management interface","port":IMMICH_PORT,"path":"/","available":tcp_open(IMMICH_PORT),"advanced":True},
        {"id":"romm-native","title":"RomM","subtitle":"Native ROM-manager interface","port":ROMM_PORT,"path":"/","available":tcp_open(ROMM_PORT),"advanced":True},
        {"id":"lancommander-native","title":"LANCommander","subtitle":"Native PC-game administration interface","port":LANCOMMANDER_PORT,"path":"/","available":lancommander_tcp_target() is not None,"advanced":True},
        {"id":"wolfden","title":"Wolf Den","subtitle":"Native streaming configuration","port":WOLFDEN_PORT,"path":"/","available":tcp_open(WOLFDEN_PORT),"advanced":True},
        {"id":"arm","title":"ARM","subtitle":"Native video/audio optical backend","port":ARM_PORT,"path":"/","available":tcp_open(ARM_PORT),"advanced":True},
        {"id":"publicmedia","title":"Public Media","subtitle":"Archive.org import interface","same_origin":True,"path":"/public-media/","available":tcp_open(8099),"advanced":True},
        {"id":"api","title":"Status API","subtitle":"Pipeline JSON diagnostics","same_origin":True,"path":"/api/status","available":True,"advanced":True},
        {"id":"health","title":"Health Endpoint","subtitle":"Portal health endpoint","same_origin":True,"path":"/health","available":True,"advanced":True},
    ]


def drive_status(dev: str) -> dict:
    name = Path(dev).name
    sys_block = Path("/host-sys/class/block") / name
    size = 0
    try:
        # Linux block-device size is exported as 512-byte sectors.  Optical
        # drives report zero when no readable medium is inserted.
        sectors = int((sys_block / "size").read_text().strip())
        size = sectors * 512
    except Exception:
        pass
    model = None
    vendor = None
    for key in ("model", "vendor"):
        try:
            val = (sys_block / "device" / key).read_text(errors="replace").strip()
        except OSError:
            val = ""
        if key == "model":
            model = val or None
        else:
            vendor = val or None
    health = optical_health(name)
    dispatch = optical_dispatch(name)
    # Optical capacity can remain stale after disc removal on some drives.
    # Prefer the periodic ioctl-based health probe when available.
    medium_present = health.get("media_present") if isinstance(health.get("media_present"), bool) else (size > 0)
    return {
        "device": dev,
        "exists": sys_block.exists(),
        "medium_present": medium_present,
        "size_bytes": size,
        "size": human_bytes(size),
        "label": ((dispatch.get("filesystem") or {}).get("label") if isinstance(dispatch.get("filesystem"), dict) else None),
        "filesystem": ((dispatch.get("filesystem") or {}).get("type") if isinstance(dispatch.get("filesystem"), dict) else None),
        "mountpoint": None,
        "media_kind": dispatch.get("kind"),
        "ingest_route": dispatch.get("route"),
        "content_guess": dispatch.get("content_guess"),
        "content_confidence": dispatch.get("content_confidence"),
        "auto_ingest_enabled": dispatch.get("auto_ingest_enabled"),
        "dispatch_status": dispatch.get("dispatch_status"),
        "model": " ".join(x for x in (vendor, model) if x) or None,
        "role": drive_role(dev),
        "health": health,
    }


def yaml_value(key: str) -> str | None:
    try:
        for raw in CONFIG_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            if k.strip() == key:
                return v.strip().strip('"\'')
    except OSError:
        pass
    return None


def arm_config() -> dict:
    return {
        "skip_transcode": yaml_value("SKIP_TRANSCODE"),
        "minlength": yaml_value("MINLENGTH"),
        "mainfeature": yaml_value("MAINFEATURE"),
        "ripmethod": yaml_value("RIPMETHOD"),
        "ripmethod_dvd": yaml_value("RIPMETHOD_DVD"),
        "ripmethod_br": yaml_value("RIPMETHOD_BR"),
        "prevent_99": yaml_value("PREVENT_99"),
    }


def _sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]


_LANCOMMANDER_DB_CACHE: Path | None = None
_LANCOMMANDER_DB_DIAG: dict = {"checked": False, "reason": "not checked", "candidates": []}


def _lancommander_state() -> str:
    try:
        return Path("/var/lib/pc-game-archive/bootstrap/lancommander.state").read_text().strip() or "missing"
    except Exception:
        return "missing"


def _sqlite_signature(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _lancommander_db() -> Path | None:
    """Locate LANCommander's catalog SQLite DB without depending on its filename.

    v0.17.20 only considered *.db/*.sqlite files and required Games, Archives and
    StorageLocations to all exist before the PC Games tile could open.  That made
    portal readiness stricter than LANCommander itself and hid an otherwise healthy
    service.  Prefer the path published by the appliance bootstrap, then fall back to
    a bounded SQLite-signature/schema scan.  A Games table is sufficient for catalog
    browsing; archive/storage tables are optional until package data is requested.
    """
    global _LANCOMMANDER_DB_CACHE, _LANCOMMANDER_DB_DIAG
    if _LANCOMMANDER_DB_CACHE is not None and _LANCOMMANDER_DB_CACHE.is_file():
        try:
            conn = sqlite3.connect(f"file:{_LANCOMMANDER_DB_CACHE}?mode=ro", uri=True, timeout=0.2)
            try:
                if "Games" in set(_sqlite_tables(conn)):
                    return _LANCOMMANDER_DB_CACHE
            finally:
                conn.close()
        except sqlite3.Error:
            pass
    _LANCOMMANDER_DB_CACHE = None
    diag = {"checked": True, "reason": "catalog not found", "candidates": []}
    _LANCOMMANDER_DB_DIAG = diag
    if not LANCOMMANDER_DATA.exists():
        diag["reason"] = f"LANCommander data mount is missing at {LANCOMMANDER_DATA}"
        return None

    root = LANCOMMANDER_DATA.resolve(strict=False)
    candidates: list[Path] = []

    # Bootstrap publishes a relative path on the host.  pcga-status sees the same
    # directory at LANCOMMANDER_DATA, so this is both faster and less ambiguous than
    # rediscovering the database every status poll.
    pointer = Path("/var/lib/pc-game-archive/bootstrap/lancommander.catalog-db")
    try:
        rel = pointer.read_text().strip()
    except Exception:
        rel = ""
    if rel:
        candidate = (root / rel).resolve(strict=False)
        if candidate == root or root in candidate.parents:
            candidates.append(candidate)
        else:
            diag["pointer_error"] = "published catalog path escaped the LANCommander data root"

    suffixes = {".db", ".sqlite", ".sqlite3"}
    pruned = {"uploads", "media", "saves", "steam", "archives", "files", "cache", "downloads"}
    try:
        # Include extensionless SQLite files.  LANCommander owns the directory, so
        # checking the 16-byte SQLite signature is cheap and avoids filename guesses.
        for current, dirs, files in os.walk(root):
            current_path = Path(current)
            try:
                depth = len(current_path.relative_to(root).parts)
            except ValueError:
                continue
            dirs[:] = [d for d in dirs if d.lower() not in pruned and depth < 4]
            if depth > 4:
                dirs[:] = []
                continue
            for name in files:
                candidate = current_path / name
                if candidate in candidates:
                    continue
                if candidate.suffix.lower() in suffixes or _sqlite_signature(candidate):
                    candidates.append(candidate)
    except OSError as exc:
        diag["walk_error"] = str(exc)[:160]

    best: tuple[int, Path] | None = None
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            candidate = candidate.resolve(strict=False)
        except OSError:
            pass
        if candidate in seen:
            continue
        seen.add(candidate)
        info = {"path": str(candidate.relative_to(root)) if root in candidate.parents else candidate.name}
        try:
            uri = f"file:{candidate}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=0.35)
            try:
                tables = set(_sqlite_tables(conn))
            finally:
                conn.close()
            info["tables"] = sorted(tables)[:24]
            has_games = "Games" in tables
            score = (100 if has_games else 0) + 10 * ("Archives" in tables) + 10 * ("StorageLocations" in tables) + 2 * ("Media" in tables) + ("Users" in tables)
            info["score"] = score
            diag["candidates"].append(info)
            if has_games and (best is None or score > best[0]):
                best = (score, candidate)
        except (sqlite3.Error, OSError) as exc:
            info["error"] = str(exc)[:120]
            diag["candidates"].append(info)

    if best is not None:
        _LANCOMMANDER_DB_CACHE = best[1]
        try:
            diag["database"] = str(best[1].relative_to(root))
        except ValueError:
            diag["database"] = best[1].name
        diag["reason"] = "catalog database discovered"
        return best[1]
    if candidates:
        diag["reason"] = "SQLite files were found, but none exposed a Games table"
    else:
        diag["reason"] = "no SQLite catalog candidates were visible in the LANCommander data mount"
    return None

def _lancommander_connect() -> sqlite3.Connection:
    db = _lancommander_db()
    if db is None:
        raise FileNotFoundError("LANCommander game database is not available to the portal")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=0.35)
    conn.row_factory = sqlite3.Row
    return conn


def _lc_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in conn.execute(f'PRAGMA table_info("{table}")')}


def _lc_game_type(value: object) -> str:
    try:
        index = int(value)
    except (TypeError, ValueError):
        return "Game"
    return {
        0: "Main Game",
        1: "Expansion",
        2: "Standalone Expansion",
        3: "Mod",
        4: "Standalone Mod",
    }.get(index, "Game")


def _lc_safe_storage_path(storage_path: str, object_key: str) -> Path | None:
    """Mirror AppPaths.ResolveStorageLocationPath inside the read-only PCGA mount."""
    storage_path = str(storage_path or "").strip()
    object_key = str(object_key or "").strip()
    if not storage_path or not object_key or "/" in object_key or "\\" in object_key or object_key in {".", ".."}:
        return None
    root = LANCOMMANDER_DATA.resolve(strict=False)
    raw = Path(storage_path)
    if raw.is_absolute():
        # The pinned Docker service stores its data at /app/Data; pcga-status sees
        # the same host directory read-only at LANCOMMANDER_DATA.
        try:
            rel = raw.relative_to("/app/Data")
        except ValueError:
            return None
        base = root / rel
    else:
        base = root / raw
    candidate = (base / object_key).resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        return None
    return candidate


def _lc_latest_archive(conn: sqlite3.Connection, game_id: str) -> dict | None:
    acols = _lc_cols(conn, "Archives")
    required = {"Id", "GameId", "ObjectKey", "StorageLocationId"}
    if not required.issubset(acols):
        return None
    order = '"CreatedOn" DESC' if "CreatedOn" in acols else 'rowid DESC'
    wanted = [c for c in ("Id", "GameId", "ObjectKey", "StorageLocationId", "Version", "CompressedSize", "UncompressedSize", "CreatedOn", "UpdatedOn") if c in acols]
    row = conn.execute(
        f'SELECT {", ".join(chr(34)+c+chr(34) for c in wanted)} FROM "Archives" WHERE "GameId"=? ORDER BY {order} LIMIT 1',
        (game_id,),
    ).fetchone()
    return dict(row) if row else None


def _lc_archive_path(conn: sqlite3.Connection, archive: dict | None) -> Path | None:
    if not archive:
        return None
    slcols = _lc_cols(conn, "StorageLocations")
    if not {"Id", "Path"}.issubset(slcols):
        return None
    storage = conn.execute('SELECT "Path" FROM "StorageLocations" WHERE "Id"=? LIMIT 1', (archive.get("StorageLocationId"),)).fetchone()
    if not storage:
        return None
    return _lc_safe_storage_path(str(storage["Path"] or ""), str(archive.get("ObjectKey") or ""))


def _lc_cover(conn: sqlite3.Connection, game_id: str) -> dict | None:
    tables = set(_sqlite_tables(conn))
    if "Media" not in tables:
        return None
    cols = _lc_cols(conn, "Media")
    needed = {"GameId", "FileId", "StorageLocationId", "Type"}
    if not needed.issubset(cols):
        return None
    wanted = [c for c in ("Id", "FileId", "StorageLocationId", "MimeType", "Name", "SortOrder", "Type") if c in cols]
    order = '"SortOrder" ASC' if "SortOrder" in cols else 'rowid ASC'
    # MediaType.Cover == 1 in LANCommander v2.1.16.
    row = conn.execute(
        f'SELECT {", ".join(chr(34)+c+chr(34) for c in wanted)} FROM "Media" WHERE "GameId"=? AND "Type"=1 ORDER BY {order} LIMIT 1',
        (game_id,),
    ).fetchone()
    if not row:
        return None
    media = dict(row)
    storage = conn.execute('SELECT "Path" FROM "StorageLocations" WHERE "Id"=? LIMIT 1', (media.get("StorageLocationId"),)).fetchone()
    if not storage:
        return None
    media["path"] = _lc_safe_storage_path(str(storage["Path"] or ""), str(media.get("FileId") or ""))
    return media


def lancommander_health() -> dict:
    state = _lancommander_state()
    bootstrap = state == "ready"
    tcp_target = lancommander_tcp_target()
    http = tcp_target is not None
    mount = LANCOMMANDER_DATA.exists()
    db = _lancommander_db() if mount else None
    catalog = db is not None
    service_ready = bootstrap and http
    fully_ready = service_ready and catalog
    if not bootstrap:
        detail = f"LANCommander appliance bootstrap state is {state!r}"
    elif not http:
        detail = f"LANCommander is not reachable through the appliance host on port {LANCOMMANDER_PORT}"
    elif not mount:
        detail = f"LANCommander data is not mounted at {LANCOMMANDER_DATA}"
    elif not catalog:
        detail = str(_LANCOMMANDER_DB_DIAG.get("reason") or "LANCommander catalog database was not discovered")
    else:
        detail = "LANCommander service and PCGA catalog bridge are ready"
    return {
        "available": fully_ready,
        "service_ready": service_ready,
        "bootstrap_ready": bootstrap,
        "bootstrap_state": state,
        "http_reachable": http,
        "http_target": tcp_target or "",
        "data_mount": mount,
        "catalog_db_readable": catalog,
        "catalog_db": str(_LANCOMMANDER_DB_DIAG.get("database") or ""),
        "detail": detail,
        "discovery": dict(_LANCOMMANDER_DB_DIAG),
    }


def lancommander_portal_ready() -> bool:
    # PC Games is now a PCGA-owned library surface. Keep it available when the
    # local ingest/install registry has games even if LANCommander itself is
    # temporarily down; LANCommander remains one catalog/package backend.
    if bool(lancommander_health().get("service_ready")):
        return True
    try:
        return any((PCGA_GAME_INSTALLS).glob("*.json"))
    except OSError:
        return False


def lancommander_library(search: str = "", limit: int = 80, offset: int = 0) -> dict:
    limit = max(1, min(int(limit), 1000)); offset = max(0, int(offset))
    conn = _lancommander_connect()
    try:
        gcols = _lc_cols(conn, "Games")
        if not {"Id", "Title"}.issubset(gcols):
            raise RuntimeError("LANCommander Games schema is missing Id/Title")
        wanted = [c for c in ("Id", "Title", "SortTitle", "Description", "Notes", "ReleasedOn", "Type", "Singleplayer", "DirectoryName", "UpdatedOn") if c in gcols]
        params: list[object] = []
        where = ""
        if search:
            needles = [c for c in ("Title", "SortTitle", "Description") if c in gcols]
            if needles:
                where = " WHERE " + " OR ".join(f'COALESCE("{c}",\'\') LIKE ? COLLATE NOCASE' for c in needles)
                params.extend([f"%{search[:120]}%"] * len(needles))
        order_col = "SortTitle" if "SortTitle" in gcols else "Title"
        rows = conn.execute(
            f'SELECT {", ".join(chr(34)+c+chr(34) for c in wanted)} FROM "Games"{where} ORDER BY COALESCE(NULLIF("{order_col}",\'\'), "Title") COLLATE NOCASE LIMIT ? OFFSET ?',
            (*params, limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            raw = dict(row); gid = str(raw.get("Id") or "")
            archive = _lc_latest_archive(conn, gid)
            path = _lc_archive_path(conn, archive)
            downloadable = bool(path and path.is_file())
            cover = _lc_cover(conn, gid)
            released = raw.get("ReleasedOn")
            year = str(released)[:4] if released and str(released)[:4].isdigit() else None
            package_bytes = int((archive or {}).get("CompressedSize") or 0)
            if downloadable and package_bytes <= 0:
                try: package_bytes = path.stat().st_size
                except OSError: pass
            items.append({
                "id": gid,
                "title": str(raw.get("Title") or "Untitled"),
                "sort_title": raw.get("SortTitle"),
                "description": str(raw.get("Description") or "")[:2000],
                "released_on": released,
                "year": year,
                "type": _lc_game_type(raw.get("Type")),
                "singleplayer": bool(raw.get("Singleplayer")),
                "directory_name": raw.get("DirectoryName"),
                "cover_url": f"/api/pc-games/game/{quote(gid, safe='')}/cover" if cover and cover.get("path") and Path(cover["path"]).is_file() else None,
                "archive_count": int(conn.execute('SELECT COUNT(*) FROM "Archives" WHERE "GameId"=?', (gid,)).fetchone()[0]) if "Archives" in _sqlite_tables(conn) else 0,
                "version": (archive or {}).get("Version") or None,
                "package_bytes": package_bytes,
                "downloadable": downloadable,
                "download_url": f"/api/pc-games/game/{quote(gid, safe='')}/download" if downloadable else None,
            })
        total = conn.execute(f'SELECT COUNT(*) FROM "Games"{where}', tuple(params)).fetchone()[0]
        return {"available": True, "items": items, "returned": len(items), "total": int(total), "offset": offset, "limit": limit}
    finally:
        conn.close()


def lancommander_game(game_id: str) -> dict:
    conn = _lancommander_connect()
    try:
        gcols = _lc_cols(conn, "Games")
        wanted = [c for c in ("Id", "Title", "SortTitle", "Description", "Notes", "ReleasedOn", "Type", "Singleplayer", "DirectoryName", "UpdatedOn") if c in gcols]
        row = conn.execute(f'SELECT {", ".join(chr(34)+c+chr(34) for c in wanted)} FROM "Games" WHERE "Id"=? LIMIT 1', (game_id,)).fetchone()
        if not row:
            raise KeyError("game not found")
        raw = dict(row); archive = _lc_latest_archive(conn, game_id); path = _lc_archive_path(conn, archive); cover = _lc_cover(conn, game_id)
        downloadable = bool(path and path.is_file())
        size = int((archive or {}).get("CompressedSize") or 0)
        if downloadable and size <= 0:
            try: size = path.stat().st_size
            except OSError: pass
        return {
            "available": True, "id": game_id, "title": str(raw.get("Title") or "Untitled"),
            "description": str(raw.get("Description") or "")[:4000], "notes": str(raw.get("Notes") or "")[:4000],
            "released_on": raw.get("ReleasedOn"), "type": _lc_game_type(raw.get("Type")),
            "singleplayer": bool(raw.get("Singleplayer")), "directory_name": raw.get("DirectoryName"),
            "cover_url": f"/api/pc-games/game/{quote(game_id, safe='')}/cover" if cover and cover.get("path") and Path(cover["path"]).is_file() else None,
            "version": (archive or {}).get("Version") or None, "package_bytes": size,
            "downloadable": downloadable, "download_url": f"/api/pc-games/game/{quote(game_id, safe='')}/download" if downloadable else None,
            "client_runtime": "lancommander-launcher",
        }
    finally:
        conn.close()


def lancommander_archive_file(game_id: str) -> tuple[Path, str, str]:
    conn = _lancommander_connect()
    try:
        row = conn.execute('SELECT "Title" FROM "Games" WHERE "Id"=? LIMIT 1', (game_id,)).fetchone()
        if not row:
            raise KeyError("game not found")
        archive = _lc_latest_archive(conn, game_id); path = _lc_archive_path(conn, archive)
        if not path or not path.is_file():
            raise FileNotFoundError("LANCommander package is not available on local storage")
        title = re.sub(r'[^A-Za-z0-9._ -]+', '_', str(row["Title"] or "game")).strip() or "game"
        version = re.sub(r'[^A-Za-z0-9._-]+', '_', str((archive or {}).get("Version") or "")).strip("._-")
        filename = f"{title}{('-' + version) if version else ''}.zip"
        return path, filename, "application/zip"
    finally:
        conn.close()


def lancommander_cover_file(game_id: str) -> tuple[Path, str]:
    conn = _lancommander_connect()
    try:
        media = _lc_cover(conn, game_id)
        if not media or not media.get("path") or not Path(media["path"]).is_file():
            raise FileNotFoundError("cover not found")
        ctype = str(media.get("MimeType") or "application/octet-stream")
        return Path(media["path"]), ctype
    finally:
        conn.close()



def _pcga_read_json(path: Path) -> dict:
    try:
        obj=json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj,dict) else {}
    except Exception:
        return {}


def _pcga_norm_title(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+"," ",str(value or "").casefold()).split())


def _pcga_cover_path(set_id: str) -> Path | None:
    base=PCGA_GAME_INTAKE/"assets"/set_id
    for name in ("cover.png","cover.jpg","cover.jpeg","cover.webp","hero.png","hero.jpg","hero.jpeg"):
        p=base/name
        if p.is_file(): return p
    return None


def _pcga_asset_path(set_id: str, key: str) -> Path | None:
    if not re.fullmatch(r"(?:hero|screenshot-[1-4])", key): return None
    base=PCGA_GAME_INTAKE/"assets"/set_id
    for ext in (".png",".jpg",".jpeg",".webp"):
        p=base/(key+ext)
        if p.is_file(): return p
    return None


def pcga_asset_file(game_id: str, key: str) -> tuple[Path,str]:
    sid=game_id.split(":",1)[1] if game_id.startswith("pcga:") else game_id
    p=_pcga_asset_path(sid,key)
    if not p: raise FileNotFoundError("game asset not found")
    return p, mimetypes.guess_type(str(p))[0] or "application/octet-stream"


def _pcga_review_id(src: Path) -> str:
    rel=(Path('media')/'metadata-pending'/src.name).as_posix().encode('utf-8')
    return base64.urlsafe_b64encode(rel).decode('ascii').rstrip('=')


def _pcga_pending_review_rows(search: str, known_set_ids: set[str]) -> list[dict]:
    rows=[]; needle=_pcga_norm_title(search)
    if not PENDING.exists(): return rows
    for src in sorted(PENDING.iterdir(),key=lambda p:p.name.lower()):
        if src.name.endswith('.pcga-classification.json'): continue
        manifest=src/'.pcga-classification.json' if src.is_dir() else src.with_name(src.name+'.pcga-classification.json')
        data=_pcga_read_json(manifest)
        if str(data.get('classification') or '')!='pc-game' or str(data.get('action') or '')!='review':
            continue
        game=_pcga_read_json(src/'.pcga-game.json') if src.is_dir() else {}
        sid=str(game.get('game_set_id') or '')
        if sid and sid in known_set_ids:
            continue
        optical=_pcga_read_json(src/'.pcga-optical.json') if src.is_dir() else {}
        fs=optical.get('filesystem') if isinstance(optical.get('filesystem'),dict) else {}
        title=str(data.get('title') or game.get('title') or game.get('collection_title') or fs.get('label') or src.stem or 'Unidentified PC Game')
        evidence=[str(x) for x in (data.get('evidence') or [])[:3]]
        hay=_pcga_norm_title(' '.join([title,*evidence,src.name]))
        if needle and needle not in hay: continue
        rid=_pcga_review_id(src)
        conf=data.get('confidence')
        try: conf=float(conf) if conf is not None else None
        except (TypeError,ValueError): conf=None
        rows.append({
            'id':'review:'+rid,'pcga_set_id':sid or None,'stream_id':None,'source':'pcga-review',
            'title':title,'sort_title':title,'description':' • '.join(evidence)[:800],
            'year':str(data.get('year') or '') or None,'released_on':None,'date_created':str(data.get('created_at') or data.get('updated_at') or ''), 'type':'PC Game','singleplayer':None,
            'developer':None,'publisher':None,'genres':[],
            'cover_url':None,'hero_url':None,'screenshots':[],
            'downloadable':False,'download_url':None,'package_bytes':0,'version':None,
            'install_status':'review-required','install_phase':'classification-review',
            'install_detail':f"Preserved disc needs classification confirmation{f' • {round(conf*100)}%' if conf is not None else ''}",
            'stream_state':'review-required','stream_backend':None,'stream_app_title':None,
            'playable':False,'setup_required':False,'metadata_provider':None,
            'identity_source':'local-classifier','identity_confidence':conf,'identity_status':'review-required',
            'metadata_incomplete':True,'lancommander_game_id':None,'review_item_id':rid,
        })
    return rows


def _pcga_game_rows_raw(search: str="") -> list[dict]:
    # Install-state files are authoritative for ready/setup games.  v0.18.10
    # additionally surfaces preserved PC-game candidates that are waiting for
    # Manual Review so an ingest never disappears between preservation and the
    # runtime orchestrator.
    rows=[]; needle=_pcga_norm_title(search); known_set_ids=set()
    if PCGA_GAME_INSTALLS.exists():
        for state_path in sorted(PCGA_GAME_INSTALLS.glob("*.json")):
            state=_pcga_read_json(state_path)
            if not state: continue
            sid=str(state.get("game_set_id") or state.get("set_id") or state_path.stem)
            game=_pcga_read_json(PCGA_GAME_INTAKE/"sets"/f"{sid}.json")
            # Set metadata owns canonical visibility.  v0.18.63 exposed an older
            # duplicate-consolidation bug where the canonical set was unhidden but
            # its install-state retained catalog_hidden/duplicate_of, causing the
            # only library card to vanish.  Still hide an explicitly superseded set,
            # but tolerate stale state flags until the orchestrator repairs them.
            if game.get("catalog_hidden") or game.get("superseded_by"):
                continue
            if (state.get("catalog_hidden") or state.get("duplicate_of")) and not game:
                # Without a surviving visible set record there is no evidence that
                # this old hidden state should be resurrected as a library card.
                continue
            known_set_ids.add(sid)
            title=str(game.get("title") or state.get("title") or "Unidentified PC Game")
            hay=_pcga_norm_title(" ".join(str(v or "") for v in (
                title, game.get("series"), game.get("developer"), game.get("publisher"),
                game.get("description"), state.get("detail"), state.get("source_path"),
            )))
            if needle and needle not in hay: continue
            year=game.get("release_year")
            marketing=game.get("marketing_assets") if isinstance(game.get("marketing_assets"),dict) else {}
            selected_profile=game.get("metadata_profile") if isinstance(game.get("metadata_profile"),dict) else {}
            cover=_pcga_cover_path(sid)
            status=str(state.get("status") or "queued")
            stream_state=str(state.get("stream_state") or "")
            rows.append({
                "id":"pcga:"+sid,"pcga_set_id":sid,"stream_id":"pcga:"+sid,"source":"pcga",
                "title":title,
                "sort_title":game.get("sort_title"),"description":str(game.get("description") or game.get("marketing_description") or "")[:4000],
                "year":str(year) if year else None,"released_on":game.get("release_date"),"date_created":game.get("created_at") or state.get("created_at") or state.get("updated_at"),"type":"PC Game","singleplayer":None,
                "developer":game.get("developer"),"publisher":game.get("publisher"),"genres":game.get("genres") or [],"edition":game.get("edition"),
                "cover_url":f"/api/pc-games/game/{quote('pcga:'+sid,safe='')}/cover" if cover else marketing.get("cover_remote"),
                "hero_url":(f"/api/pc-games/game/{quote('pcga:'+sid,safe='')}/asset/hero" if _pcga_asset_path(sid,"hero") else marketing.get("header_remote")),
                "screenshots":[f"/api/pc-games/game/{quote('pcga:'+sid,safe='')}/asset/screenshot-{i}" for i in range(1,5) if _pcga_asset_path(sid,f"screenshot-{i}")] or (marketing.get("screenshots_remote") or []),
                "downloadable":False,"download_url":None,"package_bytes":0,"version":None,
                "install_status":status,"install_phase":state.get("phase"),"install_detail":state.get("detail"),
                "install_method":state.get("install_method"),
                "stream_state":stream_state,"stream_backend":state.get("stream_backend") or "wolf",
                "stream_app_title":state.get("stream_app_title"),
                "stream_display_title":state.get("stream_display_title") or title,
                "playable":status=="ready" and stream_state=="ready",
                "launchable":status=="ready" and bool(state.get("runtime_image")),
                "launch_variants":state.get("launch_variants") if isinstance(state.get("launch_variants"),list) else [],
                "launch_variant_default":state.get("launch_variant_default"),
                "stream_variant_apps":state.get("stream_variant_apps") if isinstance(state.get("stream_variant_apps"),dict) else {},
                "setup_launchable":status=="setup-required" and bool(state.get("setup_runtime_image")),
                "setup_required":status=="setup-required","metadata_provider":((game.get("metadata_match") or {}).get("provider") if isinstance(game.get("metadata_match"),dict) else None),
                "metadata_source_url":selected_profile.get("source_url"),"metadata_attribution":selected_profile.get("attribution"),
                "metadata_selected_by_user":bool(selected_profile.get("selected_by_user")),
                "identity_source":game.get("identity_source") or state.get("identity_source"),"identity_confidence":game.get("identity_confidence") or state.get("identity_confidence"),
                "identity_status":((game.get("identity_probe") or {}).get("status") if isinstance(game.get("identity_probe"),dict) else None),
                "metadata_incomplete":not bool(game),
                "lancommander_game_id":game.get("lancommander_game_id") if isinstance(game,dict) else None,
                "disc_count":((game.get("media") or {}).get("disc_count") if isinstance(game.get("media"),dict) else None),
                "active_disc":state.get("runtime_active_disc"),
                "record_count":1+len([x for x in (game.get("merged_set_ids") or []) if str(x)]),
                "merged_set_ids":[str(x) for x in (game.get("merged_set_ids") or []) if str(x)],
                "disc_fingerprints":[str(x) for x in (game.get("disc_fingerprints") or []) if str(x)],
                "media_layouts":[str(x.get("layout") or "") for x in (((game.get("media") or {}).get("discs") or []) if isinstance(game.get("media"),dict) else []) if isinstance(x,dict)],
                "external_ids":game.get("external_ids") if isinstance(game.get("external_ids"),dict) else {},
                "identity_aliases":sorted(set().union(
                    _pcga_catalog_identity_aliases(game.get("title")),
                    _pcga_catalog_identity_aliases(state.get("title")),
                    _pcga_catalog_identity_aliases(((game.get("metadata_match") or {}).get("matched_title") if isinstance(game.get("metadata_match"),dict) else None)),
                )),
            })
    rows.extend(_pcga_pending_review_rows(search,known_set_ids))
    rows.sort(key=lambda x:_pcga_norm_title(x.get("sort_title") or x.get("title")))
    return rows


def _pcga_catalog_family_key(value: object) -> str:
    """Normalize display/catalog variants without collapsing sequels.

    Optical labels frequently glue their media suffix to the title (COD2CD1,
    GAME_DVD2).  Strip only explicit media markers plus a number; a bare final
    number remains part of the title, so Call of Duty 2 never becomes Call of
    Duty.
    """
    key=_pcga_norm_title(value)
    if not key:
        return ""
    # Normal spaced form: "cod2 cd 1", "game disc 2 of 3".
    key=re.sub(r"(?:^|\s)(?:disc|disk|cd|dvd)\s*\d+(?:\s*(?:of|/)\s*\d+)?$", " ", key).strip()
    # Compact mastering-label form after punctuation normalization: "cod2cd1".
    key=re.sub(r"(?:disc|disk|cd|dvd)\d+(?:of\d+)?$", "", key).strip()
    return " ".join(key.split())


def _pcga_catalog_identity_aliases(value: object) -> set[str]:
    family=_pcga_catalog_family_key(value)
    if not family:
        return set()
    words=re.findall(r"[a-z]+|\d+",family.casefold())
    aliases=set()
    compact="".join(words)
    if len(compact)>=4:
        aliases.add(compact)
    if len(words)>=2:
        acronym="".join((w if w.isdigit() else w[0]) for w in words if w)
        if len(acronym)>=4:
            aliases.add(acronym)
    return aliases


def _pcga_row_rank(row: dict, group_disc_count: int = 0) -> tuple:
    status=str(row.get("install_status") or "")
    stream=str(row.get("stream_state") or "")
    phase=str(row.get("install_phase") or "")
    rank=0
    if row.get("playable"): rank+=1000
    elif status=="ready": rank+=850
    elif row.get("setup_required") and stream=="setup-ready": rank+=700
    elif row.get("setup_required"): rank+=600
    elif status in {"installing","queued"}: rank+=400
    elif status=="review-required": rank+=150
    if stream=="ready": rank+=120
    if phase in {"stream-ready","installed"}: rank+=60
    try:
        disc_count=int(row.get("disc_count") or 0)
    except (TypeError,ValueError):
        disc_count=0
    if str(row.get("install_method") or "").casefold()=="portable-copy" and max(disc_count,int(group_disc_count or 0))>1:
        # The historical multi-disc portable migration is not a healthy ready
        # runtime. Prefer the linked real installer/prefix record even before
        # persistent reconciliation has finished.
        rank-=1200
    if row.get("cover_url"): rank+=20
    if row.get("description"): rank+=10
    # Prefer the richer/current install state, then a stable id as tie-breaker.
    return (rank, str(row.get("date_created") or ""), str(row.get("pcga_set_id") or row.get("id") or ""))


def _pcga_consolidate_game_rows(rows: list[dict]) -> list[dict]:
    """Collapse linked install/source records into one playable library title.

    The runtime identity and the display metadata may legitimately originate
    from different historical UUIDs. v0.18.69 therefore links records by title,
    persisted merged-set history, same RAWG id, and shared non-compilation media,
    then keeps the strongest runtime while decorating it with the richest
    user-selected metadata profile.
    """
    pcga=[x for x in rows if str(x.get("source") or "").startswith("pcga") and x.get("pcga_set_id")]
    passthrough=[x for x in rows if x not in pcga]
    if not pcga:
        return rows
    parent=list(range(len(pcga)))
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    def union(a,b):
        ra,rb=find(a),find(b)
        if ra!=rb:parent[rb]=ra
    id_index={str(x.get("pcga_set_id")):i for i,x in enumerate(pcga)}
    # Explicit persisted duplicate links survive later metadata title changes.
    for i,row in enumerate(pcga):
        for sid in row.get("merged_set_ids") or []:
            if str(sid) in id_index:union(i,id_index[str(sid)])
    # Same external profile is always the same logical game record.
    ext={}
    for i,row in enumerate(pcga):
        rawg=str((row.get("external_ids") or {}).get("rawg") or "")
        if rawg:
            if rawg in ext:union(i,ext[rawg])
            else:ext[rawg]=i
    # Conservative acronym/compact-title aliases connect common optical labels
    # to their selected database title, e.g. cod2 <-> Call of Duty 2.
    aliases={}
    for i,row in enumerate(pcga):
        row_aliases=set(row.get("identity_aliases") or [])
        row_aliases.update(_pcga_catalog_identity_aliases(row.get("title")))
        for alias in row_aliases:
            if alias in aliases:union(i,aliases[alias])
            else:aliases[alias]=i
    # Shared preserved media is strong only for non-compilation sets.
    fp={}
    for i,row in enumerate(pcga):
        if any(str(x).casefold()=="compilation" for x in row.get("media_layouts") or []):continue
        for token in row.get("disc_fingerprints") or []:
            token=str(token or "")
            if not token:continue
            if token in fp:union(i,fp[token])
            else:fp[token]=i
    # Retain title-family merging for old concurrent-intake duplicates.
    family={}
    for i,row in enumerate(pcga):
        key=_pcga_catalog_family_key(row.get("title"))
        edition=_pcga_norm_title(row.get("edition") or "")
        if key:
            token=(key,edition)
            if token in family:union(i,family[token])
            else:family[token]=i
    groups={}
    for i,row in enumerate(pcga):groups.setdefault(find(i),[]).append(row)
    merged=[]
    metadata_fields=(
        "title","sort_title","description","year","released_on","developer","publisher","genres","edition",
        "cover_url","hero_url","screenshots","metadata_provider","metadata_source_url","metadata_attribution",
        "metadata_selected_by_user","identity_source","identity_confidence","identity_status","metadata_incomplete",
    )
    for group in groups.values():
        group_disc_count=max([int(x.get("disc_count") or 0) for x in group if str(x.get("disc_count") or "").isdigit()] or [0])
        group=sorted(group,key=lambda row:_pcga_row_rank(row,group_disc_count),reverse=True)
        best=dict(group[0])
        # A user's selected database profile should decorate the strongest
        # launcher rather than becoming its own parallel card.
        donors=sorted(group,key=lambda x:(1 if x.get("metadata_selected_by_user") else 0,1 if x.get("cover_url") else 0,1 if x.get("description") else 0,str(x.get("date_created") or "")),reverse=True)
        donor=donors[0]
        if donor is not best and (donor.get("metadata_selected_by_user") or donor.get("cover_url") or donor.get("description")):
            for field in metadata_fields:
                value=donor.get(field)
                if value not in (None,"",[]):best[field]=value
            best["metadata_runtime_record_id"]=donor.get("pcga_set_id")
        if len(group)>1:
            best["record_count"]=len(group)
            best["duplicate_records"]=[{
                "pcga_set_id":x.get("pcga_set_id"),"title":x.get("title"),
                "install_status":x.get("install_status"),"install_phase":x.get("install_phase"),
                "stream_state":x.get("stream_state"),
            } for x in group[1:]]
            best["catalog_detail"]=f"{len(group)} PCGA records consolidated into this canonical title"
        merged.append(best)
    merged.extend(passthrough)
    merged.sort(key=lambda x:_pcga_norm_title(x.get("sort_title") or x.get("title")))
    return merged


def _pcga_store_catalog() -> dict:
    data=_pcga_read_json(PCGA_STORE_GAMES)
    return data if isinstance(data.get("items"),list) else {"items":[],"status":"not-indexed"}


def _pcga_store_item(set_id: str) -> dict|None:
    for row in _pcga_store_catalog()["items"]:
        if isinstance(row,dict) and str(row.get("pcga_set_id") or "")==set_id:
            return dict(row)
    return None


def _pcga_store_game_rows(search: str="") -> list[dict]:
    rows=[]
    for item in _pcga_store_catalog()["items"]:
        if isinstance(item,dict) and str(item.get("pcga_set_id") or "").startswith("store-"):
            rows.append(dict(item))
    if search:
        rows=_fuzzy_rank(rows,search,lambda x:" ".join(str(x.get(k) or "") for k in ("title","description","provider","source_label")))
    return rows


def _pcga_store_stream_info(set_id: str, lane: int=1) -> dict:
    row=_pcga_store_item(set_id)
    if row is None: raise KeyError("PCGA store game was not found")
    app_title=str(row.get("stream_app_title") or "")
    browser=moonlight_web_stream(app_title,lane) if row.get("launchable") else {"browser_ready":False}
    published=bool(browser.get("browser_ready")) and bool(row.get("launchable"))
    info={
      "available":published,"game_set_id":set_id,"backend":"wolf-store","protocol":"moonlight",
      "app_title":app_title,"display_title":row.get("title"),"launch_variant":None,
      "launch_variants":[],"launch_variant_default":None,"install_status":row.get("install_status"),
      "stream_state":"ready" if published else row.get("stream_state"),
      "detail":row.get("stream_detail"),"setup_required":bool(row.get("setup_required")),
      "launchable":bool(row.get("launchable")),"setup_launchable":False,
      "disc_count":0,"active_disc":None,"discs":[],"pairing_port":47989,
      "store_provider":row.get("provider"),"provider_game_id":row.get("provider_game_id"),
    }
    info.update(browser)
    return info


def _pcga_store_profile(set_id: str) -> dict:
    row=_pcga_store_item(set_id)
    if row is None:raise KeyError("PCGA store game was not found")
    row.update({"client_runtime":"wolf-moonlight","stream":_pcga_store_stream_info(set_id),
                "launch_variants":[],"launch_variant_default":None,"categories":[row.get("source_label")],
                "operating_system":"Windows via Wine","install":{"status":row.get("install_status"),
                "source":"pcga-store","install_path":row.get("install_path"),"provider":row.get("provider")}})
    return row


def _pcga_game_rows(search: str="") -> list[dict]:
    # Store acquisitions are already-installed games, but are not optical game
    # sets. Keep their provider IDs separate from optical title consolidation.
    return _pcga_consolidate_game_rows(_pcga_game_rows_raw(search)) + _pcga_store_game_rows(search)


def heroic_catalog() -> dict:
    data=_pcga_read_json(PCGA_HEROIC_CATALOG)
    if not data:
        return {"schema":1,"heroic_version":"2.22.3","image_ready":False,"launcher":{"id":"pcga:"+HEROIC_LAUNCHER_SID,"pcga_set_id":HEROIC_LAUNCHER_SID,"stream_app_title":"PCGA Heroic Library","available":False},"items":[],"count":0}
    return data


def heroic_status() -> dict:
    status=_pcga_read_json(PCGA_HEROIC_STATUS)
    catalog=heroic_catalog()
    return {
        "state":status.get("state") or ("ready" if catalog.get("image_ready") else "not-installed"),
        "detail":status.get("detail") or "Heroic is available as an optional PCGA game source.",
        "heroic_version":status.get("heroic_version") or catalog.get("heroic_version") or "2.22.3",
        "installed":bool(catalog.get("image_ready")),
        "catalog_count":int(catalog.get("count") or len(catalog.get("items") or [])),
        "launcher":catalog.get("launcher") or {},
        "updated_at":status.get("updated_at") or catalog.get("generated_at"),
    }


def _heroic_item(set_id: str) -> dict|None:
    if set_id==HEROIC_LAUNCHER_SID:
        c=heroic_catalog(); launcher=dict(c.get("launcher") or {})
        launcher.update({
            "id":"pcga:"+HEROIC_LAUNCHER_SID,"pcga_set_id":HEROIC_LAUNCHER_SID,"stream_id":"pcga:"+HEROIC_LAUNCHER_SID,
            "title":"Heroic Store & Library","sort_title":"Heroic Store & Library","source":"heroic-launcher","source_label":"Heroic",
            "description":"Browse your Epic Games, GOG and Amazon libraries in Heroic, install games into PCGA storage, then stream them from the PC Games library.",
            "stream_app_title":launcher.get("stream_app_title") or "PCGA Heroic Library","install_status":"ready" if c.get("image_ready") else "not-installed",
            "stream_state":"ready" if c.get("image_ready") else "not-installed","playable":bool(c.get("image_ready")),"launchable":bool(c.get("image_ready")),"setup_required":False,
        })
        return launcher
    for row in heroic_catalog().get("items") or []:
        if isinstance(row,dict) and str(row.get("pcga_set_id") or "")==set_id:
            return dict(row)
    return None


def _heroic_game_rows(search: str="") -> list[dict]:
    rows=[]
    for row in heroic_catalog().get("items") or []:
        if not isinstance(row,dict): continue
        item=dict(row)
        item.setdefault("id","pcga:"+str(item.get("pcga_set_id") or ""))
        item.setdefault("stream_id",item.get("id"))
        item.setdefault("type","PC Game")
        item.setdefault("source","heroic")
        item.setdefault("source_label","Heroic")
        item.setdefault("install_phase","Installed with Heroic")
        item.setdefault("stream_backend","wolf-heroic")
        rows.append(item)
    if search:
        rows=_fuzzy_rank(rows,search,lambda x:" ".join(str(x.get(k) or "") for k in ("title","description","heroic_runner","heroic_app_name","source_label")))
    return rows


def heroic_stream_info(set_id: str, lane: int=1) -> dict:
    row=_heroic_item(set_id)
    if not row: raise KeyError("Heroic game was not found in the PCGA index")
    app_title=str(row.get("stream_app_title") or ("PCGA Heroic Library" if set_id==HEROIC_LAUNCHER_SID else ""))
    browser=moonlight_web_stream(app_title,lane)
    installed=bool(heroic_catalog().get("image_ready"))
    title=str(row.get("title") or "Heroic")
    info={
        "available":bool(installed and browser.get("browser_ready")),"game_set_id":set_id,"backend":"wolf-heroic","protocol":"moonlight",
        "app_title":app_title,"display_title":title,"launch_variant":None,"launch_variants":[],"launch_variant_default":None,
        "install_status":"ready" if installed else "not-installed","stream_state":"ready" if installed else "not-installed",
        "detail":row.get("description") or "Heroic game streamed through the PCGA Wolf/Moonlight runtime.",
        "setup_required":False,"launchable":installed,"setup_launchable":False,"disc_count":0,"active_disc":None,"discs":[],
        "pairing_port":47989,"heroic":True,"heroic_runner":row.get("heroic_runner"),"heroic_app_name":row.get("heroic_app_name"),
    }
    info.update(browser)
    return info


def _heroic_game_profile(set_id: str) -> dict:
    row=_heroic_item(set_id)
    if not row: raise KeyError("Heroic game not found")
    row=dict(row)
    row.update({
        "client_runtime":"wolf-moonlight","stream":heroic_stream_info(set_id),"heroic":True,
        "launch_variants":[],"launch_variant_default":None,"stream_variant_apps":{},
        "categories":["Heroic"],"operating_system":"Windows/Linux via Heroic",
        "install":{"status":row.get("install_status") or "ready","source":"heroic","install_path":row.get("install_path"),"runner":row.get("heroic_runner")},
    })
    return row


def _pcga_game_profile(set_id: str) -> dict:
    if set_id.startswith("store-"):
        return _pcga_store_profile(set_id)
    if set_id.startswith("heroic-"):
        return _heroic_game_profile(set_id)
    state=_pcga_read_json(PCGA_GAME_INSTALLS/f"{set_id}.json")
    game=_pcga_read_json(PCGA_GAME_INTAKE/"sets"/f"{set_id}.json")
    redirect=str(state.get("duplicate_of") or game.get("superseded_by") or "").strip() if (state or game) else ""
    if redirect and redirect!=set_id:
        return _pcga_game_profile(redirect)
    if not state: raise KeyError("PCGA game not found")
    row=next((x for x in _pcga_game_rows_raw("") if x.get("pcga_set_id")==set_id),None)
    if not row: raise KeyError("PCGA game not found")
    row=dict(row); row.update({
        "marketing_description":game.get("marketing_description") if game else None,
        "website":game.get("website") if game else None,
        "external_ids":game.get("external_ids") or {} if game else {},
        "categories":game.get("categories") or [] if game else [],
        "series":game.get("series") if game else None,"edition":game.get("edition") if game else None,
        "operating_system":game.get("operating_system") if game else None,"install":state,
        "identity_source":game.get("identity_source") if game else state.get("identity_source"),
        "identity_confidence":game.get("identity_confidence") if game else state.get("identity_confidence"),
        "identity_probe":game.get("identity_probe") or {} if game else {},
        "compatibility":game.get("compatibility") or {} if game else {},
        "metadata_profile":game.get("metadata_profile") or {} if game else {},
        "esrb_rating":game.get("esrb_rating") if game else None,"metacritic":game.get("metacritic") if game else None,
        "database_rating":game.get("database_rating") if game else None,"database_platforms":game.get("database_platforms") or [] if game else [],
        "media":game.get("media") or {} if game else {},
        "active_disc":state.get("runtime_active_disc"),
        "launch_variants":state.get("launch_variants") if isinstance(state.get("launch_variants"),list) else [],
        "launch_variant_default":state.get("launch_variant_default"),
        "stream_variant_apps":state.get("stream_variant_apps") if isinstance(state.get("stream_variant_apps"),dict) else {},
        "disc_switch_action":"pc-game-disc-switch",
        "client_runtime":"wolf-moonlight","stream":pcga_stream_info("pcga:"+set_id),
    })
    return row

def _moonlight_lane_state(lane: int) -> dict:
    lane=max(1,min(MOONLIGHT_WEB_LANES,int(lane or 1)))
    published=_pcga_read_json(MOONLIGHT_WEB_STATE)
    rows=published.get("lanes") if isinstance(published,dict) else None
    if isinstance(rows,list):
        for row in rows:
            if isinstance(row,dict) and int(row.get("lane") or 0)==lane:
                return row
    if lane==1 and isinstance(published,dict):
        return published
    return {"lane":lane,"web_port":MOONLIGHT_WEB_PORT+lane-1,"state":"missing","paired":False}


def _moonlight_web_upstream(lane: int) -> str:
    lane=max(1,min(MOONLIGHT_WEB_LANES,int(lane or 1)))
    if lane==1:
        return MOONLIGHT_WEB_UPSTREAM
    parsed=urlparse(MOONLIGHT_WEB_UPSTREAM)
    scheme=parsed.scheme or "https"
    host=parsed.hostname or "host.docker.internal"
    port=MOONLIGHT_WEB_PORT+lane-1
    return f"{scheme}://{host}:{port}"


def _moonlight_web_json(path: str, timeout: float=5.0, lane: int=1) -> tuple[int, object]:
    upstream=_moonlight_web_upstream(lane)
    req=urllib.request.Request(upstream+path, headers={"Accept":"application/json","User-Agent":f"PCGameArchive/{VERSION}"})
    context=None
    if upstream.lower().startswith("https://"):
        try:
            context=ssl.create_default_context(cafile=str(TLS_CA_FILE))
        except Exception:
            context=ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
            raw=response.read().decode("utf-8","replace")
            try: return int(response.status), json.loads(raw or "{}")
            except Exception: return int(response.status), {"raw":raw[:1000]}
    except urllib.error.HTTPError as exc:
        try: body=json.loads(exc.read().decode("utf-8","replace") or "{}")
        except Exception: body={"error":str(exc)}
        return int(exc.code),body
    except Exception as exc:
        return 0,{"error":f"{type(exc).__name__}: {exc}"}

def _moonlight_web_apps(payload: object) -> list[dict]:
    out=[]
    def walk(x):
        if isinstance(x,dict):
            # v2.10 responses may wrap the list, but an app object always has a
            # title/name plus an application id.
            title=x.get("title") or x.get("name")
            app_id=x.get("app_id",x.get("appId",x.get("id")))
            if title is not None and app_id is not None:
                out.append(x)
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    walk(payload)
    # Keep the first occurrence of each id when wrapper objects repeat data.
    seen=set(); unique=[]
    for x in out:
        aid=str(x.get("app_id",x.get("appId",x.get("id"))))
        if aid in seen: continue
        seen.add(aid); unique.append(x)
    return unique


def moonlight_web_stream(app_title: str|None, lane: int=1) -> dict:
    lane=max(1,min(MOONLIGHT_WEB_LANES,int(lane or 1)))
    published=_moonlight_lane_state(lane)
    host_id=published.get("host_id") if isinstance(published,dict) else None
    base={
        "browser_available":False,"browser_ready":False,"needs_pairing":False,
        "browser_port":int(published.get("web_port") or (MOONLIGHT_WEB_PORT+lane-1)),"browser_scheme":"https","browser_path":"/","host_id":host_id,"browser_lane":lane,"browser_lane_count":MOONLIGHT_WEB_LANES,
        "portal_secure_port":STATUS_TLS_PORT,"secure_context_required":True,
        "browser_client":"moonlight-web-stream-v3.0.0-prerelease.6",
        "browser_transport":"auto",
        "browser_network_mode":published.get("network_mode","host") if isinstance(published,dict) else "host",
    }
    code,auth=_moonlight_web_json("/api/authenticate",3.0,lane)
    if code!=200:
        base["browser_detail"]="PCGA browser streaming client is not reachable or not appliance-authenticated"
        return base
    base["browser_available"]=True
    if host_id is None:
        base["browser_detail"]="PCGA browser streaming client has not registered Wolf yet"
        return base
    code,apps=_moonlight_web_json("/api/apps?"+urlencode({"host_id":str(host_id)}),6.0,lane)
    if code!=200:
        base["needs_pairing"]=True
        base["browser_path"]="/"
        base["browser_detail"]="PCGA browser-stream trust needs appliance reconciliation"
        return base
    wanted=_pcga_norm_title(app_title or "")
    matches=_moonlight_web_apps(apps)
    for app in matches:
        title=str(app.get("title") or app.get("name") or "")
        if wanted and _pcga_norm_title(title)==wanted:
            app_id=app.get("app_id",app.get("appId",app.get("id")))
            base.update({
                "browser_ready":True,"needs_pairing":False,"app_id":app_id,
                "browser_app_title":title,
                "browser_path":"/stream.html?"+urlencode({"hostId":str(host_id),"appId":str(app_id),"dataTransport":"websocket"}),
                "browser_transport_options":["websocket","webrtc","auto"],
                "browser_detail":"Ready to stream inside the PCGA portal",
            })
            return base
    base["browser_detail"]="Wolf is paired, but this PCGA app is not yet visible to the browser client"
    return base


def pcga_stream_info(game_id: str, lane: int=1, variant: str|None=None) -> dict:
    sid=game_id.split(":",1)[1] if game_id.startswith("pcga:") else game_id
    if sid.startswith("store-"):
        return _pcga_store_stream_info(sid,lane)
    if sid.startswith("heroic-"):
        return heroic_stream_info(sid,lane)
    state=_pcga_read_json(PCGA_GAME_INSTALLS/f"{sid}.json")
    game=_pcga_read_json(PCGA_GAME_INTAKE/"sets"/f"{sid}.json")
    redirect=str(state.get("duplicate_of") or game.get("superseded_by") or "").strip() if (state or game) else ""
    if redirect and redirect!=sid:
        return pcga_stream_info("pcga:"+redirect,lane,variant)
    if not state: raise KeyError("PCGA game install state not found")
    variants=state.get("launch_variants") if isinstance(state.get("launch_variants"),list) else []
    variant_map={str(x.get("key") or ""):x for x in variants if isinstance(x,dict) and str(x.get("key") or "")}
    requested_variant=str(variant or "").strip().casefold()
    default_variant=str(state.get("launch_variant_default") or "").strip()
    selected_variant=requested_variant or default_variant
    if requested_variant and requested_variant not in variant_map:
        raise ValueError(f"Unknown launch variant: {requested_variant}")
    stream_variant_apps=state.get("stream_variant_apps") if isinstance(state.get("stream_variant_apps"),dict) else {}
    selected_app_title=str(stream_variant_apps.get(selected_variant) or state.get("stream_app_title") or "")
    browser=moonlight_web_stream(selected_app_title,lane)
    # A persisted pending-restart flag must not block a stream when Moonlight Web
    # can already see the exact Wolf app. This heals stale pending state from the
    # pre-v0.18.16 app-block ordering bug without forcing a daemon restart.
    ready=state.get("status")=="ready" and (state.get("stream_state")=="ready" or bool(browser.get("browser_ready")))
    media = state.get("runtime_media") if isinstance(state.get("runtime_media"), list) else []
    try:
        disc_count = int(state.get("source_logical_disc_count") or len(media) or 0)
    except (TypeError, ValueError):
        disc_count = len(media)
    try:
        active_disc = int(state.get("runtime_active_disc") or 1) if disc_count else None
    except (TypeError, ValueError):
        active_disc = 1 if disc_count else None
    discs=[]
    for row in media:
        if not isinstance(row,dict): continue
        try: n=int(row.get("disc") or 0)
        except (TypeError,ValueError): n=0
        if n>0: discs.append({"disc":n,"label":row.get("label") or None,"role":row.get("disc_role") or None})
    display_title=game.get("title") or state.get("stream_display_title") or state.get("title") or "PC Game"
    title_norm=_pcga_norm_title(display_title)
    runtime_failure={}
    install_root=str(state.get("install_root") or "").strip()
    if install_root:
        runtime_failure=_pcga_read_json(Path(install_root)/"runtime-logs"/"last-failure.json")
    setup_media_mode="merged" if (state.get("status")=="setup-required" and disc_count>1 and title_norm in {"call of duty 2","cod2"}) else "manual"
    info={
        "available":bool(ready),"game_set_id":sid,"backend":"wolf","protocol":"moonlight",
        "app_title":selected_app_title or state.get("stream_app_title"),
        "display_title":display_title,
        "launch_variant":selected_variant or None,
        "launch_variant_label":(variant_map.get(selected_variant) or {}).get("label") if selected_variant else None,
        "launch_variants":variants,
        "launch_variant_default":default_variant or None,
        "install_status":state.get("status"),"stream_state":state.get("stream_state"),
        "detail":state.get("stream_detail") or state.get("detail"),
        "setup_required":state.get("status")=="setup-required",
        "launchable":state.get("status")=="ready" and bool(state.get("runtime_image")),
        "setup_launchable":state.get("status")=="setup-required" and bool(state.get("setup_runtime_image")),
        "disc_count":disc_count,"active_disc":active_disc,"discs":discs,"setup_media_mode":setup_media_mode,
        "pairing_port":47989,
        "runtime_failure":runtime_failure or None,
        "runtime_wine_runner":state.get("runtime_wine_runner") or None,
        "runtime_physical_auth":state.get("runtime_physical_auth") or None,
    }
    info.update(browser)
    return info


# Preserve the native LANCommander bridge, then layer PCGA-ingested/install state
# over it. Newly imaged games appear immediately even before a LANCommander package
# is authored, while matching LANCommander entries keep their download/archive data.
_lancommander_library_native=lancommander_library
_lancommander_game_native=lancommander_game
_lancommander_cover_native=lancommander_cover_file


def lancommander_library(search: str="", limit: int=80, offset: int=0) -> dict:
    # PCGA is the canonical library. LANCommander contributes downloadable
    # packages (or an explicitly linked catalog record) but catalog-only metadata
    # must not replace, hide, or impersonate an ingested PCGA game.
    try:
        native=_lancommander_library_native("" if search else search,1000 if search else 160,0)
        items=list(native.get("items") or [])
    except Exception:
        items=[]
    pcga=_pcga_game_rows("") if search else _pcga_game_rows(search)
    pcga_by_id={str(x.get("lancommander_game_id")):x for x in pcga if x.get("lancommander_game_id")}
    pcga_by_title={_pcga_norm_title(x.get("title")):x for x in pcga if x.get("title")}
    used=set(); packaged=[]
    for item in items:
        overlay=pcga_by_id.get(str(item.get("id") or ""))
        if not overlay:
            key=_pcga_norm_title(item.get("title"))
            candidate=pcga_by_title.get(key)
            # Exact-title fallback is allowed only for an actual local package;
            # metadata-only LANCommander rows are intentionally hidden here.
            if candidate and item.get("downloadable"):
                overlay=candidate
        if overlay:
            used.add(str(overlay.get("pcga_set_id")))
            combined=dict(overlay)
            # LANCommander package fields are supplemental distribution metadata.
            for k in ("downloadable","download_url","package_bytes","version","archive_count","directory_name"):
                if item.get(k) is not None: combined[k]=item.get(k)
            combined["lancommander_game_id"]=item.get("id")
            combined["source"]="pcga+lancommander"; packaged.append(combined)
        elif item.get("downloadable"):
            # Preserve genuinely packaged LANCommander games in the main library,
            # but do not surface catalog-only metadata stubs.
            native_item=dict(item); native_item["source"]="lancommander-package"; packaged.append(native_item)
    heroic=_heroic_game_rows(search)
    merged=[x for x in pcga if str(x.get("pcga_set_id")) not in used] + packaged + heroic
    merged.sort(key=lambda x:_pcga_norm_title(x.get("sort_title") or x.get("title")))
    if search:
        merged=_fuzzy_rank(merged,search,lambda x:" ".join(str(x.get(k) or "") for k in ("title","sort_title","description","developer","publisher","year","type")))
    total=len(merged); limit=max(1,min(int(limit),160)); offset=max(0,int(offset))
    page=merged[offset:offset+limit]
    return {"available":True,"items":page,"returned":len(page),"total":total,"offset":offset,"limit":limit,"sources":["pcga-install-state","pcga-store-ingest","lancommander-packages","heroic"]}

def lancommander_game(game_id: str) -> dict:
    if game_id.startswith("pcga:"):
        return _pcga_game_profile(game_id.split(":",1)[1])
    result=_lancommander_game_native(game_id)
    # Explicit link wins. Exact-title fallback is only permitted when the native
    # LANCommander record has a real downloadable archive.
    rows=_pcga_game_rows("")
    overlay=next((x for x in rows if str(x.get("lancommander_game_id") or "")==str(game_id)),None)
    if not overlay and result.get("downloadable"):
        key=_pcga_norm_title(result.get("title"))
        overlay=next((x for x in rows if _pcga_norm_title(x.get("title"))==key),None)
    if overlay:
        for k in ("pcga_set_id","stream_id","install_status","install_phase","install_detail","stream_state","stream_backend","stream_app_title","stream_display_title","playable","launchable","setup_launchable","setup_required","developer","publisher","genres","hero_url","screenshots","metadata_provider","cover_url"):
            if overlay.get(k) is not None: result[k]=overlay.get(k)
        if not result.get("description") and overlay.get("description"): result["description"]=overlay["description"]
        try:
            full=_pcga_game_profile(str(overlay.get("pcga_set_id") or ""))
            for k in ("marketing_description","website","external_ids","categories","series","edition","operating_system"):
                if full.get(k) is not None: result[k]=full.get(k)
        except Exception:
            pass
    return result

def lancommander_cover_file(game_id: str) -> tuple[Path,str]:
    if game_id.startswith("pcga:"):
        sid=game_id.split(":",1)[1]
        if sid.startswith("heroic-"):
            raise FileNotFoundError("Heroic artwork is rendered from launcher metadata when available")
        p=_pcga_cover_path(sid)
        if not p: raise FileNotFoundError("cover not found")
        return p, mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    return _lancommander_cover_native(game_id)


def lancommander_capabilities() -> dict:
    health = lancommander_health()
    return {
        "available": bool(health.get("service_ready")),
        "catalog_available": bool(health.get("catalog_db_readable")),
        "health": health,
        "library": "/api/pc-games/library",
        "game": "/api/pc-games/game/{id}",
        "download": "/api/pc-games/game/{id}/download",
        "health_endpoint": "/api/pc-games/health",
        "client_runtime": "wolf-moonlight",
        "stream": "/api/pc-games/game/{id}/stream",
        "browser_execution": True,
        "native_admin": "advanced-only",
        "virtual_lan": {
            "mode": "shared-docker-bridge",
            "network": "legacy-games",
            "lancommander_host": "lancommander",
            "ipx_relay_port": 213,
        },
    }


def arm_db_status() -> dict:
    if not ARM_DB.exists():
        return {"available": False, "reason": "ARM database not found"}
    try:
        uri = f"file:{ARM_DB}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=0.2)
        conn.row_factory = sqlite3.Row
        tables = _sqlite_tables(conn)
        jobs_table = next((t for t in tables if t.lower() in {"job", "jobs"}), None)
        drives_table = next((t for t in tables if "drive" in t.lower()), None)
        result: dict = {"available": True, "jobs_table": jobs_table, "drives_table": drives_table}
        if jobs_table:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{jobs_table}")').fetchall()]
            order = next((c for c in ("job_id", "id", "start_time", "created_at") if c in cols), cols[0] if cols else None)
            row = conn.execute(f'SELECT * FROM "{jobs_table}" ORDER BY "{order}" DESC LIMIT 1').fetchone() if order else None
            if row:
                wanted = ("job_id", "id", "status", "title", "year", "disctype", "video_type", "start_time", "stop_time", "devpath", "errors")
                result["latest_job"] = {k: row[k] for k in wanted if k in row.keys()}
        if drives_table:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{drives_table}")').fetchall()]
            wanted = [c for c in ("mount", "job_id_current", "job_id_previous", "name") if c in cols]
            if wanted:
                rows = conn.execute(f'SELECT {", ".join(chr(34)+c+chr(34) for c in wanted)} FROM "{drives_table}"').fetchall()
                result["drive_records"] = [{k: r[k] for k in wanted} for r in rows]
        conn.close()
        return result
    except Exception as exc:
        return {"available": False, "reason": f"database busy/unreadable: {type(exc).__name__}"}


def recent_log() -> dict:
    try:
        candidates = [p for p in ARM_LOGS.glob("*.log") if p.is_file()]
        if not candidates:
            return {"file": None, "lines": []}
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        # Keep the status endpoint bounded even if ARM's log is very large.
        with latest.open("rb") as f:
            try:
                f.seek(-65536, os.SEEK_END)
            except OSError:
                f.seek(0)
            data = f.read().decode("utf-8", "replace")
        lines = [x.rstrip() for x in data.splitlines() if x.strip()][-30:]
        return {"file": latest.name, "lines": lines}
    except Exception:
        return {"file": None, "lines": []}


def disk_status() -> dict:
    try:
        usage = shutil.disk_usage(RAW if RAW.exists() else Path("/home/arm/media"))
        return {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "total": human_bytes(usage.total),
            "used": human_bytes(usage.used),
            "free": human_bytes(usage.free),
            "used_percent": round(100.0 * usage.used / usage.total, 1) if usage.total else 0,
        }
    except OSError:
        return {}


def classification_status() -> dict:
    suggestions = []
    counts = {}
    inspected = 0
    try:
        for src in sorted(PENDING.iterdir(), key=lambda p: p.name.lower()) if PENDING.exists() else []:
            if src.name.endswith(".pcga-classification.json"):
                continue
            manifest = src / ".pcga-classification.json" if src.is_dir() else src.with_name(src.name + ".pcga-classification.json")
            data = {}
            try:
                if manifest.is_file():
                    data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                data = {}
            cls = str(data.get("classification") or "uninspected")
            counts[cls] = counts.get(cls, 0) + 1
            if data:
                inspected += 1
            if len(suggestions) < 12:
                suggestions.append({
                    "name": src.name,
                    "classification": cls,
                    "confidence": data.get("confidence"),
                    "action": data.get("action"),
                    "title": data.get("title"),
                    "evidence": (data.get("evidence") or [])[:3],
                })
    except OSError:
        pass
    auto_queues = {}
    for name in ("pc-games", "software", "disc-images"):
        auto_queues[name] = count_top_level(INGEST / name)
    return {
        "engine": "local-first",
        "auto_threshold": 0.90,
        "pending_inspected": inspected,
        "pending_by_class": counts,
        "auto_queues": auto_queues,
        "suggestions": suggestions,
    }


def _jellyfin_global_catalog() -> list[dict]:
    """Compact Jellyfin catalog used by Global Search.

    Unlike the per-library browser this is one cached request, so a landing-page
    search does not fan out into several Jellyfin queries before showing results.
    """
    user_id,_=jellyfin_playback_user()
    def load():
        params={
            "IncludeItemTypes":"Movie,Series,Episode,Video,MusicVideo,Trailer,Audio,MusicAlbum",
            "Recursive":"true","Limit":"600",
            "Fields":"PrimaryImageItemId,Album,Artists,SeriesName,ProductionYear,DateCreated",
            "SortBy":"DateCreated,SortName","SortOrder":"Descending",
        }
        path=f"/Users/{quote(user_id,safe='')}/Items?{urlencode(params)}"
        status,_,raw=jellyfin_request(path,timeout=7.0)
        if status<200 or status>=300: raise RuntimeError(f"Jellyfin global catalog returned HTTP {status}")
        data=json.loads(raw.decode("utf-8","replace") or "{}")
        out=[]
        for row in data.get("Items") or []:
            if not isinstance(row,dict): continue
            iid=str(row.get("Id") or ""); typ=str(row.get("Type") or "")
            if not valid_jellyfin_id(iid): continue
            artists=row.get("Artists") or []
            if isinstance(artists,str): artists=[artists]
            image_id=str(row.get("PrimaryImageItemId") or row.get("AlbumId") or iid)
            out.append({
                "id":iid,"title":str(row.get("Name") or "Untitled"),"type":typ,
                "album":str(row.get("Album") or ""),"artist":", ".join(str(x) for x in artists if x),
                "series":str(row.get("SeriesName") or ""),"year":row.get("ProductionYear"),
                "art_url":f"/api/jellyfin/art/{quote(image_id,safe='')}" if valid_jellyfin_id(image_id) else None,
            })
        return out
    return _search_cached(f"jellyfin:global:{user_id}",45.0,load)


def portal_global_search(query: str, limit: int = 8) -> dict:
    query=str(query or "").strip()[:120]; limit=max(1,min(16,int(limit or 8)))
    started=time.monotonic()
    if not query:
        return {"available":True,"query":"","sections":[],"elapsed_ms":0,"local_first":True}

    def jellyfin_job():
        rows=_fuzzy_rank(
            _jellyfin_global_catalog(),query,
            lambda x:" ".join(str(x.get(k) or "") for k in ("title","artist","album","series","year","type")),
            limit*3,
        )
        media=[]; music=[]
        for x in rows:
            typ=str(x.get("type") or "").lower()
            target=music if typ in {"audio","musicalbum","musicartist"} else media
            target.append(x)
        return {"media":media[:limit],"music":music[:limit]}

    jobs={
        "jellyfin":jellyfin_job,
        "console":lambda:romm_library(query,"",limit,0).get("items") or [],
        "pc_games":lambda:lancommander_library(query,limit,0).get("items") or [],
        "photos":lambda:photo_library_items(query,limit).get("items") or [],
        "audio":lambda:_control_audio_local_search(query,limit),
    }
    results={}; errors={}
    with ThreadPoolExecutor(max_workers=len(jobs),thread_name_prefix="pcga-search") as pool:
        future_map={pool.submit(fn):name for name,fn in jobs.items()}
        for future in as_completed(future_map):
            name=future_map[future]
            try: results[name]=future.result()
            except Exception as exc:
                results[name]=[] if name!="audio" else {"audiobooks":[],"podcasts":[]}
                errors[name]=f"{type(exc).__name__}: {str(exc)[:160]}"

    jf=results.get("jellyfin") if isinstance(results.get("jellyfin"),dict) else {}
    audio=results.get("audio") if isinstance(results.get("audio"),dict) else {}
    section_defs=[
        ("media","Movies & TV",jf.get("media") or []),
        ("music","Music",jf.get("music") or []),
        ("audiobooks","Audiobooks",audio.get("audiobooks") or []),
        ("podcasts","Podcast subscriptions",audio.get("podcasts") or []),
        ("console","Console Games",results.get("console") or []),
        ("pc-games","PC Games",results.get("pc_games") or []),
        ("photos","Photos",results.get("photos") or []),
    ]
    sections=[]
    for sid,title,items in section_defs:
        clean=[dict(x) for x in items[:limit] if isinstance(x,dict)]
        if clean: sections.append({"id":sid,"title":title,"items":clean})
    return {
        "available":True,"query":query,"sections":sections,"errors":errors,
        "elapsed_ms":round((time.monotonic()-started)*1000),"local_first":True,
        "note":"Global Search uses cached/local catalogs only; provider discovery stays inside Podcast and Audiobook search.",
    }


def build_status() -> dict:
    proc = process_status()
    drives = [drive_status(d) for d in configured_drives()]
    stages = {
        "raw": tree_stats(RAW),
        "transcode": tree_stats(TRANSCODE),
        "completed": tree_stats(COMPLETED),
        "music": tree_stats(MUSIC),
    }
    queues = {
        "metadata_pending_items": count_top_level(PENDING),
        "metadata_pending_media": count_media(PENDING),
        "manual_unidentified_items": count_top_level(QUAR_UNIDENTIFIED),
        "manual_unidentified_media": count_media(QUAR_UNIDENTIFIED),
        "library_media": count_media(LIBRARY),
    }

    if proc["phase"] != "idle":
        overall = proc["phase"]
    elif queues["metadata_pending_items"] or queues["manual_unidentified_items"]:
        overall = "review-pending"
    elif any(d.get("medium_present") for d in drives):
        overall = "disc-present"
    else:
        overall = "idle"

    return {
        "version": VERSION,
        "generated_at": now_iso(),
        "overall": overall,
        "process": proc,
        "drives": drives,
        "arm": {"config": arm_config(), "database": arm_db_status()},
        "stages": stages,
        "queues": queues,
        "classification": classification_status(),
        "disk": disk_status(),
        "recent_log": recent_log(),
        "tools": tool_status(),
    }



STORE_ART_ALLOWED_SUFFIXES = (
    "epicgames.com", "epicgames.dev", "epicgames.net",
    "gog.com", "gog-statics.com",
    "amazon.com", "media-amazon.com", "ssl-images-amazon.com",
    "cloudfront.net", "amazonaws.com",
)

def _store_art_url_allowed(value: str) -> bool:
    try:
        u=urlparse(str(value or ""))
        host=(u.hostname or "").lower().rstrip(".")
        if u.scheme != "https" or not host: return False
        return any(host == suffix or host.endswith("."+suffix) for suffix in STORE_ART_ALLOWED_SUFFIXES)
    except Exception:
        return False

def fetch_store_art(value: str) -> tuple[bytes,str]:
    if not _store_art_url_allowed(value):
        raise ValueError("store artwork host is not allowed")
    req=urllib.request.Request(value,headers={"User-Agent":f"PCGA/{VERSION}","Accept":"image/avif,image/webp,image/png,image/jpeg,image/*;q=.8"})
    with urllib.request.urlopen(req,timeout=15) as res:
        final=res.geturl()
        if not _store_art_url_allowed(final): raise ValueError("store artwork redirected to a disallowed host")
        ctype=str(res.headers.get_content_type() or "")
        if not ctype.startswith("image/"): raise ValueError("store artwork response was not an image")
        data=res.read(6*1024*1024+1)
        if len(data)>6*1024*1024: raise ValueError("store artwork exceeded 6 MiB")
        return data,ctype

INDEX_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Media Hub</title>
<style>
:root{color-scheme:dark;--bg-base:#1a110b;--bg-deep:#090604;--bg-deep-rgb:9,6,4;--panel-color:#2a190e;--panel-rgb:42,25,14;--glass:rgba(42,25,14,.54);--panel-surface:rgba(42,25,14,.88);--panel-solid:rgba(42,25,14,.97);--surface-low:rgba(255,255,255,.035);--surface-mid:rgba(255,255,255,.065);--surface-high:rgba(255,255,255,.10);--accent:#e8a15e;--accent-rgb:232,161,94;--accent-soft:rgba(232,161,94,.22);--accent-faint:rgba(232,161,94,.10);--accent-medium:rgba(var(--accent-rgb),.16);--accent-strong:rgba(232,161,94,.34);--line:rgba(var(--accent-rgb),.28);--text:#fff4e6;--ui-text:#fff4e6;--muted:#d7bfa5;--good:#b8d58c;--warn:#f0b35f;--bad:#e77a66;--blue:#e8a15e;--focus-ring:rgba(232,161,94,.95);--theme-ink:#fff4e6;--theme-muted:#d7bfa5;--theme-accent-dark:#b76e2f;--theme-glass:rgba(42,25,14,.88);--theme-glass-solid:rgba(42,25,14,.97);--theme-line:rgba(var(--accent-rgb),.28);--aero-sky-top:#82cbe2;--aero-sky-bottom:#eaf9fd;--aero-field:#80cb67;--aero-field-deep:#55a94a;--safe:clamp(28px,4vw,72px)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;min-height:100vh;color:var(--text);font:clamp(18px,1.45vw,25px)/1.35 var(--ui-font-family,system-ui,-apple-system,Segoe UI,Roboto,sans-serif);background:linear-gradient(180deg,var(--bg-base),var(--bg-deep));overflow-x:hidden}
body:before,body:after{content:"";position:fixed;inset:-20vmax;z-index:1;pointer-events:none;filter:blur(34px)}body:before{background:radial-gradient(circle at 18% 28%,rgba(var(--accent-rgb),.24),transparent 18%),radial-gradient(circle at 72% 18%,rgba(var(--accent-rgb),.16),transparent 16%),radial-gradient(circle at 62% 76%,rgba(var(--panel-rgb),.24),transparent 18%);animation:bgA 22s ease-in-out infinite alternate}body:after{background:radial-gradient(circle at 28% 78%,rgba(var(--accent-rgb),.13),transparent 16%),radial-gradient(circle at 86% 70%,rgba(var(--panel-rgb),.26),transparent 15%);animation:bgB 28s ease-in-out infinite alternate}@keyframes bgA{to{transform:translate3d(4%,-2%,0) scale(1.08)}}@keyframes bgB{to{transform:translate3d(-4%,2%,0) scale(.96)}}
a{color:inherit;text-decoration:none}.shell{min-height:100vh;padding:clamp(28px,4vh,54px) var(--safe) 54px;display:flex;flex-direction:column;justify-content:center}.header{display:flex;justify-content:flex-end;align-items:center;min-height:36px;margin-bottom:24px}.header-hint{color:var(--muted);font-size:.78em;text-align:right;max-width:38ch}
.launcher-wrap{overflow:hidden;padding:8px 3px 18px}.launcher{display:flex;gap:18px;overflow-x:auto;padding:7px 7px 18px;scroll-snap-type:x proximity;scrollbar-width:none}.launcher::-webkit-scrollbar{display:none}.tool{scroll-snap-align:center;flex:0 0 clamp(260px,22vw,390px);min-height:185px;padding:24px;border:1px solid var(--line);border-radius:26px;background:rgba(255,255,255,.055);backdrop-filter:blur(16px) saturate(125%);display:flex;flex-direction:column;justify-content:space-between;transition:.12s transform,.12s border-color,.12s box-shadow}.tool.primary{background:linear-gradient(180deg,rgba(191,105,45,.28),rgba(255,244,230,.05))}.tool.offline{opacity:.64}.tool-head{display:flex;align-items:center;gap:18px}.tool-icon{width:58px;height:58px;display:grid;place-items:center;flex:none;color:var(--accent)}.tool-icon svg{width:52px;height:52px;display:block;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.tool-title{font-size:clamp(27px,2.3vw,41px);font-weight:900;line-height:1.03}.tool-sub{color:var(--muted);font-size:.8em;margin-top:9px}.tool-foot{display:flex;justify-content:space-between;align-items:center;text-transform:uppercase;letter-spacing:.09em;font-size:.68em;font-weight:850;color:var(--muted)}.state-dot{width:12px;height:12px;border-radius:50%;background:var(--good)}.offline .state-dot{background:var(--warn)}
.tv-focus:focus,.tv-focus:focus-visible{outline:none;border-color:white!important;box-shadow:0 0 0 5px var(--focus-ring),0 20px 48px rgba(0,0,0,.48);transform:scale(1.025);z-index:5}
.now-playing-modal{position:fixed;right:clamp(20px,3vw,52px);top:clamp(20px,3vw,44px);z-index:28;width:min(560px,44vw);padding:16px 18px;border:1px solid var(--line);border-radius:24px;background:rgba(var(--panel-rgb),.88);backdrop-filter:blur(20px) saturate(135%);box-shadow:0 18px 45px rgba(0,0,0,.42);display:grid;grid-template-columns:86px minmax(0,1fr);gap:16px;align-items:center;opacity:0;transform:translateY(-12px);pointer-events:none;transition:.18s opacity,.18s transform}.now-playing-modal.show{opacity:1;transform:none;pointer-events:auto}.cover{width:86px;height:86px;border-radius:16px;object-fit:cover;background:rgba(255,255,255,.07);border:1px solid var(--line)}.cover-placeholder{width:86px;height:86px;border-radius:16px;background:linear-gradient(145deg,rgba(var(--accent-rgb),.20),rgba(255,244,230,.04));display:grid;place-items:center;font-size:36px;border:1px solid var(--line)}.track{min-width:0}.now-label{text-transform:uppercase;letter-spacing:.12em;font-size:.60em;color:var(--blue);font-weight:850}.track-title{font-size:clamp(22px,1.8vw,31px);font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:3px}.track-meta{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;font-size:.78em}.progress-line{display:flex;align-items:center;gap:10px;margin-top:9px}.progress{height:6px;background:rgba(255,255,255,.10);border-radius:999px;overflow:hidden;flex:1}.progress>div{height:100%;width:0;background:var(--blue);border-radius:999px}.time{color:var(--muted);font-size:.60em;min-width:72px;text-align:right}.music-device{color:var(--muted);font-size:.58em;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.controls{grid-column:1/-1;display:flex;gap:9px;align-items:center;justify-content:flex-end;margin-top:2px}.ctl{width:54px;height:54px;border-radius:16px;border:1px solid var(--line);background:rgba(255,255,255,.065);color:var(--text);font-size:23px;font-weight:900;display:grid;place-items:center;cursor:pointer}.ctl.main{width:62px;height:62px;border-radius:18px;background:rgba(var(--accent-rgb),.20);font-size:27px}.ctl[disabled]{opacity:.36;cursor:not-allowed}.ctl-label{position:absolute;left:-10000px}.volume{display:flex;gap:7px;margin-left:4px}
.music-browser{position:fixed;inset:0;z-index:42;display:none;place-items:center;padding:clamp(18px,4vw,54px);background:rgba(var(--bg-deep-rgb),.70);backdrop-filter:blur(16px)}.music-browser.show{display:grid}.music-panel{width:min(980px,92vw);max-height:min(820px,88vh);display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--line);border-radius:28px;background:rgba(var(--panel-rgb),.97);box-shadow:0 28px 80px rgba(0,0,0,.58)}.music-browser-head{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 22px 14px}.music-browser-title{font-size:clamp(27px,2.4vw,40px);font-weight:950}.music-browser-sub{color:var(--muted);font-size:.68em;margin-top:3px}.music-close{width:54px;height:54px;border-radius:16px;border:1px solid var(--line);background:rgba(255,255,255,.06);color:var(--text);font-size:25px}.music-search{display:flex;gap:10px;padding:0 22px 16px}.music-search input{flex:1;min-width:0;height:56px;border-radius:16px;border:1px solid var(--line);background:rgba(255,255,255,.055);color:var(--text);padding:0 16px;font:inherit}.music-search button{height:56px;border-radius:16px;border:1px solid var(--line);background:rgba(var(--accent-rgb),.16);color:var(--text);padding:0 20px;font-weight:900}.music-list{overflow:auto;padding:0 16px 18px;display:grid;gap:8px}.music-item{display:grid;grid-template-columns:58px minmax(0,1fr) auto;align-items:center;gap:14px;width:100%;min-height:72px;padding:7px 12px;border-radius:17px;border:1px solid transparent;background:rgba(255,255,255,.035);color:var(--text);text-align:left;cursor:pointer}.music-item:hover{background:rgba(255,255,255,.065)}.music-art{width:58px;height:58px;border-radius:12px;object-fit:cover;background:rgba(255,255,255,.07)}.music-art-placeholder{width:58px;height:58px;border-radius:12px;display:grid;place-items:center;background:rgba(var(--accent-rgb),.13);font-size:25px}.music-item-title{font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.music-item-meta{color:var(--muted);font-size:.68em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}.music-item-time{color:var(--muted);font-size:.65em;padding-left:10px}.music-empty{padding:28px;color:var(--muted);text-align:center}.music-inline-action{height:44px;padding:0 13px;border-radius:13px;border:1px solid var(--line);background:rgba(var(--accent-rgb),.14);color:var(--text);font-weight:850;margin-left:4px}

.global-search-panel{width:min(1180px,94vw);max-height:min(860px,90vh)}.global-search-head{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 22px 12px}.global-search-form{display:flex;gap:10px;padding:0 22px 14px}.global-search-form input{flex:1;min-width:0;height:58px;border:1px solid var(--line);border-radius:min(var(--ui-radius),18px);background:var(--surface-mid);color:var(--text);padding:0 17px;font:inherit}.global-search-form button{height:58px;padding:0 20px;border:1px solid var(--line);border-radius:min(var(--ui-radius),18px);background:var(--accent-soft);color:var(--text);font-weight:900}.global-search-note{padding:0 22px 13px;color:var(--muted);font-size:.60em}.global-search-content{min-height:180px;overflow:auto;padding:0 18px 22px}.global-search-section{margin:5px 0 22px}.global-search-section-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;padding:0 4px 9px}.global-search-section-head h3{margin:0;font-size:.82em}.global-search-section-head span{color:var(--muted);font-size:.58em}.global-search-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}.global-search-card{display:grid;grid-template-columns:62px minmax(0,1fr);gap:11px;align-items:center;width:100%;min-height:82px;padding:9px;border:1px solid var(--line);border-radius:min(var(--ui-radius),18px);background:var(--surface-low);color:var(--text);text-align:left;cursor:pointer}.global-search-card .pcga-art-stack,.global-search-card img{width:62px;height:62px;aspect-ratio:1;object-fit:cover;border-radius:min(var(--ui-radius),13px)}.global-search-card-copy{min-width:0}.global-search-card-title{font-size:.68em;font-weight:950;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.global-search-card-meta{margin-top:4px;color:var(--muted);font-size:.54em;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.global-search-empty{padding:36px 18px;text-align:center;color:var(--muted)}@media(max-width:620px){.global-search-form{flex-wrap:wrap}.global-search-form button{width:100%}.global-search-grid{grid-template-columns:1fr}}

.photo-browser{position:fixed;inset:0;z-index:46;display:none;place-items:center;padding:clamp(18px,3vw,46px);background:rgba(var(--bg-deep-rgb),.72);backdrop-filter:blur(16px)}.photo-browser.show{display:grid}.photo-panel{width:min(1240px,95vw);max-height:min(900px,91vh);display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--line);background:var(--panel-solid);box-shadow:0 28px 80px rgba(0,0,0,.58)}.photo-head{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 22px 14px}.photo-title{font-size:clamp(27px,2.4vw,40px);font-weight:950}.photo-sub{color:var(--muted);font-size:.68em;margin-top:3px}.photo-close{width:54px;height:54px;border:1px solid var(--line);background:rgba(255,255,255,.06);color:var(--text);font-size:25px}.photo-search{display:flex;gap:10px;padding:0 22px 14px}.photo-search input{flex:1;min-width:0;height:56px;border:1px solid var(--line);background:rgba(255,255,255,.055);color:var(--text);padding:0 16px;font:inherit}.photo-search button,.photo-action{min-height:48px;border:1px solid var(--line);background:var(--accent-soft);color:var(--text);padding:0 16px;font-weight:900}.photo-grid{overflow:auto;padding:0 18px 20px;display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}.photo-card{display:flex;flex-direction:column;min-width:0;padding:8px;border:1px solid var(--line);background:rgba(255,255,255,.035);color:var(--text);text-align:left}.photo-card img{width:100%;aspect-ratio:4/3;object-fit:cover;background:rgba(255,255,255,.05);display:block}.photo-card-name{font-weight:850;font-size:.64em;margin-top:7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.photo-card-actions{display:flex;gap:6px;margin-top:8px}.photo-card-actions button{flex:1;min-height:40px;padding:0 8px;font-size:.56em}.photo-viewer{position:fixed;inset:0;z-index:55;display:none;place-items:center;padding:20px;background:rgba(0,0,0,.9)}.photo-viewer.show{display:grid}.photo-viewer-inner{max-width:96vw;max-height:94vh;display:grid;grid-template-rows:minmax(0,1fr) auto;gap:10px}.photo-viewer img{max-width:94vw;max-height:82vh;object-fit:contain;margin:auto;display:block}.photo-viewer-bar{display:flex;justify-content:center;gap:10px;flex-wrap:wrap}.photo-empty{grid-column:1/-1;padding:32px;color:var(--muted);text-align:center}
.library-browser{position:fixed;inset:0;z-index:44;display:none;place-items:center;padding:clamp(18px,3vw,46px);background:rgba(var(--bg-deep-rgb),.72);backdrop-filter:blur(16px)}.library-browser.show{display:grid}.pc-game-stream{position:fixed;inset:0;z-index:1200;background:#050505;display:none;flex-direction:column}.pc-game-stream.show{display:flex}.pc-game-stream-bar{min-height:52px;padding:8px 12px;display:flex;align-items:center;gap:12px;background:rgba(18,20,23,.96);border-bottom:1px solid rgba(255,255,255,.14)}.pc-game-stream-heading{display:flex;align-items:baseline;gap:12px;min-width:0;flex:0 1 auto}.pc-game-stream-bar strong{font-size:18px}.pc-game-stream-bar span{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.pc-game-stream-tabs{display:flex;align-items:center;gap:7px;min-width:0;flex:1 1 auto;overflow-x:auto;scrollbar-width:thin;padding:2px}.pc-game-stream-tab{max-width:220px;min-height:34px;padding:6px 10px;border:1px solid var(--line);border-radius:9px;background:rgba(255,255,255,.045);color:var(--muted);font:inherit;font-size:12px;font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.pc-game-stream-tab.active{border-color:var(--accent);background:var(--accent-soft);color:var(--text)}.pc-game-stream-actions{display:flex;gap:8px;flex:none;align-items:center}.pc-game-stream-discs{display:none;align-items:center;gap:5px;padding-right:4px;border-right:1px solid var(--line)}.pc-game-stream-discs.show{display:flex}.pc-game-stream-discs::before{content:"Disc";font-size:11px;color:var(--muted);font-weight:800}.pc-game-stream-actions button{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 12px}.pc-game-stream-discs button{min-width:36px;padding:8px 9px}.pc-game-stream-discs button.active{border-color:var(--accent);background:var(--accent-soft);color:var(--text)}.pc-game-stream-frames{position:relative;min-height:0;flex:1;background:#000}.pc-game-stream-frame-wrap{position:absolute;inset:0;display:none;background:#000}.pc-game-stream-frame-wrap.active{display:block}.pc-game-stream-frame{width:100%;height:100%;border:0;background:#000;display:block} @media(max-width:900px){.pc-game-stream-bar{align-items:stretch;flex-wrap:wrap}.pc-game-stream-heading{flex:1 1 240px}.pc-game-stream-tabs{order:3;flex-basis:100%}.pc-game-stream-actions{margin-left:auto}}.library-panel{width:min(1180px,94vw);max-height:min(880px,90vh);display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--line);border-radius:28px;background:rgba(var(--panel-rgb),.97);box-shadow:0 28px 80px rgba(0,0,0,.58)}.review-browser{z-index:58}.review-panel{width:min(1380px,96vw)}.review-layout{display:grid;grid-template-columns:minmax(250px,330px) minmax(0,1fr);min-height:0;overflow:hidden;border-top:1px solid var(--line)}.review-queue{overflow:auto;padding:12px;border-right:1px solid var(--line);background:rgba(0,0,0,.12)}.review-queue-item{width:100%;display:block;text-align:left;padding:13px 14px;margin-bottom:8px;border:1px solid var(--line);background:rgba(255,255,255,.035);color:var(--text);cursor:pointer}.review-queue-item.selected{border-color:var(--accent);background:var(--accent-soft)}.review-queue-title{font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.review-queue-meta{color:var(--muted);font-size:.58em;margin-top:4px}.review-detail{overflow:auto;padding:18px 20px 24px}.review-detail h2{margin:0 0 4px;font-size:clamp(24px,2vw,34px)}.review-path{font:600 .58em ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--muted);overflow-wrap:anywhere}.review-block{margin-top:16px;padding:15px;border:1px solid var(--line);background:rgba(255,255,255,.025)}.review-block h3{margin:0 0 10px;font-size:.78em}.review-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.review-field{display:flex;flex-direction:column;gap:5px;color:var(--muted);font-size:.58em}.review-field input,.review-field select{min-height:48px;padding:0 11px;border:1px solid var(--line);background:rgba(255,255,255,.055);color:var(--text);font:inherit;font-size:1.2em}.review-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}.review-action{min-height:50px;padding:0 16px;border:1px solid var(--line);background:rgba(255,255,255,.055);color:var(--text);font-weight:900}.review-action.primary{background:var(--accent-soft);border-color:rgba(var(--accent-rgb),.55)}.review-action.danger{background:rgba(180,65,52,.16)}.review-list{margin:8px 0 0;padding-left:20px;color:var(--muted);font-size:.62em}.review-metadata-results{display:grid;gap:8px;margin-top:10px}.review-metadata-result{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center;padding:10px;border:1px solid var(--line);background:rgba(255,255,255,.025)}.review-metadata-result strong{display:block}.review-metadata-result span{color:var(--muted);font-size:.58em}.review-episode-row{display:flex;justify-content:space-between;gap:12px;padding:5px 0;border-top:1px solid rgba(255,255,255,.06);font-size:.60em}.review-episode-row:first-child{border-top:0}.review-preview{display:grid;grid-template-columns:minmax(220px,440px) minmax(0,1fr);gap:16px;align-items:start}.review-preview-media{min-width:0;background:#000;border:1px solid var(--line);overflow:hidden}.review-preview-media img,.review-preview-media video{display:block;width:100%;max-height:330px;object-fit:contain;background:#000}.review-preview-media audio{display:block;width:100%;min-height:52px}.review-preview-meta{color:var(--muted);font-size:.61em}.review-preview-meta strong{display:block;color:var(--text);font-size:1.18em;margin-bottom:6px;overflow-wrap:anywhere}.review-empty{padding:36px;text-align:center;color:var(--muted)}@media(max-width:820px){.review-layout{grid-template-columns:1fr}.review-queue{max-height:30vh;border-right:0;border-bottom:1px solid var(--line)}.review-form-grid{grid-template-columns:1fr}.review-preview{grid-template-columns:1fr}}.library-head{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 22px 14px}.library-title{font-size:clamp(27px,2.4vw,40px);font-weight:950}.library-sub{color:var(--muted);font-size:.68em;margin-top:3px}.library-close{width:54px;height:54px;border-radius:16px;border:1px solid var(--line);background:rgba(255,255,255,.06);color:var(--text);font-size:25px}.library-search{display:flex;gap:10px;padding:0 22px 12px}.library-search input{flex:1;min-width:0;height:56px;border-radius:16px;border:1px solid var(--line);background:rgba(255,255,255,.055);color:var(--text);padding:0 16px;font:inherit}.library-search button{height:56px;border-radius:16px;border:1px solid var(--line);background:rgba(var(--accent-rgb),.16);color:var(--text);padding:0 20px;font-weight:900}.library-filters{display:flex;gap:8px;padding:0 22px 14px;overflow-x:auto;scrollbar-width:none}.library-filters::-webkit-scrollbar{display:none}.library-filter{min-height:44px;padding:0 14px;border-radius:14px;border:1px solid var(--line);background:rgba(255,255,255,.045);color:var(--text);font-weight:850;white-space:nowrap}.library-filter.active{border-color:var(--accent);background:var(--accent-soft)}.library-grid{overflow:auto;padding:0 18px 20px;display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}.library-item{display:flex;flex-direction:column;min-width:0;padding:9px;border:1px solid var(--line);background:rgba(255,255,255,.035);color:var(--text);text-align:left;cursor:pointer}.library-item:hover{background:rgba(255,255,255,.065)}.library-art{width:100%;aspect-ratio:16/10;object-fit:cover;background:rgba(255,255,255,.06);display:block}.library-art-placeholder{width:100%;aspect-ratio:16/10;display:grid;place-items:center;background:rgba(var(--accent-rgb),.10);font-size:38px}.pcga-art-stack{position:relative;overflow:hidden;isolation:isolate;display:block}.pcga-art-stack>.pcga-art-image{position:absolute;inset:0;z-index:2;width:100%;height:100%;object-fit:cover;background:rgba(var(--panel-rgb),.86)}.pcga-art-stack.art-failed>.pcga-art-image{display:none}.pcga-fallback-art{position:absolute;inset:0;z-index:1;display:grid;place-items:center;align-content:center;gap:.35em;padding:10%;overflow:hidden;text-align:center;background:radial-gradient(circle at 28% 18%,rgba(var(--accent-rgb),.30),transparent 34%),linear-gradient(145deg,rgba(var(--accent-rgb),.19),rgba(var(--panel-rgb),.94) 58%,rgba(var(--accent-rgb),.08));color:var(--ui-text);border:1px solid rgba(var(--accent-rgb),.18)}.pcga-fallback-art::after{content:"";position:absolute;inset:8%;border:1px solid rgba(var(--accent-rgb),.20);border-radius:inherit;pointer-events:none}.pcga-fallback-mark{position:relative;z-index:1;font-size:clamp(24px,3vw,48px);line-height:.9;font-weight:1000;letter-spacing:-.055em;text-transform:uppercase;text-shadow:0 2px 18px rgba(var(--accent-rgb),.24)}.pcga-fallback-label{position:relative;z-index:1;max-width:95%;font-size:clamp(9px,.68em,14px);font-weight:900;letter-spacing:.12em;text-transform:uppercase;opacity:.88}.pcga-fallback-kicker{position:relative;z-index:1;font-size:clamp(8px,.54em,11px);font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}.platform-fallback{background:radial-gradient(circle at 72% 22%,rgba(var(--accent-rgb),.32),transparent 22%),radial-gradient(circle at 28% 76%,rgba(var(--accent-rgb),.18),transparent 30%),linear-gradient(155deg,rgba(var(--accent-rgb),.24),rgba(var(--panel-rgb),.96) 54%,rgba(var(--accent-rgb),.08))}.platform-fallback .pcga-fallback-mark{font-size:clamp(28px,3.6vw,58px)}.platform-fallback::before{content:"";position:absolute;width:46%;aspect-ratio:1;right:-14%;bottom:-18%;border:clamp(5px,.55vw,10px) solid rgba(var(--accent-rgb),.14);border-radius:28%;transform:rotate(22deg)}.media-fallback-movie .pcga-fallback-mark,.media-fallback-series .pcga-fallback-mark{letter-spacing:.04em}.media-fallback-music .pcga-fallback-mark{font-size:clamp(30px,4vw,62px)}.library-item-title{font-weight:900;font-size:.78em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:9px}.library-item-meta{color:var(--muted);font-size:.60em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:3px}.library-item-foot{display:flex;justify-content:space-between;gap:8px;color:var(--muted);font-size:.55em;margin-top:8px}.library-resume{height:4px;border-radius:999px;background:rgba(255,255,255,.10);overflow:hidden;margin-top:7px}.library-resume>span{display:block;height:100%;background:var(--accent)}.library-empty{grid-column:1/-1;padding:32px;color:var(--muted);text-align:center}.game-card .library-art,.game-card .library-art-placeholder{aspect-ratio:3/4}.pc-game-detail-cover{width:min(260px,34vw);height:auto;aspect-ratio:3/4;flex:0 0 min(260px,34vw)}.game-card{position:relative}.game-play-badge{position:absolute;right:16px;top:16px;padding:5px 9px;border-radius:999px;background:rgba(10,7,5,.88);font-size:.52em;font-weight:950;border:1px solid var(--line)}.game-detail{padding:0 22px 24px;overflow:auto}.game-detail-main{display:grid;grid-template-columns:minmax(180px,280px) minmax(0,1fr);gap:24px;align-items:start}.game-detail-cover{width:100%;aspect-ratio:3/4;object-fit:cover;border:1px solid var(--line);background:rgba(255,255,255,.04)}.game-detail-copy h2{margin:0 0 6px;font-size:clamp(28px,3vw,44px)}.game-detail-meta{color:var(--muted);font-size:.68em;margin-bottom:14px}.game-detail-summary{line-height:1.55;max-width:78ch}.game-detail-tags{display:flex;gap:7px;flex-wrap:wrap;margin:10px 0 15px}.game-detail-tag{padding:5px 9px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.045);font-size:.58em}.game-detail-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 18px;margin-top:16px}.game-detail-fact{padding:8px 0;border-top:1px solid rgba(255,255,255,.07);font-size:.62em}.game-detail-fact b{display:block;color:var(--muted);font-size:.9em;margin-bottom:2px}.game-detail-shots{display:flex;gap:12px;overflow:auto;margin-top:22px;padding-bottom:4px}.game-detail-shots img{width:min(360px,74vw);aspect-ratio:16/9;object-fit:cover;border:1px solid var(--line);border-radius:12px;background:#000}@media(max-width:760px){.game-detail-main{grid-template-columns:1fr}.game-detail-cover{width:min(260px,70vw)}.game-detail-facts{grid-template-columns:1fr}}.video-player-modal{position:fixed;inset:0;z-index:52;display:none;background:#000;overflow:hidden}.video-player-modal.show{display:block}.video-player-panel{position:relative;width:100vw;height:100dvh;min-height:100vh;display:grid;grid-template-rows:auto auto minmax(0,1fr) auto auto;overflow:hidden;border:0;border-radius:0;background:#050505;color:var(--text);box-shadow:none}.video-player-head{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:11px 14px;border-bottom:1px solid var(--line);background:var(--panel-solid);z-index:4}.video-player-title{font-size:clamp(20px,1.7vw,30px);font-weight:950;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.video-player-meta{color:var(--muted);font-size:.60em;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.video-player-close{width:46px;height:46px;flex:none;border:1px solid var(--line);background:rgba(255,255,255,.06);color:var(--text);font-size:24px}.video-player-options{display:flex;align-items:end;gap:9px;padding:8px 12px;border-bottom:1px solid var(--line);background:rgba(var(--panel-rgb),.94);overflow-x:auto;scrollbar-width:thin;z-index:4}.video-option{display:grid;gap:3px;min-width:128px;flex:0 0 auto}.video-option span{font-size:.48em;font-weight:900;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}.video-option select{height:38px;min-width:128px;border:1px solid var(--line);background:rgba(255,255,255,.06);color:var(--text);padding:0 28px 0 10px;font:inherit;font-size:.60em;font-weight:800}.video-option.compact{min-width:92px}.video-option.compact select{min-width:92px}.video-stage{position:relative;min-height:0;overflow:hidden;background:#000;display:grid;place-items:center}.video-stage video{display:block;width:100%;height:100%;min-height:0;object-fit:contain;background:#000}.video-stage video.video-fill{object-fit:cover}.video-stream-badge{position:absolute;right:12px;top:12px;z-index:3;max-width:min(72vw,720px);padding:6px 9px;border-radius:999px;background:rgba(0,0,0,.62);color:#eee;border:1px solid rgba(255,255,255,.16);font:700 11px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;pointer-events:none}.video-controls{display:grid;grid-template-columns:auto auto auto minmax(140px,1fr) auto auto auto minmax(78px,140px) auto auto;gap:8px;align-items:center;padding:9px 12px;border-top:1px solid var(--line);background:rgba(8,8,10,.94);z-index:5}.video-control-button{min-width:44px;height:40px;border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.08);color:#fff;font:inherit;font-size:.70em;font-weight:900}.video-control-button.wide{min-width:58px;font-size:.56em}.video-control-time{color:#c9c9cf;font:700 .54em ui-monospace,SFMono-Regular,Consolas,monospace;white-space:nowrap}.video-control-range{width:100%;accent-color:var(--accent)}.video-player-note{padding:7px 12px 9px;color:#bbb;font-size:.53em;background:rgba(8,8,10,.96);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.video-player-note strong{color:#fff}.video-player-panel:fullscreen,.video-player-panel:-webkit-full-screen{width:100vw;height:100vh;min-height:100vh;grid-template-rows:minmax(0,1fr);background:#000}.video-player-panel:fullscreen .video-player-head,.video-player-panel:fullscreen .video-player-options,.video-player-panel:fullscreen .video-player-note,.video-player-panel:-webkit-full-screen .video-player-head,.video-player-panel:-webkit-full-screen .video-player-options,.video-player-panel:-webkit-full-screen .video-player-note{display:none}.video-player-panel:fullscreen .video-stage,.video-player-panel:-webkit-full-screen .video-stage{grid-row:1;grid-column:1;height:100vh}.video-player-panel:fullscreen .video-controls,.video-player-panel:-webkit-full-screen .video-controls{position:absolute;left:0;right:0;bottom:0;z-index:8;border-top:0;padding:18px 18px 14px;background:linear-gradient(transparent,rgba(0,0,0,.84) 35%,rgba(0,0,0,.96));grid-template-columns:auto auto auto minmax(160px,1fr) auto auto auto minmax(90px,150px) auto auto}.video-player-panel:fullscreen .video-stream-badge,.video-player-panel:-webkit-full-screen .video-stream-badge{top:12px;right:12px}.video-player-panel:fullscreen .video-control-button,.video-player-panel:-webkit-full-screen .video-control-button{background:rgba(0,0,0,.48)}@media(max-width:900px){.video-player-options{padding:7px 9px}.video-option{min-width:115px}.video-controls{grid-template-columns:auto auto auto minmax(100px,1fr) auto auto auto auto}.video-volume{display:none}.video-control-button.wide{min-width:48px}}@media(max-width:620px){.video-player-panel{grid-template-rows:auto auto minmax(0,1fr) auto}.video-player-note{display:none}.video-player-title{font-size:19px}.video-player-meta{font-size:.52em}.video-player-options{gap:6px}.video-option{min-width:104px}.video-option select{min-width:104px}.video-controls{grid-template-columns:auto auto minmax(80px,1fr) auto auto auto;gap:6px}.video-skip-back,.video-skip-forward,.video-volume,.video-fit-control{display:none}.video-control-time:first-of-type{display:none}.video-control-button{min-width:40px}.video-fullscreen{display:block}}

.status-modal{position:fixed;left:clamp(20px,3vw,52px);top:clamp(20px,3vw,44px);z-index:30;max-width:min(540px,82vw);padding:17px 20px;border:1px solid var(--line);border-radius:20px;background:rgba(34,20,12,.90);backdrop-filter:blur(18px);box-shadow:0 18px 45px rgba(0,0,0,.45);opacity:0;transform:translateY(-12px);pointer-events:none;transition:.18s opacity,.18s transform}.status-modal.show{opacity:1;transform:none}.status-row{display:flex;gap:13px;align-items:flex-start}.status-icon{width:13px;height:13px;border-radius:50%;margin-top:7px;background:var(--good);flex:none}.status-modal.warn .status-icon{background:var(--warn)}.status-modal.bad .status-icon{background:var(--bad)}.status-title{font-weight:900;font-size:1.04em}.status-body{color:var(--muted);font-size:.78em;margin-top:3px}.footer{display:flex;justify-content:space-between;gap:20px;color:var(--muted);font-size:.67em;margin-top:17px;padding:0 6px}
.rip-modal{position:fixed;left:clamp(20px,3vw,52px);bottom:clamp(20px,3vw,44px);z-index:27;width:min(500px,42vw);padding:14px 17px;border:1px solid var(--line);border-radius:22px;background:rgba(34,20,12,.90);backdrop-filter:blur(20px) saturate(135%);box-shadow:0 18px 45px rgba(0,0,0,.42);opacity:0;transform:translateY(12px);pointer-events:none;transition:.18s opacity,.18s transform}.rip-modal.show{opacity:1;transform:none}.rip-task{min-width:0}.rip-task+.rip-task{border-top:1px solid var(--line);margin-top:12px;padding-top:12px}.rip-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.rip-label{text-transform:uppercase;letter-spacing:.12em;font-size:.58em;color:var(--blue);font-weight:900}.rip-drive{color:var(--muted);font-size:.58em;font-weight:800}.rip-title{font-size:clamp(20px,1.6vw,28px);font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:3px}.rip-meta{display:flex;justify-content:space-between;gap:12px;color:var(--muted);font-size:.64em;margin-top:4px}.rip-progress-line{display:flex;align-items:center;gap:10px;margin-top:9px}.rip-progress{height:7px;background:rgba(255,255,255,.10);border-radius:999px;overflow:hidden;flex:1}.rip-progress>div{height:100%;background:var(--blue);border-radius:999px;transition:width .35s ease}.rip-progress.indeterminate>div{width:34%!important;animation:ripPulse 1.35s ease-in-out infinite alternate}.rip-pct{font-size:.62em;color:var(--muted);min-width:48px;text-align:right}@keyframes ripPulse{from{transform:translateX(-28%)}to{transform:translateX(210%)}}
.film-grain{position:fixed;inset:-12%;z-index:1;pointer-events:none;opacity:.26;mix-blend-mode:soft-light;background-image:repeating-radial-gradient(circle at 17% 23%,rgba(255,244,220,.52) 0 .62px,rgba(38,17,7,.34) .72px 1.18px,transparent 1.28px 2.7px),repeating-radial-gradient(circle at 73% 61%,rgba(255,255,255,.34) 0 .52px,rgba(67,28,10,.20) .62px .92px,transparent 1.02px 2.15px);background-size:3.4px 3.4px,4.2px 4.2px;animation:grainShift .42s steps(2,end) infinite}
@keyframes grainShift{0%{transform:translate3d(-1.2%,.7%,0)}25%{transform:translate3d(.9%,-1%,0)}50%{transform:translate3d(-.4%,1.1%,0)}75%{transform:translate3d(1.1%,.2%,0)}100%{transform:translate3d(-.8%,-.9%,0)}}
@media (prefers-reduced-motion:reduce){body:before,body:after,.film-grain,.rip-progress.indeterminate>div{animation:none!important}}
@media(max-width:1150px){.tool{flex-basis:34vw}.now-playing-modal{width:min(520px,52vw)}.rip-modal{width:min(480px,48vw)}}@media(max-width:900px){.header-hint{display:none}.tool{flex-basis:78vw}.footer span:last-child{display:none}.now-playing-modal{right:18px;top:18px;width:min(500px,72vw)}.cover,.cover-placeholder{width:76px;height:76px}.now-playing-modal{grid-template-columns:76px minmax(0,1fr)}.rip-modal{left:18px;bottom:18px;width:min(520px,calc(100vw - 36px))}.ctl{width:50px;height:50px}.ctl.main{width:58px;height:58px}}

/* Portal customization ------------------------------------------------------ */
:root{--ui-radius:26px;--bg-base:#1a110b;--bg-deep:#090604;--panel-color:#2a190e;--panel-surface:rgba(42,25,14,.88);--panel-solid:rgba(42,25,14,.97);--accent:#e8a15e;--accent-rgb:232,161,94;--accent-soft:rgba(232,161,94,.22);--ui-text:#fff4e6;--muted:#d7bfa5;--line:rgba(232,161,94,.24);--video-opacity:.72;--video-scrim:rgba(9,6,4,.32)}
html{background:var(--bg-deep)}body{color:var(--ui-text);background:linear-gradient(180deg,var(--bg-base),var(--bg-deep))}.shell{position:relative;z-index:2}.header{justify-content:space-between;gap:18px}.header-right{display:flex;align-items:center;justify-content:flex-end;gap:14px;min-width:0}.portal-clock{display:none;position:fixed;z-index:24;line-height:1;text-align:left;white-space:nowrap;padding:12px 16px;border:1px solid var(--line);border-radius:min(var(--ui-radius),18px);background:var(--panel-surface);backdrop-filter:blur(14px) saturate(125%);box-shadow:0 12px 34px rgba(0,0,0,.28);pointer-events:none}.portal-clock.show{display:block}.portal-clock[data-boxed="false"]{padding:0;border-color:transparent;border-radius:0;background:transparent;backdrop-filter:none;box-shadow:none}.portal-clock[data-boxed="false"] .clock-time,.portal-clock[data-boxed="false"] .clock-date{text-shadow:0 2px 12px rgba(0,0,0,.78),0 1px 3px rgba(0,0,0,.9)}.clock-digital{display:block}.clock-analog{display:none;text-align:center}.portal-clock[data-style="analog"] .clock-digital{display:none}.portal-clock[data-style="analog"] .clock-analog{display:block}.analog-dial{position:relative;width:clamp(132px,11vw,176px);aspect-ratio:1;border-radius:50%;border:2px solid var(--line);background:radial-gradient(circle at 50% 44%,rgba(var(--accent-rgb),.10),transparent 58%),rgba(0,0,0,.08);box-shadow:inset 0 0 0 1px rgba(255,255,255,.035);color:var(--ui-text);transition:border-color .18s ease,background .18s ease,box-shadow .18s ease}.portal-clock[data-boxed="false"] .analog-dial{background:rgba(0,0,0,.13);box-shadow:0 2px 15px rgba(0,0,0,.28),inset 0 0 0 1px rgba(255,255,255,.035)}.analog-dial:before{content:"";position:absolute;inset:7%;border-radius:50%;background:repeating-conic-gradient(from -0.7deg,var(--muted) 0deg 1.4deg,transparent 1.4deg 6deg);-webkit-mask:radial-gradient(circle,transparent 0 83%,#000 84% 100%);mask:radial-gradient(circle,transparent 0 83%,#000 84% 100%);opacity:.58}.analog-dial:after{content:"";position:absolute;inset:4%;border-radius:50%;background:repeating-conic-gradient(from -1.3deg,var(--ui-text) 0deg 2.6deg,transparent 2.6deg 30deg);-webkit-mask:radial-gradient(circle,transparent 0 88%,#000 89% 100%);mask:radial-gradient(circle,transparent 0 88%,#000 89% 100%);opacity:.82}.analog-number{position:absolute;font-size:clamp(13px,1vw,17px);font-weight:900;color:var(--ui-text);z-index:2;text-shadow:0 1px 4px rgba(0,0,0,.6)}.portal-clock[data-face="minimal"] .analog-dial{border-width:1px;background:rgba(var(--accent-rgb),.035)}.portal-clock[data-face="minimal"] .analog-number{display:none}.portal-clock[data-face="minimal"] .analog-dial:before{inset:7%;background:repeating-conic-gradient(from -1deg,var(--ui-text) 0deg 2deg,transparent 2deg 30deg);-webkit-mask:radial-gradient(circle,transparent 0 86%,#000 87% 100%);mask:radial-gradient(circle,transparent 0 86%,#000 87% 100%);opacity:.62}.portal-clock[data-face="minimal"] .analog-dial:after{display:none}.portal-clock[data-face="minimal"] .analog-hand.hour{width:6px;height:27%;background:var(--accent)}.portal-clock[data-face="minimal"] .analog-hand.minute{width:3px;height:39%}.portal-clock[data-face="minimal"] .analog-hand.second{width:1px;height:42%}.portal-clock[data-face="roman"] .analog-dial{border:3px double var(--line);background:radial-gradient(circle at 50% 45%,rgba(var(--accent-rgb),.08),transparent 60%),rgba(0,0,0,.11)}.portal-clock[data-face="roman"] .analog-number{font-family:Georgia,'Times New Roman',serif;font-weight:700;font-size:clamp(14px,1.05vw,18px);letter-spacing:.03em}.portal-clock[data-face="roman"] .analog-dial:before{opacity:.36}.portal-clock[data-face="roman"] .analog-dial:after{opacity:.55}.portal-clock[data-face="roman"] .analog-hand.hour{width:5px;height:27%}.portal-clock[data-face="roman"] .analog-hand.minute{width:3px;height:37%}.portal-clock[data-face="railway"] .analog-dial{border:4px solid var(--ui-text);background:rgba(0,0,0,.12);box-shadow:inset 0 0 0 3px rgba(var(--accent-rgb),.18)}.portal-clock[data-face="railway"] .analog-number{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-weight:950}.portal-clock[data-face="railway"] .analog-dial:before{inset:3%;background:repeating-conic-gradient(from -.7deg,var(--ui-text) 0deg 1.4deg,transparent 1.4deg 6deg);-webkit-mask:radial-gradient(circle,transparent 0 82%,#000 83% 100%);mask:radial-gradient(circle,transparent 0 82%,#000 83% 100%);opacity:.85}.portal-clock[data-face="railway"] .analog-dial:after{inset:1%;background:repeating-conic-gradient(from -1.8deg,var(--accent) 0deg 3.6deg,transparent 3.6deg 30deg);-webkit-mask:radial-gradient(circle,transparent 0 90%,#000 91% 100%);mask:radial-gradient(circle,transparent 0 90%,#000 91% 100%);opacity:.9}.portal-clock[data-face="railway"] .analog-hand.hour,.portal-clock[data-face="railway"] .analog-hand.minute{background:var(--ui-text)}.portal-clock[data-face="railway"] .analog-hand.second{background:var(--accent);height:43%}.analog-number.n12{top:11%;left:50%;transform:translateX(-50%)}.analog-number.n3{right:12%;top:50%;transform:translateY(-50%)}.analog-number.n6{bottom:10%;left:50%;transform:translateX(-50%)}.analog-number.n9{left:12%;top:50%;transform:translateY(-50%)}.analog-hand{position:absolute;left:50%;bottom:50%;z-index:4;transform-origin:50% 100%;transform:translateX(-50%) rotate(0deg);border-radius:999px;background:var(--ui-text);box-shadow:0 1px 3px rgba(0,0,0,.55)}.analog-hand.hour{width:5px;height:28%}.analog-hand.minute{width:3px;height:38%}.analog-hand.second{width:2px;height:41%;background:var(--accent);box-shadow:none}.analog-pin{position:absolute;left:50%;top:50%;z-index:6;width:10px;height:10px;border-radius:50%;background:var(--accent);border:2px solid var(--ui-text);transform:translate(-50%,-50%);box-shadow:0 1px 4px rgba(0,0,0,.55)}.clock-analog .clock-date{font-size:clamp(12px,.72vw,15px);margin-top:8px;text-align:center}.portal-clock[data-boxed="false"] .clock-analog .clock-date{margin-top:7px}.portal-clock[data-position="top-left"]{top:clamp(18px,3vw,42px);left:clamp(18px,3vw,52px)}.portal-clock[data-position="top-center"]{top:clamp(18px,3vw,42px);left:50%;transform:translateX(-50%)}.portal-clock[data-position="top-right"]{top:clamp(94px,8vw,118px);right:clamp(18px,3vw,52px)}.portal-clock[data-position="bottom-left"]{bottom:clamp(18px,3vw,42px);left:clamp(18px,3vw,52px)}.portal-clock[data-position="bottom-center"]{bottom:clamp(18px,3vw,42px);left:50%;transform:translateX(-50%)}.portal-clock[data-position="bottom-right"]{bottom:clamp(18px,3vw,42px);right:clamp(18px,3vw,52px)}.clock-time{font-size:clamp(29px,3.0vw,48px);font-weight:950;letter-spacing:-.035em}.clock-date{font-size:.60em;color:var(--muted);margin-top:6px}.settings-open{width:58px;height:58px;flex:none;border:1px solid var(--line);background:var(--panel-surface);color:var(--ui-text);font-size:25px;cursor:pointer;display:grid;place-items:center}
.background-video,.background-photo{position:fixed;inset:0;width:100%;height:100%;object-fit:cover;z-index:0;opacity:0;pointer-events:none;transition:opacity .45s ease,transform .12s linear;transform:translate3d(var(--parallax-media-x,0px),var(--parallax-media-y,0px),0) scale(var(--parallax-media-scale,1))}.background-video.show,.background-photo.show{opacity:var(--video-opacity)}body[data-bg-pattern="video"],body[data-bg-pattern="photo"],body[data-bg-pattern="slideshow"]{background:transparent}body[data-bg-pattern="video"]:before,body[data-bg-pattern="photo"]:before,body[data-bg-pattern="slideshow"]:before{display:block;inset:0;z-index:1;filter:none;animation:none;background:var(--video-scrim)}body[data-bg-pattern="video"]:after,body[data-bg-pattern="photo"]:after,body[data-bg-pattern="slideshow"]:after{display:none}body[data-bg-motion="parallax"]:before,body[data-bg-motion="parallax"]:after{animation:none}body[data-bg-motion="parallax"]:before{transform:translate3d(var(--parallax-near-x,0px),var(--parallax-near-y,0px),0) scale(1.035)}body[data-bg-motion="parallax"]:after{transform:translate3d(var(--parallax-far-x,0px),var(--parallax-far-y,0px),0) scale(1.025)}body[data-bg-motion="parallax"][data-bg-pattern="grid"]:before,body[data-bg-motion="parallax"][data-bg-pattern="dots"]:before,body[data-bg-motion="parallax"][data-bg-pattern="diagonal"]:before{inset:-56px}body[data-bg-motion="parallax"] .background-video,body[data-bg-motion="parallax"] .background-photo{inset:-3.5%;width:107%;height:107%;--parallax-media-scale:1.035}@media(prefers-reduced-motion:reduce){body:before,body:after{animation:none!important;transform:none!important}.background-video,.background-photo{transform:none!important;transition:opacity .45s ease!important}}
body[data-bg-pattern="ambient"]:before{display:block;inset:-20vmax;filter:blur(34px);animation:bgA 22s ease-in-out infinite alternate;background:radial-gradient(circle at 18% 28%,rgba(var(--accent-rgb),.24),transparent 18%),radial-gradient(circle at 72% 18%,rgba(var(--accent-rgb),.16),transparent 16%),radial-gradient(circle at 62% 76%,rgba(var(--accent-rgb),.12),transparent 18%)}body[data-bg-pattern="ambient"]:after{display:block;inset:-20vmax;filter:blur(34px);animation:bgB 28s ease-in-out infinite alternate;background:radial-gradient(circle at 28% 78%,rgba(var(--accent-rgb),.10),transparent 16%),radial-gradient(circle at 86% 70%,rgba(var(--accent-rgb),.10),transparent 15%)}
body[data-bg-pattern="solid"]:before,body[data-bg-pattern="solid"]:after{display:none}body[data-bg-pattern="grid"]:before,body[data-bg-pattern="dots"]:before,body[data-bg-pattern="diagonal"]:before{display:block;inset:0;z-index:1;filter:none;animation:none;opacity:.42}body[data-bg-pattern="grid"]:after,body[data-bg-pattern="dots"]:after,body[data-bg-pattern="diagonal"]:after{display:none}body[data-bg-pattern="grid"]:before{background-image:linear-gradient(rgba(var(--accent-rgb),.18) 1px,transparent 1px),linear-gradient(90deg,rgba(var(--accent-rgb),.18) 1px,transparent 1px);background-size:42px 42px}body[data-bg-pattern="dots"]:before{background-image:radial-gradient(circle,rgba(var(--accent-rgb),.28) 1.4px,transparent 1.5px);background-size:28px 28px}body[data-bg-pattern="diagonal"]:before{background-image:repeating-linear-gradient(135deg,rgba(var(--accent-rgb),.12) 0 2px,transparent 2px 24px)}
.tool,.now-playing-modal,.music-panel,.library-panel,.photo-panel,.video-player-panel,.status-modal,.rip-modal,.settings-panel{background:var(--panel-surface)!important;border-color:var(--line)!important}.music-panel,.library-panel,.photo-panel,.video-player-panel,.settings-panel{background:var(--panel-solid)!important}.tool.primary{background:linear-gradient(180deg,var(--accent-soft),var(--panel-surface))!important}.tool-icon,.now-label,.rip-label{color:var(--accent)!important}.tv-focus:focus,.tv-focus:focus-visible{box-shadow:0 0 0 5px rgba(var(--accent-rgb),.92),0 20px 48px rgba(0,0,0,.48)!important}.progress>div,.rip-progress>div{background:var(--accent)!important}
.tool,.now-playing-modal,.music-panel,.library-panel,.photo-panel,.video-player-panel,.status-modal,.rip-modal,.settings-panel,.settings-card{border-radius:var(--ui-radius)!important}.cover,.cover-placeholder,.music-art,.music-art-placeholder,.ctl,.music-close,.music-search input,.music-search button,.music-item,.music-inline-action,.library-close,.library-search input,.library-search button,.library-filter,.library-item,.library-art,.library-art-placeholder,.pcga-art-stack,.pcga-fallback-art,.photo-close,.photo-card,.photo-card img,.photo-action,.video-player-close,.settings-open,.settings-close,.settings-action,.settings-control input,.settings-control select,.bg-media-item,.bg-media-art{border-radius:min(var(--ui-radius),18px)!important}

/* v0.19.6 Epic native install UX */
#store-install-modal{z-index:78}
.store-install-panel{width:min(620px,95vw);max-height:min(90vh,780px)}
.store-install-body{padding:22px 26px;display:grid;gap:14px}
.store-install-name{font-size:clamp(20px,2vw,29px);font-weight:900;overflow-wrap:anywhere}
.store-install-panel .settings-note{font-size:.75em;line-height:1.55;margin:0}
.store-install-panel .settings-actions{padding:10px 26px 24px}
.store-install-panel button:disabled{opacity:.5;cursor:not-allowed}
.store-install-controls{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.store-install-controls .control-button{min-height:40px}
.store-install-state{display:block;font-size:.64em;color:var(--muted);overflow-wrap:anywhere}
@media(max-width:720px){.store-install-panel{width:100%;max-height:100dvh}.store-install-body{padding:16px}.store-install-panel .settings-actions{padding:12px 16px max(16px,env(safe-area-inset-bottom))}}

/* Native PCGA acquisition center: responsive and TV/D-pad friendly. */
.store-jobs-toolbar{padding:14px 22px 10px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
.store-jobs-tabs{display:flex;gap:7px;flex-wrap:wrap;min-width:0}
.store-jobs-tabs button[aria-pressed="true"]{border-color:var(--accent);background:var(--accent-soft)}
#store-jobs-search{flex:1 1 185px;max-width:320px;min-width:140px;min-height:46px;padding:10px 13px;border:1px solid var(--line);background:var(--panel-solid);color:var(--ui-text);font:inherit;font-size:.7em}
.store-jobs-guidance{padding:0 22px 14px;max-width:108ch;line-height:1.5;color:var(--muted);font-size:.58em}
.store-job-row[data-state="failed"]{border-color:rgba(240,127,91,.5)}
.store-job-row[data-state="running"]{border-color:var(--accent)}
.store-job-progress.indeterminate span{width:34%!important;animation:pcga-download-pulse 2s ease-in-out infinite}
@keyframes pcga-download-pulse{0%{transform:translateX(-110%)}100%{transform:translateX(310%)}}
@media(prefers-reduced-motion:reduce){.store-job-progress.indeterminate span{animation:none;opacity:.6}}
.store-job-progress-label{display:inline-block;color:var(--ui-text);font-size:.65em;font-weight:800;margin-top:7px}
.store-install-progress{width:100%;height:7px;border-radius:99px;background:rgba(255,255,255,.10);overflow:hidden}
.store-install-progress>span{display:block;background:var(--accent);height:100%;transition:width .2s}
.store-job-actions .control-button{min-height:42px}
@media(max-width:720px){.store-jobs-toolbar{padding:12px 14px}.store-jobs-guidance{padding:0 14px 12px}.store-jobs-tabs{width:100%}.store-jobs-tabs button{flex:1 1 40%;min-height:44px}#store-jobs-search{max-width:none;flex:1 1 100%}}
#store-compat-modal{z-index:75;background:rgba(4,7,11,.6);backdrop-filter:blur(8px)}.store-compat-panel{width:min(620px,94vw);max-height:min(88dvh,860px);overflow:auto}.store-compat-fields{display:grid;gap:16px;padding:20px 24px}.store-compat-field{display:grid;gap:7px;font-size:.75em;font-weight:800}.store-compat-field select,.store-compat-field input{width:100%;min-width:0;min-height:48px;background:var(--panel-solid);color:var(--ui-text);border:1px solid var(--line);padding:9px;font:inherit}.store-compat-fields .control-actions{flex-wrap:wrap}.store-compat-fields button{min-height:46px}@media(max-width:720px){.store-compat-panel{width:min(100%,96vw);max-height:calc(100dvh - 32px)}.store-compat-fields{padding:16px}}
#store-auth-modal{z-index:72}#store-jobs-modal{z-index:74}.store-job-list{overflow:auto;padding:0 22px 22px;display:grid;gap:10px}.store-job-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;padding:15px;border:1px solid var(--line);background:rgba(255,255,255,.035)}.store-job-title{font-weight:900;overflow-wrap:anywhere}.store-job-meta{color:var(--muted);font-size:.60em;margin-top:4px}.store-job-progress{height:9px;margin-top:10px;border-radius:999px;overflow:hidden;background:rgba(255,255,255,.08)}.store-job-progress span{display:block;height:100%;background:var(--accent);transition:width .25s ease}.store-job-message{color:var(--muted);font-size:.58em;margin-top:7px;overflow-wrap:anywhere}.store-job-actions{display:flex;align-items:flex-start;gap:7px;flex-wrap:wrap;justify-content:flex-end}.store-job-log{grid-column:1/-1;margin:0;padding:10px;max-height:150px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;border:1px solid var(--line);background:rgba(0,0,0,.16);color:var(--muted);font:600 .52em ui-monospace,SFMono-Regular,Consolas,monospace}.store-job-summary{padding:0 22px 14px;color:var(--muted);font-size:.62em}@media(max-width:720px){.store-job-row{grid-template-columns:1fr}.store-job-actions{justify-content:flex-start}.store-job-log{grid-column:1}}.settings-modal{position:fixed;inset:0;z-index:60;display:none;place-items:center;padding:clamp(16px,3vw,44px);background:rgba(5,4,3,.72);backdrop-filter:blur(18px)}.settings-modal.show{display:grid}.settings-panel{width:min(1120px,95vw);max-height:90vh;overflow:auto;border:1px solid var(--line);box-shadow:0 30px 90px rgba(0,0,0,.58)}.settings-head{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:24px 26px 16px;position:sticky;top:0;z-index:3;background:var(--panel-solid);border-bottom:1px solid var(--line)}.settings-title{font-size:clamp(28px,2.5vw,42px);font-weight:950}.settings-sub{color:var(--muted);font-size:.67em;margin-top:4px}.settings-close{width:56px;height:56px;border:1px solid var(--line);background:rgba(255,255,255,.06);color:var(--ui-text);font-size:26px}.settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;padding:18px 22px}.settings-card{border:1px solid var(--line);padding:18px;background:rgba(255,255,255,.035);min-width:0}.settings-card.wide{grid-column:1/-1}.settings-card h2{font-size:1em;margin:0 0 14px}.settings-row{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:10px 0;border-top:1px solid rgba(255,255,255,.07)}.settings-row:first-of-type{border-top:0}.settings-label{font-weight:800}.settings-help{color:var(--muted);font-size:.64em;margin-top:3px;max-width:55ch}.settings-control{display:flex;align-items:center;gap:10px;flex:none}.settings-control input[type="range"]{width:min(230px,25vw);accent-color:var(--accent)}.settings-control select,.settings-control input[type="text"]{height:46px;padding:0 12px;border:1px solid var(--line);background:rgba(255,255,255,.055);color:var(--ui-text);font:inherit;font-size:.72em}.settings-control input[type="color"]{width:54px;height:46px;padding:4px;border:1px solid var(--line);background:rgba(255,255,255,.05)}.settings-control input[type="checkbox"]{width:26px;height:26px;accent-color:var(--accent)}.radius-readout{min-width:54px;text-align:right;color:var(--muted);font-size:.72em}.scheme-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.scheme-option{display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:12px;min-height:64px;padding:10px 12px;border:1px solid var(--line);background:rgba(255,255,255,.035);color:var(--ui-text);text-align:left;cursor:pointer}.scheme-option.selected{border-color:var(--accent);background:var(--accent-soft)}.scheme-swatches{display:grid;grid-template-columns:repeat(4,15px);gap:3px}.scheme-swatch{width:15px;height:34px;border-radius:min(var(--ui-radius),7px);border:1px solid rgba(255,255,255,.12)}.scheme-name,.scheme-desc{display:block}.scheme-name{font-weight:900;font-size:.76em}.scheme-desc{color:var(--muted);font-size:.56em;margin-top:2px}.settings-actions{display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap;padding:0 22px 22px}.settings-action{min-height:48px;padding:0 18px;border:1px solid var(--line);background:rgba(255,255,255,.055);color:var(--ui-text);font-weight:850}.settings-action.primary{background:var(--accent-soft)}.background-search{display:flex;gap:10px;align-items:center;margin-top:13px}.background-search input{flex:1;min-width:0}.background-results{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:14px}.bg-media-item{border:1px solid var(--line);background:rgba(255,255,255,.035);color:var(--ui-text);padding:8px;text-align:left;min-width:0;cursor:pointer}.bg-media-item.selected{border-color:var(--accent);background:var(--accent-soft)}.bg-media-art{width:100%;aspect-ratio:16/9;object-fit:cover;background:rgba(255,255,255,.06);display:block}.bg-media-placeholder{width:100%;aspect-ratio:16/9;display:grid;place-items:center;background:rgba(255,255,255,.055);font-size:30px}.bg-media-name{font-size:.68em;font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:7px}.bg-media-meta{color:var(--muted);font-size:.54em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}.background-current{color:var(--muted);font-size:.64em;margin-top:10px}.settings-note{color:var(--muted);font-size:.60em;margin-top:10px;line-height:1.45}
/* PCGA Control Center ------------------------------------------------------ */
.settings-panel{width:min(1380px,97vw);max-height:94vh}.control-nav{display:flex;gap:8px;overflow-x:auto;padding:12px 18px;border-bottom:1px solid var(--line);background:var(--panel-solid);scrollbar-width:none}.control-nav::-webkit-scrollbar{display:none}.control-nav button{flex:0 0 auto;min-height:44px;padding:0 14px;border:1px solid var(--line);background:rgba(255,255,255,.035);color:var(--ui-text);font-weight:800}.control-nav button.active{background:var(--accent-soft);border-color:var(--accent)}.control-section{display:none}.control-section.active{display:block}.control-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;padding:14px 22px 0}.control-stat{border:1px solid var(--line);background:rgba(255,255,255,.03);padding:12px 14px}.control-stat strong{display:block;font-size:1.12em}.control-stat span{display:block;color:var(--muted);font-size:.58em;margin-top:3px}.control-button{min-height:46px;padding:0 14px;border:1px solid var(--line);background:rgba(255,255,255,.055);color:var(--ui-text);font-weight:850;cursor:pointer}.control-button.primary{background:var(--accent-soft)}.control-button.warn{border-color:rgba(240,179,95,.5)}.control-button:disabled{opacity:.45;cursor:not-allowed}.control-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:12px}.control-service-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.control-service{border:1px solid var(--line);background:rgba(255,255,255,.03);padding:14px;min-width:0}.control-service-head{display:flex;justify-content:space-between;gap:8px;align-items:center}.control-service-name{font-weight:900}.control-service-state{font-size:.56em;color:var(--muted)}.control-service-state.good{color:var(--good)}.control-service-state.bad{color:var(--warn)}.control-path{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.58em;color:var(--muted);overflow-wrap:anywhere}.control-native-links{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.control-native-link{display:block;padding:14px;border:1px solid var(--line);background:rgba(255,255,255,.035)}.control-native-link strong,.control-native-link span{display:block}.control-native-link span{font-size:.58em;color:var(--muted);margin-top:4px}.diag-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:14px 22px 10px}.diag-toolbar select,.diag-toolbar button{min-height:46px;border:1px solid var(--line);background:rgba(255,255,255,.055);color:var(--ui-text);padding:0 13px;font:inherit;font-size:.66em;font-weight:800}.diag-live{display:flex;align-items:center;gap:7px;font-size:.62em;color:var(--muted);padding:0 7px}.diag-summary{padding:0 22px 12px;color:var(--muted);font-size:.60em}.diag-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:0 22px 22px}.diag-card{min-width:0;border:1px solid var(--line);background:rgba(0,0,0,.22);overflow:hidden}.diag-card-head{display:flex;justify-content:space-between;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--line);background:rgba(255,255,255,.035)}.diag-card-title{min-width:0}.diag-card-title strong{display:block;font-size:.68em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.diag-card-title span{display:block;color:var(--muted);font-size:.50em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.diag-card-actions{display:flex;align-items:center;gap:7px}.diag-state{font-size:.50em;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.diag-state.good{color:var(--good)}.diag-state.bad{color:var(--warn)}.diag-copy{min-height:34px;padding:0 9px;border:1px solid var(--line);background:rgba(255,255,255,.04);color:var(--ui-text);font-size:.50em;font-weight:800}.diag-log{height:260px;margin:0;padding:12px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:var(--bg-deep);color:var(--ui-text);font:12px/1.38 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.diag-empty{grid-column:1/-1;padding:28px;border:1px solid var(--line);color:var(--muted);text-align:center}.system-strip{min-height:48px;max-width:min(760px,55vw);padding:8px 14px;border:1px solid var(--line);background:var(--panel-surface);color:var(--ui-text);display:flex;align-items:center;gap:14px;cursor:pointer}.system-strip-main{font-weight:900;font-size:.72em;white-space:nowrap}.system-strip-meta{font-size:.58em;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.system-strip-dot{width:10px;height:10px;border-radius:50%;background:var(--good);flex:none}.system-strip.warn .system-strip-dot{background:var(--warn)}@media(max-width:900px){.control-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.diag-grid{grid-template-columns:1fr}.control-service-grid,.control-native-links{grid-template-columns:1fr}.system-strip{max-width:58vw}.settings-grid{grid-template-columns:1fr}.settings-card.wide{grid-column:auto}}


/* v0.18.10 unified portal navigation ---------------------------------------- */
:where(a[href],button,input,select,textarea).pcga-nav-selected{outline:none!important;border-color:var(--accent)!important;box-shadow:0 0 0 4px rgba(var(--accent-rgb),.90),0 14px 34px rgba(0,0,0,.34)!important;position:relative;z-index:6}
.tool.pcga-nav-selected,.library-item.pcga-nav-selected,.music-entity.pcga-nav-selected,.photo-card button.pcga-nav-selected,.bg-media-item.pcga-nav-selected,.scheme-option.pcga-nav-selected,.control-native-link.pcga-nav-selected{transform:scale(1.018)}
.settings-panel :where(input,select,button,a[href]){scroll-margin:96px 22px}
.control-nav button.pcga-nav-selected{background:var(--accent-soft)}
@media (prefers-reduced-motion:reduce){.tool.pcga-nav-selected,.library-item.pcga-nav-selected,.music-entity.pcga-nav-selected,.photo-card button.pcga-nav-selected,.bg-media-item.pcga-nav-selected,.scheme-option.pcga-nav-selected,.control-native-link.pcga-nav-selected{transform:none}}

/* v0.18.10 media UX --------------------------------------------------------- */
.music-panel,.library-panel{background:var(--panel-solid)}
.music-panel{width:min(1180px,95vw);max-height:min(900px,92vh)}
.music-nav-row,.music-breadcrumb{display:flex;gap:8px;padding:0 22px 12px;overflow-x:auto;scrollbar-width:none}.music-nav-row::-webkit-scrollbar{display:none}
.music-nav,.music-back{min-height:44px;padding:0 14px;border:1px solid var(--line);background:rgba(255,255,255,.04);color:var(--ui-text);font-weight:850;white-space:nowrap}.music-nav.active{border-color:var(--accent);background:var(--accent-soft)}
.music-content{overflow:auto;padding:0 18px 20px;overscroll-behavior:contain}.music-section+.music-section{margin-top:22px}.music-section-head,.library-section-head{display:flex;align-items:end;justify-content:space-between;gap:14px;margin:0 4px 10px}.music-section-head h3,.library-section-head h3{margin:0;font-size:.88em}.music-section-head span,.library-section-head span{color:var(--muted);font-size:.56em}
.music-shelf,.library-shelf{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(170px,210px);gap:12px;overflow-x:auto;padding:3px 4px 10px;scroll-snap-type:x proximity;overscroll-behavior-inline:contain;scrollbar-width:thin}.music-entity{scroll-snap-align:start;display:flex;flex-direction:column;min-width:0;padding:9px;border:1px solid var(--line);background:rgba(255,255,255,.035);color:var(--ui-text);text-align:left;cursor:pointer}.music-entity-art,.music-entity-placeholder{width:100%;aspect-ratio:1;display:block;background:rgba(255,255,255,.055)}.music-entity-art{object-fit:cover}.music-entity-placeholder{display:grid;place-items:center;font-size:40px}.music-entity-title{font-weight:900;font-size:.72em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:8px}.music-entity-meta{color:var(--muted);font-size:.55em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:3px}
.music-list{overflow:visible;padding:0;gap:7px}.music-item{background:rgba(255,255,255,.03)}
.library-sections{overflow:auto;padding:0 18px 22px;overscroll-behavior:contain}.library-section+.library-section{margin-top:24px}.library-section-more{min-height:40px;padding:0 12px;border:1px solid var(--line);background:rgba(255,255,255,.04);color:var(--ui-text);font-weight:800}.library-shelf .library-item{scroll-snap-align:start}.library-grid{overscroll-behavior:contain}.library-item.media-movie .library-art,.library-item.media-movie .library-art-placeholder{aspect-ratio:2/3}.library-item.media-episode .library-art,.library-item.media-episode .library-art-placeholder,.library-item.media-video .library-art,.library-item.media-video .library-art-placeholder,.library-item.media-musicvideo .library-art,.library-item.media-musicvideo .library-art-placeholder,.library-item.media-trailer .library-art,.library-item.media-trailer .library-art-placeholder{aspect-ratio:16/9}
.library-panel,.music-panel,.settings-panel{contain:layout paint}.library-browser,.music-browser,.settings-modal{overscroll-behavior:contain}
.upload-panel{width:min(980px,94vw);max-height:min(900px,92vh);display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--line);border-radius:var(--ui-radius);background:var(--panel-solid);box-shadow:0 28px 80px rgba(0,0,0,.58)}.upload-head{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding:22px}.upload-title{font-size:clamp(28px,2.6vw,42px);font-weight:950}.upload-sub{color:var(--muted);font-size:.7em;margin-top:4px}.upload-body{overflow:auto;padding:0 22px 22px;display:grid;gap:16px}.upload-options{display:grid;grid-template-columns:minmax(220px,1fr) minmax(220px,1fr);gap:12px}.upload-field{display:grid;gap:6px}.upload-field label{font-size:.66em;font-weight:850;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.upload-field select,.upload-field input{min-height:52px;border:1px solid var(--line);background:rgba(255,255,255,.05);color:var(--ui-text);padding:0 13px;font:inherit}.upload-drop{border:2px dashed var(--line);border-radius:var(--ui-radius);padding:28px;text-align:center;background:rgba(255,255,255,.025);transition:.15s border-color,.15s background}.upload-drop.drag{border-color:var(--accent);background:var(--accent-soft)}.upload-drop strong{display:block;font-size:1.05em}.upload-drop span{display:block;color:var(--muted);font-size:.68em;margin-top:6px}.upload-picker-row{display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin-top:15px}.upload-picker{min-height:48px;display:inline-grid;place-items:center;padding:0 16px;border:1px solid var(--line);border-radius:calc(var(--ui-radius)*.62);background:rgba(255,255,255,.05);font-weight:850;cursor:pointer}.upload-picker.primary{background:var(--accent-soft)}.upload-picker input{position:absolute;inline-size:1px;block-size:1px;opacity:0;pointer-events:none}.upload-selection{padding:13px 15px;border:1px solid var(--line);border-radius:calc(var(--ui-radius)*.62);background:rgba(255,255,255,.03)}.upload-selection-head{display:flex;justify-content:space-between;gap:12px;font-weight:900}.upload-selection-files{margin-top:8px;color:var(--muted);font-size:.64em;max-height:110px;overflow:auto}.upload-progress{display:none}.upload-progress.show{display:block}.upload-progress-bar{height:10px;border-radius:999px;overflow:hidden;background:rgba(255,255,255,.09);margin-top:8px}.upload-progress-bar>div{height:100%;width:0;background:var(--accent)}.upload-actions{display:flex;gap:10px;flex-wrap:wrap}.upload-action{min-height:50px;padding:0 17px;border:1px solid var(--line);background:rgba(255,255,255,.05);color:var(--ui-text);font-weight:900}.upload-action.primary{background:var(--accent-soft)}.upload-action[disabled]{opacity:.4}.upload-jobs{display:grid;gap:8px}.upload-job{padding:12px 14px;border:1px solid var(--line);border-radius:calc(var(--ui-radius)*.6);background:rgba(255,255,255,.03)}.upload-job-head{display:flex;justify-content:space-between;gap:12px;font-weight:850}.upload-job-meta{color:var(--muted);font-size:.62em;margin-top:4px}.upload-job.review{border-color:rgba(240,179,95,.55)}.upload-job.error{border-color:rgba(231,122,102,.62)}.upload-kind-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:8px}.upload-kind-chip{min-height:44px;padding:0 10px;border:1px solid var(--line);background:rgba(255,255,255,.035);color:var(--ui-text);font-weight:800}.upload-kind-chip.active{background:var(--accent-soft);border-color:var(--accent)}.upload-auto-note{display:flex;gap:12px;align-items:flex-start;padding:14px 16px;border:1px solid color-mix(in srgb,var(--accent) 42%,var(--line));border-radius:calc(var(--ui-radius)*.62);background:var(--accent-soft)}.upload-auto-note strong,.upload-auto-note span{display:block}.upload-auto-note span{margin-top:3px;color:var(--muted);font-size:.68em;line-height:1.45}.upload-auto-mark{flex:0 0 auto;display:grid!important;place-items:center;width:28px;height:28px;border-radius:999px;background:var(--accent);color:var(--accent-contrast,#081018)!important;font-size:.72em!important;font-weight:950;margin:0!important}.upload-actions-simple{justify-content:flex-end}.upload-actions-simple .upload-action.primary{min-width:min(240px,100%)}.upload-advanced,.upload-history{border:1px solid var(--line);border-radius:calc(var(--ui-radius)*.62);background:rgba(255,255,255,.025);overflow:hidden}.upload-advanced>summary,.upload-history>summary{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:52px;padding:0 14px;cursor:pointer;font-weight:900;list-style:none}.upload-advanced>summary::-webkit-details-marker,.upload-history>summary::-webkit-details-marker{display:none}.upload-advanced>summary:after,.upload-history>summary:after{content:'＋';font-size:1.15em}.upload-advanced[open]>summary:after,.upload-history[open]>summary:after{content:'−'}.upload-advanced summary small,.upload-history summary small{margin-left:auto;color:var(--muted);font-size:.7em;font-weight:650;text-align:right}.upload-advanced-body{display:grid;gap:12px;padding:0 14px 14px;border-top:1px solid var(--line);padding-top:14px}.upload-field-help{color:var(--muted);font-size:.62em;line-height:1.4}.upload-history .upload-jobs{padding:0 14px 14px;border-top:1px solid var(--line);padding-top:12px}@media(max-width:620px){.upload-auto-note{padding:12px}.upload-actions-simple .upload-action.primary{width:100%}.upload-advanced>summary,.upload-history>summary{align-items:flex-start;flex-wrap:wrap;padding-top:11px;padding-bottom:11px}.upload-advanced summary small,.upload-history summary small{order:3;width:100%;text-align:left;margin-left:0}}.library-head-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.library-upload{min-height:44px;padding:0 12px;border:1px solid var(--line);background:var(--accent-soft);color:var(--ui-text);font-weight:850}@media(max-width:720px){.upload-options{grid-template-columns:1fr}.upload-body{padding-left:14px;padding-right:14px}.upload-head{padding:16px}}
body[data-clock-position="top-right"] .now-playing-modal{top:auto;bottom:clamp(20px,3vw,44px)}
.now-playing-modal,.rip-modal{background:var(--panel-surface)}
@media(max-width:900px){.music-panel,.library-panel{width:96vw;max-height:92vh}.music-shelf,.library-shelf{grid-auto-columns:minmax(150px,68vw)}.music-browser-head,.library-head{padding:16px 16px 10px}.music-search,.library-search,.music-nav-row,.music-breadcrumb,.library-filters{padding-left:16px;padding-right:16px}.music-content,.library-sections,.library-grid{padding-left:14px;padding-right:14px}.now-playing-modal{width:min(560px,92vw);right:4vw}.rip-modal{width:min(500px,92vw);left:4vw}}
@media(max-width:520px){.music-search,.library-search{flex-wrap:wrap}.music-search button,.library-search button{width:100%}.music-shelf,.library-shelf{grid-auto-columns:minmax(150px,78vw)}.music-item{grid-template-columns:52px minmax(0,1fr)}.music-item-time{display:none}.music-art,.music-art-placeholder{width:52px;height:52px}.now-playing-modal.show{bottom:calc(10px + var(--rip-overlay-height,0px));top:auto;right:3vw;width:94vw;grid-template-columns:64px minmax(0,1fr);padding:11px 12px}.now-playing-modal .cover,.now-playing-modal .cover-placeholder{width:64px;height:64px}.now-playing-modal .controls{gap:5px}.now-playing-modal .ctl-label{display:none}.rip-modal.show{bottom:10px;left:3vw;width:94vw}}
@media(max-width:900px){.library-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.header-right .header-hint{display:none}.settings-grid{grid-template-columns:1fr}.settings-card.wide{grid-column:auto}.background-results{grid-template-columns:repeat(2,minmax(0,1fr))}.scheme-grid{grid-template-columns:1fr}.portal-clock.show{display:block}.settings-panel{max-height:92vh}}@media(max-width:520px){.library-grid{grid-template-columns:1fr}.library-search{flex-wrap:wrap}.library-search button{width:100%}.settings-row{align-items:flex-start;flex-direction:column}.settings-control{width:100%}.settings-control input[type="range"],.settings-control select,.settings-control input[type="text"]{width:100%}.background-results{grid-template-columns:1fr}.header{align-items:flex-start}.settings-open{width:52px;height:52px}.clock-time{font-size:30px}.portal-clock{padding:10px 12px}.portal-clock[data-position="top-left"]{top:14px;left:14px}.portal-clock[data-position="top-center"]{top:14px}.portal-clock[data-position="top-right"]{top:78px;right:14px}.portal-clock[data-position="bottom-left"]{bottom:14px;left:14px}.portal-clock[data-position="bottom-center"]{bottom:14px}.portal-clock[data-position="bottom-right"]{bottom:14px;right:14px}}
.secure-context-banner{position:fixed;left:50%;top:12px;transform:translateX(-50%);z-index:1300;width:min(980px,94vw);display:none;align-items:center;justify-content:space-between;gap:14px;padding:12px 14px;border:1px solid rgba(240,179,95,.55);border-radius:16px;background:rgba(35,22,13,.96);box-shadow:0 16px 42px rgba(0,0,0,.48);backdrop-filter:blur(18px)}.secure-context-banner.show{display:flex}.secure-context-copy{min-width:0}.secure-context-copy strong{display:block;font-size:.72em}.secure-context-copy span{display:block;color:var(--muted);font-size:.56em;margin-top:2px}.secure-context-actions{display:flex;gap:8px;flex-wrap:wrap}.secure-context-actions a,.secure-context-actions button{border:1px solid var(--line);background:rgba(255,255,255,.06);color:var(--text);border-radius:10px;padding:8px 11px;font:inherit;font-size:.56em;font-weight:850;white-space:nowrap}@media(max-width:720px){.secure-context-banner{align-items:flex-start;flex-direction:column}.secure-context-actions{width:100%}.secure-context-actions a{flex:1;text-align:center}}

/* v0.18.10 independent background layers */
body:before,body:after{display:none!important}
.background-layer{position:fixed;pointer-events:none;z-index:0;inset:-7%;opacity:0;transition:opacity .35s ease,transform .12s linear;will-change:transform}
.background-layer-ambient{background:radial-gradient(circle at 18% 28%,rgba(var(--accent-rgb),.24),transparent 18%),radial-gradient(circle at 72% 18%,rgba(var(--accent-rgb),.16),transparent 16%),radial-gradient(circle at 62% 76%,rgba(var(--accent-rgb),.12),transparent 18%),radial-gradient(circle at 28% 78%,rgba(var(--accent-rgb),.10),transparent 16%),radial-gradient(circle at 86% 70%,rgba(var(--accent-rgb),.10),transparent 15%);filter:blur(34px);opacity:.9;transform:translate3d(var(--parallax-ambient-x,0px),var(--parallax-ambient-y,0px),0) scale(1.05)}
.background-layer-pattern{inset:-80px;opacity:0;transform:translate3d(var(--parallax-pattern-x,0px),var(--parallax-pattern-y,0px),0) scale(1.04)}
body[data-bg-pattern="solid"] .background-layer-ambient{opacity:0}body[data-bg-pattern="ambient"] .background-layer-ambient{opacity:1}
body[data-bg-pattern="grid"] .background-layer-ambient,body[data-bg-pattern="dots"] .background-layer-ambient,body[data-bg-pattern="diagonal"] .background-layer-ambient{opacity:.56}
body[data-bg-pattern="grid"] .background-layer-pattern,body[data-bg-pattern="dots"] .background-layer-pattern,body[data-bg-pattern="diagonal"] .background-layer-pattern{opacity:.48}
body[data-bg-pattern="grid"] .background-layer-pattern{background-image:linear-gradient(rgba(var(--accent-rgb),.18) 1px,transparent 1px),linear-gradient(90deg,rgba(var(--accent-rgb),.18) 1px,transparent 1px);background-size:42px 42px}
body[data-bg-pattern="dots"] .background-layer-pattern{background-image:radial-gradient(circle,rgba(var(--accent-rgb),.32) 1.4px,transparent 1.5px);background-size:28px 28px}
body[data-bg-pattern="diagonal"] .background-layer-pattern{background-image:repeating-linear-gradient(135deg,rgba(var(--accent-rgb),.14) 0 2px,transparent 2px 24px)}
body[data-bg-pattern="photo"] .background-layer-ambient,body[data-bg-pattern="slideshow"] .background-layer-ambient,body[data-bg-pattern="video"] .background-layer-ambient{opacity:.22}
body[data-bg-motion="standard"] .background-layer{transform:none!important}
@media(prefers-reduced-motion:reduce){.background-layer{transform:none!important;transition:opacity .35s ease!important}}
.patch-drop{border:2px dashed var(--line);padding:24px;text-align:center;background:rgba(255,255,255,.025);border-radius:min(var(--ui-radius),18px);transition:.15s border-color,.15s background}.patch-drop.drag{border-color:var(--accent);background:var(--accent-soft)}.patch-drop strong{display:block}.patch-drop span{display:block;color:var(--muted);font-size:.62em;margin-top:5px}.patch-file-input{position:absolute;width:1px;height:1px;opacity:0}.patch-log{max-height:220px;overflow:auto;white-space:pre-wrap;background:var(--bg-deep);color:var(--ui-text);padding:10px;font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;border:1px solid var(--line);margin-top:10px}


/* v0.18.10 interface theme system ------------------------------------------ */
.theme-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.theme-option{display:grid;grid-template-columns:112px minmax(0,1fr);gap:13px;align-items:center;min-height:104px;padding:11px;border:1px solid var(--line);background:rgba(255,255,255,.035);color:var(--ui-text);text-align:left;cursor:pointer}.theme-option.selected{border-color:var(--accent);background:var(--accent-soft)}.theme-preview{height:80px;border-radius:min(var(--ui-radius),16px);overflow:hidden;border:1px solid rgba(255,255,255,.24);position:relative}.theme-preview.classic{background:linear-gradient(160deg,var(--bg-base),var(--bg-deep))}.theme-preview.classic:before{content:"";position:absolute;inset:13px 10px;display:block;border:1px solid rgba(var(--accent-rgb),.38);border-radius:12px;background:rgba(255,255,255,.08);box-shadow:39px 0 0 -1px rgba(255,255,255,.055),78px 0 0 -1px rgba(255,255,255,.04)}.theme-preview.wii-aero{background:linear-gradient(var(--aero-sky-top) 0 55%,var(--aero-sky-bottom) 56% 66%,var(--aero-field) 67% 100%)}.theme-preview.wii-aero:before{content:"";position:absolute;left:8px;right:8px;top:13px;height:27px;border:2px solid rgba(255,255,255,.94);border-radius:9px;background:linear-gradient(#fff,rgba(236,250,255,.84));box-shadow:31px 0 0 -2px rgba(255,255,255,.92),62px 0 0 -2px rgba(255,255,255,.88)}.theme-preview.wii-aero:after{content:"";position:absolute;width:15px;height:15px;right:8px;bottom:7px;border-radius:50%;background:rgba(255,255,255,.75);box-shadow:-18px 4px 0 -4px rgba(255,255,255,.65),-42px -3px 0 -5px rgba(255,255,255,.58)}.theme-preview.couch-grid{background:linear-gradient(155deg,var(--bg-base),var(--bg-deep))}.theme-preview.couch-grid:before{content:"";position:absolute;inset:10px;display:grid;border-radius:10px;background:linear-gradient(90deg,rgba(var(--accent-rgb),.28) 0 31%,transparent 31% 34%,rgba(255,255,255,.08) 34% 65%,transparent 65% 68%,rgba(255,255,255,.06) 68% 100%);border:1px solid rgba(var(--accent-rgb),.5)}.theme-preview.couch-grid:after{content:"";position:absolute;left:12px;right:12px;bottom:9px;height:5px;border-radius:99px;background:var(--accent)}
.theme-preview.desk-compact{background:var(--bg-deep)}.theme-preview.desk-compact:before{content:"";position:absolute;inset:8px;border:1px solid var(--line);background:repeating-linear-gradient(0deg,rgba(255,255,255,.06) 0 8px,transparent 8px 11px),linear-gradient(90deg,rgba(var(--accent-rgb),.22) 0 24%,transparent 24%)}.theme-preview.desk-compact:after{content:"";position:absolute;left:29%;right:8px;top:12px;height:4px;background:var(--accent);box-shadow:0 12px 0 rgba(255,255,255,.18),0 24px 0 rgba(255,255,255,.12),0 36px 0 rgba(255,255,255,.09)}
.theme-preview.arcade-crt{background:#020604}.theme-preview.arcade-crt:before{content:"";position:absolute;inset:9px;border:2px solid var(--accent);box-shadow:0 0 9px rgba(var(--accent-rgb),.7),inset 0 0 10px rgba(var(--accent-rgb),.18);background:repeating-linear-gradient(0deg,rgba(var(--accent-rgb),.07) 0 1px,transparent 1px 4px)}.theme-preview.arcade-crt:after{content:"PLAY";position:absolute;inset:0;display:grid;place-items:center;color:var(--accent);font:900 14px/1 ui-monospace,monospace;letter-spacing:.14em;text-shadow:0 0 7px rgba(var(--accent-rgb),.8)}
.theme-preview.high-contrast{background:var(--bg-deep);border-color:var(--ui-text)}.theme-preview.high-contrast:before{content:"";position:absolute;inset:9px;border:3px solid var(--ui-text);background:var(--panel-color)}.theme-preview.high-contrast:after{content:"";position:absolute;left:16px;right:16px;top:20px;height:8px;background:var(--accent);box-shadow:0 17px 0 var(--ui-text),0 34px 0 var(--accent)}.theme-name{display:block;font-weight:950}.theme-desc{display:block;margin-top:4px;color:var(--muted);font-size:.60em;line-height:1.35}

/* Wii-inspired Frutiger Aero: original PCGA artwork and CSS only. */
body[data-ui-theme="wii-aero"]{--wii-ink:var(--theme-ink);--wii-muted:var(--theme-muted);--wii-cyan:var(--accent);--wii-cyan-deep:var(--theme-accent-dark);--wii-glass:var(--theme-glass);--wii-glass-solid:var(--theme-glass-solid);--wii-line:var(--theme-line);color:var(--wii-ink);font-family:var(--ui-font-family,"Trebuchet MS",Verdana,system-ui,-apple-system,Segoe UI,sans-serif)}
body[data-ui-theme="wii-aero"][data-bg-pattern="ambient"]{background:linear-gradient(180deg,var(--aero-sky-top) 0%,color-mix(in srgb,var(--aero-sky-top) 48%,white) 47%,var(--aero-sky-bottom) 61%,var(--aero-field) 62%,var(--aero-field-deep) 100%)}
body[data-ui-theme="wii-aero"][data-bg-pattern="ambient"] .background-layer-ambient{inset:-5%;filter:none;opacity:1;background:radial-gradient(ellipse at 14% 18%,rgba(255,255,255,.94) 0 5%,rgba(255,255,255,.72) 5.2% 9%,transparent 9.2%),radial-gradient(ellipse at 28% 14%,rgba(255,255,255,.78) 0 5%,transparent 5.2%),radial-gradient(ellipse at 76% 23%,rgba(255,255,255,.86) 0 6%,transparent 6.2%),radial-gradient(circle at 86% 12%,rgba(255,251,178,.92) 0 4%,rgba(255,246,128,.38) 4.2% 8%,transparent 8.3%),radial-gradient(circle at 9% 69%,rgba(255,255,255,.28) 0 1.1%,transparent 1.3%),radial-gradient(circle at 84% 72%,rgba(255,255,255,.33) 0 1.4%,transparent 1.6%)}
body[data-ui-theme="wii-aero"] .shell{justify-content:flex-start;min-height:100vh;padding:clamp(22px,3vh,38px) clamp(24px,4vw,68px) 30px}
body[data-ui-theme="wii-aero"] .header{min-height:70px;margin-bottom:clamp(14px,2vh,26px);align-items:flex-start}
body[data-ui-theme="wii-aero"] .system-strip{border:2px solid rgba(255,255,255,.92);background:linear-gradient(180deg,rgba(255,255,255,.94),rgba(227,247,253,.88));color:var(--wii-ink);box-shadow:0 5px 18px rgba(20,112,145,.16),inset 0 1px 0 #fff;border-radius:999px!important}
body[data-ui-theme="wii-aero"] .system-strip-meta,body[data-ui-theme="wii-aero"] .footer,body[data-ui-theme="wii-aero"] .tool-sub,body[data-ui-theme="wii-aero"] .tool-foot{color:var(--wii-muted)}
body[data-ui-theme="wii-aero"] .settings-open{border:3px solid rgba(255,255,255,.94);border-radius:50%!important;background:linear-gradient(#fff,color-mix(in srgb,#fff 86%,var(--accent)))!important;color:var(--wii-cyan-deep);box-shadow:0 5px 18px rgba(var(--accent-rgb),.18),inset 0 1px 0 #fff}
body[data-ui-theme="wii-aero"] .launcher-wrap{flex:1;overflow:auto;padding:4px 3px 12px;display:flex;align-items:center}
body[data-ui-theme="wii-aero"] .launcher{width:min(1480px,100%);margin:auto;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));grid-auto-rows:1fr;gap:clamp(12px,1.35vw,22px);overflow:visible;padding:8px;scroll-snap-type:none}
body[data-ui-theme="wii-aero"] .tool{position:relative;isolation:isolate;overflow:hidden;flex:none;min-width:0;min-height:0;aspect-ratio:1.62/1;padding:clamp(13px,1.4vw,20px);border:3px solid rgba(255,255,255,.94)!important;border-radius:var(--ui-radius)!important;background:linear-gradient(180deg,rgba(255,255,255,.97),color-mix(in srgb,rgba(255,255,255,.90) 86%,var(--accent)))!important;color:var(--wii-ink);backdrop-filter:blur(10px) saturate(125%);box-shadow:0 7px 18px rgba(var(--accent-rgb),.18),inset 0 1px 0 #fff,inset 0 -2px 0 rgba(var(--accent-rgb),.10);transition:.14s transform,.14s box-shadow,.14s border-color}
body[data-ui-theme="wii-aero"] .tool:before{content:"";position:absolute;z-index:-1;inset:0;background:radial-gradient(circle at 82% 16%,rgba(255,255,255,.92) 0 4%,transparent 4.5%),linear-gradient(125deg,rgba(255,255,255,.68),transparent 46%);pointer-events:none}
body[data-ui-theme="wii-aero"] .tool.primary{background:linear-gradient(180deg,#fff,color-mix(in srgb,#fff 82%,var(--accent)) 70%,color-mix(in srgb,#fff 72%,var(--accent)))!important}
body[data-ui-theme="wii-aero"] .tool.offline{filter:saturate(.58);opacity:.7}
body[data-ui-theme="wii-aero"] .tool-head{align-items:center;gap:clamp(10px,1vw,16px)}
body[data-ui-theme="wii-aero"] .tool-icon{width:clamp(45px,4.2vw,66px);height:clamp(45px,4.2vw,66px);border-radius:50%;color:var(--wii-cyan-deep)!important;background:linear-gradient(#fff,color-mix(in srgb,#fff 84%,var(--accent)));border:2px solid rgba(var(--accent-rgb),.32);box-shadow:inset 0 1px 0 #fff,0 2px 8px rgba(var(--accent-rgb),.12)}
body[data-ui-theme="wii-aero"] .tool-icon svg{width:68%;height:68%}
body[data-ui-theme="wii-aero"] .tool-title{font-size:clamp(20px,1.6vw,30px);letter-spacing:-.025em;text-shadow:0 1px 0 #fff}
body[data-ui-theme="wii-aero"] .tool-sub{font-size:clamp(12px,.7em,17px);line-height:1.22;margin-top:8px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
body[data-ui-theme="wii-aero"] .tool-foot{font-size:clamp(10px,.52em,13px);letter-spacing:.05em}
body[data-ui-theme="wii-aero"] .state-dot{box-shadow:0 0 0 3px rgba(255,255,255,.8)}
body[data-ui-theme="wii-aero"] .tool.tv-focus:focus,body[data-ui-theme="wii-aero"] .tool.tv-focus:focus-visible{border-color:#fff!important;box-shadow:0 0 0 5px rgba(var(--accent-rgb),.92),0 10px 26px rgba(var(--accent-rgb),.28),inset 0 1px 0 #fff!important;transform:scale(1.035);z-index:8}
body[data-ui-theme="wii-aero"] .footer{margin:8px auto 0;width:min(1080px,96%);padding:10px 20px;border:2px solid rgba(255,255,255,.80);border-radius:999px;background:color-mix(in srgb,rgba(255,255,255,.76) 88%,var(--accent));backdrop-filter:blur(14px);box-shadow:0 5px 18px rgba(var(--accent-rgb),.12);color:var(--wii-muted)}
body[data-ui-theme="wii-aero"] .settings-modal,body[data-ui-theme="wii-aero"] .music-browser,body[data-ui-theme="wii-aero"] .library-browser,body[data-ui-theme="wii-aero"] .photo-browser,body[data-ui-theme="wii-aero"] .video-player-modal{background:rgba(var(--accent-rgb),.22)}
body[data-ui-theme="wii-aero"] .settings-panel,body[data-ui-theme="wii-aero"] .music-panel,body[data-ui-theme="wii-aero"] .library-panel,body[data-ui-theme="wii-aero"] .photo-panel,body[data-ui-theme="wii-aero"] .video-player-panel,body[data-ui-theme="wii-aero"] .upload-panel{background:var(--wii-glass-solid)!important;color:var(--wii-ink);border:2px solid rgba(255,255,255,.92)!important;box-shadow:0 24px 72px rgba(var(--accent-rgb),.22),inset 0 1px 0 #fff}
body[data-ui-theme="wii-aero"] .settings-head{background:color-mix(in srgb,#fff 94%,var(--accent));border-bottom-color:var(--wii-line)}
body[data-ui-theme="wii-aero"] .settings-card,body[data-ui-theme="wii-aero"] .control-service,body[data-ui-theme="wii-aero"] .control-native-link,body[data-ui-theme="wii-aero"] .review-block{background:color-mix(in srgb,rgba(255,255,255,.64) 82%,var(--accent));border-color:var(--wii-line)}
body[data-ui-theme="wii-aero"] .control-nav{background:linear-gradient(180deg,#fff,color-mix(in srgb,#fff 84%,var(--accent)));border-color:var(--wii-line)}
body[data-ui-theme="wii-aero"] .control-nav button,body[data-ui-theme="wii-aero"] .settings-action,body[data-ui-theme="wii-aero"] .control-button,body[data-ui-theme="wii-aero"] .settings-control select,body[data-ui-theme="wii-aero"] .settings-control input[type="text"]{color:var(--wii-ink);background:linear-gradient(#fff,color-mix(in srgb,#fff 88%,var(--accent)));border-color:var(--wii-line)}
body[data-ui-theme="wii-aero"] .control-nav button.active,body[data-ui-theme="wii-aero"] .control-button.primary,body[data-ui-theme="wii-aero"] .settings-action.primary{background:linear-gradient(color-mix(in srgb,#fff 82%,var(--accent)),color-mix(in srgb,#fff 66%,var(--accent)));border-color:rgba(var(--accent-rgb),.58)}
body[data-ui-theme="wii-aero"] .settings-help,body[data-ui-theme="wii-aero"] .settings-note,body[data-ui-theme="wii-aero"] .control-stat span,body[data-ui-theme="wii-aero"] .library-sub,body[data-ui-theme="wii-aero"] .music-browser-sub,body[data-ui-theme="wii-aero"] .audio-card-meta,body[data-ui-theme="wii-aero"] .audio-detail p{color:var(--wii-muted)}
body[data-ui-theme="wii-aero"] .now-playing-modal,body[data-ui-theme="wii-aero"] .status-modal,body[data-ui-theme="wii-aero"] .rip-modal{background:var(--wii-glass)!important;color:var(--wii-ink);border:2px solid rgba(255,255,255,.9)!important;box-shadow:0 16px 42px rgba(28,111,143,.24)}
body[data-ui-theme="wii-aero"] .ctl,body[data-ui-theme="wii-aero"] .music-close,body[data-ui-theme="wii-aero"] .library-close,body[data-ui-theme="wii-aero"] .photo-close{color:var(--wii-ink);background:linear-gradient(#fff,color-mix(in srgb,#fff 86%,var(--accent)));border-color:var(--wii-line)}
/* v0.18.10 utility themes -------------------------------------------------- */
body[data-ui-theme="couch-grid"] .shell{justify-content:flex-start;padding-top:clamp(24px,4vh,54px)}body[data-ui-theme="couch-grid"] .launcher-wrap{overflow:visible;flex:1;display:flex;align-items:center}body[data-ui-theme="couch-grid"] .launcher{width:min(1500px,100%);margin:auto;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:clamp(14px,1.5vw,24px);overflow:visible;padding:8px}body[data-ui-theme="couch-grid"] .tool{flex:none;min-width:0;min-height:0;aspect-ratio:1.7/1;padding:clamp(18px,1.6vw,26px);background:linear-gradient(155deg,rgba(var(--panel-rgb),.92),rgba(var(--panel-rgb),.68));border:1px solid rgba(var(--accent-rgb),.30);box-shadow:0 14px 38px rgba(0,0,0,.28),inset 0 1px 0 rgba(255,255,255,.06)}body[data-ui-theme="couch-grid"] .tool.primary{background:linear-gradient(150deg,rgba(var(--accent-rgb),.28),rgba(var(--panel-rgb),.86) 60%)}body[data-ui-theme="couch-grid"] .tool-icon{width:clamp(58px,5vw,78px);height:clamp(58px,5vw,78px);color:var(--accent)}body[data-ui-theme="couch-grid"] .tool-icon svg{width:72%;height:72%}body[data-ui-theme="couch-grid"] .tool-title{font-size:clamp(25px,2vw,36px)}body[data-ui-theme="couch-grid"] .tool.tv-focus:focus,body[data-ui-theme="couch-grid"] .tool.tv-focus:focus-visible{box-shadow:0 0 0 5px var(--focus-ring),0 22px 48px rgba(0,0,0,.48);transform:scale(1.035)}
body[data-ui-theme="desk-compact"]{font-size:clamp(14px,1vw,18px)}body[data-ui-theme="desk-compact"] .shell{justify-content:flex-start;padding:20px clamp(20px,2.5vw,42px) 30px}body[data-ui-theme="desk-compact"] .header{margin-bottom:12px}body[data-ui-theme="desk-compact"] .launcher-wrap{overflow:visible}body[data-ui-theme="desk-compact"] .launcher{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;overflow:visible;padding:4px}body[data-ui-theme="desk-compact"] .tool{flex:none;min-width:0;min-height:122px;padding:14px 15px;border-radius:min(var(--ui-radius),14px);background:rgba(var(--panel-rgb),.78);backdrop-filter:blur(8px);box-shadow:none}body[data-ui-theme="desk-compact"] .tool.primary{background:linear-gradient(135deg,rgba(var(--accent-rgb),.22),rgba(var(--panel-rgb),.80))}body[data-ui-theme="desk-compact"] .tool-head{gap:10px}body[data-ui-theme="desk-compact"] .tool-icon{width:38px;height:38px}body[data-ui-theme="desk-compact"] .tool-icon svg{width:34px;height:34px}body[data-ui-theme="desk-compact"] .tool-title{font-size:clamp(18px,1.25vw,24px)}body[data-ui-theme="desk-compact"] .tool-sub{font-size:.72em;margin-top:5px}body[data-ui-theme="desk-compact"] .tool-foot{font-size:.58em}body[data-ui-theme="desk-compact"] .settings-panel{width:min(1560px,97vw);max-height:94vh}body[data-ui-theme="desk-compact"] .settings-card{border-radius:min(var(--ui-radius),14px)}body[data-ui-theme="desk-compact"] .control-nav button{min-height:44px}
body[data-ui-theme="arcade-crt"]{font-family:var(--ui-font-family,ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace);text-shadow:0 0 7px rgba(var(--accent-rgb),.13)}body[data-ui-theme="arcade-crt"]:after{inset:0;filter:none;transform:none!important;animation:none;background:repeating-linear-gradient(0deg,rgba(0,0,0,0) 0 2px,rgba(0,0,0,.20) 2px 3px);z-index:20;mix-blend-mode:multiply}body[data-ui-theme="arcade-crt"] .shell{justify-content:flex-start}body[data-ui-theme="arcade-crt"] .launcher{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;overflow:visible;padding:10px}body[data-ui-theme="arcade-crt"] .tool{flex:none;min-width:0;min-height:165px;border:2px solid rgba(var(--accent-rgb),.58);border-radius:min(var(--ui-radius),12px);background:rgba(var(--bg-deep-rgb),.78);backdrop-filter:none;box-shadow:inset 0 0 18px rgba(var(--accent-rgb),.06),0 0 12px rgba(var(--accent-rgb),.08)}body[data-ui-theme="arcade-crt"] .tool.primary{background:linear-gradient(180deg,rgba(var(--accent-rgb),.16),rgba(var(--bg-deep-rgb),.88))}body[data-ui-theme="arcade-crt"] .tool-icon,body[data-ui-theme="arcade-crt"] .tool-title{color:var(--accent);text-shadow:0 0 9px rgba(var(--accent-rgb),.55)}body[data-ui-theme="arcade-crt"] .tool.tv-focus:focus,body[data-ui-theme="arcade-crt"] .tool.tv-focus:focus-visible{border-color:var(--ui-text)!important;box-shadow:0 0 0 3px var(--accent),0 0 28px rgba(var(--accent-rgb),.72)!important;transform:translateY(-3px)}body[data-ui-theme="arcade-crt"] .settings-panel,body[data-ui-theme="arcade-crt"] .music-panel,body[data-ui-theme="arcade-crt"] .library-panel,body[data-ui-theme="arcade-crt"] .photo-panel{background:rgba(var(--bg-deep-rgb),.96)!important;border:2px solid rgba(var(--accent-rgb),.58)!important;box-shadow:0 0 30px rgba(var(--accent-rgb),.15)}body[data-ui-theme="arcade-crt"] .settings-card,body[data-ui-theme="arcade-crt"] .control-service{background:rgba(var(--panel-rgb),.46);border-color:rgba(var(--accent-rgb),.34)}
body[data-ui-theme="high-contrast"]{text-shadow:none}body[data-ui-theme="high-contrast"][data-bg-pattern="ambient"]:before,body[data-ui-theme="high-contrast"][data-bg-pattern="ambient"]:after{display:none}body[data-ui-theme="high-contrast"] .shell{justify-content:flex-start}body[data-ui-theme="high-contrast"] .launcher{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;overflow:visible;padding:8px}body[data-ui-theme="high-contrast"] .tool{flex:none;min-width:0;min-height:180px;border:3px solid var(--ui-text);background:var(--bg-deep);backdrop-filter:none;box-shadow:none}body[data-ui-theme="high-contrast"] .tool.primary{border-color:var(--accent);background:var(--panel-color)}body[data-ui-theme="high-contrast"] .tool-icon{color:var(--accent)}body[data-ui-theme="high-contrast"] .tool-sub,body[data-ui-theme="high-contrast"] .tool-foot{color:var(--ui-text)}body[data-ui-theme="high-contrast"] .tool.tv-focus:focus,body[data-ui-theme="high-contrast"] .tool.tv-focus:focus-visible{outline:5px solid var(--accent);outline-offset:4px;border-color:var(--ui-text)!important;box-shadow:none!important;transform:none}body[data-ui-theme="high-contrast"] .settings-panel,body[data-ui-theme="high-contrast"] .music-panel,body[data-ui-theme="high-contrast"] .library-panel,body[data-ui-theme="high-contrast"] .photo-panel,body[data-ui-theme="high-contrast"] .video-player-panel,body[data-ui-theme="high-contrast"] .upload-panel{background:var(--bg-deep)!important;border:3px solid var(--ui-text)!important;box-shadow:none;backdrop-filter:none}body[data-ui-theme="high-contrast"] .settings-card,body[data-ui-theme="high-contrast"] .control-service,body[data-ui-theme="high-contrast"] .control-native-link,body[data-ui-theme="high-contrast"] .review-block{background:var(--panel-color);border:2px solid var(--ui-text)}body[data-ui-theme="high-contrast"] button,body[data-ui-theme="high-contrast"] input,body[data-ui-theme="high-contrast"] select{border-width:2px!important}body[data-ui-theme="high-contrast"] .settings-help,body[data-ui-theme="high-contrast"] .settings-note,body[data-ui-theme="high-contrast"] .music-item-meta,body[data-ui-theme="high-contrast"] .library-sub{color:var(--ui-text)}
@media(max-width:1180px){.theme-grid{grid-template-columns:repeat(2,minmax(0,1fr))}body[data-ui-theme="couch-grid"] .launcher{grid-template-columns:repeat(3,minmax(0,1fr))}body[data-ui-theme="high-contrast"] .launcher{grid-template-columns:repeat(3,minmax(0,1fr))}body[data-ui-theme="desk-compact"] .launcher,body[data-ui-theme="arcade-crt"] .launcher{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:820px){body[data-ui-theme="couch-grid"] .launcher,body[data-ui-theme="high-contrast"] .launcher{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:760px){body[data-ui-theme="high-contrast"] .launcher{grid-template-columns:repeat(2,minmax(0,1fr))}body[data-ui-theme="desk-compact"] .launcher,body[data-ui-theme="arcade-crt"] .launcher{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:540px){body[data-ui-theme="couch-grid"] .launcher,body[data-ui-theme="high-contrast"] .launcher{grid-template-columns:1fr}}@media(max-width:500px){body[data-ui-theme="desk-compact"] .launcher,body[data-ui-theme="arcade-crt"] .launcher{grid-template-columns:1fr}}
@media(max-width:1180px){body[data-ui-theme="wii-aero"] .launcher{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:820px){body[data-ui-theme="wii-aero"] .launcher{grid-template-columns:repeat(2,minmax(0,1fr))}body[data-ui-theme="wii-aero"] .shell{padding-left:18px;padding-right:18px}}
@media(max-width:620px){.theme-grid{grid-template-columns:1fr}}@media(max-width:520px){body[data-ui-theme="wii-aero"] .launcher{grid-template-columns:1fr}body[data-ui-theme="wii-aero"] .tool{aspect-ratio:auto;min-height:150px}}

/* v0.18.10 unified audio hub */
.audio-source-tabs{display:flex;gap:8px;padding:0 22px 14px;flex-wrap:wrap}.audio-source-tab{height:44px;padding:0 15px;border:1px solid var(--line);border-radius:14px;background:rgba(255,255,255,.045);color:var(--text);font:inherit;font-size:.68em;font-weight:900}.audio-source-tab.active{background:rgba(var(--accent-rgb),.18);border-color:rgba(var(--accent-rgb),.56)}
.audio-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:13px;padding:0 22px 20px;overflow:auto}.audio-card{display:flex;flex-direction:column;min-height:270px;border:1px solid var(--line);border-radius:19px;background:rgba(255,255,255,.035);overflow:hidden;color:var(--text);text-align:left}.audio-card button{font:inherit}.audio-card-main{display:flex;flex:1;flex-direction:column;border:0;background:transparent;color:inherit;text-align:left;padding:0;cursor:pointer}.audio-card-art{width:100%;aspect-ratio:1/1;object-fit:cover;background:rgba(255,255,255,.06)}.audio-card-art-placeholder{width:100%;aspect-ratio:1/1;display:grid;place-items:center;background:rgba(var(--accent-rgb),.11);font-size:48px}.audio-card-copy{padding:12px 13px}.audio-card-title{font-weight:950;line-height:1.15}.audio-card-meta{color:var(--muted);font-size:.62em;margin-top:5px;line-height:1.35}.audio-card-actions{display:flex;gap:7px;padding:0 12px 12px}.audio-card-actions button,.audio-action{border:1px solid var(--line);border-radius:12px;background:rgba(var(--accent-rgb),.12);color:var(--text);padding:9px 11px;font-weight:850}.audio-detail{overflow:auto;padding:0 22px 22px}.audio-detail-hero{display:grid;grid-template-columns:minmax(150px,220px) minmax(0,1fr);gap:22px;align-items:start}.audio-detail-cover{width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:20px;background:rgba(255,255,255,.06);border:1px solid var(--line)}.audio-detail h2{margin:.15em 0;font-size:clamp(28px,3vw,44px)}.audio-detail p{color:var(--muted);line-height:1.5;font-size:.72em}.audio-detail-meta{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.audio-chip{padding:6px 9px;border:1px solid var(--line);border-radius:999px;color:var(--muted);font-size:.58em}.audio-episodes{display:grid;gap:8px;margin-top:20px}.audio-episode{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center;border:1px solid transparent;border-radius:15px;background:rgba(255,255,255,.035);padding:11px 13px;color:var(--text);text-align:left}.audio-episode:hover{background:rgba(255,255,255,.065)}.audio-episode-title{font-weight:900}.audio-episode-meta{color:var(--muted);font-size:.61em;margin-top:3px}.audio-progress-mini{height:4px;background:rgba(255,255,255,.1);border-radius:999px;overflow:hidden;margin-top:6px}.audio-progress-mini span{display:block;height:100%;background:var(--accent)}.audio-provider-note{padding:0 22px 14px;color:var(--muted);font-size:.62em}.audio-search-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px;padding:0 22px 16px}.audio-search-row input,.audio-search-row select{height:54px;border-radius:15px;border:1px solid var(--line);background:rgba(255,255,255,.055);color:var(--text);padding:0 14px;font:inherit}.audio-search-row button{height:54px;border-radius:15px;border:1px solid var(--line);background:rgba(var(--accent-rgb),.15);color:var(--text);padding:0 18px;font-weight:900}.audio-job{margin:0 22px 14px;padding:11px 13px;border:1px solid var(--line);border-radius:14px;background:rgba(255,255,255,.035);color:var(--muted);font-size:.65em}@media(max-width:720px){.audio-grid{grid-template-columns:repeat(2,minmax(0,1fr));padding-left:14px;padding-right:14px}.audio-source-tabs,.audio-search-row,.audio-provider-note,.audio-detail{padding-left:14px;padding-right:14px}.audio-detail-hero{grid-template-columns:110px minmax(0,1fr);gap:14px}.audio-search-row{grid-template-columns:1fr auto}.audio-search-row select{grid-column:1/-1}}

/* v0.18.10 responsive modal headers + independent light/dark appearance ------ */
/* Keep the Control Center chrome outside the scrolling content. Focused tabs
   can no longer rise through the title bar while the section is scrolled. */
.settings-panel{display:flex;flex-direction:column;overflow:hidden}
.settings-head{position:relative;top:auto;z-index:20;flex:0 0 auto;min-width:0}
.settings-head>div:first-child{min-width:0;flex:1 1 auto}
.control-nav{position:relative;z-index:15;flex:0 0 auto;min-height:68px;align-items:center}
.control-section.active{display:block;flex:1 1 auto;min-height:0;overflow:auto;overscroll-behavior:contain}
.settings-actions{position:relative;z-index:14;flex:0 0 auto;background:var(--panel-solid);border-top:1px solid var(--line);padding-top:14px}
.control-nav .tv-focus:focus,.control-nav .tv-focus:focus-visible,.library-head-actions .tv-focus:focus,.library-head-actions .tv-focus:focus-visible,.settings-head .tv-focus:focus,.settings-head .tv-focus:focus-visible{transform:none}

/* Every modal header owns a title region and a separate action region. The
   action region wraps below the title before it is allowed to cover content. */
.library-head,.music-browser-head,.photo-head,.upload-head,.video-player-head{align-items:flex-start;flex-wrap:wrap;column-gap:18px;row-gap:10px}
.library-head>div:first-child,.music-browser-head>div:first-child,.photo-head>div:first-child,.upload-head>div:first-child,.video-player-head>div:first-child{min-width:min(280px,100%);flex:1 1 320px}
.library-head-actions{min-width:0;max-width:100%;flex:0 1 auto;align-self:flex-start;justify-content:flex-end}
.library-head-actions>*{flex:0 0 auto}
.library-title,.music-browser-title,.photo-title,.upload-title,.video-player-title,.settings-title{overflow-wrap:anywhere}
@media(max-width:760px){.library-head-actions{width:100%;justify-content:flex-start}.library-head-actions .library-close,.library-head-actions .music-close,.library-head-actions .photo-close{margin-left:auto}.control-nav{min-height:62px}.settings-head{padding:18px 18px 13px}}
@media(max-width:520px){.library-head-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));width:100%}.library-head-actions .library-close,.library-head-actions .music-close,.library-head-actions .photo-close{margin-left:0;justify-self:end}.library-upload{min-width:0;white-space:normal}.settings-title{font-size:clamp(24px,8vw,34px)}}

/* Generic light surfaces. Layout themes still own geometry; appearance mode
   owns luminance/contrast. */
body[data-color-mode="light"]{text-shadow:none}
body[data-color-mode="light"] .settings-modal,body[data-color-mode="light"] .music-browser,body[data-color-mode="light"] .library-browser,body[data-color-mode="light"] .photo-browser{background:rgba(27,38,45,.34)}
body[data-color-mode="light"] .tool,body[data-color-mode="light"] .settings-card,body[data-color-mode="light"] .control-stat,body[data-color-mode="light"] .control-service,body[data-color-mode="light"] .control-native-link,body[data-color-mode="light"] .library-item,body[data-color-mode="light"] .music-item,body[data-color-mode="light"] .audio-card,body[data-color-mode="light"] .audio-episode,body[data-color-mode="light"] .review-block{background:rgba(255,255,255,.68)}
body[data-color-mode="light"] .settings-control select,body[data-color-mode="light"] .settings-control input[type="text"],body[data-color-mode="light"] .library-search input,body[data-color-mode="light"] .music-search input,body[data-color-mode="light"] .audio-search-row input,body[data-color-mode="light"] .audio-search-row select{background:rgba(255,255,255,.84);color:var(--ui-text)}
body[data-color-mode="light"] .control-nav button,body[data-color-mode="light"] .settings-action,body[data-color-mode="light"] .control-button,body[data-color-mode="light"] .library-filter,body[data-color-mode="light"] .library-upload,body[data-color-mode="light"] .audio-source-tab{background:rgba(255,255,255,.70);color:var(--ui-text)}
body[data-color-mode="light"] .control-nav button.active,body[data-color-mode="light"] .scheme-option.selected,body[data-color-mode="light"] .theme-option.selected{background:var(--accent-soft)}
body[data-color-mode="light"] .film-grain{opacity:.08;mix-blend-mode:multiply}
body[data-color-mode="light"] .status-modal,body[data-color-mode="light"] .rip-modal{background:var(--panel-solid)}
body[data-color-mode="light"] .progress,body[data-color-mode="light"] .rip-progress,body[data-color-mode="light"] .library-resume,body[data-color-mode="light"] .audio-progress-mini{background:rgba(0,0,0,.10)}
body[data-color-mode="light"] .review-queue{background:rgba(0,0,0,.025)}

/* Dark Frutiger Aero keeps the sky/field silhouette but turns the glass into
   moonlit translucent surfaces instead of forcing white Wii-era panels. */
body[data-ui-theme="wii-aero"][data-color-mode="dark"][data-bg-pattern="ambient"]{background:linear-gradient(180deg,var(--aero-sky-top) 0%,color-mix(in srgb,var(--aero-sky-top) 72%,#163747) 47%,var(--aero-sky-bottom) 61%,var(--aero-field) 62%,var(--aero-field-deep) 100%)}
body[data-ui-theme="wii-aero"][data-color-mode="dark"][data-bg-pattern="ambient"] .background-layer-ambient{background:radial-gradient(circle at 84% 12%,rgba(225,244,255,.70) 0 2.5%,rgba(155,211,235,.14) 2.8% 8%,transparent 8.4%),radial-gradient(ellipse at 14% 18%,rgba(190,226,238,.20) 0 5%,transparent 9.2%),radial-gradient(ellipse at 76% 23%,rgba(190,226,238,.16) 0 6%,transparent 6.2%),radial-gradient(circle at 9% 69%,rgba(190,240,215,.13) 0 1.1%,transparent 1.3%),radial-gradient(circle at 84% 72%,rgba(190,240,215,.16) 0 1.4%,transparent 1.6%)}
body[data-ui-theme="wii-aero"][data-color-mode="dark"] .tool{border-color:rgba(var(--accent-rgb),.46)!important;background:linear-gradient(180deg,color-mix(in srgb,var(--panel-solid) 90%,var(--accent)),var(--panel-solid))!important;box-shadow:0 8px 24px rgba(0,0,0,.38),inset 0 1px 0 rgba(255,255,255,.08)}
body[data-ui-theme="wii-aero"][data-color-mode="dark"] .tool.primary{background:linear-gradient(180deg,color-mix(in srgb,var(--panel-solid) 76%,var(--accent)),color-mix(in srgb,var(--panel-solid) 92%,var(--accent)))!important}
body[data-ui-theme="wii-aero"][data-color-mode="dark"] .tool:before{background:radial-gradient(circle at 82% 16%,rgba(255,255,255,.17) 0 4%,transparent 4.5%),linear-gradient(125deg,rgba(255,255,255,.08),transparent 46%)}
body[data-ui-theme="wii-aero"][data-color-mode="dark"] .tool-title{text-shadow:0 1px 0 rgba(0,0,0,.8)}
body[data-ui-theme="wii-aero"][data-color-mode="dark"] .tool-icon{color:var(--accent)!important;background:linear-gradient(color-mix(in srgb,var(--panel-solid) 84%,var(--accent)),var(--panel-solid));border-color:rgba(var(--accent-rgb),.52);box-shadow:inset 0 1px 0 rgba(255,255,255,.10),0 2px 10px rgba(0,0,0,.25)}
body[data-ui-theme="wii-aero"][data-color-mode="dark"] .system-strip,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .footer,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .settings-open{background:color-mix(in srgb,var(--panel-solid) 88%,var(--accent))!important;border-color:rgba(var(--accent-rgb),.46)!important;color:var(--ui-text);box-shadow:0 7px 24px rgba(0,0,0,.32),inset 0 1px 0 rgba(255,255,255,.08)}
body[data-ui-theme="wii-aero"][data-color-mode="dark"] .settings-panel,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .music-panel,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .library-panel,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .photo-panel,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .video-player-panel,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .upload-panel{background:var(--panel-solid)!important;color:var(--ui-text);border-color:rgba(var(--accent-rgb),.46)!important}
body[data-ui-theme="wii-aero"][data-color-mode="dark"] .settings-head,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .control-nav{background:var(--panel-solid)!important;color:var(--ui-text);border-color:rgba(var(--accent-rgb),.32)!important}
body[data-ui-theme="wii-aero"][data-color-mode="dark"] .control-nav button,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .settings-action,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .control-button,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .settings-control select,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .settings-control input[type="text"]{color:var(--ui-text);background:color-mix(in srgb,var(--panel-color) 92%,var(--accent));border-color:rgba(var(--accent-rgb),.32)}
body[data-ui-theme="wii-aero"][data-color-mode="dark"] .settings-card,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .control-stat,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .control-service,body[data-ui-theme="wii-aero"][data-color-mode="dark"] .control-native-link{background:color-mix(in srgb,var(--panel-color) 94%,var(--accent));color:var(--ui-text)}


/* Light variants for strongly opinionated dark layouts. */
body[data-ui-theme="arcade-crt"][data-color-mode="light"]{font-family:var(--ui-font-family,ui-monospace,SFMono-Regular,Menlo,Consolas,monospace)}
/* Typography is orthogonal to layout/theme. Keep code, paths, and diagnostics monospace. */
body{font-family:var(--ui-font-family,system-ui,-apple-system,Segoe UI,Roboto,sans-serif)}
body button,body input,body select,body textarea{font-family:inherit}
body:not([data-font-style="theme"]) .analog-number{font-family:inherit!important}
.control-path,.diag-log,code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace!important}

body[data-ui-theme="arcade-crt"][data-color-mode="light"] .tool{background:color-mix(in srgb,#fff 92%,var(--accent));border-color:rgba(var(--accent-rgb),.68);box-shadow:0 0 0 1px rgba(var(--accent-rgb),.22),0 8px 18px rgba(0,0,0,.08)}
body[data-ui-theme="arcade-crt"][data-color-mode="light"] .tool:after{opacity:.16;mix-blend-mode:multiply}
body[data-ui-theme="arcade-crt"][data-color-mode="light"] .settings-panel,body[data-ui-theme="arcade-crt"][data-color-mode="light"] .music-panel,body[data-ui-theme="arcade-crt"][data-color-mode="light"] .library-panel,body[data-ui-theme="arcade-crt"][data-color-mode="light"] .photo-panel,body[data-ui-theme="arcade-crt"][data-color-mode="light"] .upload-panel{background:var(--panel-solid)!important;color:var(--ui-text)}
body[data-ui-theme="high-contrast"][data-color-mode="light"] .tool{background:#fff;color:#080a0b;border-color:#080a0b}body[data-ui-theme="high-contrast"][data-color-mode="light"] .tool.primary{background:color-mix(in srgb,#fff 82%,var(--accent));border-color:var(--accent)}body[data-ui-theme="high-contrast"][data-color-mode="light"] .settings-panel,body[data-ui-theme="high-contrast"][data-color-mode="light"] .music-panel,body[data-ui-theme="high-contrast"][data-color-mode="light"] .library-panel,body[data-ui-theme="high-contrast"][data-color-mode="light"] .photo-panel,body[data-ui-theme="high-contrast"][data-color-mode="light"] .upload-panel{background:#fff!important;color:#080a0b!important;border-color:#080a0b!important}



/* v0.18.6 orthogonal surface-material system ------------------------------- */
/* Theme default intentionally adds no override. Frosted/Crystal/Solid can be
   layered over every registered layout without changing its geometry. */
body[data-ui-theme][data-surface-style="frosted"]{--pcga-surface-major:rgba(var(--panel-rgb),.68);--pcga-surface-card:rgba(var(--panel-rgb),.48);--pcga-surface-control:rgba(var(--panel-rgb),.42);--pcga-surface-line:rgba(var(--accent-rgb),.34);--pcga-surface-blur:22px;--pcga-surface-saturate:150%;--pcga-surface-shadow:0 16px 42px rgba(0,0,0,.26)}
body[data-ui-theme][data-color-mode="light"][data-surface-style="frosted"]{--pcga-surface-major:rgba(var(--panel-rgb),.72);--pcga-surface-card:rgba(var(--panel-rgb),.58);--pcga-surface-control:rgba(var(--panel-rgb),.52);--pcga-surface-line:rgba(var(--accent-rgb),.38);--pcga-surface-shadow:0 16px 42px rgba(26,45,58,.16)}
body[data-ui-theme][data-surface-style="crystal"]{--pcga-surface-major:rgba(var(--panel-rgb),.46);--pcga-surface-card:rgba(var(--panel-rgb),.30);--pcga-surface-control:rgba(var(--panel-rgb),.25);--pcga-surface-line:rgba(var(--accent-rgb),.42);--pcga-surface-blur:32px;--pcga-surface-saturate:175%;--pcga-surface-shadow:0 18px 48px rgba(0,0,0,.30)}
body[data-ui-theme][data-color-mode="light"][data-surface-style="crystal"]{--pcga-surface-major:rgba(var(--panel-rgb),.54);--pcga-surface-card:rgba(var(--panel-rgb),.38);--pcga-surface-control:rgba(var(--panel-rgb),.34);--pcga-surface-line:rgba(var(--accent-rgb),.44);--pcga-surface-shadow:0 18px 48px rgba(26,45,58,.18)}
body[data-ui-theme][data-surface-style="solid"]{--pcga-surface-major:var(--panel-solid);--pcga-surface-card:var(--panel-solid);--pcga-surface-control:var(--panel-solid);--pcga-surface-line:var(--line);--pcga-surface-blur:0px;--pcga-surface-saturate:100%;--pcga-surface-shadow:0 10px 30px rgba(0,0,0,.22)}
body[data-ui-theme][data-color-mode="light"][data-surface-style="solid"]{--pcga-surface-shadow:0 10px 28px rgba(26,45,58,.12)}
body[data-ui-theme][data-surface-style="frosted"] :is(.portal-clock,.system-strip,.settings-open,.settings-panel,.music-panel,.library-panel,.photo-panel,.video-player-panel,.upload-panel,.status-modal,.rip-modal,.now-playing-modal),body[data-ui-theme][data-surface-style="crystal"] :is(.portal-clock,.system-strip,.settings-open,.settings-panel,.music-panel,.library-panel,.photo-panel,.video-player-panel,.upload-panel,.status-modal,.rip-modal,.now-playing-modal),body[data-ui-theme][data-surface-style="solid"] :is(.portal-clock,.system-strip,.settings-open,.settings-panel,.music-panel,.library-panel,.photo-panel,.video-player-panel,.upload-panel,.status-modal,.rip-modal,.now-playing-modal){background:var(--pcga-surface-major)!important;border-color:var(--pcga-surface-line)!important;box-shadow:var(--pcga-surface-shadow),inset 0 1px 0 rgba(255,255,255,.12)!important;-webkit-backdrop-filter:blur(var(--pcga-surface-blur)) saturate(var(--pcga-surface-saturate));backdrop-filter:blur(var(--pcga-surface-blur)) saturate(var(--pcga-surface-saturate))}
body[data-ui-theme][data-surface-style="frosted"] :is(.tool,.settings-card,.control-stat,.control-service,.control-native-link,.library-item,.music-item,.audio-card,.audio-episode,.game-card,.review-block,.diag-card,.patch-drop,.bg-media-item),body[data-ui-theme][data-surface-style="crystal"] :is(.tool,.settings-card,.control-stat,.control-service,.control-native-link,.library-item,.music-item,.audio-card,.audio-episode,.game-card,.review-block,.diag-card,.patch-drop,.bg-media-item),body[data-ui-theme][data-surface-style="solid"] :is(.tool,.settings-card,.control-stat,.control-service,.control-native-link,.library-item,.music-item,.audio-card,.audio-episode,.game-card,.review-block,.diag-card,.patch-drop,.bg-media-item){background:var(--pcga-surface-card)!important;border-color:var(--pcga-surface-line)!important;box-shadow:0 9px 24px rgba(0,0,0,.16),inset 0 1px 0 rgba(255,255,255,.10)!important}
body[data-ui-theme][data-surface-style="frosted"] :is(.settings-head,.control-nav,.settings-actions,.library-head,.music-browser-head,.photo-head,.upload-head,.video-player-head),body[data-ui-theme][data-surface-style="crystal"] :is(.settings-head,.control-nav,.settings-actions,.library-head,.music-browser-head,.photo-head,.upload-head,.video-player-head),body[data-ui-theme][data-surface-style="solid"] :is(.settings-head,.control-nav,.settings-actions,.library-head,.music-browser-head,.photo-head,.upload-head,.video-player-head){background:var(--pcga-surface-major)!important;border-color:var(--pcga-surface-line)!important;-webkit-backdrop-filter:blur(var(--pcga-surface-blur)) saturate(var(--pcga-surface-saturate));backdrop-filter:blur(var(--pcga-surface-blur)) saturate(var(--pcga-surface-saturate))}
body[data-ui-theme][data-surface-style="frosted"] :is(.control-nav button,.settings-action,.control-button,.library-filter,.library-upload,.audio-source-tab,.settings-control select,.settings-control input[type="text"],.settings-control input[type="password"],.library-search input,.music-search input,.audio-search-row input,.audio-search-row select),body[data-ui-theme][data-surface-style="crystal"] :is(.control-nav button,.settings-action,.control-button,.library-filter,.library-upload,.audio-source-tab,.settings-control select,.settings-control input[type="text"],.settings-control input[type="password"],.library-search input,.music-search input,.audio-search-row input,.audio-search-row select),body[data-ui-theme][data-surface-style="solid"] :is(.control-nav button,.settings-action,.control-button,.library-filter,.library-upload,.audio-source-tab,.settings-control select,.settings-control input[type="text"],.settings-control input[type="password"],.library-search input,.music-search input,.audio-search-row input,.audio-search-row select){background:var(--pcga-surface-control)!important;border-color:var(--pcga-surface-line)!important;color:var(--ui-text)!important}
body[data-ui-theme][data-surface-style="frosted"] .tool,body[data-ui-theme][data-surface-style="crystal"] .tool{position:relative;overflow:hidden}
body[data-ui-theme][data-surface-style="frosted"] .tool:after,body[data-ui-theme][data-surface-style="crystal"] .tool:after{content:"";position:absolute;inset:0;z-index:-1;pointer-events:none;background:linear-gradient(145deg,rgba(255,255,255,.18),transparent 34%,rgba(var(--accent-rgb),.06) 78%,transparent);opacity:.72}
body[data-ui-theme][data-surface-style="crystal"] .tool:after{background:linear-gradient(138deg,rgba(255,255,255,.25),transparent 28%,rgba(var(--accent-rgb),.10) 68%,rgba(255,255,255,.05));opacity:.92}
body[data-ui-theme][data-surface-style="solid"] :is(.portal-clock,.system-strip,.settings-open,.settings-panel,.music-panel,.library-panel,.photo-panel,.video-player-panel,.upload-panel,.status-modal,.rip-modal,.now-playing-modal,.settings-head,.control-nav,.settings-actions){-webkit-backdrop-filter:none!important;backdrop-filter:none!important}
body[data-ui-theme="high-contrast"][data-surface-style="frosted"] :is(.tool,.settings-card,.control-stat,.control-service,.control-native-link),body[data-ui-theme="high-contrast"][data-surface-style="crystal"] :is(.tool,.settings-card,.control-stat,.control-service,.control-native-link){border-width:2px!important}



/* v0.18.10 optional secondary home-media surface --------------------------- */
.shell{position:relative;z-index:10;transition:transform .46s cubic-bezier(.22,.75,.18,1),opacity .34s ease}
.home-media-surface{position:fixed;inset:0;z-index:9;display:flex;flex-direction:column;min-height:100vh;padding:clamp(30px,5vh,62px) var(--safe) clamp(28px,4vh,54px);transform:translateY(102vh);opacity:0;pointer-events:none;transition:transform .46s cubic-bezier(.22,.75,.18,1),opacity .34s ease;background:linear-gradient(180deg,rgba(var(--bg-deep-rgb),.10),rgba(var(--bg-deep-rgb),.30));overflow:hidden}
body.media-surface-open .shell{transform:translateY(-104vh);opacity:.10;pointer-events:none}
body.media-surface-open .home-media-surface{z-index:14;transform:translateY(0);opacity:1;pointer-events:auto}
.home-media-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;flex:0 0 auto;margin-bottom:clamp(18px,2.8vh,34px)}
.home-media-title{font-size:clamp(34px,4vw,64px);font-weight:1000;letter-spacing:-.045em;line-height:.95}.home-media-sub{margin-top:8px;color:var(--muted);font-size:.72em}.home-media-return{display:flex;cursor:pointer;align-items:center;gap:10px;color:var(--muted);font-size:.70em;font-weight:900;white-space:nowrap}.home-media-return b{display:grid;place-items:center;width:42px;height:42px;border:1px solid var(--line);border-radius:min(var(--ui-radius),14px);background:var(--surface-mid);color:var(--text);font-size:22px}
.home-media-body{flex:1 1 auto;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding:3px 5px 24px;scrollbar-width:thin}.home-media-section{margin-bottom:clamp(20px,3vh,34px)}.home-media-section:last-child{margin-bottom:0}.home-media-section-head{display:flex;align-items:baseline;justify-content:space-between;gap:14px;margin-bottom:10px}.home-media-section-head h2{font-size:clamp(22px,2vw,31px);margin:0;font-weight:950}.home-media-section-head span{font-size:.58em;color:var(--muted)}
.home-media-row{display:flex;gap:clamp(12px,1.4vw,20px);overflow-x:auto;overflow-y:visible;padding:7px 7px 16px;scroll-snap-type:x proximity;scrollbar-width:none}.home-media-row::-webkit-scrollbar{display:none}.home-media-entry{position:relative;flex:0 0 clamp(210px,18vw,320px);min-width:0;scroll-snap-align:start}.home-media-card{position:relative;width:100%;min-width:0;padding:0;border:1px solid var(--line);border-radius:var(--ui-radius);overflow:hidden;background:var(--panel-surface);color:var(--text);text-align:left;box-shadow:0 14px 34px rgba(0,0,0,.20)}.home-media-source{display:inline-block;margin:7px 10px 0;color:var(--muted);font-size:.48em;text-transform:uppercase;letter-spacing:.07em;text-decoration:none}.home-media-source:hover,.home-media-source:focus{color:var(--text);text-decoration:underline}.home-media-card .pcga-art-stack{width:100%;aspect-ratio:16/10}.home-media-card .pcga-fallback-mark{font-size:clamp(22px,2.5vw,42px)}.home-media-copy{display:block;padding:11px 13px 13px}.home-media-name{display:block;font-size:.76em;font-weight:950;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.home-media-meta{display:block;margin-top:3px;color:var(--muted);font-size:.57em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.home-media-foot{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:8px;color:var(--muted);font-size:.52em;text-transform:uppercase;letter-spacing:.06em}.home-media-card .library-resume{margin:0 13px 12px}.home-media-empty{padding:26px;border:1px dashed var(--line);border-radius:var(--ui-radius);color:var(--muted);text-align:center;background:var(--surface-low)}.home-media-loading{display:grid;place-items:center;min-height:38vh;color:var(--muted)}
body[data-surface-style="frosted"] .home-media-card{background:rgba(var(--panel-rgb),.58);backdrop-filter:blur(22px) saturate(135%)}body[data-surface-style="crystal"] .home-media-card{background:rgba(var(--panel-rgb),.34);backdrop-filter:blur(30px) saturate(150%)}body[data-surface-style="solid"] .home-media-card{background:var(--panel-solid);backdrop-filter:none}
body[data-ui-theme="wii-aero"] .home-media-card{border-radius:clamp(20px,var(--ui-radius),30px);box-shadow:0 12px 28px rgba(26,92,116,.18),inset 0 1px 0 rgba(255,255,255,.34)}body[data-ui-theme="arcade-crt"] .home-media-card{border-radius:min(var(--ui-radius),8px)}body[data-ui-theme="desk-compact"] .home-media-card{flex-basis:clamp(180px,15vw,250px);border-radius:min(var(--ui-radius),13px)}body[data-ui-theme="high-contrast"] .home-media-card{border-width:2px;box-shadow:none}
@media(max-width:720px){.home-media-surface{padding-left:18px;padding-right:18px}.home-media-head{align-items:flex-start;flex-direction:column;gap:10px}.home-media-return{font-size:.62em}.home-media-card{flex-basis:min(72vw,300px)}}
@media(prefers-reduced-motion:reduce){.shell,.home-media-surface{transition:none!important}}

/* v0.18.10 Jellyfin theater isolation --------------------------------------- */
/* Video playback is intentionally independent of portal theme/surface opacity.
   The theater overlay must completely hide the launcher, including Aero/Crystal. */
body[data-ui-theme] .video-player-modal{background:#000!important;-webkit-backdrop-filter:none!important;backdrop-filter:none!important}
body[data-ui-theme] .video-player-panel,body[data-ui-theme][data-surface-style] .video-player-panel{background:#050505!important;border-color:transparent!important;box-shadow:none!important;-webkit-backdrop-filter:none!important;backdrop-filter:none!important}
body[data-ui-theme] .video-player-panel:fullscreen,body[data-ui-theme] .video-player-panel:-webkit-full-screen{background:#000!important}

/* Informational HTTPS banner stays above the home shell but below open modal workflows. */
.secure-context-banner{z-index:36}

.pc-game-sessions-browser{z-index:1320}.pc-game-session-panel{width:min(860px,94vw);max-height:min(760px,88vh)}.pc-game-session-list{overflow:auto;padding:0 18px 18px;display:grid;gap:10px}.pc-game-session-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;align-items:center;padding:14px 16px;border:1px solid var(--line);background:rgba(255,255,255,.035);border-radius:min(var(--ui-radius),18px);transition:border-color .16s ease,background .16s ease,opacity .16s ease}.pc-game-session-row.is-ending{border-color:rgba(245,184,78,.62);background:rgba(245,184,78,.08)}.pc-game-session-title{font-weight:950}.pc-game-session-meta{color:var(--muted);font-size:.58em;margin-top:4px;overflow-wrap:anywhere}.pc-game-session-row.is-ending .pc-game-session-meta{color:var(--text)}.pc-game-session-actions{display:flex;gap:8px;align-items:center}.pc-game-session-resume{min-height:46px;padding:0 14px;border:1px solid var(--accent);background:var(--accent-soft);color:var(--text);font-weight:900;border-radius:min(var(--ui-radius),14px);display:inline-flex;align-items:center;justify-content:center;gap:9px}.pc-game-session-danger{min-height:46px;padding:0 14px;border:1px solid rgba(231,122,102,.55);background:rgba(180,65,52,.17);color:var(--text);font-weight:900;border-radius:min(var(--ui-radius),14px);display:inline-flex;align-items:center;justify-content:center;gap:9px}.pc-game-session-danger.is-ending,.pc-game-stream-actions button.is-ending{cursor:wait;opacity:.84}.pc-game-session-danger:disabled,.pc-game-stream-actions button:disabled{cursor:wait}.pcga-session-spinner{display:inline-block;width:16px;height:16px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:pcga-session-spin .75s linear infinite;flex:0 0 auto}.pc-game-session-empty{padding:30px;text-align:center;color:var(--muted)}#pc-game-stream.is-ending .pc-game-stream-frame-wrap.active{opacity:.58;transition:opacity .18s ease}#pc-game-stream.is-ending .pc-game-stream-bar{border-bottom-color:rgba(245,184,78,.55)}@keyframes pcga-session-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.pcga-session-spinner{animation:none;border-right-color:currentColor;border-top-color:transparent}}@media(max-width:700px){.pc-game-session-row{grid-template-columns:1fr}.pc-game-session-actions{justify-content:flex-start}}


/* v0.18.97 adaptive TV / desktop / ultrawide / tablet / mobile geometry -----------------
   Themes continue to own color/material styling. Device layout owns density,
   navigation geometry, modal sizing and touch/mouse affordances. */
body[data-device-layout="desktop"]{--safe:clamp(22px,3vw,52px);font-size:clamp(15px,.92vw,18px)}
body[data-device-layout="desktop"] .shell{justify-content:flex-start;max-width:1720px;margin:0 auto;padding:24px var(--safe) 34px}
body[data-device-layout="desktop"] .header{margin-bottom:14px;min-height:54px}
body[data-device-layout="desktop"] .launcher-wrap{overflow:visible;padding:4px 0 12px}
body[data-device-layout="desktop"] .launcher{display:grid!important;grid-template-columns:repeat(auto-fit,minmax(255px,1fr))!important;gap:14px;overflow:visible;padding:4px;scroll-snap-type:none}
body[data-device-layout="desktop"] .tool{flex:none!important;min-width:0;min-height:148px;padding:18px 19px;border-radius:min(var(--ui-radius),20px)}
body[data-device-layout="desktop"] .tool-head{gap:13px}body[data-device-layout="desktop"] .tool-icon{width:44px;height:44px}body[data-device-layout="desktop"] .tool-icon svg{width:40px;height:40px}body[data-device-layout="desktop"] .tool-title{font-size:clamp(22px,1.55vw,29px)}body[data-device-layout="desktop"] .tool-sub{font-size:.78em;margin-top:6px}
body[data-device-layout="desktop"] .tv-focus:focus,body[data-device-layout="desktop"] .tv-focus:focus-visible{transform:none!important;box-shadow:0 0 0 3px var(--focus-ring),0 12px 30px rgba(0,0,0,.28)!important}
@media(hover:hover){body[data-device-layout="desktop"] .tool:hover{transform:translateY(-2px);border-color:rgba(var(--accent-rgb),.55);box-shadow:0 12px 30px rgba(0,0,0,.25)}}
body[data-device-layout="desktop"] :is(.music-panel,.library-panel,.photo-panel,.settings-panel,.upload-panel){width:min(1240px,calc(100vw - 48px));max-height:calc(100vh - 48px)}
body[data-device-layout="desktop"] .review-panel{width:min(1480px,calc(100vw - 48px))}
body[data-device-layout="desktop"] .global-search-panel{width:min(1120px,calc(100vw - 48px))}
body[data-device-layout="desktop"] .library-grid,body[data-device-layout="desktop"] .photo-grid{grid-template-columns:repeat(auto-fill,minmax(175px,1fr))}
body[data-device-layout="desktop"] .audio-grid{grid-template-columns:repeat(auto-fill,minmax(165px,1fr))}
body[data-device-layout="desktop"] .global-search-grid{grid-template-columns:repeat(auto-fill,minmax(250px,1fr))}
body[data-device-layout="desktop"] .settings-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
body[data-device-layout="desktop"] .now-playing-modal{right:24px;top:24px;width:min(430px,calc(100vw - 48px));grid-template-columns:72px minmax(0,1fr);gap:12px;padding:13px 14px}body[data-device-layout="desktop"] .now-playing-modal .cover,body[data-device-layout="desktop"] .now-playing-modal .cover-placeholder{width:72px;height:72px}body[data-device-layout="desktop"] .now-playing-modal .ctl{width:44px;height:44px}body[data-device-layout="desktop"] .now-playing-modal .ctl.main{width:50px;height:50px}
body[data-device-layout="desktop"] .home-media-surface{padding:28px var(--safe) 34px}body[data-device-layout="desktop"] .home-media-entry{flex-basis:clamp(190px,16vw,270px)}

/* Ultrawide desktops use the extra horizontal space without turning cards or text into over-stretched rows. */
body[data-device-layout="ultrawide"]{--safe:clamp(24px,2vw,56px);font-size:clamp(15px,.78vw,18px)}
body[data-device-layout="ultrawide"] .shell{justify-content:flex-start;width:min(2520px,calc(100vw - var(--safe) - var(--safe)));max-width:none;margin:0 auto;padding:22px 0 34px}
body[data-device-layout="ultrawide"] .header{margin-bottom:14px;min-height:54px}
body[data-device-layout="ultrawide"] .header-hint{max-width:48ch}
body[data-device-layout="ultrawide"] .launcher-wrap{overflow:visible;padding:4px 0 12px}
body[data-device-layout="ultrawide"] .launcher{display:grid!important;grid-template-columns:repeat(6,minmax(230px,1fr))!important;gap:14px;overflow:visible;padding:4px;scroll-snap-type:none}
body[data-device-layout="ultrawide"] .tool{flex:none!important;min-width:0;min-height:146px;padding:17px 18px;border-radius:min(var(--ui-radius),20px)}
body[data-device-layout="ultrawide"] .tool-head{gap:12px}body[data-device-layout="ultrawide"] .tool-icon{width:43px;height:43px}body[data-device-layout="ultrawide"] .tool-icon svg{width:39px;height:39px}body[data-device-layout="ultrawide"] .tool-title{font-size:clamp(21px,1.08vw,29px)}body[data-device-layout="ultrawide"] .tool-sub{font-size:.76em;margin-top:6px;max-width:46ch}
body[data-device-layout="ultrawide"] .tv-focus:focus,body[data-device-layout="ultrawide"] .tv-focus:focus-visible{transform:none!important;box-shadow:0 0 0 3px var(--focus-ring),0 12px 30px rgba(0,0,0,.28)!important}
@media(hover:hover){body[data-device-layout="ultrawide"] .tool:hover{transform:translateY(-2px);border-color:rgba(var(--accent-rgb),.55);box-shadow:0 12px 30px rgba(0,0,0,.25)}}
body[data-device-layout="ultrawide"] :is(.music-panel,.library-panel,.photo-panel,.settings-panel,.upload-panel){width:min(1740px,calc(100vw - 72px));max-height:calc(100vh - 48px)}
body[data-device-layout="ultrawide"] .review-panel{width:min(2140px,calc(100vw - 72px));max-height:calc(100vh - 48px)}
body[data-device-layout="ultrawide"] .global-search-panel{width:min(1680px,calc(100vw - 72px));max-height:calc(100vh - 48px)}
body[data-device-layout="ultrawide"] .pc-game-session-panel{width:min(1180px,calc(100vw - 72px))}
body[data-device-layout="ultrawide"] .library-grid,body[data-device-layout="ultrawide"] .photo-grid{grid-template-columns:repeat(auto-fill,minmax(185px,1fr))}
body[data-device-layout="ultrawide"] .audio-grid{grid-template-columns:repeat(auto-fill,minmax(175px,1fr))}
body[data-device-layout="ultrawide"] .global-search-grid{grid-template-columns:repeat(auto-fill,minmax(270px,1fr))}
body[data-device-layout="ultrawide"] .settings-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
body[data-device-layout="ultrawide"] .music-list{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px 12px}
body[data-device-layout="ultrawide"] .music-item{min-width:0}
body[data-device-layout="ultrawide"] .now-playing-modal{right:28px;top:22px;width:min(470px,24vw);grid-template-columns:72px minmax(0,1fr);gap:12px;padding:13px 14px}body[data-device-layout="ultrawide"] .now-playing-modal .cover,body[data-device-layout="ultrawide"] .now-playing-modal .cover-placeholder{width:72px;height:72px}body[data-device-layout="ultrawide"] .now-playing-modal .ctl{width:44px;height:44px}body[data-device-layout="ultrawide"] .now-playing-modal .ctl.main{width:50px;height:50px}
body[data-device-layout="ultrawide"] .home-media-surface{padding:26px var(--safe) 34px}body[data-device-layout="ultrawide"] .home-media-entry{flex-basis:clamp(200px,12vw,285px)}
body[data-device-layout="ultrawide"] :is(.settings-help,.settings-note,.audio-detail p,.review-text){max-width:72ch}
@media(min-aspect-ratio:3/1) and (min-width:3000px){body[data-device-layout="ultrawide"] .shell{width:min(3360px,calc(100vw - var(--safe) - var(--safe)))}body[data-device-layout="ultrawide"] .launcher{grid-template-columns:repeat(8,minmax(230px,1fr))!important}body[data-device-layout="ultrawide"] :is(.music-panel,.library-panel,.photo-panel,.settings-panel,.upload-panel){width:min(2240px,calc(100vw - 96px))}body[data-device-layout="ultrawide"] .review-panel{width:min(2780px,calc(100vw - 96px))}body[data-device-layout="ultrawide"] .global-search-panel{width:min(2160px,calc(100vw - 96px))}body[data-device-layout="ultrawide"] .settings-grid{grid-template-columns:repeat(4,minmax(0,1fr))}body[data-device-layout="ultrawide"] .music-list{grid-template-columns:repeat(3,minmax(0,1fr))}}

body[data-device-layout="tablet"]{--safe:18px;font-size:17px}
body[data-device-layout="tablet"] .shell{justify-content:flex-start;padding:18px var(--safe) 28px}
body[data-device-layout="tablet"] .header{align-items:flex-start;gap:12px;margin-bottom:14px}body[data-device-layout="tablet"] .header-right{gap:9px;flex-wrap:wrap}
body[data-device-layout="tablet"] .system-strip{max-width:min(62vw,560px)}body[data-device-layout="tablet"] .settings-open{width:52px;height:52px}
body[data-device-layout="tablet"] .launcher-wrap{overflow:visible;padding:4px 0 12px}
body[data-device-layout="tablet"] .launcher{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:12px;overflow:visible;padding:4px;scroll-snap-type:none}
body[data-device-layout="tablet"] .tool{flex:none!important;min-width:0;min-height:148px;padding:18px;border-radius:min(var(--ui-radius),20px)}body[data-device-layout="tablet"] .tool-title{font-size:clamp(22px,3vw,30px)}body[data-device-layout="tablet"] .tool-icon{width:48px;height:48px}body[data-device-layout="tablet"] .tool-icon svg{width:44px;height:44px}
body[data-device-layout="tablet"] .tv-focus:focus,body[data-device-layout="tablet"] .tv-focus:focus-visible{transform:none!important;box-shadow:0 0 0 3px var(--focus-ring),0 10px 26px rgba(0,0,0,.30)!important}
body[data-device-layout="tablet"] :is(.music-browser,.library-browser,.photo-browser,.settings-modal){padding:12px}
body[data-device-layout="tablet"] :is(.music-panel,.library-panel,.photo-panel,.settings-panel,.upload-panel){width:100%;max-height:calc(100vh - 24px)}
body[data-device-layout="tablet"] .global-search-panel,body[data-device-layout="tablet"] .review-panel{width:100%}
body[data-device-layout="tablet"] .settings-grid{grid-template-columns:1fr}
body[data-device-layout="tablet"] .library-grid,body[data-device-layout="tablet"] .photo-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
body[data-device-layout="tablet"] .audio-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
body[data-device-layout="tablet"] .global-search-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
body[data-device-layout="tablet"] .control-nav{overflow-x:auto;scrollbar-width:thin;justify-content:flex-start;flex-wrap:nowrap}
body[data-device-layout="tablet"] .control-nav button{flex:0 0 auto}
body[data-device-layout="tablet"] .now-playing-modal{right:14px;top:14px;width:min(520px,calc(100vw - 28px))}
body[data-device-layout="tablet"] .home-media-surface{padding:22px 18px 28px}body[data-device-layout="tablet"] .home-media-entry{flex-basis:min(36vw,300px)}

body[data-device-layout="mobile"]{--safe:12px;font-size:16px}
body[data-device-layout="mobile"] .shell{justify-content:flex-start;min-height:100dvh;padding:max(12px,env(safe-area-inset-top)) max(var(--safe),env(safe-area-inset-right)) max(22px,env(safe-area-inset-bottom)) max(var(--safe),env(safe-area-inset-left))}
body[data-device-layout="mobile"] .header{align-items:stretch;flex-direction:column;gap:9px;margin-bottom:10px}body[data-device-layout="mobile"] .header-right{width:100%;display:grid;grid-template-columns:minmax(0,1fr) 48px 48px;gap:8px;align-items:stretch}body[data-device-layout="mobile"] .system-strip{width:100%;min-width:0;max-width:none;min-height:48px}body[data-device-layout="mobile"] .system-strip-meta{display:none}body[data-device-layout="mobile"] .settings-open{width:48px;height:48px;font-size:21px}
body[data-device-layout="mobile"] .launcher-wrap{overflow:visible;padding:2px 0 8px}
body[data-device-layout="mobile"] .launcher{display:grid!important;grid-template-columns:1fr!important;gap:9px;overflow:visible;padding:2px;scroll-snap-type:none}
body[data-device-layout="mobile"] .tool{flex:none!important;min-width:0;min-height:104px;padding:14px 15px;border-radius:min(var(--ui-radius),18px)}body[data-device-layout="mobile"] .tool-head{gap:12px}body[data-device-layout="mobile"] .tool-icon{width:42px;height:42px}body[data-device-layout="mobile"] .tool-icon svg{width:38px;height:38px}body[data-device-layout="mobile"] .tool-title{font-size:21px}body[data-device-layout="mobile"] .tool-sub{font-size:.72em;margin-top:4px}body[data-device-layout="mobile"] .tool-foot{font-size:.58em;margin-top:9px}
body[data-device-layout="mobile"] .footer{font-size:.60em;margin-top:10px;gap:8px}body[data-device-layout="mobile"] .footer span:last-child{display:none}
body[data-device-layout="mobile"] .tv-focus:focus,body[data-device-layout="mobile"] .tv-focus:focus-visible{transform:none!important;box-shadow:0 0 0 3px var(--focus-ring)!important}
body[data-device-layout="mobile"] :is(.music-browser,.library-browser,.photo-browser,.settings-modal){padding:0;place-items:stretch;background:var(--panel-solid)}
body[data-device-layout="mobile"] :is(.music-panel,.library-panel,.photo-panel,.settings-panel,.upload-panel){width:100%;height:100dvh;max-height:none;border-radius:0!important;border-left:0!important;border-right:0!important}
body[data-device-layout="mobile"] .global-search-panel,body[data-device-layout="mobile"] .review-panel,body[data-device-layout="mobile"] .pc-game-session-panel{width:100%;max-height:none;height:100dvh;border-radius:0!important}
body[data-device-layout="mobile"] :is(.library-head,.music-browser-head,.photo-head,.upload-head,.global-search-head){padding:14px 14px 10px;gap:8px}body[data-device-layout="mobile"] :is(.library-title,.music-browser-title,.photo-title,.upload-title){font-size:26px}body[data-device-layout="mobile"] :is(.library-close,.music-close,.photo-close,.settings-close){width:46px;height:46px;min-width:46px}
body[data-device-layout="mobile"] :is(.library-search,.music-search,.photo-search,.global-search-form){padding-left:12px;padding-right:12px;display:grid;grid-template-columns:1fr;gap:8px}body[data-device-layout="mobile"] :is(.library-search button,.music-search button,.photo-search button,.global-search-form button){width:100%;height:48px}body[data-device-layout="mobile"] :is(.library-search input,.music-search input,.photo-search input,.global-search-form input){height:50px}
body[data-device-layout="mobile"] .library-filters{padding:0 12px 10px}body[data-device-layout="mobile"] .library-grid,body[data-device-layout="mobile"] .photo-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;padding:0 10px 14px}body[data-device-layout="mobile"] .audio-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;padding:0 10px 14px}body[data-device-layout="mobile"] .audio-card{min-height:0}body[data-device-layout="mobile"] .audio-card-copy{padding:9px 9px 10px}body[data-device-layout="mobile"] .audio-card-title{font-size:.90em}body[data-device-layout="mobile"] .audio-card-meta{font-size:.68em}
body[data-device-layout="mobile"] .global-search-grid{grid-template-columns:1fr;gap:7px}body[data-device-layout="mobile"] .global-search-content{padding:0 10px 16px}body[data-device-layout="mobile"] .global-search-note{padding-left:12px;padding-right:12px}body[data-device-layout="mobile"] .global-search-card{grid-template-columns:54px minmax(0,1fr);min-height:70px}body[data-device-layout="mobile"] .global-search-card .pcga-art-stack,body[data-device-layout="mobile"] .global-search-card img{width:54px;height:54px}
body[data-device-layout="mobile"] .settings-head{padding:13px 12px 9px}body[data-device-layout="mobile"] .settings-title{font-size:25px}body[data-device-layout="mobile"] .settings-sub{font-size:.64em}body[data-device-layout="mobile"] .control-nav{min-height:52px;overflow-x:auto;flex-wrap:nowrap;justify-content:flex-start;scrollbar-width:none;padding-left:8px;padding-right:8px}body[data-device-layout="mobile"] .control-nav::-webkit-scrollbar{display:none}body[data-device-layout="mobile"] .control-nav button{flex:0 0 auto;min-height:42px;padding:0 12px}body[data-device-layout="mobile"] .settings-grid{grid-template-columns:1fr;padding:10px}body[data-device-layout="mobile"] .settings-card{padding:14px}body[data-device-layout="mobile"] .settings-row{flex-direction:column;align-items:stretch;gap:8px}body[data-device-layout="mobile"] .settings-control{width:100%}body[data-device-layout="mobile"] .settings-control :is(select,input[type="text"],input[type="password"],input[type="range"]){width:100%}body[data-device-layout="mobile"] .settings-actions{padding:10px;display:grid;grid-template-columns:1fr 1fr;gap:8px}body[data-device-layout="mobile"] .settings-action{min-width:0}
body[data-device-layout="mobile"] .review-layout{grid-template-columns:1fr}body[data-device-layout="mobile"] .review-queue{max-height:26vh;border-right:0;border-bottom:1px solid var(--line)}body[data-device-layout="mobile"] .review-detail{padding:12px}body[data-device-layout="mobile"] .review-form-grid,body[data-device-layout="mobile"] .review-preview{grid-template-columns:1fr}
body[data-device-layout="mobile"] .now-playing-modal{left:8px!important;right:8px!important;top:auto!important;bottom:calc(max(8px,env(safe-area-inset-bottom)) + var(--rip-overlay-height,0px))!important;width:auto!important;grid-template-columns:54px minmax(0,1fr);gap:9px;padding:9px 10px;border-radius:min(var(--ui-radius),16px)!important}body[data-device-layout="mobile"] .now-playing-modal .cover,body[data-device-layout="mobile"] .now-playing-modal .cover-placeholder{width:54px;height:54px}body[data-device-layout="mobile"] .now-playing-modal .track-title{font-size:18px}body[data-device-layout="mobile"] .now-playing-modal .controls{justify-content:space-between;gap:4px}body[data-device-layout="mobile"] .now-playing-modal .ctl{width:42px;height:42px}body[data-device-layout="mobile"] .now-playing-modal .ctl.main{width:46px;height:46px}body[data-device-layout="mobile"] .now-playing-modal .volume{display:none}
body[data-device-layout="mobile"] .home-media-surface{padding:16px 12px 22px}body[data-device-layout="mobile"] .home-media-head{align-items:flex-start;flex-direction:column;gap:8px;margin-bottom:14px}body[data-device-layout="mobile"] .home-media-title{font-size:32px}body[data-device-layout="mobile"] .home-media-entry{flex-basis:min(72vw,280px)}
body[data-device-layout="mobile"] .pc-game-stream-bar{padding:7px;gap:7px}body[data-device-layout="mobile"] .pc-game-stream-heading{flex-basis:100%}body[data-device-layout="mobile"] .pc-game-stream-tabs{order:3;flex-basis:100%}body[data-device-layout="mobile"] .pc-game-stream-actions{width:100%;overflow-x:auto;margin-left:0}body[data-device-layout="mobile"] .pc-game-stream-actions button{white-space:nowrap;flex:0 0 auto}
body[data-device-layout="mobile"] .video-player-options{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:stretch;overflow-y:auto;max-height:32vh}body[data-device-layout="mobile"] .video-option{min-width:0}body[data-device-layout="mobile"] .video-option select{width:100%;min-width:0}body[data-device-layout="mobile"] .video-controls{grid-template-columns:auto auto auto 1fr auto;gap:6px;padding:8px}body[data-device-layout="mobile"] .video-control-time:first-of-type,body[data-device-layout="mobile"] .video-volume,body[data-device-layout="mobile"] .video-fit-control{display:none}body[data-device-layout="mobile"] #video-seek{grid-column:1/-1;grid-row:2}

/* TV mode intentionally has no geometry override here: the pre-v0.18.97
   10-foot layout and each selected interface theme remain authoritative. */


/* v0.18.97 UI housekeeping -------------------------------------------------- */
/* Text-like Control Center inputs introduced by newer integrations should look
   like the rest of PCGA in every theme instead of falling back to browser UI. */
.settings-control :is(input[type="password"],input[type="url"],input[type="number"]){height:46px;min-width:0;max-width:100%;padding:0 12px;border:1px solid var(--line);background:rgba(255,255,255,.055);color:var(--ui-text);font:inherit;font-size:.72em}
body[data-color-mode="light"] .settings-control :is(input[type="password"],input[type="url"],input[type="number"]){background:rgba(255,255,255,.84);color:var(--ui-text)}
body[data-ui-theme="wii-aero"] .settings-control :is(input[type="password"],input[type="url"],input[type="number"]){color:var(--wii-ink);background:linear-gradient(#fff,color-mix(in srgb,#fff 88%,var(--accent)));border-color:var(--wii-line)}
body[data-ui-theme="wii-aero"][data-color-mode="dark"] .settings-control :is(input[type="password"],input[type="url"],input[type="number"]){color:var(--ui-text);background:color-mix(in srgb,var(--panel-color) 92%,var(--accent));border-color:rgba(var(--accent-rgb),.32)}
body[data-ui-theme][data-surface-style="frosted"] .settings-control :is(input[type="password"],input[type="url"],input[type="number"]),body[data-ui-theme][data-surface-style="crystal"] .settings-control :is(input[type="password"],input[type="url"],input[type="number"]),body[data-ui-theme][data-surface-style="solid"] .settings-control :is(input[type="password"],input[type="url"],input[type="number"]){background:var(--pcga-surface-control)!important;border-color:var(--pcga-surface-line)!important;color:var(--ui-text)!important}
/* Prevent long titles/URLs and action rows from forcing modal overflow. */
:is(.library-head,.music-browser-head,.photo-head,.upload-head,.global-search-head,.settings-head)>div:first-child{min-width:0}
:is(.library-title,.music-browser-title,.photo-title,.upload-title,.settings-title){overflow-wrap:anywhere}
.control-actions{min-width:0}.control-actions>*{max-width:100%}.control-path{max-width:100%}
/* Phone safe areas apply inside full-screen modal surfaces, not just the home shell. */
body[data-device-layout="mobile"] :is(.settings-control input[type="url"],.settings-control input[type="number"]){width:100%}
body[data-device-layout="mobile"] :is(.library-head,.music-browser-head,.photo-head,.upload-head,.global-search-head,.settings-head){padding-top:max(14px,env(safe-area-inset-top));padding-left:max(12px,env(safe-area-inset-left));padding-right:max(12px,env(safe-area-inset-right))}
body[data-device-layout="mobile"] :is(.library-grid,.photo-grid,.audio-grid,.music-list,.global-search-content,.review-detail,.pc-game-session-list){padding-bottom:max(16px,env(safe-area-inset-bottom))}
body[data-device-layout="mobile"] .settings-actions{padding-bottom:max(10px,env(safe-area-inset-bottom))}
body[data-device-layout="mobile"] .secure-context-banner{top:max(8px,env(safe-area-inset-top));left:max(8px,env(safe-area-inset-left));right:max(8px,env(safe-area-inset-right));width:auto;transform:none}
body[data-device-layout="mobile"] .status-modal{left:max(10px,env(safe-area-inset-left));right:max(10px,env(safe-area-inset-right));top:max(10px,env(safe-area-inset-top));max-width:none}
body[data-device-layout="mobile"] .rip-modal.show{left:max(3vw,env(safe-area-inset-left));right:max(3vw,env(safe-area-inset-right));bottom:max(10px,env(safe-area-inset-bottom));width:auto}
/* The controller/keyboard selected state must remain visually obvious even in
   themes that suppress the browser's normal focus outline. */
.pcga-nav-selected:not(:focus){outline:2px solid color-mix(in srgb,var(--focus-ring) 68%,transparent);outline-offset:2px}


/* v0.19.10 store login: readable contained dialog, with the portal visible behind it. */
#store-auth-modal.store-auth-overlay{z-index:82;place-items:center;padding:clamp(16px,4vh,48px) clamp(14px,4vw,48px);background:rgba(5,5,7,.42);backdrop-filter:blur(4px)}
#store-auth-modal .store-auth-panel{width:min(700px,100%);height:auto;max-height:min(82dvh,780px);display:flex;flex-direction:column;overflow:hidden;min-width:0;box-shadow:0 24px 72px rgba(0,0,0,.55)}
#store-auth-modal .store-auth-head{flex:none;padding:20px 24px 15px}
#store-auth-modal .store-auth-eyebrow{font-size:.58em;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-weight:800;margin-bottom:5px}
#store-auth-modal .store-auth-content{padding:20px 24px 14px;overflow-y:auto;min-height:0;display:grid;gap:14px}
#store-auth-modal .store-auth-content .settings-note{font-size:.68em;line-height:1.55;margin:0;overflow-wrap:anywhere}
#store-auth-modal .store-auth-progress{padding:12px 14px;border:1px solid var(--line);background:var(--accent-soft);font-size:.72em;font-weight:800;overflow-wrap:anywhere}
#store-auth-modal .store-auth-progress:empty{display:none}
#store-auth-modal .store-auth-progress[data-phase="ready"]{display:none}
#store-auth-modal .store-auth-error{padding:12px 14px;border:1px solid var(--line);background:rgba(180,65,65,.17);font-size:.68em;overflow-wrap:anywhere}
#store-auth-modal [hidden]{display:none!important}
#store-auth-modal #store-auth-code{display:block;width:100%;min-width:0;box-sizing:border-box;min-height:46px;margin:8px 0 10px;padding:9px 12px;border:1px solid var(--line);background:rgba(255,255,255,.055);color:var(--ui-text);font:inherit;font-size:.75em}
#store-auth-modal .store-auth-link-row{margin:0 0 15px;flex-wrap:wrap}
#store-auth-modal .store-auth-link-row a{max-width:100%;white-space:normal;overflow-wrap:anywhere}
#store-auth-modal .store-auth-footer{display:flex;flex-wrap:wrap;align-items:center;gap:9px;padding:16px 24px 20px;border-top:1px solid var(--line);background:var(--panel-solid)}
#store-auth-modal .store-auth-footer .control-button{min-height:44px;white-space:normal}
#store-auth-modal .store-auth-footer [data-store-auth-submit]{margin-left:auto}
#store-auth-modal .store-auth-keyhint{font-size:.78em;opacity:.65;margin-left:5px}
@media(max-width:720px){
  body[data-device-layout="mobile"] #store-auth-modal.store-auth-overlay{padding:max(12px,env(safe-area-inset-top)) max(12px,env(safe-area-inset-right)) max(12px,env(safe-area-inset-bottom)) max(12px,env(safe-area-inset-left));place-items:center;background:rgba(5,5,7,.42)}
  body[data-device-layout="mobile"] #store-auth-modal .store-auth-panel{width:100%;height:auto;max-height:calc(100dvh - 32px);border:1px solid var(--line)!important;border-radius:min(var(--ui-radius),20px)!important}
  #store-auth-modal .store-auth-head{padding:14px 16px 10px}
  #store-auth-modal .store-auth-content{padding:14px 16px 12px}
  #store-auth-modal .store-auth-footer{padding:12px 16px max(14px,env(safe-area-inset-bottom));gap:8px}
  #store-auth-modal .store-auth-footer .control-button{flex:1 1 auto}
  #store-auth-modal .store-auth-footer [data-store-auth-submit]{flex-basis:100%;order:-1}
}
@media(max-height:520px){#store-auth-modal .store-auth-panel{max-height:calc(100dvh - 24px)}#store-auth-modal .store-auth-head{padding-top:10px;padding-bottom:8px}#store-auth-modal .store-auth-content{padding-top:10px;padding-bottom:8px}}


</style>
</head>
<body data-bg-pattern="ambient" data-ui-theme="classic" data-color-mode="dark" data-layout-mode="auto" data-device-layout="tv">
<div id="secure-context-banner" class="secure-context-banner" role="status"><div class="secure-context-copy"><strong>Secure browser context required for PC game streaming</strong><span>Trust the PCGA Local Appliance CA once on this client, then use the HTTPS portal. This enables WebCodecs, controllers, and keyboard capture.</span></div><div class="secure-context-actions"><a class="tv-focus" href="/pcga-ca.crt" download="pcga-local-ca.crt">Download PCGA CA</a><a id="secure-portal-link" class="tv-focus" href="#">Open secure portal</a></div></div>
<div id="background-layer-ambient" class="background-layer background-layer-ambient" aria-hidden="true"></div>
<div id="background-layer-pattern" class="background-layer background-layer-pattern" aria-hidden="true"></div>
<video id="background-video" class="background-video" muted loop playsinline preload="metadata" aria-hidden="true"></video>
<img id="background-photo" class="background-photo" alt="" aria-hidden="true">
<div class="film-grain" aria-hidden="true"></div>
<div id="status-modal" class="status-modal" role="status" aria-live="polite" aria-atomic="true"><div class="status-row"><span class="status-icon"></span><div><div id="status-title" class="status-title">System ready</div><div id="status-body" class="status-body">Waiting for changes.</div></div></div></div>
<audio id="pcga-audio" preload="metadata"></audio>
<aside id="music-modal" class="now-playing-modal" aria-label="Audio now playing"></aside>
<section id="music-browser" class="music-browser" role="dialog" aria-modal="true" aria-label="PCGA audio library"><div id="music-panel" class="music-panel"></div></section>
<section id="library-browser" class="library-browser" role="dialog" aria-modal="true" aria-label="Jellyfin library"><div id="library-panel" class="library-panel"></div></section>
<section id="global-search-modal" class="library-browser" role="dialog" aria-modal="true" aria-label="Global search"><div class="library-panel global-search-panel"><div class="global-search-head"><div><div class="library-title">Global Search</div><div class="library-sub">Fast fuzzy search across local PCGA libraries</div></div><button class="library-close tv-focus" data-global-search-close type="button" aria-label="Close global search">×</button></div><form id="global-search-form" class="global-search-form"><input id="global-search-input" class="tv-focus" autocomplete="off" placeholder="Search movies, music, games, photos, audiobooks…"><button class="tv-focus" type="submit">Search</button></form><div class="global-search-note">Local and cached catalogs return first. Public-provider discovery stays inside Podcasts and Audiobooks so a slow internet service cannot block this search.</div><div id="global-search-content" class="global-search-content"><div class="global-search-empty">Type a title, artist, game, filename, author, or approximate spelling.</div></div></div></section>
<section id="game-browser" class="library-browser" role="dialog" aria-modal="true" aria-label="Console game library"><div id="game-panel" class="library-panel"></div></section>
<section id="steam-library-modal" class="library-browser" role="dialog" aria-modal="true" aria-label="Installed Steam games"><div class="library-panel"><div class="library-head"><div><div class="library-title">Installed Steam games</div><div class="library-sub">Native Steam · stream using Steam Link</div></div><button class="library-close tv-focus" data-steam-library-close type="button" aria-label="Close Steam library">×</button></div><div id="steam-native-games" class="library-grid"><div class="library-empty">Checking installed games…</div></div></div></section><section id="pc-game-browser" class="library-browser" role="dialog" aria-modal="true" aria-label="PC game library"><div id="pc-game-panel" class="library-panel"></div></section><section id="store-auth-modal" class="library-browser store-auth-overlay" role="dialog" aria-modal="true" aria-labelledby="store-auth-title" aria-describedby="store-auth-detail"><div class="library-panel store-auth-panel"><div class="library-head store-auth-head"><div><div class="store-auth-eyebrow">PCGA · Store accounts</div><div id="store-auth-title" class="library-title">Connect store account</div><div id="store-auth-sub" class="library-sub">Connect securely without leaving PCGA.</div></div><button class="library-close tv-focus" data-store-auth-close type="button" aria-label="Back to store accounts">×</button></div><div class="store-auth-content"><div id="store-auth-progress" class="store-auth-progress" role="status" aria-live="polite">Checking store backend readiness…</div><div id="store-auth-detail" class="settings-note">You can return to PCGA at any time while setup runs.</div><div id="store-auth-fields" hidden><div class="control-actions store-auth-link-row"><a id="store-auth-link" class="control-button primary tv-focus" href="#" target="_blank" rel="noopener noreferrer" hidden>Open provider login page ↗</a></div><label class="settings-label" for="store-auth-code">One-time authorization code</label><input id="store-auth-code" class="tv-focus" type="text" inputmode="text" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Paste the code returned by the store"><div class="settings-note store-auth-security">Sign in on the store's own site. PCGA does not request your store password or save the one-time code in appliance settings.</div></div><div id="store-auth-error" class="store-auth-error" role="alert" hidden></div></div><div class="store-auth-footer"><button class="control-button tv-focus" data-store-auth-close type="button">Back to accounts <span class="store-auth-keyhint">Esc</span></button><button class="control-button tv-focus" data-store-auth-home type="button">Back to PCGA</button><button class="control-button primary tv-focus" data-store-auth-submit type="button" hidden disabled>Finish connection</button></div></div></section>
<section id="store-install-modal" class="settings-modal" role="dialog" aria-modal="true" aria-label="Install store game"><div class="settings-panel store-install-panel"><div class="settings-head"><div><div class="settings-title" id="store-install-provider-heading">Install store game</div><div id="store-install-sub" class="settings-sub">PCGA manages the destination and download.</div></div><button class="settings-close tv-focus" data-store-install-close type="button" aria-label="Close install dialog">×</button></div><div class="store-install-body"><div id="store-install-title" class="store-install-name">Checking game…</div><div id="store-install-detail" class="settings-note" role="status" aria-live="polite">Verifying ownership, storage and download queue…</div><div id="store-install-warning" class="settings-note">PCGA downloads this game to its managed game library. Playing it through Wolf/Moonlight will be integrated in a later milestone.</div></div><div class="settings-actions"><button class="settings-action tv-focus" data-store-install-close type="button">Back</button><button id="store-install-confirm" class="settings-action primary tv-focus" data-store-install-confirm type="button" disabled>Checking…</button></div></div></section>
<section id="store-maintain-modal" class="settings-modal" role="dialog" aria-modal="true" aria-label="Store game maintenance"><div class="settings-panel store-install-panel"><div class="settings-head"><div><div class="settings-title" id="store-maintain-heading">Game maintenance</div><div id="store-maintain-sub" class="settings-sub">Epic / GOG</div></div><button type="button" class="settings-close tv-focus" data-store-maintain-close aria-label="Close maintenance dialog">×</button></div><div class="store-install-body"><div id="store-maintain-title" class="store-install-name">Checking game…</div><div id="store-maintain-detail" class="settings-note" role="status" aria-live="polite">Checking managed installation and game sessions…</div><div id="store-maintain-warning" class="settings-note">Saved games and Wine/Proton prefixes are preserved. Update and Verify may download replacement game files.</div></div><div class="settings-actions"><button class="settings-action tv-focus" type="button" data-store-maintain-close>Back</button><button id="store-maintain-confirm" class="settings-action primary tv-focus" type="button" data-store-maintain-confirm disabled>Checking…</button></div></div></section>
<section id="store-jobs-modal" class="library-browser" role="dialog" aria-modal="true" aria-label="PC store downloads"><div class="library-panel"><div class="library-head"><div><div class="library-title">Store Downloads & Maintenance</div><div id="store-jobs-sub" class="library-sub">Persistent PCGA game lifecycle queue</div></div><div class="library-head-actions"><button class="control-button tv-focus" data-store-jobs-refresh type="button">Refresh</button><button class="library-close tv-focus" data-store-jobs-close type="button" aria-label="Close store downloads">×</button></div></div><div class="store-jobs-toolbar" aria-label="Download filters"><div class="store-jobs-tabs" role="group" aria-label="Download status"><button type="button" class="control-button tv-focus selected" data-store-job-filter="all" aria-pressed="true">All</button><button type="button" class="control-button tv-focus" data-store-job-filter="active" aria-pressed="false">In progress</button><button type="button" class="control-button tv-focus" data-store-job-filter="completed" aria-pressed="false">Completed</button><button type="button" class="control-button tv-focus" data-store-job-filter="attention" aria-pressed="false">Needs attention</button></div><input type="search" id="store-jobs-search" class="tv-focus" placeholder="Find a game job…" aria-label="Search downloads" autocomplete="off"><button class="control-button primary tv-focus" data-store-jobs-library type="button">Browse Store Library</button></div><div id="store-jobs-summary" class="store-job-summary" role="status" aria-live="polite">Loading queued downloads…</div><div class="store-jobs-guidance">Install, Update, Verify and Uninstall run independently of the browser. Epic and GOG each have one managed job lane; Amazon is not yet supported.</div><div id="store-jobs-list" class="store-job-list"><div class="library-empty">Loading queued downloads…</div></div></div></section>
<section id="store-compat-modal" class="settings-modal" role="dialog" aria-modal="true" aria-label="Game compatibility settings"><div class="settings-panel store-compat-panel"><div class="settings-head"><div><div class="settings-title">Game compatibility</div><div id="store-compat-title" class="settings-sub">Epic / GOG game</div></div><button class="settings-close tv-focus" data-store-compat-close type="button" aria-label="Back to games">×</button></div><div class="store-compat-fields"><label class="store-compat-field">Runner<select id="store-compat-mode" class="tv-focus"><option value="auto">Automatic</option><option value="umu">UMU / Proton</option><option value="wine">Wine (legacy)</option></select></label><label class="store-compat-field">Proton version<select id="store-compat-proton" class="tv-focus"><option value="UMU-Proton">UMU-Proton</option><option value="GE-Proton">GE-Proton</option></select></label><label class="store-compat-field">UMU Game ID (optional)<input id="store-compat-gameid" class="tv-focus" type="text" maxlength="68" autocomplete="off" placeholder="umu-default" value="umu-default"></label><div class="settings-note" id="store-compat-info">Each runner has its own prefix. Switching runners never deletes the previous prefix or saved game data.</div><div class="control-actions"><button type="button" class="control-button primary tv-focus" data-store-compat-game-save>Save for this game</button><button type="button" class="control-button tv-focus" data-store-compat-game-reset>Use global defaults</button><button type="button" class="control-button tv-focus" data-store-compat-close>Back to games</button></div></div></div></section>

<section id="pc-game-sessions-modal" class="library-browser pc-game-sessions-browser" role="dialog" aria-modal="true" aria-label="Active PC game sessions"><div class="library-panel pc-game-session-panel"><div class="library-head"><div><div class="library-title">Active PC game sessions</div><div id="pc-game-sessions-sub" class="library-sub">Shared-LAN Wolf game and setup sessions • Resume reconnects without ending the Wine desktop</div></div><div class="library-head-actions"><button id="pc-game-sessions-end-all" class="pc-game-session-danger tv-focus" data-pc-session-end-all type="button">End all</button><button class="library-close tv-focus" data-pc-session-close type="button" aria-label="Close">×</button></div></div><div id="pc-game-sessions-list" class="pc-game-session-list"><div class="pc-game-session-empty">Checking active sessions…</div></div></div></section>
<section id="pc-game-stream" class="pc-game-stream" role="dialog" aria-modal="true" aria-label="PC game stream"><div class="pc-game-stream-bar"><div class="pc-game-stream-heading"><strong id="pc-game-stream-title">PC Game</strong><span id="pc-game-stream-note" role="status" aria-live="polite"></span></div><div id="pc-game-stream-tabs" class="pc-game-stream-tabs" role="tablist" aria-label="Live PC game sessions"></div><div class="pc-game-stream-actions"><div id="pc-game-stream-discs" class="pc-game-stream-discs" aria-label="Active optical disc"></div><button type="button" class="tv-focus" data-pc-stream-diagnostics>Diagnostics</button><button type="button" class="tv-focus" data-pc-stream-reload>Reconnect video</button><button type="button" class="tv-focus" data-pc-stream-end>End session</button><button type="button" class="tv-focus" data-pc-stream-close>Back</button></div></div><div id="pc-game-stream-frames" class="pc-game-stream-frames"></div></section>
<section id="review-browser" class="library-browser review-browser" role="dialog" aria-modal="true" aria-label="Manual media review"><div id="review-panel" class="library-panel review-panel"></div></section>
<section id="upload-browser" class="library-browser" role="dialog" aria-modal="true" aria-label="Upload media"><div id="upload-panel" class="upload-panel"></div></section>
<section id="photo-browser" class="photo-browser" role="dialog" aria-modal="true" aria-label="Photo library"><div id="photo-panel" class="photo-panel"></div></section>
<section id="photo-viewer" class="photo-viewer" role="dialog" aria-modal="true" aria-label="Photo viewer"><div class="photo-viewer-inner"><img id="photo-viewer-image" alt=""><div class="photo-viewer-bar"><button id="photo-viewer-wallpaper" class="photo-action tv-focus" type="button">Set wallpaper</button><button id="photo-viewer-close" class="photo-action tv-focus" type="button">Close</button></div></div></section>
<section id="video-player-modal" class="video-player-modal" role="dialog" aria-modal="true" aria-label="Jellyfin video player"><div class="video-player-panel"><div class="video-player-head"><div style="min-width:0"><div id="video-player-title" class="video-player-title">Jellyfin Video</div><div id="video-player-meta" class="video-player-meta"></div></div><button id="video-player-close" class="video-player-close tv-focus" data-group="videoplayer" type="button" aria-label="Close video">×</button></div><div class="video-player-options" aria-label="Jellyfin stream settings"><label class="video-option"><span>Quality</span><select id="video-quality" class="tv-focus" aria-label="Video quality"><option value="auto">Auto</option></select></label><label class="video-option"><span>Audio</span><select id="video-audio-track" class="tv-focus" aria-label="Audio track"><option value="">Default audio</option></select></label><label class="video-option"><span>Subtitles</span><select id="video-subtitle-track" class="tv-focus" aria-label="Subtitle track"><option value="-1">Off</option></select></label><label class="video-option compact"><span>Speed</span><select id="video-speed" class="tv-focus" aria-label="Playback speed"><option value="0.5">0.5×</option><option value="0.75">0.75×</option><option value="1" selected>1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option></select></label></div><div class="video-stage"><video id="jellyfin-video-player" playsinline preload="metadata"></video><div id="video-stream-badge" class="video-stream-badge" hidden></div></div><div class="video-controls" aria-label="Video playback controls"><button id="video-skip-back" class="video-control-button video-skip-back tv-focus" type="button" aria-label="Back 10 seconds">−10</button><button id="video-playpause" class="video-control-button tv-focus" type="button" aria-label="Pause">Ⅱ</button><button id="video-skip-forward" class="video-control-button video-skip-forward tv-focus" type="button" aria-label="Forward 10 seconds">+10</button><span id="video-time-current" class="video-control-time">0:00</span><input id="video-seek" class="video-control-range tv-focus" type="range" min="0" max="1000" step="1" value="0" aria-label="Video position"><span id="video-time-total" class="video-control-time">0:00</span><button id="video-mute" class="video-control-button tv-focus" type="button" aria-label="Mute">○</button><input id="video-volume" class="video-control-range video-volume tv-focus" type="range" min="0" max="100" step="1" value="100" aria-label="Video volume"><button id="video-fit" class="video-control-button wide video-fit-control tv-focus" type="button" aria-label="Toggle fit or fill">Fit</button><button id="video-fullscreen" class="video-control-button video-fullscreen tv-focus" type="button" aria-label="Fullscreen player">⛶</button></div><div id="video-player-note" class="video-player-note">Playing through the PCGA portal. Watch progress is reported to Jellyfin.</div></div></section>
<aside id="rip-modal" class="rip-modal" role="status" aria-live="polite" aria-label="Active optical ingest"></aside>
<section id="settings-modal" class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
  <div class="settings-panel">
    <div class="settings-head"><div><div id="settings-title" class="settings-title">PCGA Control Center</div><div class="settings-sub">Display settings are per screen. Appliance settings apply to this server.</div></div><button id="settings-close" class="settings-close tv-focus" type="button" aria-label="Close settings">×</button></div>
    <nav id="control-nav" class="control-nav" aria-label="Control Center sections">
      <button class="tv-focus active" data-control-tab="display" type="button">Display</button>
      <button class="tv-focus" data-control-tab="libraries" type="button">Libraries & Storage</button>
      <button class="tv-focus" data-control-tab="ingest" type="button">Ingest & Review</button>
      <button class="tv-focus" data-control-tab="games" type="button">Games & Emulation</button>
      <button class="tv-focus" data-control-tab="media" type="button">Media & Photos</button>
      <button class="tv-focus" data-control-tab="automation" type="button">Automation</button>
      <button class="tv-focus" data-control-tab="services" type="button">Services</button>
      <button class="tv-focus" data-control-tab="remote" type="button">Remote Access</button>
      <button class="tv-focus" data-control-tab="diagnostics" type="button">Diagnostics</button>
      <button class="tv-focus" data-control-tab="system" type="button">System</button>
      <button class="tv-focus" data-control-tab="advanced" type="button">Advanced</button>
    </nav>
    <section class="control-section active" data-control-section="display">
    <div class="settings-grid">
      <section class="settings-card wide"><h2>Screen layout</h2><div class="settings-row"><div><div class="settings-label">Layout mode</div><div class="settings-help">Automatic adapts this browser to TV, desktop, ultrawide, tablet, or mobile geometry. Ultrawide is optimized for 21:9 and 32:9 desktop displays. Override it when a touchscreen, kiosk, unusual browser, or multi-monitor setup should use a specific layout.</div></div><div class="settings-control"><select id="setting-layout-mode" aria-label="Portal screen layout"><option value="auto">Automatic</option><option value="tv">TV / 10-foot</option><option value="desktop">Desktop</option><option value="ultrawide">Ultrawide / 21:9+</option><option value="tablet">Tablet</option><option value="mobile">Mobile</option></select></div></div><div id="layout-current" class="settings-note">Automatic layout detection is starting…</div></section>
      <section class="settings-card wide"><h2>Interface theme</h2><div id="theme-grid" class="theme-grid" role="radiogroup" aria-label="Portal interface theme"></div><div class="settings-note">Themes change layout and component styling only. Your palette, clock, background, border radius, parallax, and media choices stay intact. The selected color palette propagates through every theme, including panels, buttons, focus rings, players, dialogs, and status surfaces.</div></section>
      <section class="settings-card"><h2>Display layout</h2>
        <div class="settings-row"><div><div class="settings-label">Clock</div><div class="settings-help">Add or remove a live clock from the portal.</div></div><div class="settings-control"><input id="setting-clock" type="checkbox" aria-label="Show clock"></div></div>
        <div class="settings-row"><div><div class="settings-label">Clock style</div><div class="settings-help">Choose a digital readout or an analog clock.</div></div><div class="settings-control"><select id="setting-clock-style"><option value="digital">Digital</option><option value="analog">Analog</option></select></div></div>
        <div class="settings-row"><div><div class="settings-label">Analog clock face</div><div class="settings-help">Choose the dial design used when Analog is selected.</div></div><div class="settings-control"><select id="setting-clock-face"><option value="classic">Classic</option><option value="minimal">Minimal</option><option value="roman">Roman</option><option value="railway">Railway</option></select></div></div>
        <div class="settings-row"><div><div class="settings-label">Clock location</div><div class="settings-help">Choose a preset position around the edge of the display.</div></div><div class="settings-control"><select id="setting-clock-position"><option value="top-left">Top left</option><option value="top-center">Top center</option><option value="top-right">Top right</option><option value="bottom-left">Bottom left</option><option value="bottom-center">Bottom center</option><option value="bottom-right">Bottom right</option></select></div></div>
        <div class="settings-row"><div><div class="settings-label">Digital clock format</div><div class="settings-help">Choose 12-hour or 24-hour time when Digital is selected.</div></div><div class="settings-control"><select id="setting-clock-format"><option value="12">12 hour</option><option value="24">24 hour</option></select></div></div>
        <div class="settings-row"><div><div class="settings-label">Clock bounding box</div><div class="settings-help">Show the clock inside a themed outer panel, or remove that outer panel. Analog dials remain circular.</div></div><div class="settings-control"><input id="setting-clock-boxed" type="checkbox" aria-label="Show clock bounding box"></div></div>
        <div class="settings-row"><div><div class="settings-label">Continue & recent</div><div class="settings-help">Enable the hidden secondary home surface. Press Down from the bottom launcher row to reveal it, then Up from its top row to return.</div></div><div class="settings-control"><input id="setting-home-media" type="checkbox" aria-label="Enable Continue and recent surface"></div></div>
        <div class="settings-row"><div><div class="settings-label">Include games</div><div class="settings-help">Mix recently launched console and PC games into Continue/Recently Accessed and newly added games into Recently Added.</div></div><div class="settings-control"><input id="setting-home-media-games" type="checkbox" aria-label="Include games in Continue and recent"></div></div>
        <div class="settings-row"><div><div class="settings-label">Continue shelf</div><div class="settings-help">Show in-progress Jellyfin video plus recent game launches on the secondary home surface.</div></div><div class="settings-control"><input id="setting-home-media-continue" type="checkbox" aria-label="Show Continue shelf"></div></div>
        <div class="settings-row"><div><div class="settings-label">Recently accessed shelf</div><div class="settings-help">Show Jellyfin media most recently played by the configured portal user.</div></div><div class="settings-control"><input id="setting-home-media-recent" type="checkbox" aria-label="Show Recently Accessed shelf"></div></div>
        <div class="settings-row"><div><div class="settings-label">Recently added shelf</div><div class="settings-help">Show the newest movies, episodes, videos, and music added to Jellyfin.</div></div><div class="settings-control"><input id="setting-home-media-added" type="checkbox" aria-label="Show Recently Added shelf"></div></div>
        <div class="settings-row"><div><div class="settings-label">Border radius</div><div class="settings-help">Move from the current rounded style down to square corners.</div></div><div class="settings-control"><input id="setting-radius" type="range" min="0" max="30" step="1"><span id="radius-readout" class="radius-readout">26 px</span></div></div>
      </section>
      <section class="settings-card"><h2>Color & appearance</h2><div class="settings-row"><div><div class="settings-label">Appearance</div><div class="settings-help">Use the screen preference automatically, or force a light or dark version of the active interface theme.</div></div><div class="settings-control"><select id="setting-appearance-mode" aria-label="Portal light or dark appearance"><option value="auto">Automatic</option><option value="light">Light</option><option value="dark">Dark</option></select></div></div><div class="settings-row"><div><div class="settings-label">Surface treatment</div><div class="settings-help">Apply a shared material treatment to the active layout without changing its geometry, palette, or light/dark mode.</div></div><div class="settings-control"><select id="setting-surface-style" aria-label="Portal surface treatment"><option value="theme">Theme default</option><option value="frosted">Frosted glass</option><option value="crystal">Crystal glass</option><option value="solid">Solid panels</option></select></div></div><div class="settings-row"><div><div class="settings-label">Interface font</div><div class="settings-help">Choose typography independently from the layout theme. Theme default preserves each layout's intended typeface; other choices override the portal UI while logs and paths stay monospace.</div></div><div class="settings-control"><select id="setting-font-style" aria-label="Portal interface font"><option value="theme">Theme default</option><option value="system">System sans</option><option value="humanist">Humanist sans</option><option value="rounded">Rounded sans</option><option value="geometric">Geometric sans</option><option value="readable">Readable sans</option><option value="serif">Book serif</option><option value="mono">Monospace</option></select></div></div><div id="scheme-grid" class="scheme-grid" role="radiogroup" aria-label="Portal color scheme"></div><div class="settings-note">Layout, appearance, surface material, font, and palette are independent. Font choices use local/system font stacks so the portal remains self-contained and offline-capable.</div></section>
      <section class="settings-card wide"><h2>Background</h2>
        <div class="settings-row"><div><div class="settings-label">Pattern</div><div class="settings-help">Ambient glow, solid color, grid, dots, diagonal lines, a photo wallpaper, a photo slideshow, or a silent Jellyfin video.</div></div><div class="settings-control"><select id="setting-pattern"><option value="ambient">Ambient glow</option><option value="solid">Solid</option><option value="grid">Grid</option><option value="dots">Dots</option><option value="diagonal">Diagonal</option><option value="photo">Photo wallpaper</option><option value="slideshow">Photo slideshow</option><option value="video">Jellyfin video</option></select></div></div>
        <div class="settings-row"><div><div class="settings-label">Motion</div><div class="settings-help">Keep the existing background behavior, or let it respond subtly to pointer movement and the currently selected keyboard/controller control.</div></div><div class="settings-control"><select id="setting-background-motion"><option value="standard">Standard</option><option value="parallax">Reactive parallax</option></select></div></div>
        <div class="settings-row"><div><div class="settings-label">Ambient glow depth</div><div class="settings-help">Independent parallax depth for the ambient glow layer. Set to 0 to keep this layer fixed.</div></div><div class="settings-control"><input id="setting-parallax-ambient" type="range" min="0" max="100" step="5"><span id="parallax-ambient-readout" class="radius-readout">30%</span></div></div>
        <div class="settings-row"><div><div class="settings-label">Pattern depth</div><div class="settings-help">Independent depth for grid, dots, or diagonal pattern layers.</div></div><div class="settings-control"><input id="setting-parallax-pattern" type="range" min="0" max="100" step="5"><span id="parallax-pattern-readout" class="radius-readout">65%</span></div></div>
        <div class="settings-row"><div><div class="settings-label">Photo/video depth</div><div class="settings-help">Independent depth for photo, slideshow, and Jellyfin video backgrounds. Reduced-motion preferences disable all movement.</div></div><div class="settings-control"><input id="setting-parallax-media" type="range" min="0" max="100" step="5"><span id="parallax-media-readout" class="radius-readout">45%</span></div></div>
        <div class="settings-row"><div><div class="settings-label">Background visibility</div><div class="settings-help">Controls how strongly photo or video backgrounds show through the UI.</div></div><div class="settings-control"><input id="setting-video-opacity" type="range" min="20" max="100" step="5"><span id="video-opacity-readout" class="radius-readout">70%</span></div></div>
        <div class="settings-row"><div><div class="settings-label">Slideshow interval</div><div class="settings-help">Seconds between photos when Photo slideshow is selected.</div></div><div class="settings-control"><input id="setting-slideshow-interval" type="range" min="5" max="120" step="5"><span id="slideshow-interval-readout" class="radius-readout">20s</span></div></div>
        <div class="settings-row"><div><div class="settings-label">Photo background</div><div class="settings-help">Choose a wallpaper or open the shared photo library and start a slideshow from the current search.</div></div><div class="settings-control"><button id="background-photo-button" class="settings-action" type="button">Browse photos</button><button id="background-photo-clear" class="settings-action" type="button">Clear photo</button></div></div>
        <div id="photo-background-current" class="background-current">No photo wallpaper selected.</div>
        <div class="background-search settings-control"><input id="background-search-input" type="text" placeholder="Search Jellyfin video library" autocomplete="off"><button id="background-search-button" class="settings-action" type="button">Search</button><button id="background-clear-button" class="settings-action" type="button">Clear video</button></div>
        <div id="background-current" class="background-current">No Jellyfin background selected.</div>
        <div id="background-results" class="background-results" aria-live="polite"></div>
        <div class="settings-note">Photos are read from the shared PCGA photo archive used by Jellyfin and Immich External Libraries. Video backgrounds remain muted and looped; PCGA asks Jellyfin for a browser-compatible H.264/AAC MP4 stream.</div>
      </section>
    </div>
    </section>
    <section class="control-section" data-control-section="libraries">
      <div class="control-summary"><div class="control-stat"><strong id="cc-disk-used">—</strong><span>Storage used</span></div><div class="control-stat"><strong id="cc-disk-free">—</strong><span>Storage free</span></div><div class="control-stat"><strong id="cc-archive-root">—</strong><span>Archive root</span></div><div class="control-stat"><strong id="cc-config-version">—</strong><span>Control schema</span></div></div>
      <div class="settings-grid">
        <section class="settings-card wide"><h2>Canonical libraries</h2><div id="cc-library-paths"></div><div class="settings-note">PCGA owns these paths and generates service-specific mounts/configuration from them. New ingest always lands locally before any NAS tiering policy runs.</div></section>
        <section class="settings-card wide"><h2>NAS storage tier</h2><div class="settings-note">Mirror keeps a secondary NAS copy without removing the local original. Smart offload can free local space, but only after the NAS copy passes a SHA-256 verification. Offloaded media remains visible to PCGA/Jellyfin through a managed read-only NAS library mount. If Smart offload leaves the NAS as the only copy, NAS snapshots or a separate backup are strongly recommended.</div>
          <div class="control-summary"><div class="control-stat"><strong id="cc-nas-state">Disabled</strong><span>NAS state</span></div><div class="control-stat"><strong id="cc-nas-free">—</strong><span>NAS free</span></div><div class="control-stat"><strong id="cc-nas-last-sync">—</strong><span>Last mirror</span></div></div>
          <div class="settings-row"><div><div class="settings-label">Enable NAS tier</div><div class="settings-help">PCGA manages the mount, scheduled mirror, and optional offload policy.</div></div><div class="settings-control"><input id="cc-nas-enabled" type="checkbox"></div></div>
          <div class="settings-row"><div><div class="settings-label">Protocol</div></div><div class="settings-control"><select id="cc-nas-protocol"><option value="smb">SMB / CIFS</option><option value="nfs">NFS</option></select></div></div>
          <div class="settings-row"><div><div class="settings-label">NAS host</div><div class="settings-help">Hostname or IP address on your LAN or tailnet.</div></div><div class="settings-control"><input id="cc-nas-host" type="text" placeholder="nas.local" autocomplete="off"></div></div>
          <div class="settings-row"><div><div class="settings-label">Share / export</div><div class="settings-help">For SMB use the share name, such as Media. For NFS use an export such as /volume1/media.</div></div><div class="settings-control"><input id="cc-nas-share" type="text" placeholder="Media" autocomplete="off"></div></div>
          <div class="settings-row"><div><div class="settings-label">SMB username</div><div class="settings-help">Leave blank for a guest share. NFS ignores this field.</div></div><div class="settings-control"><input id="cc-nas-username" type="text" autocomplete="username"></div></div>
          <div class="settings-row"><div><div class="settings-label">SMB password</div><div class="settings-help">Leave blank to preserve the password already stored on the server.</div></div><div class="settings-control"><input id="cc-nas-password" type="password" autocomplete="new-password" placeholder="unchanged"></div></div>
          <div class="settings-row"><div><div class="settings-label">SMB domain</div><div class="settings-help">Optional workgroup/domain.</div></div><div class="settings-control"><input id="cc-nas-domain" type="text" autocomplete="off"></div></div>
          <div class="settings-row"><div><div class="settings-label">PCGA folder on share</div><div class="settings-help">PCGA stores its structured mirror beneath this folder.</div></div><div class="settings-control"><input id="cc-nas-base" type="text" value="PCGA" autocomplete="off"></div></div>
          <div class="settings-row"><div><div class="settings-label">Tiering mode</div><div class="settings-help">Mirror never removes local files. Smart offload removes only old, verified local copies when free space falls below the reserve.</div></div><div class="settings-control"><select id="cc-nas-mode"><option value="mirror">Mirror only</option><option value="offload">Smart offload</option></select></div></div>
          <div class="settings-row"><div><div class="settings-label">Libraries</div><div class="settings-help">Select which media libraries are mirrored/offloaded. Games remain local in this release.</div></div><div class="settings-control" style="display:flex;flex-wrap:wrap;gap:10px"><label><input class="cc-nas-lib" type="checkbox" value="movies"> Movies</label><label><input class="cc-nas-lib" type="checkbox" value="tv"> TV</label><label><input class="cc-nas-lib" type="checkbox" value="music"> Music</label><label><input class="cc-nas-lib" type="checkbox" value="home-videos"> Home videos</label><label><input class="cc-nas-lib" type="checkbox" value="photos"> Photos</label></div></div>
          <div class="settings-row"><div><div class="settings-label">Local free-space reserve</div><div class="settings-help">Smart offload stops deleting local verified copies once this much free space is available.</div></div><div class="settings-control"><input id="cc-nas-reserve" type="number" min="1" max="16384" step="1" value="100"><span>GiB</span></div></div>
          <div class="settings-row"><div><div class="settings-label">Minimum local age</div><div class="settings-help">Files newer than this are never removed locally by Smart offload.</div></div><div class="settings-control"><input id="cc-nas-age" type="number" min="0" max="3650" step="1" value="30"><span>days</span></div></div>
          <div class="settings-row"><div><div class="settings-label">Daily maintenance</div><div class="settings-help">Runs around 03:40 with a small randomized delay.</div></div><div class="settings-control"><input id="cc-nas-schedule" type="checkbox" checked></div></div>
          <div class="control-actions"><button id="cc-nas-save" class="control-button primary tv-focus" type="button">Save & connect</button><button class="control-button tv-focus" data-control-action="nas-sync" type="button">Mirror now</button><button id="cc-nas-offload" class="control-button tv-focus" data-control-action="nas-offload" type="button">Free space now</button><button id="cc-nas-archive" class="control-button tv-focus" data-control-action="nas-archive" type="button">Archive eligible now</button><button class="control-button tv-focus" data-control-action="nas-unmount" type="button">Unmount</button></div>
          <div id="cc-nas-message" class="settings-note">Configure a NAS share to begin.</div>
        </section>
      </div>
    </section>
    <section class="control-section" data-control-section="ingest">
      <div class="settings-grid">
        <section class="settings-card"><h2>Optical ingest</h2><div class="settings-row"><div><div class="settings-label">Automatic disc ingest</div><div class="settings-help">PCGA identifies inserted media first, then routes video/audio to ARM and data discs to preservation.</div></div><div class="settings-control"><input id="cc-auto-rip" type="checkbox"></div></div><div class="settings-row"><div><div class="settings-label">Retain successful ARM work files</div><div class="settings-help">Off is recommended. The source-quality MKV remains the library output while successful raw/transcode intermediates are cleaned. Failed or incomplete raw data remains available to PCGA recovery.</div></div><div class="settings-control"><input id="cc-keep-raw" type="checkbox"></div></div><div class="control-actions"><button class="control-button primary tv-focus" data-open-upload type="button">Upload files</button><button class="control-button" data-control-action="ingest-reconcile" type="button">Reconcile ingest</button><button class="control-button" data-control-action="optical-health" type="button">Check drives</button><a class="control-button" href="/public-media/">Public Media</a></div></section>
        <section class="settings-card"><h2>Classification & review</h2><div class="settings-row"><div><div class="settings-label">Automatic classification</div><div class="settings-help">Run the local-first classifier in the background.</div></div><div class="settings-control"><input id="cc-auto-classify" type="checkbox"></div></div><div class="settings-row"><div><div class="settings-label">Auto-route confidence</div><div class="settings-help">Minimum confidence PCGA records for automatic routing policy.</div></div><div class="settings-control"><input id="cc-auto-threshold" type="range" min="50" max="100" step="1"><span id="cc-threshold-value" class="radius-readout">90%</span></div></div><div class="control-actions"><button class="control-button primary" data-control-action="classify" type="button">Classify now</button><button class="control-button tv-focus" data-open-review type="button">Open Review Queue</button></div></section>
      </div>
    </section>
    <section class="control-section" data-control-section="games">
      <div class="settings-grid">
        <section class="settings-card wide"><h2>Console games & emulation</h2><div class="settings-row"><div><div class="settings-label">Console Games service</div><div class="settings-help">RomM + bundled EmulatorJS, managed by PCGA.</div></div><div class="settings-control"><input id="cc-romm-enabled" type="checkbox"></div></div><div class="settings-row"><div><div class="settings-label">Automatic ROM discovery</div><div class="settings-help">Watch the canonical ROM library and scan after copies settle.</div></div><div class="settings-control"><input id="cc-romm-watch" type="checkbox"></div></div><div class="settings-row"><div><div class="settings-label">Discovery settle delay</div></div><div class="settings-control"><select id="cc-romm-debounce"><option value="60">1 minute</option><option value="180">3 minutes</option><option value="300">5 minutes</option><option value="600">10 minutes</option><option value="900">15 minutes</option></select></div></div><div class="settings-row"><div><div class="settings-label">Hasheous metadata</div></div><div class="settings-control"><input id="cc-hasheous" type="checkbox"></div></div><div class="settings-row"><div><div class="settings-label">PlayMatch metadata</div></div><div class="settings-control"><input id="cc-playmatch" type="checkbox"></div></div><div class="control-actions"><button class="control-button primary" data-upload-kind="bios" type="button">Upload BIOS / firmware</button><button class="control-button" data-game-rescan type="button">Refresh ROM metadata</button><button class="control-button" data-control-action="restart:romm" type="button">Restart Console Games</button></div><div class="settings-note">BIOS/firmware uploads are stored in the managed per-platform BIOS library and queued for RomM discovery. ROM scans also run the enabled metadata providers so PCGA can collect canonical titles, descriptions, dates, genres and cover art. Native RomM setup is treated as an advanced escape hatch, not a required appliance step.</div></section>
        <section class="settings-card wide" id="cc-store-compat-card"><h2>PC game compatibility · Wine / Proton</h2><div class="settings-note">Choose how newly installed Epic and GOG games run. Automatic uses UMU/Proton after preparation, but preserves Wine for games with an existing Wine prefix. Existing saves and settings are never deleted.</div><div class="settings-row"><div><div class="settings-label">Default game runner</div><div class="settings-help">Automatic is recommended; Wine remains available for older games.</div></div><div class="settings-control"><select id="cc-store-compat-mode" class="tv-focus"><option value="auto">Automatic (recommended)</option><option value="umu">UMU / Proton</option><option value="wine">Wine (legacy)</option></select></div></div><div class="settings-row"><div><div class="settings-label">Preferred Proton</div><div class="settings-help">UMU-Proton uses Valve's compatibility stack; GE-Proton may help with game-specific fixes. Downloads happen on first launch after preparation.</div></div><div class="settings-control"><select id="cc-store-compat-proton" class="tv-focus"><option value="UMU-Proton">UMU-Proton</option><option value="GE-Proton">GE-Proton</option></select></div></div><div class="control-actions"><button type="button" class="control-button primary tv-focus" data-store-compat-default-save>Save compatibility defaults</button><button type="button" class="control-button tv-focus" data-store-umu-prepare>Prepare UMU</button><button type="button" class="control-button tv-focus" data-store-compat-status>Refresh status</button></div><div id="cc-store-compat-note" class="settings-note" role="status">Checking UMU readiness…</div></section>
        <section class="settings-card wide"><h2>Steam · Native client &amp; Remote Play</h2><div class="settings-note">Steam runs as an optional isolated host runtime. Use its native client for store login, game downloads, updates, Steam Play/Proton, and pairing with Steam Link. Steam Remote Play is separate from PCGA Wolf/Moonlight. The runtime shares host networking and needs GPU/input access; enable only on a trusted LAN.</div><div class="settings-row"><div><div class="settings-label">Steam runtime</div><div class="settings-help" id="cc-steam-status">Not checked. First launch downloads the Steam Headless runtime and may expose its management UI on the trusted network.</div></div><div class="settings-control"><button class="control-button tv-focus" data-steam-action="status" type="button">Refresh</button><button class="control-button primary tv-focus" data-steam-action="start" type="button">Start Steam</button><button class="control-button tv-focus" data-steam-action="stop" type="button">Stop Steam</button></div></div><div class="settings-row"><div><div class="settings-label">Steam games</div><div class="settings-help" id="cc-steam-count">Steam game manifests will be indexed from PCGA-managed storage.</div></div><div class="settings-control"><button class="control-button tv-focus" data-steam-library type="button">Installed Steam games</button><button class="control-button tv-focus" data-steam-setup type="button">Open Steam setup</button></div></div><div class="settings-note">Use Steam Link or a logged-in Steam client to pair with the PCGA host and start Steam Remote Play. Game installation and Proton configuration are performed inside Steam; PCGA never requests your Steam password.</div></section><section class="settings-card wide"><h2>PC games & LAN sessions</h2><div class="settings-row"><div><div class="settings-label">LANCommander + shared game LAN</div><div class="settings-help">PCGA-managed LANCommander shares the <code>legacy-games</code> virtual LAN with every streamed Wine desktop. TCP/UDP LAN discovery stays between PCGA sessions; LANCommander also provides the optional UDP/213 IPX relay endpoint for games configured to use it. Native administration remains under Advanced.</div></div><div class="settings-control"><span class="badge">Managed</span></div></div><div class="settings-row"><div><div class="settings-label">Browser stream transport</div><div class="settings-help">Automatic preflights H.264 WebCodecs support and prefers WebSocket + WebCodecs; WebRTC remains the fallback and an optional low-latency path.</div></div><div class="settings-control"><select id="setting-pc-game-transport"><option value="auto">Automatic (recommended)</option><option value="websocket">WebSocket + WebCodecs</option><option value="webrtc">WebRTC (low latency)</option></select></div></div><div class="settings-row"><div><div class="settings-label">Direct3D graphics backend</div><div class="settings-help">Automatic uses pinned DXVK for Direct3D 8–11 when a working Vulkan device is available and falls back to WineD3D otherwise. Force WineD3D for old/non-Vulkan GPUs or compatibility testing.</div></div><div class="settings-control"><select id="cc-pc-graphics-backend"><option value="auto">Automatic — DXVK when available</option><option value="dxvk">Prefer DXVK</option><option value="wined3d">WineD3D / OpenGL</option></select></div></div><div class="settings-row"><div><div class="settings-label">ProtonDB compatibility knowledge</div><div class="settings-help">Match exact Steam AppIDs to ProtonDB summaries and recent community reports. Reported Proton-specific tweaks remain advisory unless PCGA has an equivalent safe runtime setting.</div></div><div class="settings-control"><input id="cc-compat-protondb" type="checkbox"></div></div><div class="settings-row"><div><div class="settings-label">PlayOnLinux known-good recipes</div><div class="settings-help">Match game titles to approved PlayOnLinux installers. PCGA parses only allow-listed architecture, Windows-version, component and executable hints; it never executes downloaded installer scripts.</div></div><div class="settings-control"><input id="cc-compat-playonlinux" type="checkbox"></div></div><div class="settings-row"><div><div class="settings-label">PC game database profiles</div><div class="settings-help">Search ranked RAWG profiles from Disc images or a game profile, preview the web-collected fields, and explicitly apply the selected canonical metadata. Search automatically broadens noisy disc/setup labels. The API key remains server-side. <a href="https://rawg.io/apidocs" target="_blank" rel="noopener">Get a RAWG API key ↗</a></div></div><div class="settings-control"><input id="cc-rawg-api-key" type="password" autocomplete="new-password" placeholder="RAWG API key"><button class="control-button" id="cc-game-db-save" type="button">Save key</button><span class="settings-note" id="cc-game-db-state">Not configured</span></div></div><div class="settings-row"><div><div class="settings-label">PC store providers</div><div class="settings-help">v0.19.12 supports native account management for Epic/Legendary, GOG/gogdl and Amazon/Nile and adds the persistent acquisition queue. PCGA opens each provider's login page and accepts only the returned one-time authorization code; store passwords and OAuth tokens are never requested by the portal. Owned Epic and GOG titles can now be installed from Store Library; the durable Epic and GOG download worker and job monitor are available.</div></div><div class="settings-control"><span class="badge" id="cc-store-state">Not prepared</span><span class="settings-note" id="cc-store-preparation">Select Connect to prepare store helpers automatically.</span><span class="settings-note" id="cc-store-epic">Epic —</span><span class="settings-note" id="cc-store-gog">GOG —</span><span class="settings-note" id="cc-store-amazon">Amazon —</span><button class="control-button" data-control-action="store-backends-prepare" type="button">Prepare backends</button><button class="control-button" data-control-action="store-backends-probe" type="button">Run diagnostics</button><button class="control-button" data-control-action="store-accounts-refresh" type="button">Refresh accounts</button></div></div><div class="settings-row"><div><div class="settings-label">Epic Games account</div><div class="settings-help">Connect through Legendary using Epic's browser login and a one-time authorization code.</div></div><div class="settings-control"><span class="badge" id="cc-store-account-epic">Checking…</span><button class="control-button primary tv-focus" data-store-account-connect="epic" type="button">Connect</button><button class="control-button tv-focus" data-store-account-logout="epic" type="button">Disconnect</button></div></div><div class="settings-row"><div><div class="settings-label">GOG account</div><div class="settings-help">Connect through GOG's browser OAuth flow; gogdl owns the resulting private auth cache.</div></div><div class="settings-control"><span class="badge" id="cc-store-account-gog">Checking…</span><button class="control-button primary tv-focus" data-store-account-connect="gog" type="button">Connect</button><button class="control-button tv-focus" data-store-account-logout="gog" type="button">Disconnect</button></div></div><div class="settings-row"><div><div class="settings-label">Amazon Games account</div><div class="settings-help">Connect through Nile's non-interactive device flow. PCGA keeps the verifier and device serial server-side while you authenticate with Amazon in the browser.</div></div><div class="settings-control"><span class="badge" id="cc-store-account-amazon">Checking…</span><button class="control-button primary tv-focus" data-store-account-connect="amazon" type="button">Connect</button><button class="control-button tv-focus" data-store-account-logout="amazon" type="button">Disconnect</button></div></div><div class="settings-row"><div><div class="settings-label">Store game job queue</div><div class="settings-help">Persistent installation and maintenance jobs continue independently of the browser. One Epic and one GOG game-management job may run simultaneously; interrupted jobs are queued to resume. Amazon downloads are planned for a later release.</div></div><div class="settings-control"><span class="badge" id="cc-store-jobs">Idle</span><button class="control-button tv-focus" data-store-jobs type="button">Downloads &amp; Maintenance</button></div></div><div class="control-actions"><button class="control-button" data-control-action="restart:lancommander" type="button">Restart PC Games</button></div><div class="settings-note">PCGA owns first-run initialization, pins LANCommander v2.1.16, and keeps the shared game-LAN topology appliance-managed so individual Wine sessions do not need manual network setup.</div></section>
      </div>
    </section>
    <section class="control-section" data-control-section="media">
      <div class="settings-grid">
        <section class="settings-card"><h2>Movies, TV & Music</h2><div class="settings-row"><div><div class="settings-label">Jellyfin service</div><div class="settings-help">Primary media backend for Movies, TV and Music.</div></div><div class="settings-control"><input id="cc-jellyfin-enabled" type="checkbox"></div></div><div class="control-actions"><button class="control-button" data-control-action="jellyfin-configure" type="button">Reconcile libraries</button><button class="control-button" data-control-action="restart:jellyfin" type="button">Restart Jellyfin</button></div></section>
        <section class="settings-card"><h2>Photos</h2><div class="settings-row"><div><div class="settings-label">Immich service</div><div class="settings-help">Photo indexing, search, albums and mobile backup against the PCGA photo archive.</div></div><div class="settings-control"><input id="cc-immich-enabled" type="checkbox"></div></div><div class="control-actions"><button class="control-button" data-control-action="restart:immich" type="button">Restart Immich</button></div><div class="settings-note">The shared photo archive is mounted read-only into Immich; its private managed upload store remains separate.</div></section>
      </div>
    </section>
    <section class="control-section" data-control-section="automation">
      <div class="settings-grid"><section class="settings-card wide"><h2>Background maintenance</h2><div class="settings-row"><div><div class="settings-label">Sorter safety scan</div></div><div class="settings-control"><input id="cc-sorter-enabled" type="checkbox"></div></div><div class="settings-row"><div><div class="settings-label">Classifier timer</div></div><div class="settings-control"><input id="cc-classifier-enabled" type="checkbox"></div></div><div class="settings-row"><div><div class="settings-label">Daily duplicate pruning</div><div class="settings-help">Conservative exact-byte dedupe; final-library-to-final-library merges remain opt-in.</div></div><div class="settings-control"><input id="cc-dedupe-enabled" type="checkbox"></div></div><div class="control-actions"><button class="control-button" data-control-action="dedupe-audit" type="button">Audit duplicates</button><button class="control-button primary" data-control-action="dedupe-run" type="button">Run dedupe</button></div></section></div>
    </section>
    <section class="control-section" data-control-section="services"><div class="settings-grid"><section class="settings-card wide"><h2>Service health</h2><div id="cc-services" class="control-service-grid"></div></section></div></section>
    <section class="control-section" data-control-section="remote"><div class="settings-grid"><section class="settings-card wide"><h2>LAN portal identity</h2><div class="settings-note">PCGA publishes a friendly LAN identity without taking over DHCP. Initial thin-client trust is always established on this physical LAN; remote overlays are never allowed to bootstrap trust.</div><div class="settings-row"><div><div class="settings-label">Friendly portal</div><div class="settings-help">Preferred URL after LAN DNS is configured.</div></div><div id="cc-lan-portal" class="control-path">—</div></div><div class="settings-row"><div><div class="settings-label">DNS name</div></div><div id="cc-lan-dns-name" class="control-path">pcga.portal</div></div></section>
      <section class="settings-card wide"><h2>Remote networking</h2><div class="settings-note">Tailscale, NetBird and ZeroTier are independent and may be active together. PCGA never signs an existing provider out just because another provider is enabled. Tailscale uses Serve; NetBird and ZeroTier access the appliance directly through their encrypted overlays using the PCGA TLS certificate.</div><div class="control-summary"><div class="control-stat"><strong id="cc-remote-ready">—</strong><span>Ready providers</span></div><div class="control-stat"><strong id="cc-remote-paths">—</strong><span>Overlay addresses</span></div></div></section>
      <section class="settings-card wide"><h2>Tailscale</h2><div class="settings-note">Integrate PCGA into an existing tailnet. PCGA publishes only the secure portal and Moonlight Web lanes with Tailscale Serve; the LAN bootstrap service is never published.</div><div class="control-summary"><div class="control-stat"><strong id="cc-ts-state">—</strong><span>State</span></div><div class="control-stat"><strong id="cc-ts-dns">—</strong><span>MagicDNS</span></div></div><div class="settings-row"><div><div class="settings-label">Remote portal</div></div><div id="cc-ts-portal" class="control-path">—</div></div><div class="settings-row"><div><div class="settings-label">Moonlight Web</div><div class="settings-help">Secure browser-stream endpoint published through Tailscale Serve.</div></div><div id="cc-ts-moonlight" class="control-path">—</div></div><div class="settings-row"><div><div class="settings-label">Addresses</div></div><div id="cc-ts-ips" class="control-path">—</div></div><div class="control-actions"><button id="cc-ts-enable" class="control-button primary tv-focus" data-control-action="tailscale-enable" type="button">Publish through Tailscale</button><button class="control-button tv-focus" data-control-action="tailscale-status" type="button">Refresh</button><button id="cc-ts-disable" class="control-button tv-focus" data-control-action="tailscale-disable" type="button">Stop publishing</button></div><div id="cc-remote-message" class="settings-note">Checking Tailscale…</div></section>
      <section class="settings-card wide"><h2>NetBird</h2><div class="settings-note">Join NetBird Cloud or an existing self-hosted NetBird management server. A setup key is consumed for enrollment and is not stored in the PCGA appliance configuration.</div><div class="control-summary"><div class="control-stat"><strong id="cc-nb-state">—</strong><span>State</span></div><div class="control-stat"><strong id="cc-nb-path">—</strong><span>Peer path</span></div></div><div class="settings-row"><div><div class="settings-label">Management URL</div><div class="settings-help">Leave blank for NetBird Cloud; set this for a self-hosted deployment.</div></div><div class="settings-control"><input id="cc-nb-management" type="url" placeholder="https://netbird.example.com"></div></div><div class="settings-row"><div><div class="settings-label">Setup key</div><div class="settings-help">One-off or reusable setup key from your NetBird management service.</div></div><div class="settings-control"><input id="cc-nb-key" type="password" autocomplete="new-password" placeholder="Setup key"></div></div><div class="settings-row"><div><div class="settings-label">Remote portal</div></div><div id="cc-nb-portal" class="control-path">—</div></div><div class="settings-row"><div><div class="settings-label">NetBird address</div></div><div id="cc-nb-ips" class="control-path">—</div></div><div class="control-actions"><button id="cc-nb-install" class="control-button tv-focus" data-control-action="netbird-install" type="button">Install client</button><button id="cc-nb-connect" class="control-button primary tv-focus" data-control-action="netbird-connect" type="button">Connect</button><button class="control-button tv-focus" data-control-action="netbird-status" type="button">Refresh</button><button id="cc-nb-disconnect" class="control-button tv-focus" data-control-action="netbird-disconnect" type="button">Disconnect</button></div><div id="cc-nb-message" class="settings-note">Checking NetBird…</div></section>
      <section class="settings-card wide"><h2>ZeroTier</h2><div class="settings-note">Join an existing ZeroTier network for direct remote access or a virtual gaming LAN. PCGA does not create or take ownership of the controller/network; authorization remains in your existing ZeroTier Central or self-hosted controller.</div><div class="control-summary"><div class="control-stat"><strong id="cc-zt-state">—</strong><span>State</span></div><div class="control-stat"><strong id="cc-zt-node">—</strong><span>Node ID</span></div></div><div class="settings-row"><div><div class="settings-label">Network ID</div><div class="settings-help">16-character network ID. After joining, authorize this PCGA node in your controller.</div></div><div class="settings-control"><input id="cc-zt-network" inputmode="text" maxlength="16" placeholder="8056c2e21c000001"></div></div><div class="settings-row"><div><div class="settings-label">Remote portal</div></div><div id="cc-zt-portal" class="control-path">—</div></div><div class="settings-row"><div><div class="settings-label">ZeroTier addresses</div></div><div id="cc-zt-ips" class="control-path">—</div></div><div class="control-actions"><button id="cc-zt-install" class="control-button tv-focus" data-control-action="zerotier-install" type="button">Install client</button><button id="cc-zt-join" class="control-button primary tv-focus" data-control-action="zerotier-join" type="button">Join network</button><button class="control-button tv-focus" data-control-action="zerotier-status" type="button">Refresh</button><button id="cc-zt-leave" class="control-button tv-focus" data-control-action="zerotier-leave" type="button">Leave network</button></div><div id="cc-zt-message" class="settings-note">Checking ZeroTier…</div></section></div></section>
    <section class="control-section" data-control-section="system"><div class="control-summary"><div class="control-stat"><strong id="cc-system-health">—</strong><span>Appliance health</span></div><div class="control-stat"><strong id="cc-review-count">—</strong><span>Review items</span></div><div class="control-stat"><strong id="cc-active-rips">—</strong><span>Active rips</span></div><div class="control-stat"><strong id="cc-system-version">0.19.13</strong><span>PCGA version</span></div></div><div class="settings-grid"><section class="settings-card wide"><h2>Maintenance</h2><div class="control-actions"><button class="control-button" data-control-action="ingest-reconcile" type="button">Reconcile ingest</button><button class="control-button" data-control-action="dedupe-audit" type="button">Storage audit</button><button class="control-button" data-control-action="optical-health" type="button">Optical health</button></div><div id="cc-last-action" class="settings-note">No maintenance action has been run from this display.</div></section><section class="settings-card wide"><h2>Install PCGA patch</h2><div class="settings-note">Drop a versioned <code>pc_game_archive_v*.zip</code> release here. PCGA validates the archive layout and manifest, then runs its versioned upgrader on the host. Patches must be newer than the installed version.</div><div id="patch-drop" class="patch-drop"><strong>Drop PCGA patch ZIP</strong><span id="patch-selected">No patch selected</span><label class="control-button primary" style="display:inline-grid;place-items:center;margin-top:12px;cursor:pointer">Choose ZIP<input id="patch-file" class="patch-file-input" type="file" accept=".zip,application/zip"></label></div><div class="control-actions"><button id="patch-install" class="control-button primary tv-focus" type="button" disabled>Validate and install patch</button></div><div id="patch-state" class="settings-note">Use the HTTPS portal to install appliance patches.</div><pre id="patch-log" class="patch-log" hidden></pre></section></div></section>
    <section class="control-section" data-control-section="advanced"><div class="settings-grid"><section class="settings-card wide"><h2>Native application interfaces</h2><div class="settings-note">These are escape hatches for deep application-specific administration. Routine appliance setup belongs in PCGA.</div><div id="cc-native-links" class="control-native-links"></div></section><section class="settings-card wide"><h2>Configuration files</h2><div class="control-path">/etc/pc-game-archive/appliance.json</div><div class="control-path">/etc/pc-game-archive/secrets/ (service credentials)</div><div class="control-path">/var/lib/pc-game-archive/control/ (operational state)</div></section></div></section>
    <div class="settings-actions"><button id="settings-reset" class="settings-action" type="button">Reset display defaults</button><button id="settings-done" class="settings-action primary" type="button">Done</button></div>
  </div>
</section>
<main class="shell">
  <header class="header"><div id="portal-clock" class="portal-clock" aria-live="off"><div id="clock-digital" class="clock-digital"><div id="clock-time" class="clock-time"></div><div id="clock-date-digital" class="clock-date"></div></div><div id="clock-analog" class="clock-analog" aria-hidden="true"><div class="analog-dial"><span class="analog-number n12">12</span><span class="analog-number n3">3</span><span class="analog-number n6">6</span><span class="analog-number n9">9</span><span id="clock-hour-hand" class="analog-hand hour"></span><span id="clock-minute-hand" class="analog-hand minute"></span><span id="clock-second-hand" class="analog-hand second"></span><span class="analog-pin"></span></div><div id="clock-date-analog" class="clock-date"></div></div></div><div class="header-right"><button id="system-strip" class="system-strip tv-focus" type="button" aria-label="Open system status"><span class="system-strip-dot"></span><span><span id="system-strip-main" class="system-strip-main">System starting…</span><span id="system-strip-meta" class="system-strip-meta">Connecting to PCGA control plane</span></span></button><button id="global-search-open" class="settings-open global-search-open tv-focus" data-group="tools" type="button" aria-label="Open global search" title="Global Search">⌕</button><button id="settings-open" class="settings-open tv-focus" data-group="tools" type="button" aria-label="Open PCGA Control Center" title="PCGA Control Center">⚙</button></div></header>
  <section class="launcher-wrap" aria-label="Tools"><div id="launcher" class="launcher"></div></section>
  <footer class="footer"><span id="updated">Connecting…</span><span id="home-nav-hint">Arrow keys navigate every portal panel; mouse hover and keyboard selection stay synchronized.</span></footer>
</main>
<section id="home-media-surface" class="home-media-surface" aria-hidden="true" aria-label="Continue and recent media" tabindex="-1">
  <header class="home-media-head"><div><div class="home-media-title">Continue & Recent</div><div class="home-media-sub">Resume media or games, or jump into what just arrived.</div></div><div class="home-media-return" role="button" tabindex="-1" data-home-return><b aria-hidden="true">↑</b><span>Up from the top row returns home</span></div></header>
  <div id="home-media-body" class="home-media-body"><div class="home-media-loading">Media shelf is ready when enabled.</div></div>
</section>
<script>
const PORTAL_BUILD_VERSION='0.19.13';const STATUS_KEY='pcga-tv-status-v0.19.0';let modalTimer=null;let lastStatusError='';let lastToolFocus=null;let musicSession=null;let externalMusicSession=null;let musicQueue=[];let musicQueueIndex=-1;let musicView='home';let musicSearch='';let musicParentId='';let musicParentName='';let portalPlayer={active:false,item:null,play_session_id:'',media_source_id:'',started:false};let audioHubMode='music';let podcastResults=[];let podcastFeed=null;let podcastSubscriptions=[];let audiobookResults=[];let audiobookCollection=[];let audiobookRecentUploads=[];let audiobookDetail=null;let pcgaAudioPlayer={active:false,kind:'',item:null,queue:[],index:-1};let pcgaAudioProgressAt=0;let libraryItems=[];let libraryFilter='all';let librarySearch='';let libraryReturnFocus=null;let librarySeries=null;let gameItems=[];let gamePlatforms=[];let gamePlatform='';let gameSearch='';let gameReturnFocus=null;let romCollectionPlatforms=[];let romCollectionItems=[];let romCollectionPlatform='';let romCollectionSearch='';let romCollectionPage=1;let romCollectionTimer=null;let pcGameItems=[];let pcGameSearch='';let pcGameReturnFocus=null;let storeLibraryItems=[];let storeLibrarySearch='';let storeLibraryProvider='all';let storeJobsTimer=null;let pcGameDiscItems=[];let pcGameDiscSets=[];let pcGameDiscSearch='';let pcGameDiscSelectedFingerprint='';let pcGameMetadataResults=[];let pcGameMetadataSelected=-1;let pcGameMetadataPreview=null;let pcGameMetadataSearchTerms=[];let pcGameMetadataContext={setId:'',fingerprint:'',returnMode:'library'};let videoPortalPlayer={active:false,item:null,play_session_id:'',media_source_id:'',started:false,start_ticks:0,quality:'auto',audio_stream_index:null,subtitle_stream_index:-1,audio_streams:[],subtitle_streams:[],quality_options:[],video_stream:null};const audio=document.getElementById('pcga-audio');const videoPlayer=document.getElementById('jellyfin-video-player');const VIDEO_PREFS_KEY='pcga-video-player-v1';let videoPrefs={quality:'auto',speed:1,fit:'contain'};try{videoPrefs={...videoPrefs,...JSON.parse(localStorage.getItem(VIDEO_PREFS_KEY)||'{}')}}catch(_){}
const PORTAL_SETTINGS_KEY='pcga-portal-customization-v1';
const PORTAL_THEMES={classic:{name:'PCGA Glass',desc:'The existing horizontal glass launcher and control-center layout.',preview:'classic'},'wii-aero':{name:'Aero Channels',desc:'A Wii-inspired channel grid with bright Frutiger Aero glass, sky, grass, and controller-friendly tiles.',preview:'wii-aero'},'couch-grid':{name:'Couch Grid',desc:'Large TV tiles with strong focus states for gamepad use from across the room.',preview:'couch-grid'},'desk-compact':{name:'Desk Compact',desc:'A denser dashboard for keyboard, mouse, administration, and smaller desktop displays.',preview:'desk-compact'},'arcade-crt':{name:'Arcade CRT',desc:'A controller-friendly retro grid with scanlines, monospace labels, and palette-colored phosphor glow.',preview:'arcade-crt'},'high-contrast':{name:'High Contrast',desc:'Reduced glass, solid surfaces, strong borders, and oversized focus indicators for readability.',preview:'high-contrast'}};
const PORTAL_SCHEMES={ember:{name:'Ember',desc:'Warm amber and dark brown',bg:'#1a110b',bgDeep:'#090604',panel:'#2a190e',accent:'#e8a15e',text:'#fff4e6'},midnight:{name:'Midnight',desc:'Deep navy with cool blue',bg:'#0b1320',bgDeep:'#04070d',panel:'#111f31',accent:'#62b5ff',text:'#edf7ff'},forest:{name:'Forest',desc:'Dark green with soft mint',bg:'#0d1813',bgDeep:'#050a07',panel:'#13251c',accent:'#78c58f',text:'#edf9f0'},plum:{name:'Plum',desc:'Deep violet with lavender',bg:'#180f1e',bgDeep:'#08050b',panel:'#28152f',accent:'#d291ff',text:'#fbf1ff'},graphite:{name:'Graphite',desc:'Neutral charcoal and silver',bg:'#151719',bgDeep:'#08090a',panel:'#22262b',accent:'#c3ced8',text:'#f3f6f8'},ocean:{name:'Ocean',desc:'Deep teal with aqua',bg:'#071a1d',bgDeep:'#031012',panel:'#0d2a2d',accent:'#4fd1c5',text:'#e9fffd'},burgundy:{name:'Burgundy',desc:'Dark wine with rose',bg:'#1c0b10',bgDeep:'#0b0406',panel:'#2b1119',accent:'#ef7d9a',text:'#fff0f4'},terminal:{name:'Terminal',desc:'Near-black with phosphor green',bg:'#07110a',bgDeep:'#020503',panel:'#0d1e12',accent:'#72e68f',text:'#eaffef'}};
const PORTAL_FONTS={system:{name:'System sans',stack:'system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif'},humanist:{name:'Humanist sans',stack:'"Trebuchet MS","Segoe UI",Verdana,sans-serif'},rounded:{name:'Rounded sans',stack:'ui-rounded,"Arial Rounded MT Bold","Avenir Next Rounded","Trebuchet MS",sans-serif'},geometric:{name:'Geometric sans',stack:'"Avenir Next","Century Gothic",Futura,"Trebuchet MS",sans-serif'},readable:{name:'Readable sans',stack:'Verdana,Tahoma,"DejaVu Sans",sans-serif'},serif:{name:'Book serif',stack:'Georgia,"Times New Roman",ui-serif,serif'},mono:{name:'Monospace',stack:'ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace'}};
const PORTAL_DEFAULTS={layoutMode:'auto',uiTheme:'classic',appearanceMode:'dark',surfaceStyle:'theme',fontStyle:'theme',clock:false,clockStyle:'digital',clockFace:'classic',clockPosition:'top-left',clockFormat:'12',clockBoxed:true,homeMediaEnabled:false,homeMediaGames:true,homeMediaContinue:true,homeMediaRecent:true,homeMediaAdded:true,radius:26,pattern:'ambient',backgroundMotion:'standard',parallaxAmbient:30,parallaxPattern:65,parallaxMedia:45,scheme:'ember',videoOpacity:70,videoId:'',videoSourceId:'',videoName:'',photoId:'',photoName:'',slideshowQuery:'',slideshowInterval:20,pcGameTransport:'auto'};
const videoSeek=document.getElementById('video-seek');const videoTimeCurrent=document.getElementById('video-time-current');const videoTimeTotal=document.getElementById('video-time-total');const videoPlayPause=document.getElementById('video-playpause');const videoMute=document.getElementById('video-mute');const videoVolume=document.getElementById('video-volume');const videoQuality=document.getElementById('video-quality');const videoAudioTrack=document.getElementById('video-audio-track');const videoSubtitleTrack=document.getElementById('video-subtitle-track');const videoSpeed=document.getElementById('video-speed');const videoFit=document.getElementById('video-fit');const videoStreamBadge=document.getElementById('video-stream-badge');let videoSeekDragging=false;let videoReconfigureBusy=false;function saveVideoPrefs(){try{localStorage.setItem(VIDEO_PREFS_KEY,JSON.stringify(videoPrefs))}catch(_){}}
let portalSettings={...PORTAL_DEFAULTS};let globalSearchQuery='';let globalSearchSections=[];let globalSearchReturnFocus=null;let homeMediaSections=[];let homeMediaLookup=new Map();let homeMediaLoadedAt=0;let homeMediaBusy=false;let homeMediaReturnFocus=null;let homeMediaReturnTool='';let homeMediaLastFocus=null;let clockTimer=null;let settingsReturnFocus=null;let backgroundItems=[];let photoItems=[];let photoSearch='';let photoReturnFocus=null;let photoViewerItem=null;let slideshowItems=[];let slideshowTimer=null;let slideshowIndex=0;let controlState=null;let controlSection='display';let latestStatus=null;let latestTools=[];let controlBusy=false;let diagnosticCatalog=null;let diagnosticCatalogAt=0;let diagnosticProfile='streaming';let diagnosticTimer=null;let diagnosticBusy=false;let diagnosticLogs={};let reviewItems=[];let reviewSelectedId='';let reviewLibraryItems=[];let reviewLibrarySelectedId='';let reviewMode='queue';let reviewReturnFocus=null;let reviewMetadataResults=[];let reviewMetadataSource='';let uploadFiles=[];let uploadPlatforms=[];let uploadJobs=[];let uploadBusy=false;let uploadReturnFocus=null;let uploadJobTimer=null;let uploadPreferredKind='auto';let uploadSelectedPlatform='';let uploadAdvancedOpen=false;let uploadHistoryOpen=false;let uploadAudiobookMeta={title:'',author:''};
const bgVideo=document.getElementById('background-video');const bgPhoto=document.getElementById('background-photo');
const reducedMotion=window.matchMedia?.('(prefers-reduced-motion: reduce)');const preferredDark=window.matchMedia?.('(prefers-color-scheme: dark)');let parallaxTarget={x:0,y:0},parallaxCurrent={x:0,y:0},parallaxFrame=0;
function clamp(n,a,b){n=Number(n);return Number.isFinite(n)?Math.max(a,Math.min(b,n)):a}
function parallaxEnabled(){return portalSettings.backgroundMotion==='parallax'&&!reducedMotion?.matches}
function writeParallax(x,y){const px=(depth)=>42*(clamp(depth,0,100)/100);const a=px(portalSettings.parallaxAmbient),p=px(portalSettings.parallaxPattern),m=px(portalSettings.parallaxMedia);setVar('--parallax-ambient-x',`${(-x*a).toFixed(2)}px`);setVar('--parallax-ambient-y',`${(-y*a).toFixed(2)}px`);setVar('--parallax-pattern-x',`${(-x*p).toFixed(2)}px`);setVar('--parallax-pattern-y',`${(-y*p).toFixed(2)}px`);setVar('--parallax-media-x',`${(-x*m).toFixed(2)}px`);setVar('--parallax-media-y',`${(-y*m).toFixed(2)}px`)}
function tickParallax(){parallaxFrame=0;const tx=parallaxEnabled()?parallaxTarget.x:0,ty=parallaxEnabled()?parallaxTarget.y:0;parallaxCurrent.x+=(tx-parallaxCurrent.x)*.14;parallaxCurrent.y+=(ty-parallaxCurrent.y)*.14;writeParallax(parallaxCurrent.x,parallaxCurrent.y);if(Math.abs(tx-parallaxCurrent.x)>.002||Math.abs(ty-parallaxCurrent.y)>.002)parallaxFrame=requestAnimationFrame(tickParallax)}
function setParallaxTarget(x=0,y=0){parallaxTarget.x=clamp(x,-1,1);parallaxTarget.y=clamp(y,-1,1);if(!parallaxFrame)parallaxFrame=requestAnimationFrame(tickParallax)}
function setParallaxFromPoint(x,y){if(!parallaxEnabled())return setParallaxTarget(0,0);setParallaxTarget((x/window.innerWidth-.5)*2,(y/window.innerHeight-.5)*2)}
function resetParallax(){setParallaxTarget(0,0)}
reducedMotion?.addEventListener?.('change',()=>{document.body.dataset.bgMotion=parallaxEnabled()?'parallax':'standard';resetParallax();syncSettingsControls()});
preferredDark?.addEventListener?.('change',()=>{if(portalSettings.appearanceMode==='auto')applyPortalSettings()});
function validHex(v,fallback){return/^#[0-9a-f]{6}$/i.test(String(v||''))?String(v):fallback}
function hexRgb(hex){hex=validHex(hex,'#000000').slice(1);return[parseInt(hex.slice(0,2),16),parseInt(hex.slice(2,4),16),parseInt(hex.slice(4,6),16)]}
function mixHex(a,b,t){const A=hexRgb(a),B=hexRgb(b);return'#'+A.map((v,i)=>Math.round(v+(B[i]-v)*t).toString(16).padStart(2,'0')).join('')}
function nearestScheme(raw){const colors=['bg','bgDeep','panel','accent','text'];if(!colors.some(k=>/^#[0-9a-f]{6}$/i.test(String(raw?.[k]||''))))return PORTAL_DEFAULTS.scheme;let best=PORTAL_DEFAULTS.scheme,bestScore=Infinity;for(const[id,t]of Object.entries(PORTAL_SCHEMES)){let score=0;for(const k of colors){const a=hexRgb(validHex(raw[k],t[k])),b=hexRgb(t[k]);score+=a.reduce((n,v,i)=>n+(v-b[i])*(v-b[i]),0)}if(score<bestScore){best=id;bestScore=score}}return best}
function normalizePortalSettings(raw){raw=raw&&typeof raw==='object'?raw:{};const patterns=new Set(['ambient','solid','grid','dots','diagonal','photo','slideshow','video']);const motions=new Set(['standard','parallax']);const layouts=new Set(['auto','tv','desktop','ultrawide','tablet','mobile']);const appearances=new Set(['auto','light','dark']);const surfaces=new Set(['theme','frosted','crystal','solid']);const fonts=new Set(['theme','system','humanist','rounded','geometric','readable','serif','mono']);const clockPositions=new Set(['top-left','top-center','top-right','bottom-left','bottom-center','bottom-right']);const clockStyles=new Set(['digital','analog']);const clockFaces=new Set(['classic','minimal','roman','railway']);const streamTransports=new Set(['websocket','webrtc','auto']);const scheme=PORTAL_SCHEMES[raw.scheme]?raw.scheme:nearestScheme(raw);const uiTheme=PORTAL_THEMES[raw.uiTheme]?raw.uiTheme:PORTAL_DEFAULTS.uiTheme;const appearanceMode=appearances.has(raw.appearanceMode)?raw.appearanceMode:(uiTheme==='wii-aero'?'light':PORTAL_DEFAULTS.appearanceMode);const surfaceStyle=surfaces.has(raw.surfaceStyle)?raw.surfaceStyle:PORTAL_DEFAULTS.surfaceStyle;const fontStyle=fonts.has(raw.fontStyle)?raw.fontStyle:PORTAL_DEFAULTS.fontStyle;const layoutMode=layouts.has(raw.layoutMode)?raw.layoutMode:PORTAL_DEFAULTS.layoutMode;return{layoutMode,uiTheme,appearanceMode,surfaceStyle,fontStyle,clock:!!raw.clock,clockStyle:clockStyles.has(raw.clockStyle)?raw.clockStyle:PORTAL_DEFAULTS.clockStyle,clockFace:clockFaces.has(raw.clockFace)?raw.clockFace:PORTAL_DEFAULTS.clockFace,clockPosition:clockPositions.has(raw.clockPosition)?raw.clockPosition:PORTAL_DEFAULTS.clockPosition,clockFormat:raw.clockFormat==='24'?'24':'12',clockBoxed:raw.clockBoxed!==false,homeMediaEnabled:raw.homeMediaEnabled===true,homeMediaGames:raw.homeMediaGames!==false,homeMediaContinue:raw.homeMediaContinue!==false,homeMediaRecent:raw.homeMediaRecent!==false,homeMediaAdded:raw.homeMediaAdded!==false,radius:clamp(raw.radius??PORTAL_DEFAULTS.radius,0,30),pattern:patterns.has(raw.pattern)?raw.pattern:'ambient',backgroundMotion:motions.has(raw.backgroundMotion)?raw.backgroundMotion:'standard',parallaxAmbient:clamp(raw.parallaxAmbient??(raw.parallaxDepth!=null?Number(raw.parallaxDepth)*.67:PORTAL_DEFAULTS.parallaxAmbient),0,100),parallaxPattern:clamp(raw.parallaxPattern??(raw.parallaxDepth!=null?raw.parallaxDepth:PORTAL_DEFAULTS.parallaxPattern),0,100),parallaxMedia:clamp(raw.parallaxMedia??(raw.parallaxDepth!=null?raw.parallaxDepth:PORTAL_DEFAULTS.parallaxMedia),0,100),scheme,videoOpacity:clamp(raw.videoOpacity??PORTAL_DEFAULTS.videoOpacity,20,100),videoId:/^[A-Za-z0-9_-]{1,160}$/.test(String(raw.videoId||''))?String(raw.videoId):'',videoSourceId:/^[A-Za-z0-9_-]{1,160}$/.test(String(raw.videoSourceId||''))?String(raw.videoSourceId):'',videoName:String(raw.videoName||'').slice(0,160),photoId:/^[A-Za-z0-9_-]{1,4096}$/.test(String(raw.photoId||''))?String(raw.photoId):'',photoName:String(raw.photoName||'').slice(0,220),slideshowQuery:String(raw.slideshowQuery||'').slice(0,120),slideshowInterval:clamp(raw.slideshowInterval??PORTAL_DEFAULTS.slideshowInterval,5,120),pcGameTransport:streamTransports.has(raw.pcGameTransport)?raw.pcGameTransport:PORTAL_DEFAULTS.pcGameTransport}}
function detectDeviceLayout(){const w=Math.max(document.documentElement.clientWidth||0,window.innerWidth||0),h=Math.max(document.documentElement.clientHeight||0,window.innerHeight||0),shortSide=Math.min(w,h),aspect=h>0?w/h:1,coarse=!!window.matchMedia?.('(pointer: coarse)')?.matches,noHover=!!window.matchMedia?.('(hover: none)')?.matches,remoteLike=coarse||noHover;if(w<=680||(remoteLike&&shortSide<=600))return'mobile';if(remoteLike&&w>=1600&&shortSide>=800)return'tv';if(w<=1180||remoteLike)return'tablet';if(w>=1800&&aspect>=2.05)return'ultrawide';return'desktop'}
function activeDeviceLayout(){const requested=portalSettings.layoutMode||PORTAL_DEFAULTS.layoutMode;return requested==='auto'?detectDeviceLayout():requested}
function applyDeviceLayout(){const requested=portalSettings.layoutMode||PORTAL_DEFAULTS.layoutMode,active=activeDeviceLayout(),w=Math.max(document.documentElement.clientWidth||0,window.innerWidth||0),h=Math.max(document.documentElement.clientHeight||0,window.innerHeight||0),aspect=h>0?w/h:1;document.body.dataset.deviceLayout=active;document.body.dataset.layoutMode=requested;document.body.dataset.screenShape=aspect>=3?'super-ultrawide':aspect>=2.05?'ultrawide':'standard';const note=document.getElementById('layout-current');if(note){const shape=active==='ultrawide'?` (${aspect.toFixed(2)}:1 viewport)` :'';note.textContent=requested==='auto'?`Automatic currently resolves this browser to ${active}${shape}. Resize or rotate the display and PCGA will adapt automatically.`:`This display is forced to the ${active} layout${shape}. Choose Automatic to resume device detection.`}return active}
let pcgaLayoutResizeTimer=0;window.addEventListener('resize',()=>{if((portalSettings.layoutMode||'auto')!=='auto')return;clearTimeout(pcgaLayoutResizeTimer);pcgaLayoutResizeTimer=setTimeout(()=>applyDeviceLayout(),120)},{passive:true});window.addEventListener('orientationchange',()=>{if((portalSettings.layoutMode||'auto')==='auto')setTimeout(()=>applyDeviceLayout(),80)},{passive:true});
function loadPortalSettings(){try{portalSettings=normalizePortalSettings(JSON.parse(localStorage.getItem(PORTAL_SETTINGS_KEY)||'{}'))}catch(_){portalSettings={...PORTAL_DEFAULTS}}}
function savePortalSettings(){portalSettings=normalizePortalSettings(portalSettings);try{localStorage.setItem(PORTAL_SETTINGS_KEY,JSON.stringify(portalSettings))}catch(_){}applyPortalSettings()}
function setVar(name,val){document.documentElement.style.setProperty(name,val)}
function videoUrl(){if(!portalSettings.videoId)return'';const q=portalSettings.videoSourceId?`?media_source_id=${encodeURIComponent(portalSettings.videoSourceId)}`:'';return`/api/jellyfin/video/${encodeURIComponent(portalSettings.videoId)}${q}`}
function stopBackgroundVideo(){bgVideo.pause();bgVideo.classList.remove('show');if(bgVideo.getAttribute('src')){bgVideo.removeAttribute('src');bgVideo.load()}}
function applyBackgroundVideo(){if(portalSettings.pattern!=='video'||!portalSettings.videoId){stopBackgroundVideo();return}const src=videoUrl();if(bgVideo.getAttribute('src')!==src){bgVideo.src=src;bgVideo.load()}bgVideo.muted=true;bgVideo.volume=0;bgVideo.loop=true;bgVideo.playsInline=true;try{if(bgVideo.audioTracks)for(const track of bgVideo.audioTracks)track.enabled=false}catch(_){}bgVideo.classList.add('show');const p=bgVideo.play();if(p?.catch)p.catch(()=>{})}
function stopBackgroundPhoto(){if(slideshowTimer){clearInterval(slideshowTimer);slideshowTimer=null}bgPhoto.classList.remove('show');bgPhoto.removeAttribute('src');slideshowItems=[];slideshowIndex=0}
function setBackgroundPhotoSrc(url){if(!url)return;bgPhoto.classList.remove('show');const done=()=>{bgPhoto.classList.add('show');bgPhoto.removeEventListener('load',done)};bgPhoto.addEventListener('load',done);bgPhoto.src=url}
async function loadSlideshow(){if(portalSettings.pattern!=='slideshow'){stopBackgroundPhoto();return}if(slideshowTimer){clearInterval(slideshowTimer);slideshowTimer=null}const q=new URLSearchParams({limit:'120'});if(portalSettings.slideshowQuery)q.set('search',portalSettings.slideshowQuery);try{const r=await fetch('/api/photos/library?'+q.toString(),{cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(d.error||r.status);slideshowItems=d.items||[];if(!slideshowItems.length){stopBackgroundPhoto();return}slideshowIndex=Math.floor(Math.random()*slideshowItems.length);setBackgroundPhotoSrc(slideshowItems[slideshowIndex].url);slideshowTimer=setInterval(()=>{if(!slideshowItems.length)return;slideshowIndex=(slideshowIndex+1)%slideshowItems.length;setBackgroundPhotoSrc(slideshowItems[slideshowIndex].url)},portalSettings.slideshowInterval*1000)}catch(_){stopBackgroundPhoto()}}
function applyPhotoBackground(){if(portalSettings.pattern==='photo'&&portalSettings.photoId){if(slideshowTimer){clearInterval(slideshowTimer);slideshowTimer=null}setBackgroundPhotoSrc(`/api/photos/file/${encodeURIComponent(portalSettings.photoId)}`);return}if(portalSettings.pattern==='slideshow'){loadSlideshow();return}stopBackgroundPhoto()}

function updateClock(){const el=document.getElementById('portal-clock');el.dataset.position=portalSettings.clockPosition;el.dataset.boxed=portalSettings.clockBoxed?'true':'false';el.dataset.style=portalSettings.clockStyle;el.dataset.face=portalSettings.clockFace;const analog=document.getElementById('clock-analog');if(analog)analog.setAttribute('aria-hidden',portalSettings.clockStyle==='analog'?'false':'true');if(!portalSettings.clock){el.classList.remove('show');return}el.classList.add('show');const now=new Date(),dateText=now.toLocaleDateString([], {weekday:'long',month:'short',day:'numeric'});document.getElementById('clock-time').textContent=now.toLocaleTimeString([], {hour:'numeric',minute:'2-digit',hour12:portalSettings.clockFormat!=='24'});document.getElementById('clock-date-digital').textContent=dateText;document.getElementById('clock-date-analog').textContent=dateText;const nums=document.querySelectorAll('.analog-number');const faceNums=portalSettings.clockFace==='roman'?['XII','III','VI','IX']:['12','3','6','9'];nums.forEach((node,i)=>{node.textContent=faceNums[i]||node.textContent});const sec=now.getSeconds()+now.getMilliseconds()/1000,min=now.getMinutes()+sec/60,hour=(now.getHours()%12)+min/60;document.getElementById('clock-hour-hand').style.transform=`translateX(-50%) rotate(${hour*30}deg)`;document.getElementById('clock-minute-hand').style.transform=`translateX(-50%) rotate(${min*6}deg)`;document.getElementById('clock-second-hand').style.transform=`translateX(-50%) rotate(${sec*6}deg)`}
function renderThemeOptions(){const box=document.getElementById('theme-grid');if(!box)return;box.innerHTML=Object.entries(PORTAL_THEMES).map(([id,t])=>`<button type="button" class="theme-option tv-focus ${id===portalSettings.uiTheme?'selected':''}" role="radio" aria-checked="${id===portalSettings.uiTheme?'true':'false'}" data-group="settings-themes" data-pcga-theme="${id}"><span class="theme-preview ${t.preview}" aria-hidden="true"></span><span><span class="theme-name">${t.name}</span><span class="theme-desc">${t.desc}</span></span></button>`).join('')}
function renderSchemeOptions(){const box=document.getElementById('scheme-grid');if(!box)return;box.innerHTML=Object.entries(PORTAL_SCHEMES).map(([id,t])=>`<button type="button" class="scheme-option tv-focus ${id===portalSettings.scheme?'selected':''}" role="radio" aria-checked="${id===portalSettings.scheme?'true':'false'}" data-group="settings-schemes" data-scheme="${id}"><span class="scheme-swatches" aria-hidden="true"><i class="scheme-swatch" style="background:${t.bgDeep}"></i><i class="scheme-swatch" style="background:${t.panel}"></i><i class="scheme-swatch" style="background:${t.accent}"></i><i class="scheme-swatch" style="background:${t.text}"></i></span><span><span class="scheme-name">${t.name}</span><span class="scheme-desc">${t.desc}</span></span></button>`).join('')}
function syncSettingsControls(){const by=id=>document.getElementById(id);if(!by('setting-clock'))return;if(by('setting-layout-mode'))by('setting-layout-mode').value=portalSettings.layoutMode||'auto';applyDeviceLayout();if(by('setting-appearance-mode'))by('setting-appearance-mode').value=portalSettings.appearanceMode||'auto';if(by('setting-surface-style'))by('setting-surface-style').value=portalSettings.surfaceStyle||'theme';if(by('setting-font-style'))by('setting-font-style').value=portalSettings.fontStyle||'theme';by('setting-clock').checked=portalSettings.clock;by('setting-clock-style').value=portalSettings.clockStyle;by('setting-clock-face').value=portalSettings.clockFace;by('setting-clock-face').disabled=portalSettings.clockStyle!=='analog';by('setting-clock-position').value=portalSettings.clockPosition;by('setting-clock-format').value=portalSettings.clockFormat;by('setting-clock-format').disabled=portalSettings.clockStyle==='analog';by('setting-clock-boxed').checked=portalSettings.clockBoxed;if(by('setting-home-media'))by('setting-home-media').checked=!!portalSettings.homeMediaEnabled;for(const[id,key]of[['setting-home-media-games','homeMediaGames'],['setting-home-media-continue','homeMediaContinue'],['setting-home-media-recent','homeMediaRecent'],['setting-home-media-added','homeMediaAdded']]){if(by(id)){by(id).checked=!!portalSettings[key];by(id).disabled=!portalSettings.homeMediaEnabled}}by('setting-radius').value=portalSettings.radius;by('radius-readout').textContent=`${portalSettings.radius} px`;by('setting-pattern').value=portalSettings.pattern;by('setting-background-motion').value=portalSettings.backgroundMotion;for(const [id,key,out] of [['setting-parallax-ambient','parallaxAmbient','parallax-ambient-readout'],['setting-parallax-pattern','parallaxPattern','parallax-pattern-readout'],['setting-parallax-media','parallaxMedia','parallax-media-readout']]){if(by(id)){by(id).value=portalSettings[key];by(id).disabled=portalSettings.backgroundMotion!=='parallax'||!!reducedMotion?.matches;by(out).textContent=reducedMotion?.matches?'Reduced motion':`${portalSettings[key]}%`}};by('setting-video-opacity').value=portalSettings.videoOpacity;by('video-opacity-readout').textContent=`${portalSettings.videoOpacity}%`;by('background-current').textContent=portalSettings.videoId?`Selected: ${portalSettings.videoName||portalSettings.videoId}`:'No Jellyfin background selected.';renderSchemeOptions();renderBackgroundResults(backgroundItems);by('setting-slideshow-interval').value=portalSettings.slideshowInterval;by('slideshow-interval-readout').textContent=`${portalSettings.slideshowInterval}s`;renderThemeOptions();by('photo-background-current').textContent=portalSettings.photoId?`Wallpaper: ${portalSettings.photoName||portalSettings.photoId}`:(portalSettings.slideshowQuery?`Slideshow filter: ${portalSettings.slideshowQuery}`:'No photo wallpaper selected.');if(by('setting-pc-game-transport'))by('setting-pc-game-transport').value=portalSettings.pcGameTransport}
function resolvedAppearanceMode(){if(portalSettings.appearanceMode==='light'||portalSettings.appearanceMode==='dark')return portalSettings.appearanceMode;return preferredDark?.matches===false?'light':'dark'}
function applyPortalSettings(){applyDeviceLayout();document.body.dataset.uiTheme=portalSettings.uiTheme||PORTAL_DEFAULTS.uiTheme;document.body.dataset.surfaceStyle=portalSettings.surfaceStyle||PORTAL_DEFAULTS.surfaceStyle;document.body.dataset.fontStyle=portalSettings.fontStyle||PORTAL_DEFAULTS.fontStyle;const base=PORTAL_SCHEMES[portalSettings.scheme]||PORTAL_SCHEMES[PORTAL_DEFAULTS.scheme],layout=portalSettings.uiTheme||PORTAL_DEFAULTS.uiTheme,aero=layout==='wii-aero',mode=resolvedAppearanceMode(),light=mode==='light',accent=base.accent,bg=light?mixHex('#ffffff',accent,.055):base.bg,bgDeep=light?mixHex('#f1f4f6',accent,.055):base.bgDeep,panel=light?mixHex('#ffffff',accent,.025):base.panel,baseText=light?mixHex('#11161c',accent,.055):base.text,ar=hexRgb(accent),pr=hexRgb(panel),br=hexRgb(bgDeep),accentDark=light?mixHex(accent,'#101418',.26):mixHex(accent,bgDeep,.34),aeroInk=light?mixHex('#12212a',accent,.10):mixHex('#eef8fb',accent,.08),aeroMuted=light?mixHex(aeroInk,'#ffffff',.42):mixHex(aeroInk,'#071117',.34),aeroGlass=light?mixHex('#ffffff',accent,.055):mixHex('#10222c',accent,.12),aeroGlass2=light?mixHex('#ffffff',accent,.025):mixHex('#0a171f',accent,.10),aeroSky=light?mixHex('#86d7ef',accent,.24):mixHex('#071928',accent,.22),aeroSky2=light?mixHex('#edfaff',accent,.08):mixHex('#153440',accent,.18),aeroField=light?mixHex('#83d866',accent,.16):mixHex('#153a28',accent,.16),aeroFieldDeep=light?mixHex('#52ad4b',accent,.14):mixHex('#071f16',accent,.12),text=aero?aeroInk:baseText,muted=aero?aeroMuted:(light?mixHex(baseText,'#ffffff',.42):mixHex(base.text,base.bgDeep,.38)),panelRgb=aero?hexRgb(aeroGlass):pr,surfaceInk=light?'0,0,0':'255,255,255',fontStyle=portalSettings.fontStyle||PORTAL_DEFAULTS.fontStyle,themeFont=layout==='wii-aero'?'"Trebuchet MS",Verdana,system-ui,-apple-system,"Segoe UI",sans-serif':layout==='arcade-crt'?'ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace':'system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif',fontStack=fontStyle==='theme'?themeFont:(PORTAL_FONTS[fontStyle]?.stack||themeFont);document.body.dataset.colorMode=mode;setVar('--ui-font-family',fontStack);setVar('--ui-radius',`${portalSettings.radius}px`);setVar('--bg-base',bg);setVar('--bg-deep',bgDeep);setVar('--bg-deep-rgb',br.join(','));setVar('--panel-color',aero?aeroGlass:panel);setVar('--panel-rgb',panelRgb.join(','));setVar('--glass',`rgba(${panelRgb.join(',')},${light?'.66':'.54'})`);setVar('--panel-surface',`rgba(${panelRgb.join(',')},${light?'.90':'.88'})`);setVar('--panel-solid',`rgba(${panelRgb.join(',')},${light?'.98':'.97'})`);setVar('--surface-low',`rgba(${surfaceInk},${light?'.035':'.035'})`);setVar('--surface-mid',`rgba(${surfaceInk},${light?'.06':'.065'})`);setVar('--surface-high',`rgba(${surfaceInk},${light?'.09':'.10'})`);setVar('--accent',accent);setVar('--blue',accent);setVar('--accent-rgb',ar.join(','));setVar('--accent-soft',`rgba(${ar.join(',')},${light?'.18':'.22'})`);setVar('--accent-faint',`rgba(${ar.join(',')},.10)`);setVar('--accent-medium',`rgba(${ar.join(',')},.16)`);setVar('--accent-strong',`rgba(${ar.join(',')},${light?'.28':'.34'})`);setVar('--focus-ring',`rgba(${ar.join(',')},.95)`);setVar('--ui-text',text);setVar('--text',text);setVar('--muted',muted);setVar('--line',`rgba(${ar.join(',')},${light?'.36':'.28'})`);setVar('--theme-ink',aeroInk);setVar('--theme-muted',aeroMuted);setVar('--theme-accent-dark',accentDark);setVar('--theme-glass',`rgba(${hexRgb(aeroGlass).join(',')},${light?'.90':'.92'})`);setVar('--theme-glass-solid',`rgba(${hexRgb(aeroGlass2).join(',')},${light?'.98':'.98'})`);setVar('--theme-line',`rgba(${ar.join(',')},${light?'.38':'.42'})`);setVar('--aero-sky-top',aeroSky);setVar('--aero-sky-bottom',aeroSky2);setVar('--aero-field',aeroField);setVar('--aero-field-deep',aeroFieldDeep);setVar('--video-opacity',String(portalSettings.videoOpacity/100));setVar('--video-scrim',`rgba(${br.join(',')},${light?Math.max(.08,.36-(portalSettings.videoOpacity/100)*.18).toFixed(2):Math.max(.14,.62-(portalSettings.videoOpacity/100)*.38).toFixed(2)})`);document.documentElement.style.colorScheme=mode;document.body.dataset.bgPattern=portalSettings.pattern;document.body.dataset.bgMotion=parallaxEnabled()?'parallax':'standard';document.body.dataset.clockPosition=portalSettings.clock?portalSettings.clockPosition:'off';if(!parallaxEnabled())resetParallax();else writeParallax(parallaxCurrent.x,parallaxCurrent.y);updateClock();applyBackgroundVideo();applyPhotoBackground();syncSettingsControls();const homeHint=document.getElementById('home-nav-hint');if(homeHint)homeHint.textContent=portalSettings.homeMediaEnabled?'↓ from the bottom row opens Continue & Recent; ↑ from its top row returns home.':'Arrow keys navigate every portal panel; mouse hover and keyboard selection stay synchronized.';if(!portalSettings.homeMediaEnabled&&document.body.classList.contains('media-surface-open'))closeHomeMediaSurface(false);else if(document.body.classList.contains('media-surface-open'))renderHomeMediaSurface()}
function renderBackgroundResults(items){const box=document.getElementById('background-results');if(!box)return;items=items||[];if(!items.length){box.innerHTML='<div class="settings-note">Search Jellyfin to choose a movie, episode, music video, trailer, or other video item.</div>';return}box.innerHTML=items.map((x,i)=>`<button type="button" class="bg-media-item ${x.id===portalSettings.videoId?'selected':''}" data-bg-item="${i}">${x.art_url?`<img class="bg-media-art" src="${esc(x.art_url)}" alt="">`:'<span class="bg-media-placeholder">▶</span>'}<div class="bg-media-name">${esc(x.name)}</div><div class="bg-media-meta">${esc(x.subtitle||x.type||'Video')}${x.video_codec?` • ${esc(x.video_codec)}`:''}</div></button>`).join('')}
async function loadBackgroundLibrary(search=''){const box=document.getElementById('background-results');if(box)box.innerHTML='<div class="settings-note">Loading Jellyfin videos…</div>';const q=new URLSearchParams({limit:'40'});if(search)q.set('search',search);const r=await fetch('/api/jellyfin/background/library?'+q.toString(),{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);backgroundItems=d.items||[];renderBackgroundResults(backgroundItems);return d}
function selectBackgroundItem(item){if(!item)return;portalSettings.videoId=item.id||'';portalSettings.videoSourceId=item.media_source_id||'';portalSettings.videoName=item.name||'';portalSettings.pattern='video';savePortalSettings();showStatus('Background updated',`${portalSettings.videoName||'Jellyfin video'} will loop silently behind the portal.`,'good',4200)}
function updateSettingFromControl(id){const e=document.getElementById(id);if(!e)return;if(id==='setting-layout-mode')portalSettings.layoutMode=e.value;else if(id==='setting-appearance-mode')portalSettings.appearanceMode=e.value;else if(id==='setting-surface-style')portalSettings.surfaceStyle=e.value;else if(id==='setting-font-style')portalSettings.fontStyle=e.value;else if(id==='setting-clock')portalSettings.clock=e.checked;else if(id==='setting-clock-style')portalSettings.clockStyle=e.value;else if(id==='setting-clock-face')portalSettings.clockFace=e.value;else if(id==='setting-clock-position')portalSettings.clockPosition=e.value;else if(id==='setting-clock-format')portalSettings.clockFormat=e.value;else if(id==='setting-clock-boxed')portalSettings.clockBoxed=e.checked;else if(id==='setting-home-media')portalSettings.homeMediaEnabled=e.checked;else if(id==='setting-home-media-games')portalSettings.homeMediaGames=e.checked;else if(id==='setting-home-media-continue')portalSettings.homeMediaContinue=e.checked;else if(id==='setting-home-media-recent')portalSettings.homeMediaRecent=e.checked;else if(id==='setting-home-media-added')portalSettings.homeMediaAdded=e.checked;else if(id==='setting-radius')portalSettings.radius=Number(e.value);else if(id==='setting-pattern')portalSettings.pattern=e.value;else if(id==='setting-background-motion')portalSettings.backgroundMotion=e.value;else if(id==='setting-parallax-ambient')portalSettings.parallaxAmbient=Number(e.value);else if(id==='setting-parallax-pattern')portalSettings.parallaxPattern=Number(e.value);else if(id==='setting-parallax-media')portalSettings.parallaxMedia=Number(e.value);else if(id==='setting-video-opacity')portalSettings.videoOpacity=Number(e.value);else if(id==='setting-slideshow-interval')portalSettings.slideshowInterval=clamp(e.value,5,120);else if(id==='setting-pc-game-transport')portalSettings.pcGameTransport=e.value;if(id==='setting-home-media-games'){homeMediaLoadedAt=0;homeMediaSections=[]}savePortalSettings();if(id==='setting-home-media-games'&&homeMediaOpen())loadHomeMediaSurface(true)}
function diagnosticStateClass(s){return s?.active?'good':'bad'}
function diagnosticServiceIds(){const profile=document.getElementById('diag-profile')?.value||diagnosticProfile||'streaming';diagnosticProfile=profile;const p=diagnosticCatalog?.profiles?.[profile];return Array.isArray(p?.services)?p.services:[]}
async function loadDiagnosticCatalog(force=false){if(diagnosticCatalog&&!force&&Date.now()-diagnosticCatalogAt<8000)return diagnosticCatalog;const r=await fetch('/api/diagnostics/catalog',{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok||!d.ok)throw Error(d.detail||d.error||`HTTP ${r.status}`);diagnosticCatalog=d;diagnosticCatalogAt=Date.now();return d}
function renderDiagnostics(){const grid=document.getElementById('diag-grid'),summary=document.getElementById('diag-summary');if(!grid||!summary)return;const ids=diagnosticServiceIds(),byId=new Map((diagnosticCatalog?.services||[]).map(x=>[x.id,x]));if(!ids.length){grid.innerHTML='<div class="diag-empty">No services are registered for this diagnostic profile.</div>';summary.textContent='No matching services.';return}grid.innerHTML=ids.map(id=>{const svc=byId.get(id)||diagnosticLogs[id]?.service||{id,name:id,source:id,state:'unknown',active:false};const entry=diagnosticLogs[id];const body=entry?.loading?'Loading…':entry?.error?`[diagnostics error] ${entry.error}`:(entry?.log||'[no log entries in selected window]');const kind=svc.kind==='docker'?'container':svc.kind==='file'?'persisted log':'systemd';return `<article class="diag-card" data-diag-service="${esc(id)}"><div class="diag-card-head"><div class="diag-card-title"><strong>${esc(svc.name||svc.source||id)}</strong><span>${esc(kind)} • ${esc(svc.source||id)}</span></div><div class="diag-card-actions"><span class="diag-state ${diagnosticStateClass(svc)}">${esc(svc.health||svc.state||'unknown')}</span><button class="diag-copy tv-focus" type="button" data-diag-copy="${esc(id)}">Copy</button></div></div><pre class="diag-log">${esc(body)}</pre></article>`}).join('');const loaded=ids.filter(id=>diagnosticLogs[id]&&!diagnosticLogs[id].loading).length,errors=ids.filter(id=>diagnosticLogs[id]?.error).length;summary.textContent=`${diagnosticCatalog?.profiles?.[diagnosticProfile]?.label||diagnosticProfile}: ${loaded}/${ids.length} logs loaded${errors?` • ${errors} errors`:''} • secrets are redacted by the host control API • ${new Date().toLocaleTimeString()}`}
async function refreshDiagnostics(forceCatalog=false){if(diagnosticBusy)return;diagnosticBusy=true;try{await loadDiagnosticCatalog(forceCatalog);const ids=diagnosticServiceIds(),lines=Number(document.getElementById('diag-lines')?.value||160),seconds=Number(document.getElementById('diag-window')?.value||900);for(const id of ids)diagnosticLogs[id]={...(diagnosticLogs[id]||{}),service:(diagnosticCatalog.services||[]).find(x=>x.id===id),loading:true};renderDiagnostics();const results=await Promise.all(ids.map(async id=>{try{const q=new URLSearchParams({service:id,lines:String(lines),seconds:String(seconds)}),r=await fetch('/api/diagnostics/logs?'+q.toString(),{cache:'no-store'}),d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||`HTTP ${r.status}`);return[id,d]}catch(e){return[id,{service:(diagnosticCatalog.services||[]).find(x=>x.id===id),error:String(e?.message||e)}]}}));for(const[id,d]of results)diagnosticLogs[id]=d;renderDiagnostics()}catch(e){const summary=document.getElementById('diag-summary');if(summary)summary.textContent=`Diagnostics unavailable: ${e.message||e}`;const grid=document.getElementById('diag-grid');if(grid)grid.innerHTML=`<div class="diag-empty">${esc(e.message||e)}</div>`}finally{diagnosticBusy=false}}
function startDiagnosticTimer(){stopDiagnosticTimer();if(document.getElementById('diag-auto')?.checked)diagnosticTimer=setInterval(()=>{if(controlSection==='diagnostics')refreshDiagnostics().catch(()=>{})},4000)}
function stopDiagnosticTimer(){if(diagnosticTimer){clearInterval(diagnosticTimer);diagnosticTimer=null}}
function downloadDiagnosticSnapshot(){const ids=diagnosticServiceIds(),wanted=new Set(ids),services=(diagnosticCatalog?.services||[]).filter(s=>wanted.has(s.id)),profileDef=diagnosticCatalog?.profiles?.[diagnosticProfile]||{},compactLogs=Object.fromEntries(ids.map(id=>{const src=diagnosticLogs[id]||null;if(!src)return[id,null];const copy={...src};delete copy.service;return[id,copy]})),payload={snapshot_schema:2,pcga_version:PORTAL_BUILD_VERSION,captured_at:new Date().toISOString(),profile:diagnosticProfile,catalog:{ok:diagnosticCatalog?.ok!==false,version:diagnosticCatalog?.version||PORTAL_BUILD_VERSION,generated_at:diagnosticCatalog?.generated_at||null,services,profiles:{[diagnosticProfile]:{label:profileDef.label||diagnosticProfile,services:ids}}},logs:compactLogs};const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`pcga-diagnostics-${diagnosticProfile}-${new Date().toISOString().replace(/[:.]/g,'-')}.json`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}

loadPortalSettings();applyPortalSettings();clockTimer=setInterval(updateClock,1000);

function esc(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}

function pcgaSearchNorm(v){return String(v??'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim().replace(/\s+/g,' ')}
function pcgaEditDistance(a,b){a=String(a||'');b=String(b||'');const row=Array.from({length:b.length+1},(_,i)=>i);for(let i=1;i<=a.length;i++){let prev=row[0];row[0]=i;for(let j=1;j<=b.length;j++){const old=row[j];row[j]=Math.min(row[j]+1,row[j-1]+1,prev+(a[i-1]===b[j-1]?0:1));prev=old}}return row[b.length]}
function pcgaFuzzyScore(q,text){q=pcgaSearchNorm(q);text=pcgaSearchNorm(text);if(!q||!text)return 0;if(q===text)return 1.3;if(text.includes(q))return 1.18;const qs=q.split(' '),ts=text.split(' ');let sum=0,covered=0;for(const x of qs){let best=0;for(const y of ts){if(x===y){best=1;break}if(x.length<=2){if(y.startsWith(x))best=Math.max(best,1);continue}const d=pcgaEditDistance(x,y),r=1-d/Math.max(x.length,y.length);best=Math.max(best,r)}sum+=best;if(best>=.72)covered++}let score=(sum/qs.length)*.96;score*=.72+.28*(covered/qs.length);return score}
function pcgaFuzzyMatch(q,text){const n=pcgaSearchNorm(q).replace(/ /g,'');const t=n.length<=3?.88:n.length<=5?.80:(pcgaSearchNorm(q).includes(' ')?.67:.70);return pcgaFuzzyScore(q,text)>=t}
function toolURL(t){if(t.same_origin)return t.path;return `${location.protocol}//${location.hostname}:${t.port}${t.path||'/'}`}
const PCGA_PLATFORM_PLACEHOLDERS={
  snes:['SNES','Super Nintendo','16-bit console'],sfam:['SFC','Super Famicom','16-bit console'],
  'super-nintendo-original-european-version':['SNES','Super Nintendo','16-bit console'],'super-famicom-shvc-001':['SFC','Super Famicom','16-bit console'],'super-famicom-jr-model-shvc-101':['SFC','Super Famicom','16-bit console'],'new-style-super-nes-model-sns-101':['SNES','Super Nintendo','16-bit console'],
  n64:['N64','Nintendo 64','64-bit console'],'ique-player':['N64','Nintendo 64','64-bit console'],
  nes:['NES','Nintendo','8-bit console'],famicom:['FC','Famicom','8-bit console'],fds:['FDS','Famicom Disk System','8-bit console'],'new-style-nes':['NES','Nintendo','8-bit console'],
  gb:['GB','Game Boy','Handheld'],gbc:['GBC','Game Boy Color','Handheld'],gba:['GBA','Game Boy Advance','Handheld'],'game-boy-pocket':['GB','Game Boy','Handheld'],'game-boy-light':['GB','Game Boy','Handheld'],'game-boy-adavance-sp':['GBA','Game Boy Advance','Handheld'],'game-boy-micro':['GBA','Game Boy Advance','Handheld'],
  nds:['DS','Nintendo DS','Dual-screen handheld'],'nintendo-ds-lite':['DS','Nintendo DS','Dual-screen handheld'],'nintendo-dsi':['DSi','Nintendo DSi','Dual-screen handheld'],'nintendo-dsi-xl':['DSi','Nintendo DSi','Dual-screen handheld'],virtualboy:['VB','Virtual Boy','Nintendo console'],
  psx:['PS1','PlayStation','32-bit console'],psp:['PSP','PlayStation Portable','Handheld'],
  genesis:['GENESIS','Sega Genesis','16-bit console'],'sega-mega-drive-2-slash-genesis':['MD','Mega Drive','16-bit console'],'sega-mega-jet':['MD','Mega Drive','16-bit console'],saturn:['SATURN','Sega Saturn','32-bit console'],segacd:['SEGA CD','Sega CD','CD console'],sega32:['32X','Sega 32X','32-bit add-on'],sms:['SMS','Master System','8-bit console'],gamegear:['GG','Game Gear','Handheld'],
  atari2600:['2600','Atari 2600','Classic console'],'atari-2600-plus':['2600','Atari 2600','Classic console'],atari5200:['5200','Atari 5200','Classic console'],atari7800:['7800','Atari 7800','Classic console'],jaguar:['JAGUAR','Atari Jaguar','64-bit console'],lynx:['LYNX','Atari Lynx','Handheld'],'atari-lynx-mkii':['LYNX','Atari Lynx','Handheld'],
  tg16:['TG16','TurboGrafx-16','16-bit console'],'turbografx-cd':['TG-CD','TurboGrafx-CD','CD console'],supergrafx:['SGX','SuperGrafx','Console'],
  neogeoaes:['NEO GEO','Neo Geo AES','Arcade console'],neogeomvs:['MVS','Neo Geo MVS','Arcade system'],arcade:['ARCADE','Arcade','Coin-op'],
  c64:['C64','Commodore 64','Home computer'],'commodore-64c':['C64','Commodore 64','Home computer'],amiga:['AMIGA','Commodore Amiga','Home computer'],'amiga-cd32':['CD32','Amiga CD32','CD console'],dos:['DOS','DOS PC','Computer'],
  'neo-geo-pocket':['NGP','Neo Geo Pocket','Handheld'],'neo-geo-pocket-color':['NGPC','Neo Geo Pocket Color','Handheld'],wonderswan:['WS','WonderSwan','Handheld'],'wonderswan-color':['WSC','WonderSwan Color','Handheld'],swancrystal:['WSC','SwanCrystal','Handheld'],
  '3do':['3DO','3DO','CD console'],'pc-fx':['PC-FX','NEC PC-FX','CD console'],'philips-cd-i':['CD-i','Philips CD-i','CD console'],colecovision:['COLECO','ColecoVision','Classic console'],zxs:['ZX','ZX Spectrum','Home computer']
};
function fallbackAcronym(name,slug=''){const words=String(name||slug||'Console').replace(/[-_]+/g,' ').trim().split(/\s+/).filter(Boolean);if(words.length===1)return words[0].replace(/[^A-Za-z0-9]+/g,'').slice(0,8).toUpperCase()||'GAME';return words.map(w=>w[0]).join('').slice(0,6).toUpperCase()||'GAME'}
function platformFallbackInfo(slug,name=''){slug=String(slug||'').toLowerCase();const known=PCGA_PLATFORM_PLACEHOLDERS[slug];if(known)return{mark:known[0],label:known[1],kicker:known[2]};const label=String(name||slug.replace(/[-_]+/g,' ')||'Console').trim();return{mark:fallbackAcronym(label,slug),label,kicker:'Console game'}}
function fallbackMarkup(kind,item={}){let mark='MEDIA',label='Media',kicker='Artwork unavailable',klass='media-fallback-generic';if(kind==='platform'){const p=platformFallbackInfo(item.platform_slug,item.platform);mark=p.mark;label=p.label;kicker=p.kicker;klass='platform-fallback'}else{const type=String(item.type||kind||'media').toLowerCase();const defs={movie:['MOVIE','Movie','Poster unavailable'],series:['TV','TV Series','Artwork unavailable'],episode:['EP','TV Episode','Artwork unavailable'],video:['VIDEO','Video','Artwork unavailable'],musicvideo:['MV','Music Video','Artwork unavailable'],music:['♫','Music','Artwork unavailable'],album:['ALBUM','Album','Cover unavailable'],artist:['ARTIST','Artist','Image unavailable'],podcast:['PODCAST','Podcast','Artwork unavailable'],audiobook:['BOOK','Audiobook','Cover unavailable'],pcgame:['PC','PC Game','Cover unavailable'],photo:['PHOTO','Photo','Preview unavailable']};const d=defs[type]||defs[kind]||['MEDIA','Media','Artwork unavailable'];[mark,label,kicker]=d;klass=`media-fallback-${type.replace(/[^a-z0-9_-]+/g,'-')}`}return `<span class="pcga-fallback-art ${klass}" aria-hidden="true"><span class="pcga-fallback-mark">${esc(mark)}</span><span class="pcga-fallback-label">${esc(label)}</span><span class="pcga-fallback-kicker">${esc(kicker)}</span></span>`}
function artStack(url,fallback,classes='library-art',alt=''){const has=!!String(url||'').trim();return `<span class="${classes} pcga-art-stack${has?'':' art-failed'}" data-pcga-art-stack>${fallback}${has?`<img class="pcga-art-image" data-pcga-art-image loading="lazy" src="${esc(url)}" alt="${esc(alt)}">`:''}</span>`}
document.addEventListener('error',e=>{const img=e.target;if(img instanceof HTMLImageElement&&img.matches('[data-pcga-art-image]'))img.closest('[data-pcga-art-stack]')?.classList.add('art-failed')},true);document.addEventListener('load',e=>{const img=e.target;if(img instanceof HTMLImageElement&&img.matches('[data-pcga-art-image]'))img.closest('[data-pcga-art-stack]')?.classList.remove('art-failed')},true);
function toolIcon(id){const common='viewBox=\"0 0 48 48\" aria-hidden=\"true\" focusable=\"false\"';const icons={photos:`<svg ${common}><rect x="6" y="8" width="36" height="32" rx="5"></rect><circle cx="17" cy="18" r="4"></circle><path d="M9 35l10-10 7 7 5-5 8 8"></path></svg>`,jellyfinlibrary:`<svg ${common}><rect x=\"7\" y=\"9\" width=\"34\" height=\"30\" rx=\"4\"></rect><path d=\"M18 17l12 7-12 7z\"></path><path d=\"M11 5h26\"></path></svg>`,jellyfin:`<svg ${common}><circle cx=\"24\" cy=\"24\" r=\"17\"></circle><path d=\"M20 17l12 7-12 7z\"></path></svg>`,immich:`<svg ${common}><rect x=\"7\" y=\"9\" width=\"34\" height=\"30\" rx=\"5\"></rect><circle cx=\"18\" cy=\"19\" r=\"4\"></circle><path d=\"M10 34l9-9 6 6 5-5 8 8\"></path></svg>`,romm:`<svg ${common}><rect x=\"6\" y=\"8\" width=\"36\" height=\"32\" rx=\"5\"></rect><path d=\"M15 22h18c3 0 5 2 6 5l1 5c.5 3-3 5-5 3l-4-4H17l-4 4c-2 2-5.5 0-5-3l1-5c1-3 3-5 6-5z\"></path><path d=\"M16 27h6M19 24v6M31 26h.01M35 29h.01\"></path><path d=\"M13 14h22\"></path></svg>`,lancommander:`<svg ${common}><path d=\"M15 19h18c4 0 7 3 8 8l1 7c.5 3-3 5-5 3l-5-5H16l-5 5c-2 2-5.5 0-5-3l1-7c1-5 4-8 8-8z\"></path><path d=\"M15 25h7M18.5 21.5v7M31.5 24h.01M35 28h.01\"></path></svg>`,wolfden:`<svg ${common}><rect x=\"7\" y=\"10\" width=\"34\" height=\"24\" rx=\"3\"></rect><path d=\"M17 40h14M24 34v6M14 18c4-4 16-4 20 0M18 22c3-3 9-3 12 0M22 26c1-1 3-1 4 0\"></path></svg>`,arm:`<svg ${common}><circle cx=\"24\" cy=\"24\" r=\"17\"></circle><circle cx=\"24\" cy=\"24\" r=\"5\"></circle><path d=\"M24 7v8M41 24h-8M24 41v-8M7 24h8\"></path></svg>`,addmedia:`<svg ${common}><path d="M24 7v34M7 24h34"></path><circle cx="24" cy="24" r="16"></circle></svg>`,review:`<svg ${common}><rect x=\"8\" y=\"10\" width=\"32\" height=\"28\" rx=\"3\"></rect><path d=\"M14 10v28M34 10v28M8 18h6M34 18h6M8 30h6M34 30h6M19 25l4 4 7-8\"></path></svg>`,publicmedia:`<svg ${common}><rect x=\"7\" y=\"10\" width=\"34\" height=\"28\" rx=\"4\"></rect><path d=\"M13 10v28M35 10v28M7 18h6M35 18h6M7 30h6M35 30h6M20 19l9 5-9 5z\"></path></svg>`,api:`<svg ${common}><path d=\"M18 12L8 24l10 12M30 12l10 12-10 12M27 8l-6 32\"></path></svg>`,health:`<svg ${common}><path d=\"M5 25h9l4-9 7 18 5-11 4 7h9\"></path><path d=\"M24 42C13 36 7 29 7 19 7 12 12 8 18 8c4 0 6 2 6 5 0-3 2-5 6-5 6 0 11 4 11 11 0 10-6 17-17 23z\"></path></svg>`};return icons[id]||icons.health}
function showStatus(title,body,tone='good',ms=4500){const box=document.getElementById('status-modal');document.getElementById('status-title').textContent=title;document.getElementById('status-body').textContent=body;box.className=`status-modal show ${tone||'good'}`;clearTimeout(modalTimer);modalTimer=setTimeout(()=>{box.className='status-modal'},Math.max(1200,Number(ms)||4500))}
function humanBytes(n){n=Number(n)||0;const u=['B','KiB','MiB','GiB','TiB'];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++}return`${n.toFixed(i?1:0)} ${u[i]}`}
function renderSystemStrip(d){const strip=document.getElementById('system-strip'),main=document.getElementById('system-strip-main'),meta=document.getElementById('system-strip-meta');if(!strip||!main||!meta)return;const rips=(d.process?.active_ingests||[]).filter(x=>x?.live).length,review=(d.queues?.metadata_pending_items||0)+(d.queues?.manual_unidentified_items||0),used=d.disk?.used_percent;const warn=review>0||d.overall==='review-pending';strip.classList.toggle('warn',warn);main.textContent=warn?'System needs attention':'System healthy';meta.textContent=[Number.isFinite(used)?`${used}% storage`:'',rips?`${rips} rip${rips===1?'':'s'} active`:'No active rip',review?`${review} review item${review===1?'':'s'}`:'Review clear'].filter(Boolean).join(' • ')}
function openSettings(section='display'){settingsReturnFocus=document.activeElement;const modal=document.getElementById('settings-modal');if(!modal)return;modal.classList.add('show');showControlSection(section);syncSettingsControls();loadControlCenter().catch(()=>{});setTimeout(()=>{const target=document.querySelector(`[data-control-tab="${controlSection}"]`)||document.getElementById('settings-close');if(target)pcgaSetSelection(target,{focus:true,scroll:true})},0);if(!backgroundItems.length)loadBackgroundLibrary().catch(()=>{})}
function closeSettings(){const modal=document.getElementById('settings-modal');if(modal)modal.classList.remove('show');stopDiagnosticTimer();settingsReturnFocus?.focus?.();settingsReturnFocus=null}
function showControlSection(name){const allowed=new Set(['display','libraries','ingest','games','media','automation','services','remote','diagnostics','system','advanced']);controlSection=allowed.has(name)?name:'display';document.querySelectorAll('[data-control-section]').forEach(x=>x.classList.toggle('active',x.dataset.controlSection===controlSection));document.querySelectorAll('[data-control-tab]').forEach(x=>x.classList.toggle('active',x.dataset.controlTab===controlSection));if(controlSection==='games'){refreshStoreCompat().catch(()=>{})}if(controlSection==='diagnostics'){refreshDiagnostics().catch(()=>{});startDiagnosticTimer()}else stopDiagnosticTimer()}
async function loadControlCenter(){try{const r=await fetch('/api/control/state',{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);controlState=d;renderControlCenter();try{const sr=await fetch('/api/secure-context',{cache:'no-store'}),sc=await sr.json();const u=document.getElementById('cc-lan-portal'),n=document.getElementById('cc-lan-dns-name');if(u)u.textContent=sc.lan_portal_url||'https://pcga.portal:8443/';if(n)n.textContent=sc.lan_dns_name||'pcga.portal'}catch(_){}}catch(e){controlState=null;document.getElementById('cc-last-action').textContent=`Control plane unavailable: ${e.message||e}`}}
function checked(id,v){const e=document.getElementById(id);if(e)e.checked=!!v}function value(id,v){const e=document.getElementById(id);if(e)e.value=String(v??'')}
function renderControlCenter(){const d=controlState,c=d?.config;if(c){checked('cc-auto-rip',c.ingest?.auto_rip);checked('cc-keep-raw',c.ingest?.keep_raw);checked('cc-auto-classify',c.review?.auto_classify);value('cc-auto-threshold',Math.round((Number(c.review?.auto_threshold)||.9)*100));const tv=document.getElementById('cc-threshold-value');if(tv)tv.textContent=`${Math.round((Number(c.review?.auto_threshold)||.9)*100)}%`;checked('cc-romm-enabled',c.games?.romm_enabled);checked('cc-romm-watch',c.games?.filesystem_watch);value('cc-romm-debounce',c.games?.watch_debounce_seconds||300);checked('cc-hasheous',c.games?.metadata_hasheous);checked('cc-playmatch',c.games?.metadata_playmatch);checked('cc-compat-protondb',c.games?.compat_protondb!==false);checked('cc-compat-playonlinux',c.games?.compat_playonlinux!==false);value('cc-pc-graphics-backend',c.games?.graphics_backend||'auto');const gdb=d?.pc_game_metadata||{},gdbState=document.getElementById('cc-game-db-state'),gdbKey=document.getElementById('cc-rawg-api-key');if(gdbState)gdbState.textContent=gdb.rawg?.configured?'RAWG configured • metadata search ready':'RAWG API key required';if(gdbKey)gdbKey.placeholder=gdb.rawg?.configured?'Configured — enter a replacement key':'RAWG API key';const stores=d?.store_providers||{},storeState=document.getElementById('cc-store-state'),providerRows=stores.providers||[];if(storeState)storeState.textContent=stores.prepared?(stores.ready_count===providerRows.length&&providerRows.length?'Ready':'Prepared'):'Not prepared';const preparation=document.getElementById('cc-store-preparation');if(preparation&&!storeLoginBusy)preparation.textContent=stores.prepared?'Store backends ready for account connection.':'Connect starts backend preparation automatically; no manual setup required.';for(const [id,label] of [['epic','Epic'],['gog','GOG'],['amazon','Amazon']]){const el=document.getElementById('cc-store-'+id),row=providerRows.find(x=>x.id===id);if(el)el.textContent=row?`${label} • ${row.binary_ready?'ready':row.runtime_ready?'not probed':'waiting'}`:`${label} —`}const storeAccounts=d?.store_accounts?.providers||[];for(const [id,label] of [['epic','Epic'],['gog','GOG'],['amazon','Amazon']]){const row=storeAccounts.find(x=>x.id===id)||{},badge=document.getElementById('cc-store-account-'+id),connect=document.querySelector(`[data-store-account-connect="${id}"]`),logout=document.querySelector(`[data-store-account-logout="${id}"]`);if(badge){const state=String(row.state||'disconnected').replaceAll('-',' ');badge.textContent=`${label} • ${!stores.prepared?'setup needed':state}${row.verified?' • verified':''}`;badge.title=row.detail||''}if(connect){connect.disabled=!!row.connected||storeLoginBusy;connect.title=!stores.prepared?'PCGA will prepare the store backends automatically before starting login.':''}if(logout)logout.disabled=!row.connected}const sj=d?.store_jobs||{},sjc=sj.counts||{},sjBadge=document.getElementById('cc-store-jobs');if(sjBadge){const active=Number(sjc.running||0)+Number(sjc.cancelling||0),queued=Number(sjc.queued||0),failed=Number(sjc.failed||0);sjBadge.textContent=active?`${active} active${queued?` • ${queued} queued`:''}`:queued?`${queued} queued`:failed?`${failed} failed`:'Idle'}checked('cc-jellyfin-enabled',c.media?.jellyfin_enabled);checked('cc-immich-enabled',c.photos?.immich_enabled);checked('cc-sorter-enabled',c.automation?.sorter_enabled);checked('cc-classifier-enabled',c.automation?.classifier_enabled);checked('cc-dedupe-enabled',c.automation?.dedupe_enabled);const paths=document.getElementById('cc-library-paths');if(paths)paths.innerHTML=Object.entries(c.libraries||{}).map(([k,v])=>`<div class="settings-row"><div class="settings-label">${esc(k.replaceAll('_',' '))}</div><div class="control-path">${esc(v)}</div></div>`).join('');document.getElementById('cc-config-version').textContent=`schema ${c.schema||1}`;document.getElementById('cc-archive-root').textContent=d.archive_root||'—';document.getElementById('cc-disk-used').textContent=humanBytes(d.disk?.used);document.getElementById('cc-disk-free').textContent=humanBytes(d.disk?.free)}const nas=d?.nas||{},nasCfg=c?.nas||{};checked('cc-nas-enabled',nasCfg.enabled);value('cc-nas-protocol',nasCfg.protocol||'smb');value('cc-nas-host',nasCfg.host||'');value('cc-nas-share',nasCfg.share||'');value('cc-nas-username',nasCfg.username||'');value('cc-nas-domain',nasCfg.domain||'');value('cc-nas-base',nasCfg.base_dir||'PCGA');value('cc-nas-mode',nasCfg.mode||'mirror');value('cc-nas-reserve',nasCfg.local_reserve_gib||100);value('cc-nas-age',nasCfg.min_age_days??30);checked('cc-nas-schedule',nasCfg.schedule_enabled!==false);document.querySelectorAll('.cc-nas-lib').forEach(x=>x.checked=(nasCfg.libraries||[]).includes(x.value));const nasState=document.getElementById('cc-nas-state'),nasFree=document.getElementById('cc-nas-free'),nasLast=document.getElementById('cc-nas-last-sync'),nasMsg=document.getElementById('cc-nas-message'),nasOff=document.getElementById('cc-nas-offload'),nasArchive=document.getElementById('cc-nas-archive');if(nasState)nasState.textContent=!nasCfg.enabled?'Disabled':(nas.mounted?(nasCfg.mode==='offload'?'Mounted • offload':'Mounted • mirror'):'Disconnected');if(nasFree)nasFree.textContent=nas.disk?.free?humanBytes(nas.disk.free):'—';if(nasLast){const t=Number(nas.state?.last_sync_at||0);nasLast.textContent=t?new Date(t*1000).toLocaleString():'Never'}if(nasMsg)nasMsg.textContent=nas.detail||nas.state?.last_error||(nasCfg.enabled?(nas.mounted?`Connected to ${nas.remote||'NAS'}.`:'NAS configured but not mounted.'):'NAS tiering is disabled.');if(nasOff)nasOff.disabled=nasCfg.mode!=='offload'||!nas.mounted;if(nasArchive)nasArchive.disabled=nasCfg.mode!=='offload'||!nas.mounted;const services=document.getElementById('cc-services');if(services&&d?.services){const rows=[];for(const[name,x]of Object.entries(d.services.docker||{}))rows.push({name,type:'container',...x});for(const[name,x]of Object.entries(d.services.systemd||{}))rows.push({name,type:'unit',...x});services.innerHTML=rows.map(x=>`<div class="control-service"><div class="control-service-head"><span class="control-service-name">${esc(x.name)}</span><span class="control-service-state ${x.active?'good':'bad'}">${esc(x.state||'unknown')}</span></div><div class="settings-note">${esc(x.type)}${x.health?` • ${esc(x.health)}`:''}</div></div>`).join('')}const links=document.getElementById('cc-native-links');if(links){links.innerHTML=(latestTools||[]).filter(t=>t.advanced).map(t=>`<a class="control-native-link tv-focus" href="${esc(toolURL(t))}"><strong>${esc(t.title)}</strong><span>${esc(t.subtitle)} • ${t.available?'available':'offline'}</span></a>`).join('')}const ts=d?.remote_access||{};const tsState=document.getElementById('cc-ts-state'),tsDns=document.getElementById('cc-ts-dns'),tsPortal=document.getElementById('cc-ts-portal'),tsMoon=document.getElementById('cc-ts-moonlight'),tsIps=document.getElementById('cc-ts-ips'),tsMsg=document.getElementById('cc-remote-message'),tsEnable=document.getElementById('cc-ts-enable'),tsDisable=document.getElementById('cc-ts-disable');if(tsState)tsState.textContent=ts.configured?'Ready':(ts.state||'Unavailable').replaceAll('-',' ');if(tsDns)tsDns.textContent=ts.dns_name||'—';if(tsPortal)tsPortal.textContent=ts.portal_url||'—';if(tsMoon)tsMoon.textContent=ts.moonlight_url||'—';if(tsIps)tsIps.textContent=(ts.tailscale_ips||[]).join(' • ')||'—';if(tsMsg)tsMsg.textContent=ts.detail||(ts.available?'Tailscale status available.':'Install Tailscale on the PCGA host and sign it into the same tailnet as the thin client.');if(tsEnable)tsEnable.disabled=!ts.available||ts.configured||ts.state==='needs-login';if(tsDisable)tsDisable.disabled=!ts.configured;const rp=d?.remote_providers||{tailscale:ts},nb=rp.netbird||{},zt=rp.zerotier||{};const ready=Object.values(rp).filter(x=>x?.configured).length,allIps=[...(ts.tailscale_ips||[]),...(nb.ips||[]),...(zt.ips||[])];const rr=document.getElementById('cc-remote-ready'),ri=document.getElementById('cc-remote-paths');if(rr)rr.textContent=String(ready);if(ri)ri.textContent=allIps.length?String(allIps.length):'0';const nbState=document.getElementById('cc-nb-state'),nbPath=document.getElementById('cc-nb-path'),nbPortal=document.getElementById('cc-nb-portal'),nbIps=document.getElementById('cc-nb-ips'),nbMsg=document.getElementById('cc-nb-message'),nbInstall=document.getElementById('cc-nb-install'),nbConnect=document.getElementById('cc-nb-connect'),nbDisconnect=document.getElementById('cc-nb-disconnect');if(nbState)nbState.textContent=(nb.state||'unavailable').replaceAll('-',' ');if(nbPath)nbPath.textContent=`${Number(nb.p2p_peers||0)} direct • ${Number(nb.relayed_peers||0)} relayed`;if(nbPortal)nbPortal.textContent=nb.portal_url||'—';if(nbIps)nbIps.textContent=(nb.ips||[]).join(' • ')||'—';if(nbMsg)nbMsg.textContent=nb.detail||'NetBird status unavailable.';if(nbInstall)nbInstall.disabled=!!nb.available;if(nbConnect)nbConnect.disabled=!nb.available||!!nb.configured;if(nbDisconnect)nbDisconnect.disabled=!nb.configured;const ztState=document.getElementById('cc-zt-state'),ztNode=document.getElementById('cc-zt-node'),ztPortal=document.getElementById('cc-zt-portal'),ztIps=document.getElementById('cc-zt-ips'),ztMsg=document.getElementById('cc-zt-message'),ztInstall=document.getElementById('cc-zt-install'),ztJoin=document.getElementById('cc-zt-join'),ztLeave=document.getElementById('cc-zt-leave'),ztNetwork=document.getElementById('cc-zt-network');if(ztState)ztState.textContent=(zt.state||'unavailable').replaceAll('-',' ');if(ztNode)ztNode.textContent=zt.node_id||'—';if(ztPortal)ztPortal.textContent=zt.portal_url||'—';if(ztIps)ztIps.textContent=(zt.ips||[]).join(' • ')||'—';if(ztMsg)ztMsg.textContent=zt.detail||'ZeroTier status unavailable.';if(ztInstall)ztInstall.disabled=!!zt.available;if(ztJoin)ztJoin.disabled=!zt.available;if(ztLeave)ztLeave.disabled=!zt.available||!(zt.networks||[]).length;if(ztNetwork&&!ztNetwork.value)ztNetwork.value=c?.remote_access?.zerotier_network_id||zt.networks?.[0]?.id||'';if(latestStatus){document.getElementById('cc-system-health').textContent=latestStatus.overall==='idle'?'Healthy':String(latestStatus.overall||'Unknown').replaceAll('-',' ');document.getElementById('cc-review-count').textContent=String((latestStatus.queues?.metadata_pending_items||0)+(latestStatus.queues?.manual_unidentified_items||0));document.getElementById('cc-active-rips').textContent=String((latestStatus.process?.active_ingests||[]).filter(x=>x?.live).length)}}
async function patchControl(config){if(controlBusy)return;controlBusy=true;try{const r=await fetch('/api/control/config',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({config,apply:true})});const d=await r.json().catch(()=>({}));if(!r.ok&&!d.config)throw Error(d.detail||d.error||r.status);controlState=controlState||{};controlState.config=d.config||controlState.config;showStatus(d.ok===false?'Applied with warnings':'Appliance settings updated',d.ok===false?'One or more service operations reported a warning.':'PCGA applied the new appliance configuration. ',d.ok===false?'warn':'good',5000);await loadControlCenter()}catch(e){showStatus('Control Center update failed',String(e.message||e),'warn',8000)}finally{controlBusy=false}}
async function nasConfigure(){if(controlBusy)return;controlBusy=true;const note=document.getElementById('cc-nas-message');if(note)note.textContent='Saving NAS settings and reconciling mount…';try{const libraries=[...document.querySelectorAll('.cc-nas-lib:checked')].map(x=>x.value);const nas={enabled:!!document.getElementById('cc-nas-enabled')?.checked,protocol:document.getElementById('cc-nas-protocol')?.value||'smb',host:document.getElementById('cc-nas-host')?.value||'',share:document.getElementById('cc-nas-share')?.value||'',username:document.getElementById('cc-nas-username')?.value||'',password:document.getElementById('cc-nas-password')?.value||'',domain:document.getElementById('cc-nas-domain')?.value||'',base_dir:document.getElementById('cc-nas-base')?.value||'PCGA',mode:document.getElementById('cc-nas-mode')?.value||'mirror',libraries,local_reserve_gib:Number(document.getElementById('cc-nas-reserve')?.value||100),min_age_days:Number(document.getElementById('cc-nas-age')?.value||30),schedule_enabled:!!document.getElementById('cc-nas-schedule')?.checked};const r=await fetch('/api/control/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'nas-configure',nas})}),d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw Error(d.detail||d.error||r.status);const pw=document.getElementById('cc-nas-password');if(pw)pw.value='';if(note)note.textContent=d.detail||'NAS configuration saved.';showStatus('NAS storage updated',d.detail||'Storage tier configuration applied.','good',5500);await loadControlCenter()}catch(e){if(note)note.textContent=String(e.message||e);showStatus('NAS configuration failed',String(e.message||e),'warn',9000)}finally{controlBusy=false}}
async function saveGameDbConfig(){if(controlBusy)return;const key=document.getElementById('cc-rawg-api-key')?.value?.trim()||'';if(!key){showStatus('RAWG key unchanged','Enter a new RAWG API key to configure or replace the current key.','info',5000);return}controlBusy=true;try{const r=await fetch('/api/control/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'pc-game-metadata-configure',provider:'rawg',rawg_api_key:key})}),d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw Error(d.detail||d.error||r.status);const input=document.getElementById('cc-rawg-api-key');if(input)input.value='';showStatus('Game database configured','RAWG metadata search is ready.','good',5000);await loadControlCenter()}catch(e){showStatus('Game database configuration failed',e.message||String(e),'warn',9000)}finally{controlBusy=false}}
async function controlAction(name){if(controlBusy)return;controlBusy=true;const remoteName=name.startsWith('tailscale-')||name.startsWith('netbird-')||name.startsWith('zerotier-');const note=document.getElementById(name.startsWith('netbird-')?'cc-nb-message':name.startsWith('zerotier-')?'cc-zt-message':name.startsWith('tailscale-')?'cc-remote-message':name.startsWith('nas-')?'cc-nas-message':'cc-last-action');if(note)note.textContent=`Running ${name}…`;const req={action:name};if(name==='netbird-connect'){req.setup_key=document.getElementById('cc-nb-key')?.value||'';req.management_url=document.getElementById('cc-nb-management')?.value||''}if(name==='zerotier-join'||name==='zerotier-leave')req.network_id=(document.getElementById('cc-zt-network')?.value||'').trim();try{const r=await fetch('/api/control/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(req)});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||d.stderr||r.status);const detail=(d.stdout||d.detail||'Completed').trim().slice(-900);if(note)note.textContent=detail||`${name} completed`;if(name==='netbird-connect'){const k=document.getElementById('cc-nb-key');if(k)k.value=''}showStatus(remoteName?'Remote access updated':name.startsWith('nas-')?'NAS storage updated':'Maintenance completed',detail||name,'good',5000);await loadControlCenter()}catch(e){if(note)note.textContent=String(e.message||e);showStatus(remoteName?'Remote access update failed':name.startsWith('nas-')?'NAS storage action failed':'Maintenance action failed',String(e.message||e),'warn',8000)}finally{controlBusy=false}}
function ripKind(t){if(t.phase==='audio-ripping')return'Music rip';if(t.phase==='transcoding')return'Transcode';if(t.phase==='pc-disc-imaging')return'PC game image';if(t.phase==='ripping')return'Disc rip';return'Optical ingest'}
function renderRips(tasks){const box=document.getElementById('rip-modal');tasks=(tasks||[]).filter(t=>t&&t.live);if(!tasks.length){box.className='rip-modal';box.innerHTML='';document.body.dataset.ripActive='false';document.documentElement.style.setProperty('--rip-overlay-height','0px');return}box.className='rip-modal show';document.body.dataset.ripActive='true';box.innerHTML=tasks.map(t=>{const p=Number(t.percent),determinate=Number.isFinite(p);const pct=determinate?Math.max(0,Math.min(100,p)):0;const pctText=determinate?`${pct.toFixed(pct%1?1:0)}%${t.percent_estimated?' est.':''}`:'Working';const track=t.track_number?`Track ${esc(t.track_number)}${t.track_count?` / ${esc(t.track_count)}`:''}${t.track_title?` • ${esc(t.track_title)}`:''}`:'';const meta=[t.operation,track].filter(Boolean).join(' • ');return `<div class="rip-task"><div class="rip-head"><span class="rip-label">${esc(ripKind(t))}</span><span class="rip-drive">${esc(t.drive||'')}</span></div><div class="rip-title">${esc(t.title||'Optical media')}</div><div class="rip-meta"><span>${esc(meta||'Working')}</span><span>${esc(t.elapsed||'')}</span></div><div class="rip-progress-line"><div class="rip-progress ${determinate?'':'indeterminate'}"><div style="width:${determinate?pct:34}%"></div></div><div class="rip-pct">${esc(pctText)}</div></div></div>`}).join('');requestAnimationFrame(()=>document.documentElement.style.setProperty('--rip-overlay-height',`${Math.ceil(box.getBoundingClientRect().height)+18}px`))}
async function refreshStatus(){try{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error(`HTTP ${r.status}`);const d=await r.json();if(d.version&&String(d.version)!==PORTAL_BUILD_VERSION){const k='pcga-build-reload:'+String(d.version);if(!sessionStorage.getItem(k)){sessionStorage.setItem(k,'1');location.reload();return}}latestStatus=d;latestTools=d.tools||[];renderTools(latestTools);renderRips(d.process?.active_ingests||[]);renderSystemStrip(d);if(document.getElementById('settings-modal').classList.contains('show'))renderControlCenter();const stamp=d.generated_at?new Date(d.generated_at):new Date();document.getElementById('updated').textContent=`Updated ${stamp.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}`;lastStatusError=''}catch(e){document.getElementById('updated').textContent='Status unavailable';renderRips([]);const sig=String(e?.message||e);if(lastStatusError!==sig){lastStatusError=sig;showStatus('Portal status unavailable',sig,'warn',7000)}}}
function renderTools(tools){const box=document.getElementById('launcher');const active=document.activeElement?.dataset?.tool;const visible=(tools||[]).filter(t=>!t.advanced);box.innerHTML=visible.map(t=>`<a class="tool tv-focus ${t.primary?'primary':''} ${t.available?'':'offline'}" data-group="tools" data-tool="${esc(t.id)}" href="${esc(toolURL(t))}"><div><div class="tool-head"><div class="tool-icon">${toolIcon(t.id)}</div><div class="tool-title">${esc(t.title)}</div></div><div class="tool-sub">${esc(t.subtitle)}</div></div><div class="tool-foot"><span>${t.available?'Ready':'Unavailable'}</span><span class="state-dot"></span></div></a>`).join('');let target=active?[...box.querySelectorAll('[data-tool]')].find(x=>x.dataset.tool===active):null;if(!target)target=box.querySelector('.primary')||box.querySelector('.tv-focus');if(target&&(!document.activeElement||document.activeElement===document.body||active))target.focus({preventScroll:true})}

function globalSearchKind(section,item){if(section==='media')return String(item.type||'video').toLowerCase();if(section==='music')return String(item.type||'music').toLowerCase()==='musicalbum'?'album':'music';if(section==='audiobooks')return'audiobook';if(section==='podcasts')return'podcast';if(section==='pc-games')return'pcgame';if(section==='photos')return'photo';if(section==='console')return'platform';return'media'}
function globalSearchArt(section,item){return item.art_url||item.cover_url||item.hero_url||(section==='photos'?item.url:'')||''}
function globalSearchTitle(item){return item.title||item.name||'Untitled'}
function globalSearchMeta(section,item){if(section==='media')return[item.type,item.series,item.year].filter(Boolean).join(' • ');if(section==='music')return[item.artist,item.album,item.type].filter(Boolean).join(' • ');if(section==='audiobooks')return[item.author,item.language,'Local audiobook'].filter(Boolean).join(' • ');if(section==='podcasts')return[item.author,'Subscribed podcast'].filter(Boolean).join(' • ');if(section==='console')return[item.platform,item.release_date].filter(Boolean).join(' • ');if(section==='pc-games')return[item.developer,item.year,item.type].filter(Boolean).join(' • ');if(section==='photos')return[item.folder,item.name].filter(Boolean).join(' • ');return''}
function renderGlobalSearch(data){globalSearchSections=data?.sections||[];const box=document.getElementById('global-search-content');if(!box)return;const count=globalSearchSections.reduce((n,s)=>n+(s.items?.length||0),0);if(!globalSearchQuery){box.innerHTML='<div class="global-search-empty">Type a title, artist, game, filename, author, or approximate spelling.</div>';return}if(!count){box.innerHTML=`<div class="global-search-empty">No local matches for “${esc(globalSearchQuery)}”. Try a shorter spelling, or open Audiobooks/Podcasts for public-provider discovery.</div>`;return}box.innerHTML=globalSearchSections.map((section,si)=>`<section class="global-search-section"><div class="global-search-section-head"><h3>${esc(section.title)}</h3><span>${section.items?.length||0}</span></div><div class="global-search-grid">${(section.items||[]).map((item,ii)=>{const title=globalSearchTitle(item),kind=globalSearchKind(section.id,item),art=globalSearchArt(section.id,item);return `<button type="button" class="global-search-card tv-focus" data-global-result="${si}:${ii}">${artStack(art,fallbackMarkup(kind,item),'pcga-art-stack',title)}<span class="global-search-card-copy"><span class="global-search-card-title">${esc(title)}</span><span class="global-search-card-meta">${esc(globalSearchMeta(section.id,item))}</span></span></button>`}).join('')}</div></section>`).join('')+`<div class="global-search-note">${esc(String(data.elapsed_ms||0))} ms • fuzzy local/cached search${Object.keys(data.errors||{}).length?' • some services unavailable':''}</div>`}
async function runGlobalSearch(query){globalSearchQuery=String(query||'').trim();const input=document.getElementById('global-search-input');if(input&&input.value!==globalSearchQuery)input.value=globalSearchQuery;if(!globalSearchQuery){renderGlobalSearch({sections:[]});return}const box=document.getElementById('global-search-content');if(box)box.innerHTML='<div class="global-search-empty">Searching local libraries…</div>';try{const r=await fetch('/api/search/global?'+new URLSearchParams({q:globalSearchQuery,limit:'8'}),{cache:'no-store'}),d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);renderGlobalSearch(d)}catch(e){if(box)box.innerHTML=`<div class="global-search-empty">Search unavailable: ${esc(e.message||String(e))}</div>`}}
function openGlobalSearch(query=''){globalSearchReturnFocus=document.activeElement;document.getElementById('global-search-modal')?.classList.add('show');const input=document.getElementById('global-search-input');if(input){input.value=query||globalSearchQuery||'';setTimeout(()=>{input.focus();input.select()},0)}if(query)runGlobalSearch(query);else renderGlobalSearch({sections:globalSearchSections})}
function closeGlobalSearch(){document.getElementById('global-search-modal')?.classList.remove('show');globalSearchReturnFocus?.focus?.();globalSearchReturnFocus=null}
function openGlobalResult(section,item){const q=globalSearchTitle(item)||globalSearchQuery;closeGlobalSearch();if(section==='media'){lastToolFocus=document.querySelector('[data-tool="jellyfinlibrary"]');openJellyfinLibrary(q,'all')}else if(section==='music'){lastToolFocus=document.querySelector('[data-tool="musicplayer"]');openMusicBrowser(q,'home')}else if(section==='audiobooks'){lastToolFocus=document.querySelector('[data-tool="musicplayer"]');openAudiobookBrowser(q,'title')}else if(section==='podcasts'){lastToolFocus=document.querySelector('[data-tool="musicplayer"]');openPodcastBrowser(q)}else if(section==='console'){lastToolFocus=document.querySelector('[data-tool="romm"]');openGameBrowser(q,'')}else if(section==='pc-games'){lastToolFocus=document.querySelector('[data-tool="lancommander"]');openPcGameBrowser(q)}else if(section==='photos'){lastToolFocus=document.querySelector('[data-tool="photos"]');openPhotos(q)}}

function uploadKindLabel(k){return({auto:'Automatic',movie:'Movie',tv:'TV episodes',music:'Music',audiobook:'Audiobook','home-video':'Home video',photos:'Photos','pc-game':'PC game',software:'Software','disc-image':'Disc image',rom:'Console game / ROM',bios:'Emulator BIOS / firmware'})[k]||k}
function uploadModeSummary(hint){if(hint==='auto')return'PCGA will identify the content type, read available metadata, and organize it automatically.';if(hint==='audiobook')return'PCGA will keep this selection together as one audiobook and infer its title, author, chapter order, and cover art when available.';if(hint==='rom')return'PCGA will identify the console when it can do so safely and send ambiguous images to Review Queue.';if(hint==='bios')return'PCGA will infer the console from filenames/folders when safe; ambiguous firmware is kept for review.';return`Opened from ${uploadKindLabel(hint)}. PCGA will use that as a routing hint and still preserve anything uncertain for review.`}
function renderUploadPanel(){const box=document.getElementById('upload-panel');if(!box)return;const current=document.getElementById('upload-kind')?.value;const oldPlatform=document.getElementById('upload-platform')?.value;const oldTitle=document.getElementById('upload-book-title')?.value,oldAuthor=document.getElementById('upload-book-author')?.value;if(current)uploadPreferredKind=current;if(oldPlatform!=null)uploadSelectedPlatform=oldPlatform;if(oldTitle!=null)uploadAudiobookMeta.title=oldTitle;if(oldAuthor!=null)uploadAudiobookMeta.author=oldAuthor;const hint=uploadPreferredKind||'auto',audiobook=hint==='audiobook';const accept=audiobook?' accept=".mp3,.m4b,.m4a,.flac,.ogg,.opus,.wav,.aac,.wma,.alac,.ape,.zip"':'';const totalBytes=uploadFiles.reduce((n,x)=>n+(Number(x.file?.size)||0),0);const statusCount=uploadJobs.filter(j=>!['complete','failed'].includes(String(j.state||''))).length;const reviewCount=uploadJobs.reduce((n,j)=>n+(Number(j.review)||0),0);const uploadTitle=audiobook?'Add Audiobook':'Add Media';const selected=uploadFiles.length?`<div id="upload-selection" class="upload-selection"><div class="upload-selection-head"><span>${uploadFiles.length} file${uploadFiles.length===1?'':'s'} ready</span><span>${humanBytes(totalBytes)}</span></div><div class="upload-selection-files">${uploadFiles.slice(0,8).map(x=>esc(x.path)).join('<br>')}${uploadFiles.length>8?`<br>…and ${uploadFiles.length-8} more`:''}</div></div>`:'';const advancedPlatform=['rom','bios'].includes(hint)?`<div class="upload-field"><label for="upload-platform">Console platform override</label><select id="upload-platform" class="tv-focus"><option value="">Detect automatically</option>${uploadPlatforms.map(x=>`<option value="${esc(x.slug)}" ${x.slug===uploadSelectedPlatform?'selected':''}>${esc(x.name)}</option>`).join('')}</select><div class="upload-field-help">Leave this on automatic unless PCGA cannot distinguish the platform safely.</div></div>`:'';const advancedBook=audiobook?`<div class="upload-options"><div class="upload-field"><label for="upload-book-title">Book title override</label><input id="upload-book-title" class="tv-focus" value="${esc(uploadAudiobookMeta.title)}" placeholder="Detected from tags or folder name" autocomplete="off"></div><div class="upload-field"><label for="upload-book-author">Author override</label><input id="upload-book-author" class="tv-focus" value="${esc(uploadAudiobookMeta.author)}" placeholder="Detected from embedded metadata" autocomplete="off"></div></div>`:'';box.innerHTML=`<div class="upload-head"><div><div class="upload-title">${uploadTitle}</div><div class="upload-sub">Choose files or a folder. PCGA handles the organization.</div></div><button class="settings-close tv-focus" data-upload-close type="button" aria-label="Close uploads">×</button></div><div class="upload-body"><div class="upload-auto-note"><span class="upload-auto-mark">✓</span><div><strong>${hint==='auto'?'Automatic organization':esc(uploadKindLabel(hint))+' upload'}</strong><span>${esc(uploadModeSummary(hint))} Anything PCGA cannot classify confidently stays in Review Queue instead of being guessed.</span></div></div><div id="upload-drop" class="upload-drop"><strong>${audiobook?'Drop an audiobook here':'Drop media here'}</strong><span>${audiobook?'Choose a ZIP, a folder, or all chapter files for one book.':'Files and folders can be mixed; PCGA keeps folder structure while it identifies and routes each top-level item.'}</span><div class="upload-picker-row"><label class="upload-picker primary tv-focus" tabindex="0">Choose files<input id="upload-files" type="file" multiple${accept}></label><label class="upload-picker tv-focus" tabindex="0">Choose folder<input id="upload-folder" type="file" webkitdirectory multiple${accept}></label></div></div>${selected}<div id="upload-progress" class="upload-progress"><div id="upload-progress-text" class="upload-job-meta">Preparing upload…</div><div class="upload-progress-bar"><div id="upload-progress-fill"></div></div></div><div class="upload-actions upload-actions-simple"><button id="upload-start" class="upload-action primary tv-focus" type="button" ${uploadFiles.length&&!uploadBusy?'':'disabled'}>${uploadBusy?'Uploading…':'Add to PCGA'}</button></div><details id="upload-advanced" class="upload-advanced" ${uploadAdvancedOpen?'open':''}><summary class="tv-focus"><span>Advanced options</span><small>Only change these if automatic organization needs help</small></summary><div class="upload-advanced-body"><div class="upload-field"><label for="upload-kind">Content type override</label><select id="upload-kind" class="tv-focus"><option value="auto">Automatic detection</option><option value="movie">Movie</option><option value="tv">TV episodes</option><option value="music">Music</option><option value="audiobook">Audiobook</option><option value="home-video">Home video</option><option value="photos">Photos</option><option value="pc-game">PC game</option><option value="software">Software</option><option value="disc-image">Disc image</option><option value="rom">Console game / ROM</option><option value="bios">Emulator BIOS / firmware</option></select><div class="upload-field-help">The source page already supplies a useful hint when you choose Upload from Music, Audiobooks, Photos, Movies/TV, Console Games, or PC Games.</div></div>${advancedPlatform}${advancedBook}</div></details><details id="upload-history" class="upload-history" ${uploadHistoryOpen?'open':''}><summary class="tv-focus"><span>Recent activity</span><small>${statusCount?`${statusCount} processing`:reviewCount?`${reviewCount} need review`:uploadJobs.length?'Latest uploads complete':'No uploads yet'}</small></summary><div id="upload-jobs" class="upload-jobs"></div></details></div>`;const k=document.getElementById('upload-kind');if(k)k.value=hint;renderUploadJobs()}
function renderUploadJobs(){const box=document.getElementById('upload-jobs');if(!box)return;if(!uploadJobs.length){box.innerHTML='<div class="settings-note">No local uploads yet.</div>';return}box.innerHTML=uploadJobs.slice(0,8).map(j=>`<div class="upload-job ${esc(j.state||'')}"><div class="upload-job-head"><span>${esc(j.title||'Upload')}</span><span>${esc(String(j.state||'').replaceAll('-',' '))}</span></div><div class="upload-job-meta">${esc(j.message||'')}${j.review?` • ${Number(j.review)} need review`:''}</div></div>`).join('')}
async function loadUploadMeta(){const [pr,jr]=await Promise.all([fetch('/api/uploads/platforms',{cache:'no-store'}),fetch('/api/uploads/jobs',{cache:'no-store'})]);const pd=await pr.json().catch(()=>({})),jd=await jr.json().catch(()=>({}));if(pr.ok)uploadPlatforms=pd.items||[];if(jr.ok)uploadJobs=jd.jobs||[];renderUploadPanel()}
function openUploadBrowser(kind='auto'){const valid=new Set(['auto','movie','tv','music','audiobook','home-video','photos','pc-game','software','disc-image','rom','bios']);if(valid.has(String(kind||'')))uploadPreferredKind=String(kind);uploadSelectedPlatform='';uploadAdvancedOpen=false;uploadHistoryOpen=false;uploadReturnFocus=document.activeElement;document.getElementById('upload-browser').classList.add('show');renderUploadPanel();loadUploadMeta().catch(()=>{});clearInterval(uploadJobTimer);uploadJobTimer=setInterval(()=>refreshUploadJobs().catch(()=>{}),1800);setTimeout(()=>pcgaSetSelection(document.querySelector('#upload-browser .upload-picker.primary')||document.querySelector('#upload-browser .tv-focus'),{focus:true,scroll:true}),0)}
function closeUploadBrowser(){document.getElementById('upload-browser').classList.remove('show');clearInterval(uploadJobTimer);uploadJobTimer=null;uploadReturnFocus?.focus?.();uploadReturnFocus=null}
async function refreshUploadJobs(){const r=await fetch('/api/uploads/jobs',{cache:'no-store'}),d=await r.json().catch(()=>({}));if(r.ok){uploadJobs=d.jobs||[];renderUploadJobs()}}
function setUploadFiles(files,folderMode=false){uploadFiles=[...files].map(f=>({file:f,path:(folderMode?(f.webkitRelativePath||f.name):f.name)||f.name}));renderUploadPanel()}
function uploadOne(session,item,doneBytes,totalBytes,index,totalFiles){return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST',`/api/uploads/file?session=${encodeURIComponent(session)}&path=${encodeURIComponent(item.path)}`);xhr.setRequestHeader('Content-Type','application/octet-stream');xhr.upload.onprogress=e=>{const loaded=e.lengthComputable?e.loaded:0,pct=totalBytes?Math.min(100,(doneBytes+loaded)*100/totalBytes):0;const text=document.getElementById('upload-progress-text'),fill=document.getElementById('upload-progress-fill');if(text)text.textContent=`Uploading ${index}/${totalFiles}: ${item.path} • ${pct.toFixed(1)}%`;if(fill)fill.style.width=`${pct}%`};xhr.onload=()=>{let d={};try{d=JSON.parse(xhr.responseText||'{}')}catch(_){}if(xhr.status>=200&&xhr.status<300)resolve(d);else reject(Error(d.error||`Upload failed (HTTP ${xhr.status})`))};xhr.onerror=()=>reject(Error('Upload connection failed'));xhr.send(item.file)})}
async function startUserUpload(){if(uploadBusy||!uploadFiles.length)return;const hint=document.getElementById('upload-kind')?.value||uploadPreferredKind||'auto',platform=document.getElementById('upload-platform')?.value||uploadSelectedPlatform||'';uploadPreferredKind=hint;uploadSelectedPlatform=platform;if(hint==='audiobook'){uploadAudiobookMeta.title=document.getElementById('upload-book-title')?.value?.trim()||uploadAudiobookMeta.title||'';uploadAudiobookMeta.author=document.getElementById('upload-book-author')?.value?.trim()||uploadAudiobookMeta.author||''}uploadBusy=true;renderUploadPanel();document.getElementById('upload-progress')?.classList.add('show');try{let r=await fetch('/api/uploads/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hint,platform,book_title:hint==='audiobook'?uploadAudiobookMeta.title:'',book_author:hint==='audiobook'?uploadAudiobookMeta.author:''})}),d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||r.status);const session=d.session,total=uploadFiles.reduce((n,x)=>n+(Number(x.file?.size)||0),0);let done=0;for(let i=0;i<uploadFiles.length;i++){const item=uploadFiles[i];await uploadOne(session,item,done,total,i+1,uploadFiles.length);done+=Number(item.file?.size)||0}r=await fetch('/api/uploads/commit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session})});d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||r.status);uploadFiles=[];uploadSelectedPlatform='';if(hint==='audiobook')uploadAudiobookMeta={title:'',author:''};uploadHistoryOpen=true;showStatus('Upload received','PCGA is identifying and organizing the new files. Anything uncertain will appear in Review Queue.','good',6000);await refreshUploadJobs();renderUploadPanel()}catch(err){showStatus('Upload failed',err.message||String(err),'warn',9000)}finally{uploadBusy=false;renderUploadPanel()}}
function fmtBytes(n){n=Number(n)||0;if(n<=0)return'';const u=['B','KiB','MiB','GiB','TiB'];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++}return `${n>=10||i===0?n.toFixed(0):n.toFixed(1)} ${u[i]}`}
function fmt(sec){sec=Math.max(0,Math.floor(Number(sec)||0));const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=sec%60;return h?`${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`:`${m}:${String(s).padStart(2,'0')}`}
function audioHubTabs(){return `<div class="audio-source-tabs"><button type="button" class="audio-source-tab tv-focus ${audioHubMode==='music'?'active':''}" data-audio-hub="music">Music</button><button type="button" class="audio-source-tab tv-focus ${audioHubMode==='podcasts'?'active':''}" data-audio-hub="podcasts">Podcasts</button><button type="button" class="audio-source-tab tv-focus ${audioHubMode==='audiobooks'?'active':''}" data-audio-hub="audiobooks">Audiobooks</button></div>`}
function musicButton(action,label,symbol,main=false,disabled=false){return `<button class="ctl ${main?'main':''} tv-focus" data-group="music" data-action="${action}" aria-label="${esc(label)}" title="${esc(label)}" ${disabled?'disabled':''}>${symbol}<span class="ctl-label">${esc(label)}</span></button>`}
function portalMusicState(){if(pcgaAudioPlayer.active&&pcgaAudioPlayer.item){const item=pcgaAudioPlayer.item,dur=Number(item.duration_seconds)||((Number.isFinite(audio.duration)&&audio.duration>0)?Number(audio.duration):0),pos=Number(audio.currentTime)||0,q=pcgaAudioPlayer.queue||[];return{available:true,playing:true,source:'pcga-audio',audio_kind:pcgaAudioPlayer.kind,item_id:item.id||item.key,title:item.title||item.name||'Audio',artist:item.artist||item.author||'',album:item.album||item.show||item.book||'',art_url:item.art_url||null,paused:audio.paused,muted:audio.muted,volume:Math.round(audio.volume*100),position_seconds:pos,runtime_seconds:dur,progress_percent:dur>0?(pos/dur)*100:0,device:'PCGA Portal',client:pcgaAudioPlayer.kind==='podcast'?'PCGA Podcasts':'PCGA Audiobooks',controllable:true,capabilities:{previous:q.length>1,playpause:true,next:q.length>1,volume_down:true,volume_up:true,mute:true}}}if(!portalPlayer.active||!portalPlayer.item)return null;const item=portalPlayer.item;const dur=Number(item.runtime_seconds)||Number(item.runtime_ticks)/10000000||((Number.isFinite(audio.duration)&&audio.duration>0)?Number(audio.duration):0);const pos=Number(audio.currentTime)||0;return{available:true,playing:true,source:'portal',item_id:item.id,title:item.name,artist:item.artist||'',album:item.album||'',art_url:item.art_url||null,paused:audio.paused,muted:audio.muted,volume:Math.round(audio.volume*100),position_seconds:pos,runtime_seconds:dur,progress_percent:dur>0?(pos/dur)*100:0,device:'PCGA Portal',client:'PCGA Music Player',controllable:true,capabilities:{previous:musicQueue.length>1,playpause:true,next:musicQueue.length>1,volume_down:true,volume_up:true,mute:true}}}
function renderMusic(m){const box=document.getElementById('music-modal');externalMusicSession=m?.playing?m:null;const shown=portalMusicState()||externalMusicSession;musicSession=shown;if(!shown?.available||!shown.playing){box.className='now-playing-modal';box.innerHTML='';return}box.className='now-playing-modal show';const caps=shown.capabilities||{};const disabled=!shown.controllable;const art=artStack(shown.art_url,fallbackMarkup(shown.audio_kind==='podcast'?'podcast':shown.audio_kind==='audiobook'?'audiobook':'music',shown),'cover',shown.title||'Now playing artwork');const takeover=shown.source!=='portal'&&shown.source!=='pcga-audio'?`<button class="music-inline-action tv-focus" data-group="music" data-action="takeover">Play Here</button>`:'';box.innerHTML=`${art}<div class="track"><div class="now-label">Now Playing • ${shown.source==='pcga-audio'?(shown.audio_kind==='podcast'?'Podcast':'Audiobook'):(shown.source==='portal'?'PCGA Music':'Jellyfin')}</div><div class="track-title">${esc(shown.title)}</div><div class="track-meta">${esc(shown.artist||'Unknown artist')}${shown.album?` • ${esc(shown.album)}`:''}</div><div class="progress-line"><div class="progress"><div style="width:${Math.max(0,Math.min(100,Number(shown.progress_percent)||0))}%"></div></div><div class="time">${fmt(shown.position_seconds)} / ${fmt(shown.runtime_seconds)}</div></div><div class="music-device">${esc(shown.device||shown.client||'Jellyfin client')}${shown.volume!=null?` • Volume ${esc(shown.volume)}%`:''}${disabled?' • Remote controls unavailable on this client':''} ${takeover}</div></div><div class="controls">${musicButton('browse','Browse audio','♫')}${musicButton('previous','Previous track','⏮',false,!caps.previous)}${musicButton('playpause',shown.paused?'Play':'Pause',shown.paused?'▶':'Ⅱ',true,!caps.playpause)}${musicButton('next','Next track','⏭',false,!caps.next)}<div class="volume">${musicButton('volume_down','Volume down','−',false,!caps.volume_down)}${musicButton('mute',shown.muted?'Unmute':'Mute',shown.muted?'◉':'○',false,!caps.mute)}${musicButton('volume_up','Volume up','+',false,!caps.volume_up)}</div></div>`}
async function fetchMusicLibrary(search='',view='home',parentId=''){const q=new URLSearchParams({limit:view==='tracks'||view==='albums'||view==='artists'?'60':'36',view});if(search)q.set('search',search);if(parentId)q.set('parent_id',parentId);const r=await fetch('/api/jellyfin/music/library?'+q.toString(),{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);return d}
function musicNavButton(id,label){return`<button type="button" class="music-nav tv-focus ${musicView===id?'active':''}" data-group="music-nav" data-music-view="${id}">${label}</button>`}
function musicTrackRow(x){const art=artStack(x.art_url,fallbackMarkup('music',x),'music-art',x.name||'Music artwork');return`<button class="music-item tv-focus" data-group="music-tracks" data-music-item="${esc(x.id)}" type="button">${art}<span><span class="music-item-title">${esc(x.name)}</span><span class="music-item-meta">${esc(x.artist||'Unknown artist')}${x.album?` • ${esc(x.album)}`:''}</span></span><span class="music-item-time">${fmt(x.runtime_seconds)}</span></button>`}
function musicEntityCard(x,kind){const meta=kind==='albums'?(x.artist||`${x.child_count||0} tracks`):'Artist';const attr=kind==='albums'?`data-music-album="${esc(x.id)}" data-music-album-name="${esc(x.name)}"`:`data-music-artist="${esc(x.name)}"`;const art=artStack(x.art_url,fallbackMarkup(kind==='albums'?'album':'artist',x),'music-entity-art',x.name||'Music artwork');return`<button class="music-entity tv-focus" data-group="music-${kind}" ${attr} type="button">${art}<span class="music-entity-title">${esc(x.name)}</span><span class="music-entity-meta">${esc(meta)}</span></button>`}
function renderMusicSection(section){const items=section?.items||[];if(!items.length)return'';const kind=section.kind||'tracks';const body=kind==='tracks'?`<div class="music-list">${items.map(musicTrackRow).join('')}</div>`:`<div class="music-shelf">${items.map(x=>musicEntityCard(x,kind)).join('')}</div>`;return`<section class="music-section"><div class="music-section-head"><h3>${esc(section.title||'Music')}</h3><span>${items.length} ${items.length===1?'item':'items'}</span></div>${body}</section>`}
function renderMusicBrowser(data,search=''){const panel=document.getElementById('music-panel');const sections=data?.sections||[];musicView=data?.view||musicView||'home';musicSearch=search;musicParentId=data?.parent_id||musicParentId||'';musicQueue=sections.filter(x=>x.kind==='tracks').flatMap(x=>x.items||[]);const albumTitle=musicView==='album'?(musicParentName||'Album'):'';panel.innerHTML=`<div class="music-browser-head"><div><div class="music-browser-title">${albumTitle?esc(albumTitle):'Music'}</div><div class="music-browser-sub">${musicView==='album'?'Album tracks':search?`Search results for “${esc(search)}”`:'Albums, artists and tracks • '+esc(data?.user_name||'Jellyfin')}</div></div><div class="library-head-actions"><button class="library-upload tv-focus" data-upload-kind="music" type="button">Upload music</button><button class="music-close tv-focus" data-group="music-head" data-music-close aria-label="Close">×</button></div></div>${audioHubTabs()}${musicView==='album'?`<div class="music-breadcrumb"><button type="button" class="music-back tv-focus" data-group="music-nav" data-music-back>← Music home</button></div>`:`<div class="music-nav-row">${musicNavButton('home','Home')}${musicNavButton('albums','Albums')}${musicNavButton('artists','Artists')}${musicNavButton('tracks','Tracks')}</div>`}<form class="music-search" id="music-search-form"><input class="tv-focus" data-group="music-search" id="music-search-input" value="${esc(search)}" placeholder="Search artists, albums or tracks" autocomplete="off"><button class="tv-focus" data-group="music-search" type="submit">Search</button></form><div class="music-content">${sections.length?sections.map(renderMusicSection).join(''):`<div class="music-empty">No music found.</div>`}</div>`}
async function openMusicBrowser(search='',view='home',parentId='',parentName=''){audioHubMode='music';musicSearch=search;musicView=view;musicParentId=parentId;musicParentName=parentName||musicParentName;const box=document.getElementById('music-browser');box.classList.add('show');document.getElementById('music-panel').innerHTML='<div class="music-empty">Loading music…</div>';try{const d=await fetchMusicLibrary(search,view,parentId);renderMusicBrowser(d,search);setTimeout(()=>document.querySelector('#music-browser .tv-focus')?.focus(),0)}catch(e){document.getElementById('music-panel').innerHTML=`<div class="music-browser-head"><div class="music-browser-title">Music</div><button class="music-close tv-focus" data-music-close>×</button></div><div class="music-empty">${esc(e.message||e)}</div>`}}
function closeMusicBrowser(){document.getElementById('music-browser').classList.remove('show');musicParentId='';musicParentName='';(lastToolFocus||document.querySelector('[data-tool="musicplayer"]'))?.focus?.()}
function audioDate(v){if(!v)return'';const d=new Date(v);return Number.isNaN(d.getTime())?String(v):d.toLocaleDateString([],{year:'numeric',month:'short',day:'numeric'})}
function audioCard(item,i,kind){const audioKind=kind.startsWith('podcast')?'podcast':'audiobook',art=artStack(item.art_url,fallbackMarkup(audioKind,item),'audio-card-art',item.title||`${audioKind} artwork`);const source=item.uploaded?'Local upload':(item.search_source_label||(item.collected?'Local copy':''));const meta=kind==='podcast'?[item.author,item.genre].filter(Boolean).join(' • '):[item.author,item.language,item.total_time,source].filter(Boolean).join(' • ');return `<article class="audio-card"> <button class="audio-card-main tv-focus" data-group="audio-grid" data-${kind}-index="${i}" type="button">${art}<div class="audio-card-copy"><div class="audio-card-title">${esc(item.title||'Untitled')}</div><div class="audio-card-meta">${esc(meta)}</div></div></button></article>`}
async function audioJson(url,options){const r=await fetch(url,options),d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw Error(d.detail||d.error||`HTTP ${r.status}`);return d}

let storeAuthProvider='';
let storeLoginBusy=false;
let storeLoginSequence=0;
let storeLoginAbort=null;
let storeAuthReturnFocus=null;
let storeAuthSubmitting=false;
function storeAuthMessage(phase,detail,error=''){
  const progress=document.getElementById('store-auth-progress'),body=document.getElementById('store-auth-detail'),err=document.getElementById('store-auth-error');
  if(progress){progress.dataset.phase=phase;progress.textContent=phase==='preparing'?'Preparing store helpers…':phase==='starting'?'Starting store authentication…':phase==='submitting'?'Connecting account…':phase==='error'?'Connection could not start':phase==='ready'?'':'';}
  if(body)body.textContent=detail;
  if(err){err.hidden=!error;err.textContent=error;}
}
function storeAuthBegin(provider){
  const modal=document.getElementById('store-auth-modal'),title=document.getElementById('store-auth-title'),sub=document.getElementById('store-auth-sub'),fields=document.getElementById('store-auth-fields'),submit=document.querySelector('[data-store-auth-submit]'),link=document.getElementById('store-auth-link'),code=document.getElementById('store-auth-code');
  storeAuthReturnFocus=document.activeElement;
  storeAuthProvider=provider;
  if(title)title.textContent=`Connect ${{epic:'Epic Games',gog:'GOG',amazon:'Amazon Games'}[provider]||provider}`;
  if(sub)sub.textContent='Set up and sign in without leaving the PCGA interface.';
  if(fields)fields.hidden=true;
  if(submit){submit.hidden=true;submit.disabled=true;submit.textContent='Finish connection';}
  if(link){link.hidden=true;link.removeAttribute('href');}
  if(code)code.value='';
  storeAuthMessage('preparing','Checking provider tools. You may return to PCGA while preparation continues.');
  modal?.classList.add('show');
  setTimeout(()=>{if(modal?.classList.contains('show'))modal.querySelector('[data-store-auth-close]')?.focus();},0);
}
function storeAuthShowReady(provider,data){
  const fields=document.getElementById('store-auth-fields'),link=document.getElementById('store-auth-link'),submit=document.querySelector('[data-store-auth-submit]'),sub=document.getElementById('store-auth-sub');
  if(sub)sub.textContent='Authenticate on the store site in a separate browser tab.';
  storeAuthMessage('ready',data.detail||'Open the provider login page and paste the returned one-time code below.');
  if(fields)fields.hidden=false;
  if(link){link.href=data.login_url||'#';link.textContent=`Open ${data.provider_label||provider} login page ↗`;link.hidden=!data.login_url;}
  if(submit){submit.hidden=false;submit.disabled=false;}
  setTimeout(()=>{if(document.getElementById('store-auth-modal')?.classList.contains('show'))(link?.hidden?document.getElementById('store-auth-code'):link)?.focus();},0);
}
// Backend preparation may continue after a user leaves. Abort browser polling
// and ignore any late result; never reopen an abandoned auth dialog.
function closeStoreAuth(home=false){
  ++storeLoginSequence;
  storeLoginAbort?.abort();storeLoginAbort=null;
  storeLoginBusy=false;storeAuthSubmitting=false;
  document.getElementById('store-auth-modal')?.classList.remove('show');
  storeAuthProvider='';
  const code=document.getElementById('store-auth-code');if(code)code.value='';
  const focus=storeAuthReturnFocus;storeAuthReturnFocus=null;
  if(home){closeSettings();}
  else setTimeout(()=>{if(document.getElementById('settings-modal')?.classList.contains('show'))(focus?.isConnected?focus:document.querySelector('[data-store-account-connect]'))?.focus?.();},0);
}
function storeLoginSleep(ms,signal){return new Promise((resolve,reject)=>{if(signal?.aborted){reject(new DOMException('Cancelled','AbortError'));return;}const timer=setTimeout(()=>{signal?.removeEventListener('abort',onAbort);resolve();},ms);function onAbort(){clearTimeout(timer);reject(new DOMException('Cancelled','AbortError'));}signal?.addEventListener('abort',onAbort,{once:true});});}
// Preparing providers is explicitly user-initiated. Do not make portal boot
// depend on any storefront, and do not repeatedly poll the whole Control Center.
async function storeBackendsReadyForLogin(provider,signal){
  const endpoint='/api/control/store/backends';
  async function state(){const r=await fetch(endpoint,{cache:'no-store',signal}),d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw Error(d.detail||d.error||'Unable to check store backend preparation');return d;}
  let status=await state();
  if(status.prepared)return;
  const note=document.getElementById('cc-store-preparation');
  if(note)note.textContent=`Preparing ${provider==='epic'?'Epic':provider==='gog'?'GOG':'Amazon'} store helpers…`;
  storeAuthMessage('preparing','Downloading and preparing the store helpers. This can continue if you close this window.');
  await storeAccountAction('store-backends-prepare',{},signal);
  const startedAt=Date.now()/1000-2;
  for(let i=0;i<100;i++){
    await storeLoginSleep(3000,signal);
    status=await state();
    if(status.prepared){if(note)note.textContent='Store helpers ready.';return;}
    const bs=status.bootstrap||{},phase=String(bs.state||'not-started');
    if(note)note.textContent='Preparing store helpers: '+phase.replaceAll('-',' ')+'…';
    storeAuthMessage('preparing',`Preparing helpers: ${phase.replaceAll('-',' ')}. You can return to PCGA at any time.`);
    if(phase==='error'&&Number(bs.updated_at||0)>=startedAt)throw Error((bs.detail||'Backend preparation failed')+' — See: sudo journalctl -u pcga-store-bootstrap.service -n 100 --no-pager');
  }
  throw Error('Store preparation is still running. Retry Connect when it finishes. Check: sudo systemctl status pcga-store-bootstrap.service');
}
async function storeAccountAction(action,payload={},signal){const r=await fetch('/api/control/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,...payload}),cache:'no-store',signal}),d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw Error(d.detail||d.error||r.status);return d}
async function fetchStoreJobs(){const r=await fetch('/api/control/store/jobs?limit=120',{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw Error(d.detail||d.error||r.status);return d}
let storeJobsView='all';let storeJobsSearch='';let storeJobsLastData=null;let storeJobsRequestBusy=false;let storeJobsRenderedHtml='';
function storeJobStateText(v){return ({queued:'Queued',running:'Running',cancelling:'Cancelling',completed:'Completed',failed:'Failed',cancelled:'Cancelled'})[v]||String(v||'queued').replaceAll('-',' ')}
function storeJobHasProgress(j){return j.progress!==null&&j.progress!==undefined&&Number.isFinite(Number(j.progress))}
function storeJobPercentage(j){return Math.max(0,Math.min(100,Number(j.progress)||0))}
function storeJobEta(seconds){if(!Number.isFinite(Number(seconds))||Number(seconds)<0)return '';const s=Math.round(Number(seconds));return s>=3600?`${Math.floor(s/3600)}h ${Math.ceil((s%3600)/60)}m`:s>=60?`${Math.ceil(s/60)}m`:`${s}s`}
function storeJobsVisible(j){const state=String(j.state||'');const matches=storeJobsView==='all'||(storeJobsView==='active'&&['queued','running','cancelling'].includes(state))||(storeJobsView==='completed'&&state==='completed')||(storeJobsView==='attention'&&['failed','cancelled'].includes(state));const needle=storeJobsSearch.trim().toLocaleLowerCase();return matches&&(!needle||[j.title,j.app_id,j.provider,j.message].some(x=>String(x||'').toLocaleLowerCase().includes(needle)))}
function renderStoreJobs(data){
  storeJobsLastData=data;
  const list=document.getElementById('store-jobs-list'),summary=document.getElementById('store-jobs-summary'),sub=document.getElementById('store-jobs-sub');
  const jobs=data?.jobs||[],counts=data?.counts||{},shown=jobs.filter(storeJobsVisible);
  if(sub)sub.textContent=`Epic + GOG • ${jobs.length} recent job${jobs.length===1?'':'s'}`;
  if(summary){const active=Number(counts.running||0)+Number(counts.cancelling||0),queued=Number(counts.queued||0),done=Number(counts.completed||0),failed=Number(counts.failed||0)+Number(counts.cancelled||0);const value=`${active} running • ${queued} queued • ${done} completed • ${failed} need attention`;if(summary.textContent!==value)summary.textContent=value}
  document.querySelectorAll('[data-store-job-filter]').forEach(b=>{const selected=b.dataset.storeJobFilter===storeJobsView;b.setAttribute('aria-pressed',String(selected));b.classList.toggle('selected',selected)});
  if(!list)return;
  // Polls must not steal controller focus, scroll position, or expanded logs.
  const focused=document.activeElement;
  const focusedAction=focused?.closest?.('[data-store-job-cancel],[data-store-job-retry],[data-store-job-delete]');
  const focusAttribute=focusedAction?.hasAttribute('data-store-job-cancel')?'data-store-job-cancel':focusedAction?.hasAttribute('data-store-job-retry')?'data-store-job-retry':focusedAction?.hasAttribute('data-store-job-delete')?'data-store-job-delete':null;
  const focusId=focusAttribute?focusedAction.getAttribute(focusAttribute):null;
  const openLogs=new Set([...list.querySelectorAll('details[open][data-log-job]')].map(n=>n.dataset.logJob));
  const previousScroll=list.scrollTop;
  const html=shown.map(j=>{
    const state=String(j.state||'queued'),hasPct=storeJobHasProgress(j),pct=hasPct?storeJobPercentage(j):(state==='completed'?100:0);
    const active=['queued','running','cancelling'].includes(state),retry=['failed','cancelled'].includes(state),terminal=['completed','failed','cancelled'].includes(state);
    const speed=Number(j.speed_bps)||0,bytes=Number(j.bytes_done)||0,total=Number(j.bytes_total)||0;
    const queue=state==='queued'&&j.queue_position?` • #${Number(j.queue_position)} in ${String(j.provider||'').toUpperCase()} queue`:'';
    const eta=state==='running'&&j.eta_seconds!=null?` • approx. ${storeJobEta(j.eta_seconds)} remaining`:'';
    const op=String(j.operation||'install');const detail=[String(j.provider||'').toUpperCase(),op.charAt(0).toUpperCase()+op.slice(1),storeJobStateText(state)].join(' • ')+queue+(bytes?` • ${humanBytes(bytes)}${total?` / ${humanBytes(total)}`:''}`:'')+(speed?` • ${humanBytes(speed)}/s`:'')+eta;
    const indeterminate=state==='running'&&!hasPct;
    const aria=hasPct||state==='completed'?`role="progressbar" aria-valuenow="${pct.toFixed(0)}" aria-valuemin="0" aria-valuemax="100"`:'role="progressbar" aria-label="Waiting for provider progress"';
    return `<article class="store-job-row" data-job-id="${esc(j.id)}" data-state="${esc(state)}"><div><div class="store-job-title">${esc(j.title||j.app_id||'Store game')}</div><div class="store-job-meta">${esc(detail)}</div><div class="store-job-progress${indeterminate?' indeterminate':''}" ${aria}><span style="width:${pct}%"></span></div><span class="store-job-progress-label">${state==='completed'?'100% complete':hasPct?`${pct.toFixed(0)}%`:(state==='running'?op.charAt(0).toUpperCase()+op.slice(1)+'…':storeJobStateText(state))}</span><div class="store-job-message">${esc(j.message||j.error||'')}</div></div><div class="store-job-actions">${active&&!(j.operation==='uninstall'&&state!=='queued')?`<button class="control-button tv-focus" data-store-job-cancel="${esc(j.id)}" type="button">${state==='cancelling'?'Stopping…':'Cancel'}</button>`:''}${retry?`<button class="control-button primary tv-focus" data-store-job-retry="${esc(j.id)}" type="button">Retry</button>`:''}${terminal?`<button class="control-button tv-focus" data-store-job-delete="${esc(j.id)}" type="button">Clear history</button>`:''}</div>${j.log_tail?`<details class="store-job-log" data-log-job="${esc(j.id)}"><summary>Recent provider output</summary>${esc(j.log_tail)}</details>`:''}</article>`;
  }).join('')||'<div class="library-empty">No game jobs match this view. Browse Store Library to manage a game.</div>';
  if(storeJobsRenderedHtml!==html){list.innerHTML=html;storeJobsRenderedHtml=html;list.scrollTop=previousScroll;for(const id of openLogs){const entry=[...list.querySelectorAll('details[data-log-job]')].find(x=>x.dataset.logJob===id);if(entry)entry.open=true}if(focusId&&focusAttribute){const next=[...list.querySelectorAll(`[${focusAttribute}]`)].find(x=>x.getAttribute(focusAttribute)===focusId);next?.focus({preventScroll:true})}}
}
async function refreshStoreJobs(){if(storeJobsRequestBusy)return;storeJobsRequestBusy=true;try{const data=await fetchStoreJobs();renderStoreJobs(data);storeInstallJobs=data.jobs||[];updateStoreInstallControls()}catch(e){const summary=document.getElementById('store-jobs-summary');if(summary)summary.textContent=`Unable to refresh downloads: ${e.message||e}. Retry with Refresh.`}finally{storeJobsRequestBusy=false}}
function openStoreJobs(jobId=''){const modal=document.getElementById('store-jobs-modal');modal?.classList.add('show');refreshStoreJobs().then(()=>{if(jobId){const row=[...document.querySelectorAll('#store-jobs-list [data-job-id]')].find(x=>x.dataset.jobId===jobId);row?.scrollIntoView({block:'nearest'});row?.querySelector('.tv-focus')?.focus({preventScroll:true})}});if(storeJobsTimer)clearInterval(storeJobsTimer);storeJobsTimer=setInterval(()=>{if(modal?.classList.contains('show')&&!document.hidden)refreshStoreJobs()},2500);setTimeout(()=>document.querySelector('#store-jobs-modal [data-store-job-filter="all"]')?.focus(),0)}
function closeStoreJobs(){document.getElementById('store-jobs-modal')?.classList.remove('show');if(storeJobsTimer){clearInterval(storeJobsTimer);storeJobsTimer=null}setTimeout(()=>document.querySelector('#pc-game-browser .tv-focus')?.focus()||document.querySelector('[data-tool="lancommander"]')?.focus(),0)}
async function storeJobAction(action,id){if(action==='store-job-cancel'){const job=storeJobsLastData?.jobs?.find(x=>x.id===id);if(job?.state==='running'&&!confirm(`Cancel ${job.operation||'install'} for ${job.title||job.app_id}? A cancelled update/repair may leave incomplete game files; retry before playing.`))return}try{await storeAccountAction(action,{id});await refreshStoreJobs()}catch(e){showStatus('Game maintenance action failed',e.message||String(e),'warn',8500)}}
let storeMaintenanceSelected=null;let storeMaintenanceBusy=false;let storeMaintenanceNonce=0;
function closeStoreMaintenance(){storeMaintenanceNonce++;storeMaintenanceSelected=null;storeMaintenanceBusy=false;document.getElementById('store-maintain-modal')?.classList.remove('show');document.querySelector('#pc-game-browser [data-store-maintain]')?.focus()}
async function openStoreMaintenance(key,operation){
  if(!['update','verify','uninstall'].includes(operation))return;
  const game=storeLibraryItems.find(x=>x.provider+':'+String(x.provider_game_id)===key)||pcGameItems.find(x=>x.source==='pcga-store'&&x.provider+':'+String(x.provider_game_id)===key);
  if(!game||!['epic','gog'].includes(game.provider))return;
  const token=++storeMaintenanceNonce;
  storeMaintenanceSelected={...game,operation};storeMaintenanceBusy=true;
  const modal=document.getElementById('store-maintain-modal'),detail=document.getElementById('store-maintain-detail'),button=document.getElementById('store-maintain-confirm');
  const verb={update:'Update',verify:'Verify files',uninstall:'Uninstall'}[operation];
  document.getElementById('store-maintain-heading').textContent=verb;
  document.getElementById('store-maintain-sub').textContent=(game.provider_label||game.source_label||game.provider)+' • managed PCGA game';
  document.getElementById('store-maintain-title').textContent=game.title||game.provider_game_id;
  document.getElementById('store-maintain-warning').textContent=operation==='uninstall'?'Uninstall deletes files in this PCGA-managed game directory, including any local saves or mods stored inside it. Your store ownership and separate PCGA Wine/Proton prefixes are not removed. Back up local saves first. This cannot be undone.':operation==='verify'?'Epic checks installed files; GOG repair can download replacement files. Back up any modified game files before proceeding.':'The store may download updated game files. Saves and Wine/Proton prefixes remain untouched.';
  button.disabled=true;button.textContent='Checking…';detail.textContent='Checking installed game, storage and active sessions…';modal.classList.add('show');modal.querySelector('[data-store-maintain-close]')?.focus();
  try{const preflight=await storeAccountAction('store-maintenance-preflight',{provider:game.provider,app_id:game.provider_game_id,operation});if(token!==storeMaintenanceNonce)return;storeMaintenanceSelected={...game,operation,preflight};detail.textContent=preflight.active_job?`A ${preflight.active_job.operation} job already exists for this game. Open Downloads & Maintenance to track it.`:preflight.detail;button.disabled=!preflight.can_enqueue;button.textContent=preflight.active_job?'Job already active':operation==='uninstall'?'Uninstall game files':verb+' now'}
  catch(e){if(token===storeMaintenanceNonce){detail.textContent=e.message||String(e);button.textContent='Unavailable';button.disabled=true}}
  finally{if(token===storeMaintenanceNonce)storeMaintenanceBusy=false}
}
async function confirmStoreMaintenance(){if(storeMaintenanceBusy||!storeMaintenanceSelected?.preflight?.can_enqueue)return;const game=storeMaintenanceSelected,button=document.getElementById('store-maintain-confirm');storeMaintenanceBusy=true;button.disabled=true;button.textContent='Queuing…';try{await storeAccountAction('store-job-enqueue',{provider:game.provider,app_id:game.provider_game_id,operation:game.operation});closeStoreMaintenance();showStatus('Maintenance queued',`${game.operation} queued for ${game.title||game.provider_game_id}`,'good',5500);openStoreJobs()}catch(e){document.getElementById('store-maintain-detail').textContent=e.message||String(e);button.textContent='Retry';button.disabled=false}finally{storeMaintenanceBusy=false}}
function stopStoreInstallPoll(){if(storeInstallPoll){clearInterval(storeInstallPoll);storeInstallPoll=null}}
function updateStoreInstallControls(){for(const container of document.querySelectorAll('[data-store-game-controls]')){const item=storeLibraryItems.find(x=>x.provider+':'+String(x.provider_game_id)===container.dataset.storeGameControls);if(!item)continue;const html=storeGameInstallControls(item);if(container.innerHTML===html)continue;const hadFocus=container.contains(document.activeElement);container.innerHTML=html;if(hadFocus)container.querySelector('.tv-focus')?.focus({preventScroll:true})}}
function startStoreInstallPoll(){stopStoreInstallPoll();storeInstallPoll=setInterval(async()=>{if(!document.getElementById('pc-game-browser')?.classList.contains('show')||!document.getElementById('store-library-search-form')){stopStoreInstallPoll();return}try{const data=await fetchStoreJobs();storeInstallJobs=data.jobs||[];updateStoreInstallControls()}catch(_){}},3500)}
function closeStoreInstall(){document.getElementById('store-install-modal')?.classList.remove('show');storeInstallSelected=null;storeInstallBusy=false;document.querySelector('#pc-game-browser [data-store-install]')?.focus()}
async function openStoreInstall(appId){const game=storeLibraryItems.find(x=>x.provider+':'+String(x.provider_game_id)===String(appId));if(!game||game.installed||game.installable===false)return;storeInstallSelected=game;storeInstallBusy=true;const m=document.getElementById('store-install-modal'),name=document.getElementById('store-install-title'),detail=document.getElementById('store-install-detail'),btn=document.getElementById('store-install-confirm');name.textContent=game.title||game.provider_game_id;document.getElementById('store-install-provider-heading').textContent=`Install from ${game.provider_label||game.provider}`;detail.textContent=`Checking ${game.provider_label||game.provider} ownership, available space and queue…`;btn.disabled=true;btn.textContent='Checking…';m.classList.add('show');m.querySelector('[data-store-install-close]')?.focus();try{const d=await storeAccountAction('store-install-preflight',{provider:game.provider,app_id:game.provider_game_id});if(storeInstallSelected!==game)return;storeInstallSelected={...game,preflight:d};const gb=(Number(d.free_bytes||0)/(1024**3)).toFixed(1);const pending=d.active_job||d.completed_job;detail.textContent=pending?`A download for this title is already ${pending.state}. Open Downloads to monitor it.`:`${gb} GiB free in PCGA game storage. At least 2 GiB is reserved. Estimated game size is not available from the store catalog; the downloader reports disk-space errors.`;btn.disabled=!d.can_enqueue;btn.textContent=pending?'Already in Downloads':'Add to downloads'}catch(e){if(storeInstallSelected===game){detail.textContent=e.message||String(e);btn.textContent='Unavailable';btn.disabled=true}}finally{storeInstallBusy=false}}
async function confirmStoreInstall(){if(storeInstallBusy||!storeInstallSelected?.preflight?.can_enqueue)return;const game=storeInstallSelected,btn=document.getElementById('store-install-confirm');storeInstallBusy=true;btn.disabled=true;btn.textContent='Adding…';try{await storeAccountAction('store-job-enqueue',{provider:game.provider,operation:'install',app_id:game.provider_game_id});closeStoreInstall();showStatus(`${game.provider_label||game.provider} download queued`,`${game.title||game.provider_game_id} is now in Downloads.`,'good',5500);openStoreJobs()}catch(e){document.getElementById('store-install-detail').textContent=e.message||String(e);btn.textContent='Try again';btn.disabled=false}finally{storeInstallBusy=false}}
async function storeAccountConnect(provider){
  if(storeLoginBusy||!['epic','gog','amazon'].includes(provider))return;
  const sequence=++storeLoginSequence,controller=new AbortController();
  storeLoginAbort=controller;storeLoginBusy=true;
  storeAuthBegin(provider);
  try{
    await storeBackendsReadyForLogin(provider,controller.signal);
    if(sequence!==storeLoginSequence||controller.signal.aborted)return;
    storeAuthMessage('starting','Preparing a secure sign-in link…');
    const d=await storeAccountAction('store-account-login-start',{provider},controller.signal);
    if(sequence!==storeLoginSequence||controller.signal.aborted)return;
    storeAuthShowReady(provider,d);
  }catch(e){
    if(sequence!==storeLoginSequence||controller.signal.aborted)return;
    storeAuthMessage('error','Back to accounts or Back to PCGA are always available.',e.message||String(e));
  }finally{
    if(sequence===storeLoginSequence){storeLoginBusy=false;storeLoginAbort=null;await loadControlCenter();}
  }
}
async function storeAccountComplete(){
  const provider=storeAuthProvider,code=document.getElementById('store-auth-code')?.value||'';
  if(!provider||storeAuthSubmitting)return;
  if(!code.trim()){storeAuthMessage('ready','Paste the one-time code returned by the provider.', 'An authorization code is required.');return;}
  const sequence=storeLoginSequence,submit=document.querySelector('[data-store-auth-submit]');
  storeAuthSubmitting=true;
  if(submit){submit.disabled=true;submit.textContent='Connecting…';}
  storeAuthMessage('submitting','Exchanging the one-time code with the selected provider…');
  try{
    const d=await storeAccountAction('store-account-login-complete',{provider,code});
    if(sequence!==storeLoginSequence)return;
    closeStoreAuth();
    showStatus('Store account connected',d.detail||'Account connection completed.','good',6500);
    await loadControlCenter();
  }catch(e){if(sequence===storeLoginSequence)storeAuthMessage('ready','Check the code and try again, or return to PCGA.',e.message||String(e));}
  finally{if(sequence===storeLoginSequence){storeAuthSubmitting=false;if(submit){submit.disabled=false;submit.textContent='Finish connection';}}}
}
async function storeAccountLogout(provider){if(!confirm(`Disconnect the ${provider==='epic'?'Epic':provider==='gog'?'GOG':'Amazon'} account from this PCGA appliance? Installed game files are not removed.`))return;try{const d=await storeAccountAction('store-account-logout',{provider});showStatus('Store account disconnected',d.detail||'Account disconnected.','good',6000);await loadControlCenter()}catch(e){showStatus('Store account disconnect failed',e.message||String(e),'warn',9000)}}
async function openPodcastBrowser(search=''){audioHubMode='podcasts';const box=document.getElementById('music-browser'),panel=document.getElementById('music-panel');box.classList.add('show');panel.innerHTML='<div class="music-empty">Loading podcasts…</div>';try{const subsPromise=audioJson('/api/control/audio/podcasts/subscriptions',{cache:'no-store'}),foundPromise=search?audioJson('/api/control/audio/podcasts/search?'+new URLSearchParams({q:search,limit:'30'}),{cache:'no-store'}):Promise.resolve({items:[],provider:'gPodder directory'});const [subs,found]=await Promise.all([subsPromise,foundPromise]);podcastSubscriptions=subs.items||[];podcastResults=found.items||[];panel.innerHTML=`<div class="music-browser-head"><div><div class="music-browser-title">Podcasts</div><div class="music-browser-sub">Search openly, subscribe by RSS, and play episodes in the PCGA portal.</div></div><button class="music-close tv-focus" data-music-close aria-label="Close">×</button></div>${audioHubTabs()}<form id="podcast-search-form" class="audio-search-row"><input id="podcast-search-input" class="tv-focus" value="${esc(search)}" placeholder="Search podcasts or paste an RSS feed URL" autocomplete="off"><button class="tv-focus" type="submit">Search</button></form><div class="audio-provider-note">PCGA can act as an AntennaPod sync server. In AntennaPod choose Settings → Synchronization → gPodder → Other server and enter this PCGA portal address. Use username pcga-admin and the appliance password shown by sudo game-archive credentials. Search is only used to locate publisher RSS feeds; playback comes directly from the publisher feed.</div>${podcastSubscriptions.length?`<div class="music-section-head"><h3>Subscriptions</h3><span>${podcastSubscriptions.length}</span></div><div class="audio-grid">${podcastSubscriptions.map((x,i)=>audioCard(x,i,'podcast-sub')).join('')}</div>`:''}${search?`<div class="music-section-head"><h3>Search results</h3><span>${podcastResults.length}</span></div><div class="audio-grid">${podcastResults.length?podcastResults.map((x,i)=>audioCard(x,i,'podcast')).join(''):'<div class="music-empty">No podcasts found.</div>'}</div>`:(!podcastSubscriptions.length?'<div class="music-empty">Search for a podcast, or paste a public RSS/Atom feed URL to subscribe directly.</div>':'')}`;setTimeout(()=>document.querySelector('#music-browser .tv-focus')?.focus(),0)}catch(e){panel.innerHTML=`<div class="music-browser-head"><div class="music-browser-title">Podcasts</div><button class="music-close tv-focus" data-music-close>×</button></div>${audioHubTabs()}<div class="music-empty">${esc(e.message||e)}</div>`}}
async function openPodcastFeed(item){const panel=document.getElementById('music-panel');panel.innerHTML='<div class="music-empty">Loading podcast feed…</div>';try{podcastFeed=await audioJson('/api/control/audio/podcasts/feed?'+new URLSearchParams({url:item.feed_url,limit:'120'}),{cache:'no-store'});const f=podcastFeed,art=f.art_url||item.art_url||'';panel.innerHTML=`<div class="music-browser-head"><div><div class="music-browser-title">${esc(f.title||item.title||'Podcast')}</div><div class="music-browser-sub">${esc(f.author||item.author||'Publisher RSS')}</div></div><div class="library-head-actions"><button class="library-upload tv-focus" data-podcast-subscribe type="button">${f.subscribed?'Subscribed':'Subscribe'}</button><a class="library-upload tv-focus" target="_blank" rel="noopener" href="https://antennapod.org/deeplink/subscribe?${new URLSearchParams({url:f.feed_url,title:f.title||item.title||'Podcast'}).toString()}">Open in AntennaPod</a><button class="music-close tv-focus" data-music-close>×</button></div></div>${audioHubTabs()}<div class="audio-detail"><div class="audio-detail-hero">${artStack(art,fallbackMarkup('podcast',f),'audio-detail-cover',f.title||item.title||'Podcast artwork')}<div><h2>${esc(f.title||item.title||'Podcast')}</h2><p>${esc(f.description||'')}</p><div class="audio-detail-meta"><span class="audio-chip">${f.episodes?.length||0} recent episodes</span><span class="audio-chip">RSS feed</span></div></div></div><div class="audio-episodes">${(f.episodes||[]).map((ep,i)=>{const pct=ep.duration_seconds?Math.min(100,(Number(ep.resume_seconds)||0)*100/ep.duration_seconds):0;return `<button class="audio-episode tv-focus" data-group="podcast-episodes" data-podcast-episode="${i}" type="button"><span><span class="audio-episode-title">${esc(ep.title)}</span><span class="audio-episode-meta">${esc(audioDate(ep.published))}${ep.duration_seconds?` • ${fmt(ep.duration_seconds)}`:''}</span>${pct>1?`<span class="audio-progress-mini"><span style="width:${pct}%"></span></span>`:''}</span><span>▶</span></button>`}).join('')||'<div class="music-empty">No playable enclosures were found in this feed.</div>'}</div></div>`}catch(e){showStatus('Podcast feed failed',String(e.message||e),'warn',9000);openPodcastBrowser('')}}
async function podcastSubscribe(){if(!podcastFeed?.feed_url)return;try{const d=await audioJson('/api/control/audio/podcasts/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({feed_url:podcastFeed.feed_url})});showStatus('Podcast subscribed',d.subscription?.title||podcastFeed.title,'good',4000);podcastFeed.subscribed=true;await openPodcastFeed({feed_url:podcastFeed.feed_url,title:podcastFeed.title,author:podcastFeed.author,art_url:podcastFeed.art_url})}catch(e){showStatus('Subscription failed',String(e.message||e),'warn',8000)}}
async function openAudiobookBrowser(search='',field='title'){audioHubMode='audiobooks';const box=document.getElementById('music-browser'),panel=document.getElementById('music-panel');box.classList.add('show');panel.innerHTML='<div class="music-empty">Loading audiobooks…</div>';try{const collPromise=audioJson('/api/control/audio/librivox/collection',{cache:'no-store'}),foundPromise=search?audioJson('/api/control/audio/audiobooks/search?'+new URLSearchParams({q:search,field,limit:'40'}),{cache:'no-store'}):Promise.resolve({items:[],local_items:[],online_items:[],provider:'PCGA local library + LibriVox',remote_provider:'LibriVox'});const [coll,found]=await Promise.all([collPromise,foundPromise]);audiobookCollection=coll.items||[];audiobookRecentUploads=coll.recent_uploaded||[];audiobookResults=found.items||[];const localHits=(found.local_items||[]).map(x=>({item:x,index:audiobookResults.findIndex(y=>String(y.id)===String(x.id))})).filter(x=>x.index>=0),onlineHits=(found.online_items||[]).map(x=>({item:x,index:audiobookResults.findIndex(y=>String(y.id)===String(x.id))})).filter(x=>x.index>=0),remoteProvider=found.remote_provider||'LibriVox';const recentIds=new Set(audiobookRecentUploads.map(x=>String(x.id))),remainingCollection=audiobookCollection.filter(x=>!recentIds.has(String(x.id))),collectionRows=audiobookRecentUploads.length?remainingCollection:audiobookCollection,collectionTitle=audiobookRecentUploads.length?'More in your collection':'Your collection';const recentShelf=!search&&audiobookRecentUploads.length?`<div class="music-section-head"><h3>Recently uploaded</h3><span>${audiobookRecentUploads.length}</span></div><div class="audio-grid">${audiobookRecentUploads.map(x=>audioCard(x,audiobookCollection.findIndex(y=>String(y.id)===String(x.id)),'audiobook-col')).join('')}</div>`:'';const collectionShelf=!search&&collectionRows.length?`<div class="music-section-head"><h3>${collectionTitle}</h3><span>${collectionRows.length}</span></div><div class="audio-grid">${collectionRows.map(x=>audioCard(x,audiobookCollection.findIndex(y=>String(y.id)===String(x.id)),'audiobook-col')).join('')}</div>`:'';const searchShelves=search?`${localHits.length?`<div class="music-section-head"><h3>Local library</h3><span>${localHits.length}</span></div><div class="audio-grid">${localHits.map(x=>audioCard(x.item,x.index,'audiobook')).join('')}</div>`:''}<div class="music-section-head"><h3>${esc(remoteProvider)} catalog</h3><span>${onlineHits.length}</span></div><div class="audio-grid">${onlineHits.length?onlineHits.map(x=>audioCard(x.item,x.index,'audiobook')).join(''):'<div class="music-empty">No online audiobooks matched this search.</div>'}</div>${found.remote_error?`<div class="audio-provider-note">Online catalog warning: ${esc(found.remote_error)}. Local search results are still available.</div>`:''}`:'';panel.innerHTML=`<div class="music-browser-head"><div><div class="music-browser-title">Audiobooks</div><div class="music-browser-sub">Recently uploaded local books, your collection, and public-domain catalog search in one place.</div></div><div class="library-head-actions"><button class="library-upload tv-focus" data-upload-kind="audiobook" type="button">Upload audiobook</button><button class="music-close tv-focus" data-music-close aria-label="Close">×</button></div></div>${audioHubTabs()}<form id="audiobook-search-form" class="audio-search-row"><input id="audiobook-search-input" class="tv-focus" value="${esc(search)}" placeholder="Search local library + LibriVox" autocomplete="off"><select id="audiobook-search-field" class="tv-focus"><option value="title" ${field==='title'?'selected':''}>Title</option><option value="author" ${field==='author'?'selected':''}>Author</option><option value="genre" ${field==='genre'?'selected':''}>Genre</option></select><button class="tv-focus" type="submit">Search</button></form><div class="audio-provider-note">Search checks books already stored on PCGA first, then LibriVox. If the LibriVox API is throttled or blocked, PCGA automatically searches the Internet Archive LibriVox collection instead. Included cover/folder/front artwork is shown when available.</div>${search?searchShelves:(recentShelf+collectionShelf+(!audiobookCollection.length?'<div class="music-empty">Upload an audiobook or search the local library and public-domain catalogs by title, author, or genre.</div>':''))}`;setTimeout(()=>document.querySelector('#music-browser .tv-focus')?.focus(),0)}catch(e){panel.innerHTML=`<div class="music-browser-head"><div class="music-browser-title">Audiobooks</div><button class="music-close tv-focus" data-music-close>×</button></div>${audioHubTabs()}<div class="music-empty">${esc(e.message||e)}</div>`}}
async function openAudiobookDetail(item){const panel=document.getElementById('music-panel');panel.innerHTML='<div class="music-empty">Loading audiobook…</div>';try{const d=await audioJson('/api/control/audio/librivox/book?'+new URLSearchParams({id:item.id}),{cache:'no-store'});audiobookDetail=d.book;const b=audiobookDetail,job=(await audioJson('/api/control/audio/librivox/collection',{cache:'no-store'})).jobs?.[`librivox-${b.id}`];const action=b.collected?'Collected locally':(job?.state==='downloading'?'Collecting…':'Collect locally');const source=b.uploaded?'PCGA local upload':(d.provider||'LibriVox');const collectControl=b.uploaded?'<span class="badge">Uploaded locally</span>':`<button class="library-upload tv-focus" data-audiobook-collect type="button" ${job?.state==='downloading'?'disabled':''}>${action}</button>`;panel.innerHTML=`<div class="music-browser-head"><div><div class="music-browser-title">Audiobook</div><div class="music-browser-sub">${esc(source)}</div></div><div class="library-head-actions">${collectControl}<button class="music-close tv-focus" data-music-close>×</button></div></div>${audioHubTabs()}${job&&job.state!=='complete'?`<div class="audio-job">Local collection: ${esc(job.state||'')} ${job.sections?`• chapter ${job.section||0}/${job.sections}`:''}${job.detail?` • ${esc(job.detail)}`:''}</div>`:''}<div class="audio-detail"><div class="audio-detail-hero">${artStack(b.art_url,fallbackMarkup('audiobook',b),'audio-detail-cover',b.title||'Audiobook cover')}<div><h2>${esc(b.title)}</h2><div class="audio-detail-meta">${[b.author,b.language,b.total_time,b.copyright_year].filter(Boolean).map(x=>`<span class="audio-chip">${esc(x)}</span>`).join('')}</div><p>${esc(b.description||'')}</p></div></div><div class="audio-episodes">${(b.sections||[]).map((ch,i)=>{const pct=ch.duration_seconds?Math.min(100,(Number(ch.resume_seconds)||0)*100/ch.duration_seconds):0;return `<button class="audio-episode tv-focus" data-group="audiobook-chapters" data-audiobook-chapter="${i}" type="button"><span><span class="audio-episode-title">${String(ch.number).padStart(2,'0')}. ${esc(ch.title)}</span><span class="audio-episode-meta">${ch.readers?.length?`Read by ${esc(ch.readers.join(', '))} • `:''}${fmt(ch.duration_seconds)}${ch.local?' • Local copy':' • Stream'}</span>${pct>1?`<span class="audio-progress-mini"><span style="width:${pct}%"></span></span>`:''}</span><span>▶</span></button>`}).join('')||'<div class="music-empty">No playable chapters are available.</div>'}</div></div>`}catch(e){showStatus('Audiobook unavailable',String(e.message||e),'warn',9000);openAudiobookBrowser('')}}
async function collectAudiobook(){if(!audiobookDetail?.id)return;try{await audioJson('/api/control/audio/librivox/collect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:audiobookDetail.id})});showStatus('Audiobook collection started',`${audiobookDetail.title} will be copied chapter-by-chapter into PCGA.`,'good',5500);setTimeout(()=>openAudiobookDetail(audiobookDetail),1200)}catch(e){showStatus('Collection failed',String(e.message||e),'warn',9000)}}
function savePcgaAudioProgress(force=false){if(!pcgaAudioPlayer.active||!pcgaAudioPlayer.item?.key)return;const now=Date.now();if(!force&&now-pcgaAudioProgressAt<12000)return;pcgaAudioProgressAt=now;fetch('/api/control/audio/progress',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:pcgaAudioPlayer.item.key,seconds:Number(audio.currentTime)||0,duration:Number(audio.duration)||Number(pcgaAudioPlayer.item.duration_seconds)||0,feed_url:pcgaAudioPlayer.kind==='podcast'?(pcgaAudioPlayer.item.feed_url||''):'',episode_url:pcgaAudioPlayer.kind==='podcast'?(pcgaAudioPlayer.item.source_url||''):''}),keepalive:force}).catch(()=>{})}
function stopPcgaAudio(clear=true){if(!pcgaAudioPlayer.active)return;savePcgaAudioProgress(true);pcgaAudioPlayer.active=false;if(clear){audio.pause();audio.removeAttribute('src');audio.load()}renderMusic(externalMusicSession)}
function playPcgaAudio(item,kind,queue,index){if(!item?.stream_url)return;if(portalPlayer.active){reportPortal('stopped');portalPlayer={active:false,item:null,play_session_id:'',media_source_id:'',started:false}}if(pcgaAudioPlayer.active)savePcgaAudioProgress(true);audio.pause();pcgaAudioPlayer={active:true,kind,item,queue:[...(queue||[])],index:Number(index)||0};audio.src=item.stream_url;const seek=()=>{const pos=Number(item.resume_seconds)||0;if(pos>0&&Number.isFinite(audio.duration)&&audio.duration>0&&pos<audio.duration-10){try{audio.currentTime=pos}catch(_){}}};audio.addEventListener('loadedmetadata',seek,{once:true});audio.play().catch(e=>showStatus('Playback blocked',String(e.message||e),'warn',7000));renderMusic(externalMusicSession)}
function pcgaAudioMove(delta){const q=pcgaAudioPlayer.queue||[];if(!q.length)return;const i=(Math.max(0,pcgaAudioPlayer.index)+delta+q.length)%q.length;playPcgaAudio(q[i],pcgaAudioPlayer.kind,q,i)}

async function fetchPhotos(search=''){const q=new URLSearchParams({limit:'100'});if(search)q.set('search',search);const r=await fetch('/api/photos/library?'+q.toString(),{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);return d}
function renderPhotos(data,search=''){photoItems=data?.items||[];photoSearch=search;const panel=document.getElementById('photo-panel');panel.innerHTML=`<div class="photo-head"><div><div class="photo-title">Photos</div><div class="photo-sub">Shared PCGA photo archive • visible to Jellyfin and Immich</div></div><div class="library-head-actions"><button class="library-upload tv-focus" data-upload-kind="photos" type="button">Upload photos</button><button class="photo-close tv-focus" data-group="photos" data-photo-close aria-label="Close">×</button></div></div><form class="photo-search" id="photo-search-form"><input class="tv-focus" data-group="photos" id="photo-search-input" value="${esc(search)}" placeholder="Search file or folder names" autocomplete="off"><button class="tv-focus" data-group="photos" type="submit">Search</button><button class="tv-focus" data-group="photos" data-photo-slideshow type="button">Slideshow these</button></form><div class="photo-grid">${photoItems.length?photoItems.map((x,i)=>`<div class="photo-card"><button class="tv-focus" data-group="photos" data-photo-view="${i}" type="button" style="padding:0;border:0;background:transparent;color:inherit"><img loading="lazy" src="${esc(x.url)}" alt="${esc(x.title||x.name)}"><div class="photo-card-name">${esc(x.name)}</div></button><div class="photo-card-actions"><button class="photo-action tv-focus" data-group="photos" data-photo-wallpaper="${i}" type="button">Wallpaper</button></div></div>`).join(''):`<div class="photo-empty">No browser-compatible images found under the shared photo directory.</div>`}</div>`}
async function openPhotos(search=''){photoReturnFocus=document.activeElement?.closest?.('[data-tool]')||lastToolFocus||photoReturnFocus;document.getElementById('photo-browser').classList.add('show');document.getElementById('photo-panel').innerHTML='<div class="photo-empty">Loading photos…</div>';try{const d=await fetchPhotos(search);renderPhotos(d,search);setTimeout(()=>document.querySelector('#photo-browser .tv-focus')?.focus(),0)}catch(e){document.getElementById('photo-panel').innerHTML=`<div class="photo-head"><div><div class="photo-title">Photos</div></div><button class="photo-close tv-focus" data-photo-close>×</button></div><div class="photo-empty">${esc(e.message||e)}</div>`}}
function closePhotos(){document.getElementById('photo-browser').classList.remove('show');(photoReturnFocus||document.querySelector('[data-tool="photos"]'))?.focus?.()}
function setPhotoWallpaper(item){if(!item)return;portalSettings.photoId=item.id;portalSettings.photoName=item.name||item.title||'';portalSettings.pattern='photo';savePortalSettings();showStatus('Wallpaper set',portalSettings.photoName,'good',3000)}
function startPhotoSlideshow(search=photoSearch){portalSettings.slideshowQuery=String(search||'').slice(0,120);portalSettings.pattern='slideshow';savePortalSettings();showStatus('Slideshow started',portalSettings.slideshowQuery?`Filter: ${portalSettings.slideshowQuery}`:'Using the shared photo archive','good',3500)}
function viewPhoto(item){if(!item)return;photoViewerItem=item;document.getElementById('photo-viewer-image').src=item.url;document.getElementById('photo-viewer-image').alt=item.title||item.name||'Photo';document.getElementById('photo-viewer').classList.add('show');document.getElementById('photo-viewer-wallpaper').focus()}
function closePhotoViewer(){document.getElementById('photo-viewer').classList.remove('show');document.getElementById('photo-viewer-image').removeAttribute('src');photoViewerItem=null;setTimeout(()=>document.querySelector('#photo-browser .tv-focus')?.focus(),0)}
async function fetchJellyfinLibrary(search='',filter='all',parentId=''){const q=new URLSearchParams({limit:filter==='episodes'?'300':'60',filter});if(search)q.set('search',search);if(parentId)q.set('parent_id',parentId);const r=await fetch('/api/jellyfin/library?'+q.toString(),{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);return d}
function libraryFilterButton(id,label){return`<button type="button" class="library-filter tv-focus ${libraryFilter===id?'active':''}" data-group="library-filters" data-library-filter="${id}">${label}</button>`}
function libraryCard(x,index,group='library-grid'){const resume=Number(x.played_percent)||0;const meta=x.subtitle||x.type||'';const type=String(x.type||'video').toLowerCase();const typeClass=`media-${type.replace(/[^a-z0-9_-]+/g,'-')}`;const art=artStack(x.art_url,fallbackMarkup(type,x),'library-art',x.name||'Media artwork');const tail=type==='series'?'Browse episodes':fmt(x.runtime_seconds);return`<button class="library-item ${typeClass} tv-focus" data-group="${group}" data-library-index="${index}" type="button">${art}<span class="library-item-title">${esc(x.name)}</span><span class="library-item-meta">${esc(meta)}</span><span class="library-item-foot"><span>${esc(x.type||'Video')}</span><span>${esc(tail)}</span></span>${resume>0&&resume<98?`<span class="library-resume" title="Resume ${Math.round(resume)}%"><span style="width:${Math.max(1,Math.min(100,resume))}%"></span></span>`:''}</button>`}

function homeMediaSectionEnabled(id){return id==='continue'?portalSettings.homeMediaContinue:id==='recent'?portalSettings.homeMediaRecent:id==='added'?portalSettings.homeMediaAdded:true}
function homeMediaCard(item,sectionId,index){const key=`${sectionId}:${index}`,resume=Number(item.played_percent)||0,isConsole=item.kind==='console-game',isPc=item.kind==='pc-game',type=isConsole?'platform':isPc?'pcgame':String(item.kind==='audio'?'music':(item.type||'video')).toLowerCase(),art=artStack(item.art_url,fallbackMarkup(type,item),'library-art',item.name||'Artwork');homeMediaLookup.set(key,item);const action=(isConsole||isPc)?(sectionId==='added'?'View game':'Play again'):(sectionId==='continue'&&resume>0?`Resume ${Math.round(resume)}%`:item.kind==='audio'?'Play audio':'Play');const source=item.metadata_source_url?`<a class="home-media-source tv-focus" href="${esc(item.metadata_source_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${esc(item.metadata_attribution||'Metadata')} ↗</a>`:'';return`<div class="home-media-entry"><button class="home-media-card tv-focus" type="button" data-group="home-media-${esc(sectionId)}" data-home-media-key="${esc(key)}">${art}<span class="home-media-copy"><span class="home-media-name">${esc(item.name||item.title||'Untitled')}</span><span class="home-media-meta">${esc(item.subtitle||item.type||'Media')}</span><span class="home-media-foot"><span>${esc(item.type||item.kind||'Media')}</span><span>${esc(action)}</span></span></span>${resume>0&&resume<98?`<span class="library-resume" title="Resume ${Math.round(resume)}%"><span style="width:${Math.max(1,Math.min(100,resume))}%"></span></span>`:''}</button>${source}</div>`}
function renderHomeMediaSurface(){const box=document.getElementById('home-media-body');if(!box)return;homeMediaLookup=new Map();const sections=(homeMediaSections||[]).filter(s=>homeMediaSectionEnabled(s.id));if(!sections.length){box.innerHTML='<div class="home-media-empty">No shelves are enabled. Choose Continue, Recently Accessed, or Recently Added in Display settings.</div>';return}const visible=sections.filter(s=>(s.items||[]).length);if(!visible.length){box.innerHTML='<div class="home-media-empty">Nothing is available for the enabled shelves yet.</div>';return}box.innerHTML=visible.map(section=>`<section class="home-media-section" data-home-section="${esc(section.id)}"><div class="home-media-section-head"><h2>${esc(section.title||'Media')}</h2><span>${(section.items||[]).length} ${(section.items||[]).length===1?'item':'items'}</span></div><div class="home-media-row">${(section.items||[]).map((item,i)=>homeMediaCard(item,section.id,i)).join('')}</div></section>`).join('')}
async function loadHomeMediaSurface(force=false){if(!portalSettings.homeMediaEnabled)return;const box=document.getElementById('home-media-body');if(homeMediaBusy)return;if(!force&&homeMediaSections.length&&Date.now()-homeMediaLoadedAt<30000){renderHomeMediaSurface();return}homeMediaBusy=true;if(box)box.innerHTML='<div class="home-media-loading">Loading recent activity…</div>';try{const q=new URLSearchParams({limit:'12',include_games:portalSettings.homeMediaGames?'1':'0'}),r=await fetch('/api/jellyfin/home-media?'+q.toString(),{cache:'no-store'}),d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||`HTTP ${r.status}`);homeMediaSections=Array.isArray(d.sections)?d.sections:[];homeMediaLoadedAt=Date.now();renderHomeMediaSurface()}catch(e){homeMediaSections=[];if(box)box.innerHTML=`<div class="home-media-empty">Recent activity is unavailable right now.<br><small>${esc(e.message||e)}</small></div>`}finally{homeMediaBusy=false}}
function homeMediaOpen(){return document.body.classList.contains('media-surface-open')}
async function openHomeMediaSurface(){if(!portalSettings.homeMediaEnabled||homeMediaOpen())return false;homeMediaReturnFocus=document.activeElement?.closest?.(PCGA_NAV_SELECTOR)||document.activeElement;homeMediaReturnTool=homeMediaReturnFocus?.closest?.('[data-tool]')?.dataset?.tool||'';const shell=document.querySelector('.shell'),surface=document.getElementById('home-media-surface');document.body.classList.add('media-surface-open');surface?.classList.add('show');shell?.setAttribute('aria-hidden','true');if(shell)shell.inert=true;surface?.setAttribute('aria-hidden','false');await loadHomeMediaSurface(false);const first=surface?.querySelector('.home-media-card');if(first)pcgaSetSelection(first,{focus:true,scroll:true});else surface?.focus?.({preventScroll:true});return true}
function closeHomeMediaSurface(restoreFocus=true){if(!homeMediaOpen())return false;const shell=document.querySelector('.shell'),surface=document.getElementById('home-media-surface');document.body.classList.remove('media-surface-open');surface?.classList.remove('show');surface?.setAttribute('aria-hidden','true');shell?.removeAttribute('aria-hidden');if(shell)shell.inert=false;let target=homeMediaReturnFocus;if((!target||!document.contains(target))&&homeMediaReturnTool)target=[...document.querySelectorAll('[data-tool]')].find(x=>x.dataset.tool===homeMediaReturnTool)||null;homeMediaReturnFocus=null;homeMediaReturnTool='';if(restoreFocus&&target&&document.contains(target))pcgaSetSelection(target,{focus:true,scroll:true});return true}
function playHomeMediaKey(key){const item=homeMediaLookup.get(String(key||''));if(!item)return;homeMediaLastFocus=document.activeElement;if(item.kind==='console-game'){closeHomeMediaSurface(false);gameReturnFocus=document.querySelector('[data-tool="romm"]');document.getElementById('game-browser').classList.add('show');gameItems=[{id:item.id,name:item.name||item.title||'Console Game'}];gameDetails(0);return}if(item.kind==='pc-game'){closeHomeMediaSurface(false);pcGameReturnFocus=document.querySelector('[data-tool="lancommander"]');document.getElementById('pc-game-browser').classList.add('show');pcGameItems=[{...item,title:item.title||item.name||'PC Game'}];pcGameDetails(0);return}if(item.kind==='audio'){homeMediaLastFocus=null;playPortalItem(item.id,Number(item.resume_ticks)||0,item,-1)}else playVideoItem(item)}
function renderLibraryOverview(data){const sections=data?.sections||[];let offset=0;return`<div class="library-sections">${sections.map(section=>{const items=section.items||[];const start=offset;offset+=items.length;const group=`library-${section.id||'shelf'}`;const viewAll=section.id==='continue'?'':`<button class="library-section-more tv-focus" data-group="${group}" data-library-filter="${esc(section.filter||section.id||'all')}" type="button">View all</button>`;return`<section class="library-section"><div class="library-section-head"><div><h3>${esc(section.title||'Media')}</h3><span>${items.length} shown</span></div>${viewAll}</div><div class="library-shelf">${items.map((x,i)=>libraryCard(x,start+i,group)).join('')}</div></section>`}).join('')}</div>`}
function gamePlatformButton(p){const id=String(p?.id??'');return `<button class="library-filter tv-focus ${gamePlatform===id?'active':''}" data-group="game-filter" data-game-platform="${esc(id)}" type="button">${esc(p?.name||p?.slug||'Platform')}</button>`}
async function fetchGamePlatforms(){const r=await fetch('/api/games/platforms',{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);gamePlatforms=(d.items||[]).filter(x=>x.playable);return gamePlatforms}
async function fetchGames(search='',platform=''){const q=new URLSearchParams({limit:'120'});if(search)q.set('search',search);if(platform)q.set('platform_id',platform);const r=await fetch('/api/games/library?'+q.toString(),{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);return d}
function romReleaseDate(value){if(value===null||value===undefined||value==='')return null;let d;if(/^\d+$/.test(String(value))){const n=Number(value);d=new Date(n>1e12?n:n*1000)}else d=new Date(value);return Number.isNaN(d.getTime())?null:d}function romReleaseText(value){const d=romReleaseDate(value);return d?d.toLocaleDateString([],{year:'numeric',month:'short',day:'numeric'}):(value===null||value===undefined?'':String(value))}function romReleaseYear(value){const d=romReleaseDate(value);return d?String(d.getFullYear()):''}
function gameCard(x,i){const coverUrl=x.metadata_state==='identified'?x.cover_url:null;const art=artStack(coverUrl,fallbackMarkup('platform',x),'library-art',`${x.platform||x.platform_slug||'Console'} placeholder or game cover`);const release=romReleaseYear(x.release_date);const meta=[x.platform||x.platform_slug||'Console',release].filter(Boolean).join(' • ');return `<button class="library-item game-card tv-focus" data-group="game-grid" data-game-index="${i}" type="button">${art}<span class="game-play-badge">INFO</span><span class="library-item-title">${esc(x.name||'Untitled')}</span><span class="library-item-meta">${esc(meta)}</span><span class="library-item-foot"><span>${x.metadata_state==='identified'?'Metadata ready':x.metadata_state==='identifying'?'Identifying…':'Needs metadata'}</span><span>${esc((x.genres||[])[0]||x.default_core||'')}</span></span></button>`}
function renderGameBrowser(data,search='',platform=''){const panel=document.getElementById('game-panel');gameItems=data?.items||[];gameSearch=search;gamePlatform=String(platform||'');const enriched=gameItems.filter(x=>x.metadata_state==='identified'||x.cover_url||x.summary).length;const filters=`<button class="library-filter tv-focus ${!gamePlatform?'active':''}" data-group="game-filter" data-game-platform="" type="button">All playable</button>`+gamePlatforms.map(gamePlatformButton).join('');panel.innerHTML=`<div class="library-head"><div><div class="library-title">Console Games</div><div class="library-sub">PCGA portal emulation • ${gameItems.length} playable title${gameItems.length===1?'':'s'} shown • ${enriched} enriched</div></div><div class="library-head-actions"><button class="library-upload tv-focus" data-game-rescan type="button">Refresh metadata</button><button class="library-upload tv-focus" data-upload-kind="rom" type="button">Upload ROM</button><button class="library-upload tv-focus" data-upload-kind="bios" type="button">Upload BIOS</button><button class="library-close tv-focus" data-game-close aria-label="Close">×</button></div></div><div class="settings-note" style="margin:0 22px 14px">PCGA asks RomM to identify ROMs during library scans. Enabled metadata providers can add canonical titles, descriptions, dates, genres and cover art; select a game to inspect the collected profile before launching it.</div><div class="library-filters"><button class="library-filter tv-focus active" type="button">Library</button><button class="library-filter tv-focus" data-rom-collection-open type="button">Find ROMs</button></div><form class="library-search" id="game-search-form"><input class="tv-focus" id="game-search-input" value="${esc(search)}" placeholder="Search console games" autocomplete="off"><button class="tv-focus" type="submit">Search</button></form><div class="library-filters">${filters}</div><div class="library-grid">${gameItems.length?gameItems.map(gameCard).join(''):`<div class="library-empty">No browser-playable games match this view. Use Find ROMs to search rights-cleared Archive.org software, or use Advanced → RomM for unsupported systems.</div>`}</div>`}
async function fetchRomCollectionPlatforms(){const r=await fetch('/api/games/collection/platforms',{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||d.detail||r.status);romCollectionPlatforms=d.items||[];return romCollectionPlatforms}
function collectionPlatformOptions(){return romCollectionPlatforms.map(p=>`<option value="${esc(p.slug)}" ${romCollectionPlatform===p.slug?'selected':''}>${esc(p.name)}</option>`).join('')}
function romCollectionPlatformName(slug){return romCollectionPlatforms.find(p=>p.slug===slug)?.name||gamePlatforms.find(p=>p.slug===slug)?.name||slug}
async function fetchRomCollection(search='',platform='',page=1){const q=new URLSearchParams({q:search,platform:platform,page:String(page)});const r=await fetch('/api/games/collection/search?'+q.toString(),{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||d.detail||r.status);return d}
function romRightsBadge(x){const ok=!!x.verified_rights;return `<span class="badge" style="${ok?'':'opacity:.7'}">${ok?'✓ importable':'review'} • ${esc(x.rights_hint||'unverified')}</span>`}
function romCollectionCard(x,i){return `<article class="library-item" style="text-align:left;cursor:default"><div>${romRightsBadge(x)}</div><div class="library-item-title">${esc(x.title||x.identifier)}</div><div class="library-item-meta">${esc(x.creator||'Unknown creator')}${x.date?' • '+esc(x.date):''}</div><div class="library-item-meta">${esc(x.description||'')}</div><div class="control-actions" style="margin-top:12px"><button class="control-button primary tv-focus" data-rom-item-index="${i}" type="button">Inspect files</button><a class="control-button tv-focus" href="https://archive.org/details/${encodeURIComponent(x.identifier)}" target="_blank" rel="noopener">Archive.org</a></div></article>`}
function renderRomCollection(data,search='',platform='',page=1){const panel=document.getElementById('game-panel');romCollectionItems=data?.items||[];romCollectionSearch=search;romCollectionPlatform=platform;romCollectionPage=page;panel.innerHTML=`<div class="library-head"><div><div class="library-title">ROM Collection</div><div class="library-sub">Rights-aware Archive.org discovery • ${Number(data?.num_found||0).toLocaleString()} candidate item${Number(data?.num_found||0)===1?'':'s'}</div></div><button class="library-close tv-focus" data-game-close aria-label="Close">×</button></div><div class="library-filters"><button class="library-filter tv-focus" data-rom-collection-back type="button">Library</button><button class="library-filter tv-focus active" type="button">Find ROMs</button></div><form class="library-search" id="rom-collection-search-form"><select class="tv-focus" id="rom-collection-platform" required><option value="">Choose console…</option>${collectionPlatformOptions()}</select><input class="tv-focus" id="rom-collection-search-input" value="${esc(search)}" placeholder="Search public-domain, Creative Commons, homebrew…" autocomplete="off"><button class="tv-focus" type="submit">Search</button></form><div class="settings-note" style="margin:0 22px 14px">Search results may include old or freely downloadable software whose redistribution rights are unclear. One-click import is enabled only when Archive.org metadata contains an explicit public-domain, Creative Commons, or redistribution-permission signal.</div><div id="rom-collection-jobs"></div><div class="library-grid">${romCollectionItems.length?romCollectionItems.map(romCollectionCard).join(''):`<div class="library-empty">${platform?'No matching ROM collection items were found.':'Choose a console to search compatible Archive.org software.'}</div>`}</div>${Number(data?.num_found||0)>page*24?`<div class="control-actions" style="padding:16px 22px"><button class="control-button tv-focus" data-rom-next type="button">More results</button></div>`:''}`;pollRomCollectionJobs()}
async function openRomCollection(search='',platform='',page=1){if(!gamePlatforms.length)await fetchGamePlatforms();if(!romCollectionPlatforms.length)await fetchRomCollectionPlatforms();let chosen=platform||romCollectionPlatform||'';if(!chosen&&gamePlatform){chosen=String(gamePlatforms.find(p=>String(p.id)===String(gamePlatform))?.slug||'')}if(!chosen){renderRomCollection({items:[],num_found:0},search,'',1);return}document.getElementById('game-panel').innerHTML='<div class="library-empty">Searching Archive.org ROM collection…</div>';try{const d=await fetchRomCollection(search,chosen,page);renderRomCollection(d,search,chosen,page);startRomCollectionPolling()}catch(e){document.getElementById('game-panel').innerHTML=`<div class="library-head"><div><div class="library-title">ROM Collection</div><div class="library-sub">Archive.org collection endpoint</div></div><button class="library-close tv-focus" data-game-close>×</button></div><div class="library-empty">${esc(e.message||e)}</div>`}}
function romCollectionFileCard(f,i,allowed,identifier){const action=allowed?'<button class="control-button primary tv-focus" data-rom-import="'+i+'" data-rom-identifier="'+esc(identifier)+'" type="button">Import to library</button>':'<span class="badge">Import disabled</span>';return '<article class="library-item" style="text-align:left;cursor:default"><div class="library-item-title">'+esc(f.basename||f.name)+'</div><div class="library-item-meta">'+esc(f.ext||'')+' • '+fmtBytes(Number(f.size||0))+'</div><div class="library-item-meta">'+esc(f.format||'')+'</div><div class="control-actions" style="margin-top:12px">'+action+'</div></article>'}
async function openRomCollectionItem(index){const x=romCollectionItems[index];if(!x)return;const panel=document.getElementById('game-panel');panel.innerHTML='<div class="library-empty">Inspecting ROM files and rights…</div>';try{const q=new URLSearchParams({identifier:x.identifier,platform:romCollectionPlatform});const r=await fetch('/api/games/collection/item?'+q.toString(),{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||d.detail||r.status);const files=d.files||[],allowed=!!d.rights?.allowed;const fileHtml=files.length?files.map((f,i)=>romCollectionFileCard(f,i,allowed,d.identifier)).join(''):'<div class="library-empty">No compatible ROM files were found for this console in the item.</div>';panel.innerHTML=`<div class="library-head"><div><div class="library-title">${esc(d.title||d.identifier)}</div><div class="library-sub">${esc(romCollectionPlatformName(romCollectionPlatform))} • ${esc(d.rights?.basis||'unverified')}</div></div><button class="library-close tv-focus" data-game-close>×</button></div><div class="control-actions" style="padding:0 22px 14px"><button class="control-button tv-focus" data-rom-collection-return type="button">← Results</button><a class="control-button tv-focus" href="${esc(d.archive_url||'https://archive.org/details/'+encodeURIComponent(d.identifier))}" target="_blank" rel="noopener">Archive.org details</a></div><div class="settings-note" style="margin:0 22px 14px"><b>${allowed?'Import permitted by PCGA metadata policy':'Rights review required'}</b><br>${esc(d.rights?.detail||'No explicit redistribution signal found.')}</div><div class="library-grid">${fileHtml}</div>`;panel.dataset.romItem=JSON.stringify({identifier:d.identifier,files:files})}catch(e){panel.innerHTML=`<div class="library-head"><div><div class="library-title">ROM Collection</div></div><button class="library-close tv-focus" data-game-close>×</button></div><div class="library-empty">${esc(e.message||e)}</div>`}}
async function importRomFile(button){const panel=document.getElementById('game-panel');let detail={};try{detail=JSON.parse(panel.dataset.romItem||'{}')}catch(_){ }const f=detail.files?.[Number(button.dataset.romImport)];if(!f||!detail.identifier||!romCollectionPlatform)return;button.disabled=true;button.textContent='Queueing…';try{const r=await fetch('/api/games/collection/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({identifier:detail.identifier,file:f.name,platform:romCollectionPlatform})});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||d.detail||r.status);showStatus('ROM import queued',`${f.basename||f.name} will be added to Console Games and indexed by RomM.`,'ok',7000);button.textContent='Queued';startRomCollectionPolling()}catch(e){button.disabled=false;button.textContent='Import to library';showStatus('ROM import failed',e.message||String(e),'warn',9000)}}
async function pollRomCollectionJobs(){const box=document.getElementById('rom-collection-jobs');if(!box)return;try{const r=await fetch('/api/games/collection/jobs',{cache:'no-store'}),d=await r.json();if(!r.ok)return;const jobs=(d.jobs||[]).slice(0,6);box.innerHTML=jobs.length?`<div class="settings-note" style="margin:0 22px 14px"><b>ROM imports</b>${jobs.map(j=>`<div style="margin-top:8px"><span>${esc(j.title||j.file||j.identifier)}</span> — <b>${esc(j.state||'')}</b><div>${esc(j.message||'')}</div><progress max="100" value="${Number(j.progress||0)}" style="width:100%"></progress></div>`).join('')}</div>`:''}catch(_){}}
function startRomCollectionPolling(){if(romCollectionTimer)clearInterval(romCollectionTimer);romCollectionTimer=setInterval(pollRomCollectionJobs,1600);pollRomCollectionJobs()}
function stopRomCollectionPolling(){if(romCollectionTimer){clearInterval(romCollectionTimer);romCollectionTimer=null}}
async function openGameBrowser(search='',platform=''){gameReturnFocus=document.activeElement?.closest?.('[data-tool]')||lastToolFocus||gameReturnFocus;const box=document.getElementById('game-browser');box.classList.add('show');document.getElementById('game-panel').innerHTML='<div class="library-empty">Loading console library…</div>';try{if(!gamePlatforms.length)await fetchGamePlatforms();const d=await fetchGames(search,String(platform||''));renderGameBrowser(d,search,String(platform||''));setTimeout(()=>document.querySelector('#game-browser .tv-focus')?.focus(),0)}catch(e){document.getElementById('game-panel').innerHTML=`<div class="library-head"><div><div class="library-title">Console Games</div><div class="library-sub">PCGA emulator endpoint</div></div><button class="library-close tv-focus" data-game-close>×</button></div><div class="library-empty">${esc(e.message||e)}</div>`}}
function closeGameBrowser(){stopRomCollectionPolling();document.getElementById('game-browser').classList.remove('show');(gameReturnFocus||document.querySelector('[data-tool="romm"]'))?.focus?.()}
async function refreshRomMetadata(){try{const r=await fetch('/api/games/rescan',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}),d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);showStatus('Console metadata refresh queued',d.detail||'RomM is rescanning the library and enriching identified games.','good',7000)}catch(e){showStatus('Metadata refresh failed',e.message||String(e),'warn',9000)}}
async function gameDetails(i){const x=gameItems[Number(i)];if(!x)return;const panel=document.getElementById('game-panel');panel.innerHTML='<div class="library-empty">Loading console game metadata…</div>';try{const r=await fetch('/api/games/rom/'+encodeURIComponent(x.id),{cache:'no-store'}),d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);const cover=artStack(d.metadata_state==='identified'?d.cover_url:null,fallbackMarkup('platform',d),'game-detail-cover',d.name||'Console game cover');const release=romReleaseText(d.release_date);const genres=(d.genres||[]).map(v=>`<span class="game-detail-tag">${esc(v)}</span>`).join('');const facts=[];if((d.companies||[]).length)facts.push(['Companies',(d.companies||[]).join(', ')]);if((d.franchises||[]).length)facts.push(['Franchise',(d.franchises||[]).join(', ')]);if((d.game_modes||[]).length)facts.push(['Modes',(d.game_modes||[]).join(', ')]);if((d.regions||[]).length)facts.push(['Regions',(d.regions||[]).join(', ')]);if((d.languages||[]).length)facts.push(['Languages',(d.languages||[]).join(', ')]);if((d.metadata_providers||[]).length)facts.push(['Metadata',(d.metadata_providers||[]).join(', ')]);if(d.rating!==null&&d.rating!==undefined&&d.rating!=='')facts.push(['Rating',String(Math.round(Number(d.rating)*10)/10)]);if((d.alternative_names||[]).length)facts.push(['Also known as',(d.alternative_names||[]).slice(0,5).join(', ')]);const shots=(d.screenshots||[]).slice(0,6).map(u=>`<img src="${esc(u)}" loading="lazy" alt="Screenshot">`).join('');panel.innerHTML=`<div class="library-head"><div><div class="library-title">${esc(d.name||x.name||'Console Game')}</div><div class="library-sub">${esc([d.platform||d.platform_slug,release].filter(Boolean).join(' • ')||'Console game')}</div></div><button class="library-close tv-focus" data-game-close>×</button></div><div class="game-detail"><div class="game-detail-main">${cover}<div class="game-detail-copy"><div class="control-actions" style="margin-bottom:14px"><button class="control-button tv-focus" data-game-back type="button">← Library</button>${d.player_url?`<button class="control-button primary tv-focus" data-game-play-url="${esc(d.player_url)}" type="button">Play game</button>`:''}<button class="control-button tv-focus" data-game-rescan type="button">Refresh metadata</button></div><h2>${esc(d.name||x.name||'Console Game')}</h2><div class="game-detail-meta">${esc([d.platform||d.platform_slug,release,d.metadata_state==='identified'?'Metadata identified':'Metadata '+(d.metadata_state||'unknown')].filter(Boolean).join(' • '))}</div>${genres?`<div class="game-detail-tags">${genres}</div>`:''}<p class="game-detail-summary">${esc(d.summary||'No description has been collected yet. Use Refresh metadata to ask RomM to identify this ROM with the enabled providers.')}</p><div class="game-detail-facts">${facts.map(([k,v])=>`<div class="game-detail-fact"><b>${esc(k)}</b>${esc(v)}</div>`).join('')}</div></div></div>${shots?`<div class="game-detail-shots">${shots}</div>`:''}</div>`}catch(e){showStatus('Game metadata unavailable',e.message||String(e),'warn',9000);openGameBrowser(gameSearch,gamePlatform)}}
function playGame(i){gameDetails(i)}
async function fetchPcGames(search=''){const q=new URLSearchParams({limit:'120'});if(search)q.set('search',search);const r=await fetch('/api/pc-games/library?'+q.toString(),{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);return d}
function pcGameOwnedSessionForSet(setId){setId=String(setId||'').replace(/^pcga:/,'');if(!setId)return null;return pcGameActiveSessions.find(x=>String(x.game_set_id||'')===setId)||null}
function pcGameOwnedSessionForContainer(containerId){containerId=String(containerId||'');return pcGameActiveSessions.find(x=>String(x.container_id||'')===containerId)||null}
function pcGameCard(x,i){const art=artStack(x.cover_url,fallbackMarkup('pcgame',x),'library-art',x.title||'PC game cover');const st=x.install_status||'',ss=x.stream_state||'';const reviewing=st==='review-required'&&x.review_item_id;const preparing=st==='ready'&&ss==='pending-restart';const launchable=Boolean(x.launchable);const setupLaunchable=Boolean(x.setup_launchable||(x.setup_required&&ss==='setup-ready'));const active=pcGameOwnedSessionForSet(x.pcga_set_id||x.stream_id||'');const availability=active?(active.kind==='setup'?'SETUP ACTIVE':'SESSION ACTIVE'):reviewing?'NEEDS REVIEW':x.playable?'READY TO STREAM':preparing?'PREPARING STREAM':(launchable&&ss==='failed')?'RETRY STREAM':(setupLaunchable&&ss==='failed')?'RETRY INSTALLER':(x.setup_required&&ss==='setup-ready')?'INSTALLER READY':x.setup_required?'SETUP REQUIRED':st==='installing'?'INSTALLING':x.downloadable?'PACKAGE READY':st==='queued'?'QUEUED':'METADATA';const details=[x.source_label||null,x.year,x.developer||x.publisher,x.type,Number(x.record_count)>1?`${Number(x.record_count)} records consolidated`:null].filter(Boolean).join(' • ');const desc=x.description?`<span class="library-item-meta">${esc(String(x.description).slice(0,180))}</span>`:'';let play='';if(active)play=`<button class="photo-action tv-focus" data-pc-session-resume="${esc(active.container_id||'')}" type="button">${active.kind==='setup'?'Resume setup':'Resume game'}</button>`;else if(x.playable&&Array.isArray(x.launch_variants)&&x.launch_variants.length>1)play=`<button class="photo-action tv-focus" data-pc-game-detail="${i}" type="button">Choose mode</button>`;else if(x.playable)play=`<button class="photo-action tv-focus" data-pc-stream="${esc(x.stream_id)}" type="button">Play in portal</button>`;else if(preparing)play=`<button class="photo-action tv-focus" data-pc-stream="${esc(x.stream_id)}" type="button">Prepare stream</button>`;else if(launchable)play=`<button class="photo-action tv-focus" data-pc-stream="${esc(x.stream_id)}" type="button">Retry stream</button>`;else if(x.setup_required&&ss==='setup-ready')play=`<button class="photo-action tv-focus" data-pc-stream="${esc(x.stream_id)}" type="button">Install in portal</button>`;else if(setupLaunchable)play=`<button class="photo-action tv-focus" data-pc-stream="${esc(x.stream_id)}" type="button">Retry installer</button>`;const repair=!reviewing&&!play&&x.pcga_set_id&&!x.heroic&&!String(x.source||'').startsWith('heroic')?`<button class="photo-action tv-focus" data-pc-retry="${esc(x.stream_id||('pcga:'+x.pcga_set_id))}" type="button">Repair launch</button>`:'';const review=reviewing?`<button class="photo-action tv-focus" data-review-open-item="${esc(x.review_item_id)}" type="button">Review classification</button>`:'';const dl=x.downloadable?`<a class="photo-action tv-focus" href="${esc(x.download_url)}" download>Download package</a>`:'';const detail=reviewing?'':`<button class="photo-action tv-focus" data-pc-game-detail="${i}" type="button">Details</button>`;const compatButton=x.source==='pcga-store'?`<button class="photo-action tv-focus" data-store-compat-open="${esc(x.pcga_set_id)}" data-store-compat-title="${esc(x.title||'Store game')}" type="button">Wine / Proton</button>`:'';const manage=x.source==='pcga-store'&&x.provider&&x.provider_game_id?`<button class="photo-action tv-focus" data-store-maintain="${esc(x.provider+':'+x.provider_game_id)}" data-store-maintain-operation="update" type="button">Update</button><button class="photo-action tv-focus" data-store-maintain="${esc(x.provider+':'+x.provider_game_id)}" data-store-maintain-operation="verify" type="button">Verify files</button><button class="photo-action tv-focus" data-store-maintain="${esc(x.provider+':'+x.provider_game_id)}" data-store-maintain-operation="uninstall" type="button">Uninstall</button>`:'';const source=x.metadata_source_url?`<a class="photo-action tv-focus" href="${esc(x.metadata_source_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${esc(x.metadata_attribution||x.metadata_provider||'Metadata')} ↗</a>`:'';const attrs=reviewing?`data-pc-review-item="${esc(x.review_item_id)}"`:`data-pc-game-open="${i}"`;return `<div class="library-item pc-game-card tv-focus" tabindex="0" role="button" ${attrs} data-group="pc-game-grid">${art}<span class="game-play-badge">${esc(availability)}</span><span class="library-item-title">${esc(x.title||'Unidentified PC Game')}</span><span class="library-item-meta">${esc(details||'PC Game')}</span>${desc}<span class="library-item-foot"><span>${esc(x.install_phase||x.version||'')}</span><span>${x.package_bytes?fmtBytes(x.package_bytes):''}</span></span><div class="control-actions">${review}${play}${repair}${detail}${compatButton}${manage}${source}${dl}</div></div>`}
function renderPcGameBrowser(data,search=''){const panel=document.getElementById('pc-game-panel');pcGameItems=data?.items||[];pcGameSearch=search;panel.innerHTML=`<div class="library-head"><div><div class="library-title">PC Games</div><div class="library-sub">PCGA game library • ${pcGameItems.length} title${pcGameItems.length===1?'':'s'} shown</div></div><div class="library-head-actions"><button class="control-button primary tv-focus" data-store-library type="button">Store Library</button><button class="control-button tv-focus" data-store-jobs type="button">Downloads</button><button class="control-button tv-focus" data-store-backends type="button">Store settings</button><button class="control-button tv-focus" data-pc-discs type="button">Disc images</button><button class="control-button tv-focus" data-pc-sessions type="button">Sessions</button><button class="library-upload tv-focus" data-upload-kind="pc-game" type="button">Upload PC game</button><button class="library-close tv-focus" data-pc-game-close aria-label="Close">×</button></div></div><form class="library-search" id="pc-game-search-form"><input class="tv-focus" id="pc-game-search-input" value="${esc(search)}" placeholder="Search PC games" autocomplete="off"><button class="tv-focus" type="submit">Search</button></form>${pcGameActiveSessions.length?`<div class="settings-note" style="margin:0 22px 14px"><b>${pcGameActiveSessions.length} active session${pcGameActiveSessions.length===1?'':'s'} owned by this browser.</b> Titles with a live desktop show <b>Resume game/setup</b>; Sessions can reopen or end them without launching duplicates.</div>`:''}<div class="settings-note" style="margin:0 22px 14px">PCGA is authoritative for ingested games and Wolf/Moonlight readiness. Preserved optical images remain immutable source artifacts; use Disc images to inspect ownership, then search the configured game database to build a canonical title profile.</div><div class="library-grid">${pcGameItems.length?pcGameItems.map(pcGameCard).join(''):`<div class="library-empty">No PC games have reached the catalog yet. Insert or upload a game disc and PCGA will add it here after classification.</div>`}</div>`}

async function steamNativeRequest(action){const r=await fetch('/api/control/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'steam-native-'+action}),cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw Error(d.detail||d.error||String(r.status));return d}
let steamNativeItems=[];
async function steamNativeRefresh(){const d=await steamNativeRequest('status');steamNativeItems=d.games||[];const label=document.getElementById('cc-steam-status'),count=document.getElementById('cc-steam-count');if(label)label.textContent=`${d.status||'Unknown'} · ${d.detail||''}`;if(count)count.textContent=`${steamNativeItems.length} installed Steam games indexed. Steam handles updates and Proton.`;return d}
async function steamNativeAction(action){const label=document.getElementById('cc-steam-status');try{if(action==='start'&&!confirm('Start the optional Steam host? This requires GPU/input devices, may download a container image, and exposes Steam Remote Play and management services on your trusted LAN.'))return;if(label)label.textContent=action==='start'?'Starting Steam runtime…':'Checking Steam…';const d=await steamNativeRequest(action);steamNativeItems=d.games||[];await steamNativeRefresh();showStatus('Steam runtime',`Steam is ${d.status||'ready'}.`,'good',6000)}catch(e){if(label)label.textContent=String(e.message||e);showStatus('Steam runtime unavailable',String(e.message||e),'warn',9000)}}
async function openSteamNativeLibrary(){document.getElementById('steam-library-modal')?.classList.add('show');const list=document.getElementById('steam-native-games');list.innerHTML='<div class="library-empty">Checking Steam library…</div>';try{await steamNativeRefresh();list.innerHTML=steamNativeItems.length?steamNativeItems.map(x=>`<article class="library-item pc-game-card"><div class="library-item-title">${esc(x.title)}</div><div class="library-item-meta">Steam App ${esc(x.appid)} · Installed</div><div class="library-item-meta">Play with Steam Link / Steam Remote Play</div></article>`).join(''):'<div class="library-empty">No installed Steam games indexed. Sign in and install games through the native Steam client first.</div>'}catch(e){list.innerHTML=`<div class="library-empty">${esc(e.message||e)}</div>`}document.querySelector('[data-steam-library-close]')?.focus()}
document.addEventListener('click',e=>{const b=e.target.closest('[data-steam-action]');if(b){e.preventDefault();steamNativeAction(b.dataset.steamAction);return}if(e.target.closest('[data-steam-library]')){e.preventDefault();openSteamNativeLibrary();return}if(e.target.closest('[data-steam-library-close]')){e.preventDefault();document.getElementById('steam-library-modal')?.classList.remove('show');return}if(e.target.closest('[data-steam-setup]')){e.preventDefault();const url='http://'+location.hostname+':8083/';if(confirm('Open the local Steam Headless setup interface? This works only if its management port is reachable on your trusted network.'))window.open(url,'_blank','noopener,noreferrer');return}});
async function fetchStoreLibrary(search='',provider='all',refresh=false){const q=new URLSearchParams({q:search,provider:provider,limit:'300'});if(refresh)q.set('refresh','1');const r=await fetch('/api/control/store/library?'+q.toString(),{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw Error(d.detail||d.error||r.status);return d}
function storeProviderFilter(id,label,count){const active=storeLibraryProvider===id?' active':'';return `<button class="library-filter tv-focus${active}" data-store-provider="${esc(id)}" type="button">${esc(label)}${Number.isFinite(count)?` (${count})`:''}</button>`}
let storeInstallJobs=[];let storeInstallSelected=null;let storeInstallBusy=false;let storeInstallPoll=null;
function storeJobForGame(x){return storeInstallJobs.find(j=>j.provider===x.provider&&String(j.app_id)===String(x.provider_game_id)&&['queued','running','cancelling'].includes(j.state))||storeInstallJobs.find(j=>j.provider===x.provider&&String(j.app_id)===String(x.provider_game_id)&&j.state==='completed')||null}
function storeInstallLabel(x){const j=storeJobForGame(x);if(x.installed)return 'Installed';if(!j)return 'Install';if(j.state==='completed')return 'Downloaded • refresh library';if(j.state==='running')return storeJobHasProgress(j)?`Downloading ${storeJobPercentage(j).toFixed(0)}%`:'Downloading…';if(j.state==='queued')return `Queued${j.queue_position?' #'+j.queue_position:''}`;return 'Cancelling…'}
function storeGameInstallControls(x){const key=esc(x.provider+':'+x.provider_game_id),j=storeJobForGame(x);const label=esc(storeInstallLabel(x));if(x.installed){const active=storeInstallJobs.find(job=>job.provider===x.provider&&String(job.app_id)===String(x.provider_game_id)&&['queued','running','cancelling'].includes(job.state));return active?`<button class="control-button tv-focus" data-store-job-open="${esc(active.id)}" type="button">View ${esc(active.operation||'job')}</button><span class="store-install-state">${esc(storeJobStateText(active.state))}</span>`:`<button class="control-button tv-focus" data-store-maintain="${key}" data-store-maintain-operation="update" type="button">Update</button><button class="control-button tv-focus" data-store-maintain="${key}" data-store-maintain-operation="verify" type="button">Verify files</button><button class="control-button tv-focus" data-store-maintain="${key}" data-store-maintain-operation="uninstall" type="button">Uninstall</button>`;}if(!['epic','gog'].includes(x.provider))return `<span class="store-install-state">Amazon game installation is not available yet.</span>`;if(x.installable===false)return '<span class="store-install-state">This item is not installable.</span>';if(j){const has=storeJobHasProgress(j),pct=has?storeJobPercentage(j):(j.state==='completed'?100:0);return `<button class="control-button tv-focus" data-store-job-open="${esc(j.id)}" type="button">View download</button><span class="store-install-state" data-store-install-state="${key}">${label}</span>${j.state==='running'||j.state==='completed'?`<div class="store-install-progress" role="progressbar" aria-label="${label}"${has?` aria-valuenow="${pct.toFixed(0)}" aria-valuemin="0" aria-valuemax="100"`:''}><span style="width:${pct}%"></span></div>`:''}`}return `<button class="control-button primary tv-focus" data-store-install="${key}" type="button">Install</button><span class="store-install-state" data-store-install-state="${key}">Download and organize in PCGA</span>`}
function storeGameCard(x){const art=x.art_url?`/api/store/art?url=${encodeURIComponent(x.art_url)}`:'';const artwork=artStack(art,fallbackMarkup('pcgame',x),'library-art',x.title||'Store game cover');const state=x.installed?'INSTALLED':'OWNED';const meta=[x.provider_label,x.year,x.developer,(x.genres||[]).slice(0,2).join(' / ')].filter(Boolean).join(' • ');return `<article class="library-item pc-game-card" style="text-align:left;cursor:default">${artwork}<span class="game-play-badge">${esc(state)}</span><span class="library-item-title">${esc(x.title||x.provider_game_id||'Store game')}</span><span class="library-item-meta">${esc(meta||x.provider_label||'PC store')}</span>${x.description?`<span class="library-item-meta">${esc(String(x.description).slice(0,190))}</span>`:''}<span class="library-item-foot"><span>${esc(x.installed?(x.version||'Installed'):'Available in your library')}</span><span>${esc(x.provider_label||'')}</span></span><div class="store-install-controls" data-store-game-controls="${esc(x.provider+':'+x.provider_game_id)}">${storeGameInstallControls(x)}</div></article>`}
function renderStoreLibrary(data,search='',provider='all'){const panel=document.getElementById('pc-game-panel');storeLibraryItems=data?.items||[];storeLibrarySearch=search;storeLibraryProvider=provider;const ps=data?.providers||[],counts=Object.fromEntries(ps.map(x=>[x.provider,Number(x.count||0)]));const problems=ps.filter(x=>!x.available||x.stale);panel.innerHTML=`<div class="library-head"><div><div class="library-title">PC Store Library</div><div class="library-sub">Owned store games • ${Number(data?.total_owned||0)} in this view</div></div><div class="library-head-actions"><button class="control-button tv-focus" data-store-refresh type="button">Refresh catalogs</button><button class="control-button tv-focus" data-store-jobs type="button">Downloads</button><button class="control-button tv-focus" data-store-backends type="button">Store settings</button><button class="library-close tv-focus" data-pc-game-close aria-label="Close">×</button></div></div><div class="library-filters"><button class="library-filter tv-focus" data-store-library-back type="button">← PC Games</button>${storeProviderFilter('all','All stores',provider==='all'?Number(data?.total_owned||0):undefined)}${storeProviderFilter('epic','Epic',counts.epic)}${storeProviderFilter('gog','GOG',counts.gog)}${storeProviderFilter('amazon','Amazon',counts.amazon)}</div><form class="library-search" id="store-library-search-form"><input class="tv-focus" id="store-library-search-input" value="${esc(search)}" placeholder="Search owned games — fuzzy spelling supported" autocomplete="off"><button class="tv-focus" type="submit">Search</button></form><div class="settings-note" style="margin:0 22px 14px"><b>Epic and GOG game management is available.</b> Install owned games, or Update, Verify and Uninstall PCGA-managed installations. Use Downloads &amp; Maintenance for job progress. Amazon remains library/account-only. Completed downloads are reconciled with the PC Games library and Wolf/Moonlight automatically.${problems.length?`<br><br>${problems.map(x=>`<b>${esc(x.provider_label||x.provider)}:</b> ${esc(x.detail&&x.detail!=='null'?x.detail:'Account not connected. Connect it in Store settings.')}`).join('<br>')}`:''}</div><div class="library-grid">${storeLibraryItems.length?storeLibraryItems.map(storeGameCard).join(''):`<div class="library-empty">${search?'No owned games match this search.':'No store catalog is available yet. Open Store settings and prepare the PC-store backends first. Existing Heroic authentication can then be migrated/refreshed; connect an Epic, GOG, or Amazon account from Store settings.'}</div>`}</div>`}
async function openStoreLibrary(search='',provider='all',refresh=false){const box=document.getElementById('pc-game-browser');box.classList.add('show');document.getElementById('pc-game-panel').innerHTML='<div class="library-empty">Loading owned store games…</div>';try{const [d,j]=await Promise.all([fetchStoreLibrary(search,provider,refresh),fetchStoreJobs().catch(()=>({jobs:[]}))]);storeInstallJobs=j.jobs||[];renderStoreLibrary(d,search,provider);startStoreInstallPoll();setTimeout(()=>document.querySelector('#pc-game-browser .tv-focus')?.focus(),0)}catch(e){document.getElementById('pc-game-panel').innerHTML=`<div class="library-head"><div><div class="library-title">PC Store Library</div><div class="library-sub">Epic and GOG installs • Amazon library-only</div></div><button class="library-close tv-focus" data-pc-game-close>×</button></div><div class="library-empty">${esc(e.message||e)}<br><br>Open Store settings to prepare or diagnose the provider backends.</div>`}}
async function pcGameDiscAction(payload){const r=await fetch('/api/control/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),cache:'no-store'}),d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw Error(d.detail||d.error||r.status);return d}
function pcGameDiscFormat(x){const files=(x.copies||[]).flatMap(c=>c.files||[]);return [...new Set(files.map(f=>String(f.format||'').toUpperCase()).filter(Boolean))].join(' + ')||'image'}
function pcGameDiscOwner(x){const owners=x.owners||[];return owners.length?owners.map(o=>o.title||o.id).join(', '):'Unassigned'}
function pcGameDiscCard(x,i){const label=x.volume_label||'Unlabeled optical image';const disc=x.disc_number?`Disc ${x.disc_number}${x.disc_count?` of ${x.disc_count}`:''}`:'Disc number not set';const owner=pcGameDiscOwner(x);const size=Number(x.bytes||0)?fmtBytes(Number(x.bytes||0)):'size unavailable';const state=x.assigned?'ASSIGNED':'UNASSIGNED';return `<article class="library-item pc-game-card" style="text-align:left;cursor:default"><span class="game-play-badge">${esc(state)}</span><span class="library-item-title">${esc(label)}</span><span class="library-item-meta">${esc(disc)} • ${esc(pcGameDiscFormat(x))} • ${esc(size)}</span><span class="library-item-meta">Owner: ${esc(owner)}</span><span class="library-item-meta">Fingerprint: ${esc(String(x.fingerprint||'').slice(0,32))}${String(x.fingerprint||'').length>32?'…':''}</span><span class="library-item-foot"><span>${x.copy_count||0} preserved cop${Number(x.copy_count||0)===1?'y':'ies'}</span><span>${esc(x.metadata_status||'')}</span></span><div class="control-actions"><button class="photo-action tv-focus" data-pc-disc-index="${i}" type="button">Inspect / assign</button></div></article>`}
function renderPcGameDiscBrowser(data,search=''){const panel=document.getElementById('pc-game-panel');pcGameDiscSets=data?.sets||[];pcGameDiscSearch=search;const needle=String(search||'').trim().toLowerCase();pcGameDiscItems=(data?.items||[]).map((x,i)=>({x,i,score:needle?pcgaFuzzyScore(needle,[x.volume_label,x.fingerprint,x.disc_role,pcGameDiscOwner(x),...(x.copies||[]).map(c=>c.path)].join(' ')):0})).filter(r=>!needle||pcgaFuzzyMatch(needle,[r.x.volume_label,r.x.fingerprint,r.x.disc_role,pcGameDiscOwner(r.x),...(r.x.copies||[]).map(c=>c.path)].join(' '))).sort((a,b)=>needle?(b.score-a.score||a.i-b.i):a.i-b.i).map(r=>r.x);const unassigned=pcGameDiscItems.filter(x=>!x.assigned).length;panel.innerHTML=`<div class="library-head"><div><div class="library-title">Preserved PC Game Discs</div><div class="library-sub">${pcGameDiscItems.length} image record${pcGameDiscItems.length===1?'':'s'} shown • ${unassigned} unassigned</div></div><div class="library-head-actions"><button class="control-button tv-focus" data-pc-game-back type="button">← Library</button><button class="library-close tv-focus" data-pc-game-close aria-label="Close">×</button></div></div><form class="library-search" id="pc-game-disc-search-form"><input class="tv-focus" id="pc-game-disc-search-input" value="${esc(search)}" placeholder="Search labels, titles, fingerprints, paths" autocomplete="off"><button class="tv-focus" type="submit">Search</button></form><div class="settings-note" style="margin:0 22px 14px">This is the preservation inventory. Assigning a disc changes title ownership metadata and the travelling PCGA sidecar only; ISO/BIN payloads and checksums are never rewritten.</div><div class="library-grid">${pcGameDiscItems.length?pcGameDiscItems.map(pcGameDiscCard).join(''):`<div class="library-empty">No preserved PC-game optical images match this view.</div>`}</div>`}
async function openPcGameDiscs(search=''){const panel=document.getElementById('pc-game-panel');panel.innerHTML='<div class="library-empty">Reading preserved PC-game disc inventory…</div>';try{const d=await pcGameDiscAction({action:'pc-game-disc-library'});renderPcGameDiscBrowser(d,search)}catch(e){panel.innerHTML=`<div class="library-head"><div><div class="library-title">Preserved PC Game Discs</div><div class="library-sub">Inventory unavailable</div></div><button class="library-close tv-focus" data-pc-game-close>×</button></div><div class="library-empty">${esc(e.message||String(e))}</div>`}}
function pcGameDiscDetails(index){const x=pcGameDiscItems[Number(index)];if(!x)return;pcGameDiscSelectedFingerprint=String(x.fingerprint||'');const panel=document.getElementById('pc-game-panel');const ownerIds=x.game_set_ids||[];const selected=ownerIds[0]||'';const options=['<option value="">Choose a PC game title…</option>',...pcGameDiscSets.map(t=>`<option value="${esc(t.id)}" ${String(t.id)===String(selected)?'selected':''}>${esc(t.title||t.id)}</option>`)].join('');const copies=(x.copies||[]).map(c=>`<div class="settings-note" style="margin:8px 0"><b>${esc(c.path||'Preserved bundle')}</b><br>${esc((c.files||[]).map(f=>`${f.name} (${fmtBytes(Number(f.bytes||0))})`).join(' • ')||'No image payload listed')}</div>`).join('');panel.innerHTML=`<div class="library-head"><div><div class="library-title">${esc(x.volume_label||'Preserved optical image')}</div><div class="library-sub">${esc(pcGameDiscOwner(x))} • ${esc(pcGameDiscFormat(x))}</div></div><button class="library-close tv-focus" data-pc-game-close>×</button></div><div style="padding:22px"><div class="control-actions" style="margin-bottom:16px"><button class="control-button tv-focus" data-pc-disc-back type="button">← Disc images</button></div><div class="settings-note"><b>Fingerprint:</b> ${esc(x.fingerprint||'')}<br><b>Current owner:</b> ${esc(pcGameDiscOwner(x))}<br><b>Disc:</b> ${esc(x.disc_number||'—')} / ${esc(x.disc_count||'—')} • ${esc(x.disc_role||'role unset')}<br><b>Preserved copies:</b> ${Number(x.copy_count||0)}</div>${copies}<h3 style="margin-top:22px">Assign to title</h3><form id="pc-game-disc-assign-form" data-fingerprint="${esc(x.fingerprint||'')}"><div class="settings-row"><div><div class="settings-label">PC game title</div><div class="settings-help">Reassignment removes this disc from its previous title inventory and attaches it to the selected title.</div></div><div class="settings-control"><select id="pc-game-disc-set" class="tv-focus" required>${options}</select></div></div><div class="settings-row"><div class="settings-label">Disc number</div><div class="settings-control"><input id="pc-game-disc-number" class="tv-focus" type="number" min="1" max="99" value="${esc(x.disc_number||'')}"></div></div><div class="settings-row"><div class="settings-label">Disc count</div><div class="settings-control"><input id="pc-game-disc-count" class="tv-focus" type="number" min="1" max="99" value="${esc(x.disc_count||'')}"></div></div><div class="settings-row"><div class="settings-label">Role</div><div class="settings-control"><input id="pc-game-disc-role" class="tv-focus" value="${esc(x.disc_role||'')}" placeholder="installer, data, play…"></div></div><div class="control-actions" style="margin-top:16px"><button class="control-button primary tv-focus" type="submit">Assign preserved disc</button></div></form><h3 style="margin-top:28px">Game database</h3><div class="settings-note" style="margin-bottom:12px">Search RAWG for the canonical game, then let PCGA create/update the title profile and attach this preserved disc. The image payload is not modified.</div><div class="control-actions" style="margin-bottom:18px"><button class="control-button primary tv-focus" data-pc-metadata-for-disc type="button">Search game database</button></div><h3 style="margin-top:28px">Title missing?</h3><form id="pc-game-title-create-form"><div class="settings-row"><div><div class="settings-label">Create a new PC game title</div><div class="settings-help">Creates a confirmed title record. You can then assign this preserved image to it.</div></div><div class="settings-control"><input id="pc-game-new-title" class="tv-focus" maxlength="180" placeholder="Game title" required></div></div><div class="control-actions" style="margin-top:16px"><button class="control-button tv-focus" type="submit">Create title</button></div></form></div>`}
async function submitPcGameDiscAssignment(form){const fp=form?.dataset?.fingerprint||pcGameDiscSelectedFingerprint;const setId=document.getElementById('pc-game-disc-set')?.value||'';if(!fp||!setId)return;const payload={action:'pc-game-disc-assign',fingerprint:fp,game_set_id:setId};const n=document.getElementById('pc-game-disc-number')?.value,c=document.getElementById('pc-game-disc-count')?.value,r=document.getElementById('pc-game-disc-role')?.value;if(n)payload.disc_number=Number(n);if(c)payload.disc_count=Number(c);if(r)payload.disc_role=r;try{const d=await pcGameDiscAction(payload);showStatus('Disc assigned',d.detail||'Preserved disc ownership updated.','good',7000);await openPcGameDiscs(pcGameDiscSearch)}catch(e){showStatus('Disc assignment failed',e.message||String(e),'warn',10000)}}
async function createPcGameTitle(){const title=document.getElementById('pc-game-new-title')?.value?.trim();if(!title)return;try{const d=await pcGameDiscAction({action:'pc-game-title-create',title});showStatus('PC game title created',d.detail||title,'good',6000);const inv=await pcGameDiscAction({action:'pc-game-disc-library'});pcGameDiscSets=inv.sets||[];const idx=(inv.items||[]).findIndex(x=>String(x.fingerprint||'')===pcGameDiscSelectedFingerprint);pcGameDiscItems=inv.items||[];if(idx>=0){pcGameDiscDetails(idx);setTimeout(()=>{const sel=document.getElementById('pc-game-disc-set');if(sel&&d.game_set_id)sel.value=d.game_set_id},0)}else renderPcGameDiscBrowser(inv,pcGameDiscSearch)}catch(e){showStatus('Title creation failed',e.message||String(e),'warn',9000)}}

function pcGameMetadataResultCard(x,i){const selected=i===pcGameMetadataSelected;const art=x.image_url?`<img class="library-art" src="${esc(x.image_url)}" loading="lazy" alt="${esc(x.title||'Game')} artwork">`:fallbackMarkup('pcgame',x);const meta=[x.release_year,(x.platforms||[]).slice(0,3).join(', '),(x.genres||[]).slice(0,3).join(', ')].filter(Boolean).join(' • ');const pct=Math.round(Math.max(0,Math.min(1,Number(x.match_score)||0))*100);const reason=x.match_reason?` • ${x.match_reason}`:'';return `<article class="library-item pc-game-card${selected?' selected':''}" style="text-align:left;cursor:default;${selected?'border-color:var(--accent);box-shadow:0 0 0 2px var(--accent-soft) inset;':''}">${art}<span class="library-item-title">${esc(x.title||'Untitled game')}</span><span class="library-item-meta">${esc(meta||'Video game database result')}</span><span class="library-item-meta">${pct?`Match ${pct}%${esc(reason)}`:esc(x.match_reason||'Web catalog result')}</span>${x.metacritic?`<span class="library-item-meta">Metacritic: ${esc(x.metacritic)}</span>`:''}<div class="control-actions"><button class="photo-action tv-focus" data-pc-metadata-select="${i}" type="button">${selected?'Selected':'Select & preview'}</button><a class="photo-action tv-focus" href="${esc(x.source_url||'https://rawg.io/')}" target="_blank" rel="noopener">RAWG ↗</a></div></article>`}
function pcGameMetadataPreviewMarkup(){if(pcGameMetadataSelected<0)return `<div class="review-block"><h3>Selected web profile</h3><div class="settings-note">Choose a search result to inspect the metadata PCGA will store before changing the local game profile.</div></div>`;const row=pcGameMetadataResults[pcGameMetadataSelected]||{};if(!pcGameMetadataPreview)return `<div class="review-block"><h3>Selected web profile</h3><div class="settings-note">Loading full metadata for <b>${esc(row.title||'selected game')}</b>…</div></div>`;const p=pcGameMetadataPreview;const art=p.cover_url?`<img src="${esc(p.cover_url)}" alt="${esc(p.title||'Game')} cover" style="width:min(240px,32vw);max-height:300px;object-fit:cover;border-radius:12px;border:1px solid var(--line)">`:'';const facts=[p.release_date||p.release_year,p.developer,p.publisher,(p.platforms||[]).slice(0,5).join(', ')].filter(Boolean).join(' • ');const ratings=[p.esrb_rating?`ESRB ${p.esrb_rating}`:'',p.metacritic?`Metacritic ${p.metacritic}`:'',p.database_rating?`RAWG ${Number(p.database_rating).toFixed(1)}/5`: ''].filter(Boolean).join(' • ');const tags=[...(p.genres||[]).slice(0,8),...(p.categories||[]).slice(0,8)].filter((v,i,a)=>a.indexOf(v)===i).map(g=>`<span class="badge">${esc(g)}</span>`).join(' ');return `<div class="review-block"><h3>Selected web profile</h3><div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap">${art}<div style="flex:1;min-width:250px"><h2 style="margin:0 0 6px">${esc(p.title||row.title||'Selected game')}</h2><div class="settings-note">${esc(facts||'No release/developer details supplied by the provider.')}</div>${ratings?`<div class="settings-note" style="margin-top:5px">${esc(ratings)}</div>`:''}<div style="margin:10px 0">${tags}</div><p style="max-height:180px;overflow:auto">${esc(p.description||'No description was returned for this profile.')}</p><div class="control-actions"><button class="control-button primary tv-focus" data-pc-metadata-apply-selected type="button">Use selected metadata</button>${p.website?`<a class="control-button tv-focus" href="${esc(p.website)}" target="_blank" rel="noopener">Official site ↗</a>`:''}${p.source_url?`<a class="control-button tv-focus" href="${esc(p.source_url)}" target="_blank" rel="noopener">RAWG source ↗</a>`:''}</div></div></div></div>`}
function renderPcGameMetadataSearch(query='',message=''){const panel=document.getElementById('pc-game-panel');const target=pcGameMetadataContext.setId?'Update existing title':pcGameMetadataContext.fingerprint?'Create title for preserved disc':'Create PC game profile';const searched=pcGameMetadataSearchTerms.length>1?`<br><span>Also searched: ${pcGameMetadataSearchTerms.slice(1).map(esc).join(' • ')}</span>`:'';panel.innerHTML=`<div class="library-head"><div><div class="library-title">Game Profile Search</div><div class="library-sub">${esc(target)} • ranked web metadata candidates</div></div><button class="library-close tv-focus" data-pc-game-close>×</button></div><div class="control-actions" style="padding:0 22px 14px"><button class="control-button tv-focus" data-pc-metadata-back type="button">← Back</button></div><form class="library-search" id="pc-game-metadata-search-form"><input class="tv-focus" id="pc-game-metadata-query" value="${esc(query)}" placeholder="Game title, disc label, RAWG URL, or RAWG id" autocomplete="off" required><button class="tv-focus" type="submit">Search profiles</button></form><div class="settings-note" style="margin:0 22px 14px">Search keeps your exact query, then also tries cleaned optical/setup labels and broader PC/global matches. Selecting a result only previews it; nothing is written until you choose <b>Use selected metadata</b>. RAWG attribution is retained. <a href="https://rawg.io/" target="_blank" rel="noopener">RAWG ↗</a>${message?`<br><b>${esc(message)}</b>`:''}${searched}</div><div style="padding:0 22px 14px">${pcGameMetadataPreviewMarkup()}</div><div class="library-grid">${pcGameMetadataResults.length?pcGameMetadataResults.map(pcGameMetadataResultCard).join(''):`<div class="library-empty">Search for a title to choose its canonical web metadata profile.</div>`}</div>`}
async function openPcGameMetadataSearch(context={}){pcGameMetadataContext={setId:String(context.setId||''),fingerprint:String(context.fingerprint||''),returnMode:String(context.returnMode||'library')};pcGameMetadataResults=[];pcGameMetadataSelected=-1;pcGameMetadataPreview=null;pcGameMetadataSearchTerms=[];const query=String(context.query||'').trim();renderPcGameMetadataSearch(query);if(query)await pcGameMetadataSearch(query)}
async function pcGameMetadataSearch(query=''){query=String(query||document.getElementById('pc-game-metadata-query')?.value||'').trim();if(!query)return;pcGameMetadataResults=[];pcGameMetadataSelected=-1;pcGameMetadataPreview=null;pcGameMetadataSearchTerms=[];renderPcGameMetadataSearch(query,'Searching exact and broad web profiles…');try{const payload={action:'pc-game-metadata-search',query};if(pcGameMetadataContext.setId)payload.game_set_id=pcGameMetadataContext.setId;if(pcGameMetadataContext.fingerprint)payload.fingerprint=pcGameMetadataContext.fingerprint;const d=await pcGameDiscAction(payload);pcGameMetadataResults=d.results||[];pcGameMetadataSearchTerms=d.search_terms||[];renderPcGameMetadataSearch(query,pcGameMetadataResults.length?`${pcGameMetadataResults.length} ranked candidate${pcGameMetadataResults.length===1?'':'s'} found. Select one to inspect all collected fields.`:'No matches found. Try the product name rather than the disc/setup label, or paste a RAWG game URL.') }catch(e){renderPcGameMetadataSearch(query,e.message||String(e))}}
async function pcGameMetadataSelect(index){index=Number(index);const x=pcGameMetadataResults[index];if(!x)return;pcGameMetadataSelected=index;pcGameMetadataPreview=null;const query=document.getElementById('pc-game-metadata-query')?.value||x.title;renderPcGameMetadataSearch(query,`Selected ${x.title}; loading full web metadata…`);try{const d=await pcGameDiscAction({action:'pc-game-metadata-preview',provider:x.provider||'rawg',provider_id:x.provider_id});if(pcGameMetadataSelected!==index)return;pcGameMetadataPreview=d.profile||null;renderPcGameMetadataSearch(query,`Review the selected profile below, then apply it when it is the correct game.`);setTimeout(()=>document.querySelector('[data-pc-metadata-apply-selected]')?.focus(),0)}catch(e){if(pcGameMetadataSelected!==index)return;renderPcGameMetadataSearch(query,e.message||String(e));showStatus('Metadata preview failed',e.message||String(e),'warn',8000)}}
async function pcGameMetadataApply(index=pcGameMetadataSelected){const x=pcGameMetadataResults[Number(index)];if(!x){showStatus('Choose a game profile','Select and preview a web result before applying metadata.','info',5000);return}const payload={action:'pc-game-metadata-apply',provider:x.provider||'rawg',provider_id:x.provider_id};if(pcGameMetadataContext.setId)payload.game_set_id=pcGameMetadataContext.setId;if(pcGameMetadataContext.fingerprint){payload.fingerprint=pcGameMetadataContext.fingerprint;const disc=pcGameDiscItems.find(d=>String(d.fingerprint||'')===pcGameMetadataContext.fingerprint);if(disc){if(disc.disc_number)payload.disc_number=disc.disc_number;if(disc.disc_count)payload.disc_count=disc.disc_count;if(disc.disc_role)payload.disc_role=disc.disc_role}}renderPcGameMetadataSearch(document.getElementById('pc-game-metadata-query')?.value||x.title,`Applying the selected ${x.title} profile…`);try{const d=await pcGameDiscAction(payload);showStatus('Game profile updated',d.detail||`Applied metadata for ${x.title}.`,'good',7000);if(pcGameMetadataContext.returnMode==='disc'){await openPcGameDiscs(pcGameDiscSearch);return}await openPcGameBrowser(pcGameSearch)}catch(e){renderPcGameMetadataSearch(document.getElementById('pc-game-metadata-query')?.value||x.title,e.message||String(e));showStatus('Metadata update failed',e.message||String(e),'warn',9000)}}
function returnFromPcGameMetadata(){if(pcGameMetadataContext.returnMode==='disc'&&pcGameMetadataContext.fingerprint){const i=pcGameDiscItems.findIndex(x=>String(x.fingerprint||'')===pcGameMetadataContext.fingerprint);if(i>=0){pcGameDiscDetails(i);return}openPcGameDiscs(pcGameDiscSearch);return}if(pcGameMetadataContext.returnMode==='game'&&pcGameMetadataContext.setId){const i=pcGameItems.findIndex(x=>String(x.pcga_set_id||'')===pcGameMetadataContext.setId);if(i>=0){pcGameDetails(i);return}}openPcGameBrowser(pcGameSearch)}
function pcgaPcClientId(){const key='pcga-pc-client-id-v1';let id='';try{id=localStorage.getItem(key)||''}catch(_){ }if(!/^[A-Za-z0-9._:-]{8,128}$/.test(id)){const raw=(globalThis.crypto?.randomUUID?.()||`${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`);id=`portal-${raw}`;try{localStorage.setItem(key,id)}catch(_){ }}return id}
const PCGA_PC_CLIENT_ID=pcgaPcClientId();
let pcGameStreamUrl='',pcGameStreamId='',pcGameStreamSetId='',pcGameStreamReservationId='',pcGameStreamContainerId='',pcGamePairTimer=0;let pcGameSessionsReturnFocus=null,pcGameSessionResumeId='',pcGameActiveSessions=[];let pcGameSessionStopping=new Set(),pcGameSessionStopAll=false,pcGameStreamEnding=false;const pcGameStreams=new Map();let pcGameActiveStreamKey='';
function stopPcGamePairPoll(){if(pcGamePairTimer){clearInterval(pcGamePairTimer);pcGamePairTimer=0}}
function activePcGameStream(){return pcGameStreams.get(pcGameActiveStreamKey)||null}
function renderPcGameStreamDiscControls(){const box=document.getElementById('pc-game-stream-discs'),x=activePcGameStream();if(!box)return;const count=Math.max(0,Number(x?.discCount)||0);if(!x||count<=1){box.classList.remove('show');box.innerHTML='';return}const active=Math.max(1,Number(x.activeDisc)||1),merged=String(x.mediaMode||'')==='merged';const rows=Array.isArray(x.discs)&&x.discs.length?x.discs:Array.from({length:count},(_,i)=>({disc:i+1}));const auto=merged?`<button type="button" class="tv-focus active" title="Automatic synthetic setup media: all ${count} preserved discs are presented through one stable optical D: volume" aria-pressed="true" disabled>AUTO</button>`:'';box.innerHTML=auto+rows.map(row=>{const n=Number(row.disc)||0;if(!n)return'';const title=[merged?'Manual override':`Disc ${n}`,`Disc ${n}`,row.label||'',row.role||''].filter(Boolean).join(' • ');return`<button type="button" class="tv-focus${!merged&&n===active?' active':''}" data-pc-stream-disc="${n}" title="${esc(title)}" aria-pressed="${!merged&&n===active?'true':'false'}">${n}</button>`}).join('');box.classList.add('show')}
async function switchCurrentPcGameDisc(disc){const x=activePcGameStream();disc=Number(disc)||0;if(!x||disc<1||disc>16||disc===Number(x.activeDisc)||!x.setId)return;if(!x.containerId){showStatus('Disc switch is not ready','PCGA is still claiming the Wine runtime container. Try again in a moment.','info',5000);return}const box=document.getElementById('pc-game-stream-discs');for(const b of box?.querySelectorAll('button')||[])b.disabled=true;try{const d=await pcGameSessionAction({action:'pc-game-disc-switch',client_id:PCGA_PC_CLIENT_ID,container_id:x.containerId,game_set_id:x.setId,disc});x.activeDisc=disc;x.mediaMode='manual';renderPcGameStreamDiscControls();showStatus(`Disc ${disc} inserted manually`,d.detail||`The selected Wine session now sees title disc ${disc} as D:.`,'good',5000)}catch(e){showStatus('Disc switch failed',e.message||String(e),'warn',9000);renderPcGameStreamDiscControls()}}
function setPcGameStreamEnding(on){pcGameStreamEnding=!!on;const box=document.getElementById('pc-game-stream'),btn=box?.querySelector('[data-pc-stream-end]'),note=document.getElementById('pc-game-stream-note'),actions=box?[...box.querySelectorAll('.pc-game-stream-actions button')]:[];box?.classList.toggle('is-ending',pcGameStreamEnding);box?.setAttribute('aria-busy',pcGameStreamEnding?'true':'false');for(const b of actions)b.disabled=pcGameStreamEnding;if(btn){btn.classList.toggle('is-ending',pcGameStreamEnding);btn.innerHTML=pcGameStreamEnding?'<span class="pcga-session-spinner" aria-hidden="true"></span>Ending…':'End session'}if(note){if(pcGameStreamEnding){note.dataset.preEndingText=note.textContent||'';note.textContent='Shutdown requested • waiting for this game container to exit…'}else if(note.dataset.preEndingText!==undefined){note.textContent=note.dataset.preEndingText;delete note.dataset.preEndingText}}}
function renderPcGameStreamTabs(){const tabs=document.getElementById('pc-game-stream-tabs');if(!tabs)return;tabs.innerHTML=[...pcGameStreams.entries()].map(([key,x])=>`<button type="button" role="tab" class="pc-game-stream-tab tv-focus${key===pcGameActiveStreamKey?' active':''}" aria-selected="${key===pcGameActiveStreamKey?'true':'false'}" data-pc-stream-tab="${esc(key)}" title="${esc(x.title||'PC Game')}">${esc(x.title||'PC Game')} · lane ${Number(x.lane)||1}</button>`).join('')}
function activatePcGameStream(key,show=true){const x=pcGameStreams.get(String(key||''));if(!x)return false;pcGameActiveStreamKey=String(key);for(const [k,v] of pcGameStreams){v.holder?.classList.toggle('active',k===pcGameActiveStreamKey)}pcGameStreamUrl=x.url||'';pcGameStreamId=x.gameId||'';pcGameStreamSetId=x.setId||'';pcGameStreamReservationId=x.reservationId||'';pcGameStreamContainerId=x.containerId||'';document.getElementById('pc-game-stream-title').textContent=x.title||'PCGA game';document.getElementById('pc-game-stream-note').textContent=x.note||`Secure browser stream • lane ${Number(x.lane)||1}`;renderPcGameStreamTabs();renderPcGameStreamDiscControls();if(show)document.getElementById('pc-game-stream').classList.add('show');return true}
function removePcGameStream(key){key=String(key||'');const x=pcGameStreams.get(key);if(!x)return;if(x.claimTimer)clearInterval(x.claimTimer);try{x.frame.src='about:blank'}catch(_){ }x.holder?.remove?.();pcGameStreams.delete(key);if(pcGameActiveStreamKey===key){const next=pcGameStreams.keys().next().value||'';pcGameActiveStreamKey='';if(next)activatePcGameStream(next,false);else{pcGameStreamUrl='';pcGameStreamId='';pcGameStreamSetId='';pcGameStreamReservationId='';pcGameStreamContainerId='';document.getElementById('pc-game-stream').classList.remove('show')}}renderPcGameStreamTabs()}
function removePcGameStreamByContainer(containerId){containerId=String(containerId||'');for(const [key,x] of pcGameStreams){if(containerId&&String(x.containerId||'')===containerId){removePcGameStream(key);break}}}
function refreshPcGameActiveCardState(){syncPcGameSessionCache().then(()=>{const box=document.getElementById('pc-game-browser'),panel=document.getElementById('pc-game-panel');if(box?.classList.contains('show')&&panel?.querySelector('.library-grid')&&pcGameItems.length)renderPcGameBrowser({items:pcGameItems},pcGameSearch)}).catch(()=>{})}
function closePcGameStream(){stopPcGamePairPoll();setPcGameStreamEnding(false);document.getElementById('pc-game-stream').classList.remove('show');refreshPcGameActiveCardState();(pcGameReturnFocus||document.querySelector('[data-tool="lancommander"]'))?.focus?.()}
function securePortalUrl(port=8443){return `https://${location.hostname}:${Number(port)||8443}${location.pathname}${location.search}${location.hash}`}
function updateSecureContextBanner(){const banner=document.getElementById('secure-context-banner'),link=document.getElementById('secure-portal-link');if(link)link.href=securePortalUrl();if(banner)banner.classList.toggle('show',!window.isSecureContext)}
function requireSecurePcGameContext(d={}){if(window.isSecureContext)return true;const port=Number(d.portal_secure_port)||8443,link=document.getElementById('secure-portal-link'),banner=document.getElementById('secure-context-banner');if(link)link.href=securePortalUrl(port);banner?.classList.add('show');showStatus('Secure streaming required','Download/trust the PCGA Local Appliance CA, then open the secure portal. PCGA will not start the embedded Moonlight client from an insecure parent page.','warn',12000);return false}
async function pcgaH264WebCodecsSupported(){if(!window.isSecureContext||typeof VideoDecoder==='undefined'||typeof VideoDecoder.isConfigSupported!=='function')return false;for(const codec of ['avc1.64002A','avc1.640028','avc1.640020','avc1.42E01F']){try{const r=await VideoDecoder.isConfigSupported({codec,codedWidth:codec==='avc1.64002A'||codec==='avc1.640028'?1920:1280,codedHeight:codec==='avc1.64002A'||codec==='avc1.640028'?1080:720,optimizeForLatency:true});if(r?.supported)return true}catch(_){}}return false}
async function moonlightWebUrl(d){if(!window.isSecureContext)throw Error('PCGA browser streaming requires the secure HTTPS portal.');const u=new URL(`https://${location.hostname}:${Number(d.browser_port)||8101}${d.browser_path||'/'}`);const preferred=['websocket','webrtc','auto'].includes(portalSettings.pcGameTransport)?portalSettings.pcGameTransport:(d.browser_transport||'auto');const webcodecs=await pcgaH264WebCodecsSupported();let transport=preferred==='auto'?(webcodecs?'websocket':'webrtc'):preferred;if(transport==='websocket'&&!webcodecs)transport='webrtc';/* Moonlight Web v3 launch overrides only support bitrate/fps/hdr/videoSize/custom size/dataTransport/language. Renderer and codec preferences are persisted settings, not query overrides. */u.searchParams.set('dataTransport',transport);return{url:u.toString(),transport,webcodecs}}
async function claimPcGameStream(entry){if(!entry?.reservationId)return;let attempts=0;const poll=async()=>{attempts++;try{const d=await pcGameSessionAction({action:'pc-game-session-claim',client_id:PCGA_PC_CLIENT_ID,reservation_id:entry.reservationId});const session=d.session||d.claimed_session||null;if(session?.container_id){entry.containerId=String(session.container_id);if(Number(session.active_disc)>0)entry.activeDisc=Number(session.active_disc);if(pcGameActiveStreamKey===entry.reservationId)pcGameStreamContainerId=entry.containerId;if(entry.claimTimer){clearInterval(entry.claimTimer);entry.claimTimer=0}renderPcGameStreamTabs();renderPcGameStreamDiscControls();return}}catch(_){ }if(attempts>=45&&entry.claimTimer){clearInterval(entry.claimTimer);entry.claimTimer=0}};await poll();if(!entry.containerId&&attempts<45)entry.claimTimer=setInterval(poll,1000)}
async function openPcGameStream(d,id,reservation){if(!requireSecurePcGameContext(d))return;const key=String(reservation?.reservation_id||'');if(!key)throw Error('PCGA did not return a browser-session reservation.');const resolved=await moonlightWebUrl(d);let entry=pcGameStreams.get(key);if(!entry){const holder=document.createElement('div');holder.className='pc-game-stream-frame-wrap';holder.dataset.pcStreamKey=key;const frame=document.createElement('iframe');frame.className='pc-game-stream-frame';frame.title=`PCGA game stream lane ${Number(reservation.lane)||1}`;frame.setAttribute('allow','autoplay; fullscreen; gamepad');frame.setAttribute('allowfullscreen','');holder.appendChild(frame);document.getElementById('pc-game-stream-frames').appendChild(holder);entry={reservationId:key,gameId:String(id||''),setId:String(d.game_set_id||reservation.game_set_id||''),lane:Number(reservation.lane)||Number(d.browser_lane)||1,title:String(d.display_title||d.app_title||'PCGA game')+(d.launch_variant_label?' — '+String(d.launch_variant_label):''),variant:String(d.launch_variant||reservation.launch_variant||''),url:resolved.url,transport:resolved.transport,holder,frame,containerId:'',claimTimer:0,discCount:Math.max(0,Number(d.disc_count)||0),activeDisc:Math.max(1,Number(d.active_disc)||1),discs:Array.isArray(d.discs)?d.discs:[],mediaMode:String(d.setup_media_mode||'manual')};pcGameStreams.set(key,entry)}else{entry.url=resolved.url;entry.transport=resolved.transport;entry.discCount=Math.max(0,Number(d.disc_count)||entry.discCount||0);entry.activeDisc=Math.max(1,Number(d.active_disc)||entry.activeDisc||1);entry.discs=Array.isArray(d.discs)?d.discs:entry.discs;entry.mediaMode=String(d.setup_media_mode||entry.mediaMode||'manual')}entry.note=`Secure browser stream • lane ${entry.lane} • ${resolved.transport}${resolved.transport==='websocket'?' • H.264 WebCodecs':' • native WebRTC renderer'}`;entry.frame.src=entry.url;activatePcGameStream(key,true);setPcGameStreamEnding(false);claimPcGameStream(entry);setTimeout(()=>document.querySelector('#pc-game-stream [data-pc-stream-close]')?.focus(),0)}
async function reconcileMoonlightWeb(){const r=await fetch('/api/control/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'moonlight-reconcile'}),cache:'no-store'}),d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw Error(d.detail||d.stderr||d.error||'PCGA could not establish browser-stream trust');return d}
async function reconcilePcGameStream(id){const r=await fetch('/api/control/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'pc-game-stream-reconcile',game_set_id:id}),cache:'no-store'}),d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw Error(d.detail||d.stderr||d.error||'PCGA could not reconcile the Wolf game profile');return d}
async function pcGameSessionAction(payload){const r=await fetch('/api/control/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),cache:'no-store'}),d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw Error(d.detail||d.error||'PCGA game-session control failed');return d}
function pcGameSessionAge(seconds){const n=Math.max(0,Number(seconds)||0);if(n<60)return`${Math.floor(n)}s`;if(n<3600)return`${Math.floor(n/60)}m`;if(n<86400)return`${Math.floor(n/3600)}h ${Math.floor((n%3600)/60)}m`;return`${Math.floor(n/86400)}d ${Math.floor((n%86400)/3600)}h`}
function renderPcGameSessions(data){const list=document.getElementById('pc-game-sessions-list'),sub=document.getElementById('pc-game-sessions-sub'),all=document.getElementById('pc-game-sessions-end-all'),items=Array.isArray(data?.sessions)?data.sessions:[],pending=Math.max(0,Number(data?.pending_count)||0),totalPending=Math.max(0,Number(data?.total_pending_count)||0);pcGameActiveSessions=items;const endingCount=items.filter(x=>pcGameSessionStopping.has(String(x.container_id||''))).length;sub.textContent=pcGameSessionStopAll?'Shutdown requested for this client’s sessions • waiting for runtime containers to exit…':endingCount?`${endingCount} owned session${endingCount===1?'':'s'} shutting down • please wait…`:items.length||pending?`${items.length} active desktop${items.length===1?'':'s'}${pending?` • ${pending} launch${pending===1?'':'es'} waiting for Wolf`:''} owned by this portal client • ${Number(data?.total_count||items.length)} active / ${totalPending} pending appliance-wide`:`No active sessions owned by this portal client${Number(data?.total_count||0)>0?` • ${Number(data.total_count)} other appliance session${Number(data.total_count)===1?'':'s'} remain`:''}`;all.disabled=(!items.length&&!pending)||pcGameSessionStopAll||endingCount>0;all.classList.toggle('is-ending',pcGameSessionStopAll);all.innerHTML=pcGameSessionStopAll?'<span class="pcga-session-spinner" aria-hidden="true"></span>Ending mine…':'End my sessions';list.innerHTML=items.length?items.map(x=>{const cid=String(x.container_id||''),ending=pcGameSessionStopAll||pcGameSessionStopping.has(cid),lane=Number(x.lane)||0,lanIp=String(x.lan_ip||''),lanPart=lanIp?` • LAN ${lanIp}`:(String(x.network_mode||'')==='legacy-games'?' • LAN address pending':''),discPart=Number(x.active_disc)>0?` • D:=disc ${Number(x.active_disc)}`:'',resumable=!ending&&lane>0&&Boolean(x.reservation_id),meta=ending?'Shutdown requested • waiting for the runtime container to exit…':`${x.name||''} • lane ${lane||'—'}${lanPart}${discPart} • running ${pcGameSessionAge(x.age_seconds)} • ${String(x.container_short_id||'')}`;const resume=resumable?`<button class="pc-game-session-resume tv-focus" data-pc-session-resume="${esc(cid)}" type="button">Resume ${x.kind==='setup'?'setup':'game'}</button>`:'';return `<div class="pc-game-session-row${ending?' is-ending':''}" ${ending?'aria-busy="true"':''}><div><div class="pc-game-session-title">${esc(x.title||'PC Game')} ${x.kind==='setup'?'<span class="badge">Setup</span>':''}</div><div class="pc-game-session-meta" role="status" aria-live="polite">${esc(meta)}</div></div><div class="pc-game-session-actions">${resume}<button class="pc-game-session-danger tv-focus${ending?' is-ending':''}" data-pc-session-stop="${esc(cid)}" data-pc-session-set="${esc(x.game_set_id||'')}" type="button" ${ending?'disabled aria-disabled="true"':''}>${ending?'<span class="pcga-session-spinner" aria-hidden="true"></span>Ending…':'End session'}</button></div></div>`}).join(''):'<div class="pc-game-session-empty">This portal client has no active PC game streams or interactive setup sessions.</div>'}
async function syncPcGameSessionCache(){const d=await pcGameSessionAction({action:'pc-game-session-list',client_id:PCGA_PC_CLIENT_ID});pcGameActiveSessions=Array.isArray(d?.sessions)?d.sessions:[];return d}
async function refreshPcGameSessions(){const d=await syncPcGameSessionCache();renderPcGameSessions(d);return d}
async function reservePcGameSession(id,variant=''){const sid=String(id||'').replace(/^pcga:/,'');if(!sid)throw Error('This PC game does not have a valid PCGA set id.');return pcGameSessionAction({action:'pc-game-session-reserve',client_id:PCGA_PC_CLIENT_ID,game_set_id:sid,launch_variant:String(variant||''),lane_count:4})}
async function releasePcGameSession(reservation){const rid=String(reservation?.reservation_id||reservation||'');if(!rid)return;try{await pcGameSessionAction({action:'pc-game-session-release',client_id:PCGA_PC_CLIENT_ID,reservation_id:rid})}catch(_){ }}
async function openPcGameSessions(resumeId=''){pcGameSessionsReturnFocus=document.activeElement;pcGameSessionResumeId=String(resumeId||'');pcGameSessionStopAll=false;pcGameSessionStopping.clear();const box=document.getElementById('pc-game-sessions-modal');box.classList.add('show');document.getElementById('pc-game-sessions-list').innerHTML='<div class="pc-game-session-empty">Checking sessions owned by this portal client…</div>';try{const d=await refreshPcGameSessions();setTimeout(()=>box.querySelector('.tv-focus:not([disabled])')?.focus(),0);if(!d.count&&pcGameSessionResumeId){const retry=pcGameSessionResumeId;pcGameSessionResumeId='';closePcGameSessions(false);if(Number(d.total_count||0)>0){showStatus('Wolf catalog update is waiting','Another client still owns an active PC game session. PCGA will not restart Wolf underneath that stream; retry after it ends.','warn',12000)}else setTimeout(()=>pcGameStream(retry),250)}}catch(e){document.getElementById('pc-game-sessions-list').innerHTML=`<div class="pc-game-session-empty">${esc(e.message||String(e))}</div>`}}
function closePcGameSessions(restore=true){document.getElementById('pc-game-sessions-modal').classList.remove('show');pcGameSessionResumeId='';if(restore)(pcGameSessionsReturnFocus||document.querySelector('[data-tool="lancommander"]'))?.focus?.()}
async function resumePcGameSession(containerId){if(!requireSecurePcGameContext())return;containerId=String(containerId||'');if(!containerId)return;try{let session=pcGameOwnedSessionForContainer(containerId);if(!session){await syncPcGameSessionCache();session=pcGameOwnedSessionForContainer(containerId)}if(!session)throw Error('This session is no longer running or is no longer owned by this portal client.');const existing=[...pcGameStreams.values()].find(x=>String(x.containerId||'')===containerId||String(x.reservationId||'')===String(session.reservation_id||''));closePcGameSessions(false);if(existing){activatePcGameStream(existing.reservationId,true);showStatus('Session resumed',`Returned to the existing ${session.kind==='setup'?'installer':'game'} desktop on lane ${Number(session.lane)||1}.`,'good',6000);return}const sid=String(session.game_set_id||'');const lane=Math.max(1,Number(session.lane)||1);const variant=String(session.launch_variant||'');if(!sid||!session.reservation_id)throw Error('PCGA retained the runtime container but its browser-stream ownership record is incomplete. End the session and relaunch it once.');const resumeQuery='?lane='+encodeURIComponent(lane)+(variant?'&variant='+encodeURIComponent(variant):'');let r=await fetch('/api/pc-games/game/'+encodeURIComponent('pcga:'+sid)+'/stream'+resumeQuery,{cache:'no-store'}),d=await r.json().catch(()=>({}));if(d.needs_pairing){showStatus('Restoring browser lane',`Re-establishing secure stream lane ${lane} without ending the Wine desktop.`,'info',9000);await reconcileMoonlightWeb();r=await fetch('/api/pc-games/game/'+encodeURIComponent('pcga:'+sid)+'/stream'+resumeQuery,{cache:'no-store'});d=await r.json().catch(()=>({}))}if(!r.ok||!d.browser_ready)throw Error(d.detail||d.browser_detail||`Stream lane ${lane} cannot currently reconnect to the active desktop.`);await openPcGameStream(d,'pcga:'+sid,{reservation_id:String(session.reservation_id),lane,game_set_id:sid});const entry=pcGameStreams.get(String(session.reservation_id));if(entry){entry.containerId=containerId;entry.activeDisc=Math.max(1,Number(session.active_disc)||entry.activeDisc||1);entry.note=`Resumed existing ${session.kind==='setup'?'setup':'game'} session • lane ${lane} • container ${String(session.container_short_id||containerId.slice(0,12))}`;activatePcGameStream(entry.reservationId,true)}showStatus('Session resumed',`Reconnected to the existing ${session.kind==='setup'?'installer':'game'} desktop. The Wine container was not restarted.`,'good',7000)}catch(e){showStatus('Could not resume session',e.message||String(e),'warn',12000)}}
async function stopPcGameSession(containerId,setId=''){containerId=String(containerId||'');if(!containerId||pcGameSessionStopping.has(containerId)||pcGameSessionStopAll)return;if(!confirm('End this PC game session? The running game or installer will be terminated. Saved data already written to the game prefix is preserved.'))return;pcGameSessionStopping.add(containerId);renderPcGameSessions({sessions:pcGameActiveSessions,total_count:pcGameActiveSessions.length});showStatus('Ending PC game session','Shutdown was accepted. Waiting for this client’s game/runtime container to exit cleanly…','info',12000);try{const d=await pcGameSessionAction({action:'pc-game-session-stop',client_id:PCGA_PC_CLIENT_ID,container_id:containerId});removePcGameStreamByContainer(containerId);const left=await refreshPcGameSessions();pcGameSessionStopping.delete(containerId);renderPcGameSessions(left);showStatus('PC game session ended',d.detail||'The selected session was terminated.','good',6000);if(!left.count&&pcGameSessionResumeId&&Number(left.total_count||0)===0){const retry=pcGameSessionResumeId;pcGameSessionResumeId='';closePcGameSessions(false);showStatus('Preparing game stream','The blocking session is gone. PCGA is applying the deferred Wolf update and retrying the requested game.','info',7000);setTimeout(()=>pcGameStream(retry),350)}}catch(e){pcGameSessionStopping.delete(containerId);renderPcGameSessions({sessions:pcGameActiveSessions});showStatus('Could not end game session',e.message||String(e),'warn',9000)}}
async function stopAllPcGameSessions(){if(pcGameSessionStopAll)return;if(!confirm('End every PCGA game/setup session owned by this portal client? Other clients are not affected.'))return;pcGameSessionStopAll=true;for(const x of pcGameActiveSessions)pcGameSessionStopping.add(String(x.container_id||''));renderPcGameSessions({sessions:pcGameActiveSessions});showStatus('Ending this client’s PC game sessions','Shutdown was accepted. Waiting for the owned runtime containers to exit cleanly…','info',12000);try{const d=await pcGameSessionAction({action:'pc-game-session-stop',client_id:PCGA_PC_CLIENT_ID,all:true});for(const x of [...pcGameStreams.values()])removePcGameStream(x.reservationId);const left=await refreshPcGameSessions();pcGameSessionStopAll=false;pcGameSessionStopping.clear();renderPcGameSessions(left);showStatus('Client sessions ended',d.detail||'This client’s active PCGA game sessions were terminated.','good',6500);if(pcGameSessionResumeId&&Number(left.total_count||0)===0){const retry=pcGameSessionResumeId;pcGameSessionResumeId='';closePcGameSessions(false);setTimeout(()=>pcGameStream(retry),350)}}catch(e){pcGameSessionStopAll=false;pcGameSessionStopping.clear();renderPcGameSessions({sessions:pcGameActiveSessions});showStatus('Could not end game sessions',e.message||String(e),'warn',9000)}}
async function endCurrentPcGameSession(){const entry=activePcGameStream();if(pcGameStreamEnding)return;if(!entry){closePcGameStream();return}if(!confirm('End this game session? This terminates only the selected Wine/game desktop; your other sessions stay running.'))return;setPcGameStreamEnding(true);showStatus('Ending PC game session','Shutdown was accepted. Waiting for the selected game/runtime container to exit cleanly…','info',12000);try{const payload={action:'pc-game-session-stop',client_id:PCGA_PC_CLIENT_ID,reservation_id:entry.reservationId};if(entry.containerId)payload.container_id=entry.containerId;const d=await pcGameSessionAction(payload);const key=entry.reservationId;removePcGameStream(key);setPcGameStreamEnding(false);if(pcGameStreams.size){const next=pcGameStreams.keys().next().value;activatePcGameStream(next,true)}else closePcGameStream();showStatus('PC game session ended',d.detail||'The selected game session was terminated.','good',6500)}catch(e){setPcGameStreamEnding(false);showStatus('Could not end game session',e.message||String(e),'warn',9000)}}
function pcGamePendingMessage(d){const detail=String(d?.detail||d?.browser_detail||'');if(detail.includes('managed runtime container active:'))return detail+' You can end the previous game/setup session from the portal and retry immediately.';return detail||'PCGA is still applying this game to the Wolf app catalog.'}
function recordGameActivity(payload){fetch('/api/control/game-activity',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload||{})}).catch(()=>{})}
async function pcGameStream(id,variant=''){
if(!requireSecurePcGameContext())return;
variant=String(variant||'').trim();let reservation=null;
const streamUrl=(lane=0)=>'/api/pc-games/game/'+encodeURIComponent(id)+'/stream?'+new URLSearchParams({...((lane>0)?{lane:String(lane)}:{}),...(variant?{variant}:{})}).toString();
try{
 const requestedSid=String(id||'').replace(/^pcga:/,'');
 try{await syncPcGameSessionCache();const active=pcGameOwnedSessionForSet(requestedSid);if(active){showStatus('Resuming active session',`This portal client already owns a ${active.kind==='setup'?'setup':'game'} desktop for this title. Reconnecting instead of launching a duplicate.`,'info',7000);await resumePcGameSession(active.container_id);return}}catch(_){}
 let r=await fetch(streamUrl(),{cache:'no-store'}),d=await r.json().catch(()=>({}));
 if(d.needs_pairing){showStatus('Preparing browser stream pool','PCGA is establishing the appliance browser clients with Wolf. No PIN entry is required.','info',12000);await reconcileMoonlightWeb();r=await fetch(streamUrl(),{cache:'no-store'});d=await r.json().catch(()=>({}))}
 if(!d.browser_ready&&(d.stream_state==='pending-restart'||d.stream_state==='failed')&&(d.launchable||d.setup_launchable)){showStatus('Preparing game stream','PCGA is reconciling the Wolf app catalog and retrying this title. Existing live desktops will not be interrupted.','info',12000);await reconcilePcGameStream(d.game_set_id||id);for(let i=0;i<12;i++){await new Promise(resolve=>setTimeout(resolve,1000));r=await fetch(streamUrl(),{cache:'no-store'});d=await r.json().catch(()=>({}));if(d.browser_ready)break;if(String(d.detail||'').includes('managed runtime container active:'))break}}
 if(d.browser_available&&d.browser_ready){reservation=await reservePcGameSession(d.game_set_id||id,variant||d.launch_variant||'');const lane=Number(reservation.lane)||1;r=await fetch(streamUrl(lane),{cache:'no-store'});d=await r.json().catch(()=>({}));if(d.needs_pairing){showStatus('Preparing browser lane',`PCGA is pairing stream lane ${lane} with Wolf.`,'info',12000);await reconcileMoonlightWeb();r=await fetch(streamUrl(lane),{cache:'no-store'});d=await r.json().catch(()=>({}))}if(!r.ok||!d.browser_ready)throw Error(d.detail||d.browser_detail||`Browser stream lane ${lane} is not ready.`);const current=pcGameItems.find(x=>String(x.stream_id||x.id||'')===String(id))||{};recordGameActivity({kind:'pc-game',id:String(current.id||id),title:current.title||document.querySelector('#pc-game-panel .library-title')?.textContent||'PC Game',subtitle:[d.launch_variant_label,current.developer,current.year].filter(Boolean).join(' • ')||'PC Game',art_url:current.cover_url||'',stream_id:String(id)});await openPcGameStream(d,id,reservation);reservation=null;showStatus('PC game session started',`${d.launch_variant_label?d.launch_variant_label+' • ':''}This client now owns stream lane ${lane}. Back only hides the stream; the Wine desktop stays alive.`,'good',7500);return}
 if(!r.ok&&d.stream_state!=='pending-restart')throw Error(d.detail||d.stream_state||r.status);if(d.stream_state==='pending-restart'){const msg=pcGamePendingMessage(d);if(String(d.detail||'').includes('managed runtime container active:')){showStatus('Wolf catalog change is waiting',msg,'warn',12000);await openPcGameSessions(id);return}throw Error(msg)}if(d.setup_required&&!d.app_title)throw Error(d.detail||'This installer still needs an interactive setup runtime.');if(d.browser_available)throw Error(d.browser_detail||'The browser streaming app is not ready yet.');const app=d.app_title||'PCGA game';throw Error((d.browser_detail||'PCGA browser streaming is unavailable')+`. Native Moonlight fallback: choose “${app}”.`)
}catch(e){if(reservation)await releasePcGameSession(reservation);showStatus('PC game streaming is not ready',e.message||String(e),'warn',12000)}}
async function pcGameRetry(id){try{const r=await fetch('/api/pc-games/game/'+encodeURIComponent(id)+'/retry',{method:'POST'}),d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);showStatus('PC game reconciliation started',d.detail||'PCGA is re-reading the preserved source, refreshing metadata, and retrying installation.','good',7000);setTimeout(()=>openPcGameBrowser(pcGameSearch),1800)}catch(e){showStatus('PC game retry failed',e.message||String(e),'warn',9000)}}
async function pcGameReinstall(id){if(!confirm('Reinstall this game from its preserved PCGA source? The archived disc/image will be kept, but the mutable Wine install/runtime will be rebuilt.'))return;try{const r=await fetch('/api/pc-games/game/'+encodeURIComponent(id)+'/reinstall',{method:'POST'}),d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);showStatus('PC game reinstall started',d.detail||'PCGA is rebuilding the game from preserved media.','good',9000);setTimeout(()=>openPcGameBrowser(pcGameSearch),2200)}catch(e){showStatus('PC game reinstall failed',e.message||String(e),'warn',10000)}}
function pcGameCompatibilityMarkup(c){c=c&&typeof c==='object'?c:{};const p=c.profile&&typeof c.profile==='object'?c.profile:{},m=c.matches&&typeof c.matches==='object'?c.matches:{},pdb=m.protondb&&typeof m.protondb==='object'?m.protondb:{},pol=m.playonlinux&&typeof m.playonlinux==='object'?m.playonlinux:{},known=m.pcga_known_good&&typeof m.pcga_known_good==='object'?m.pcga_known_good:{},sum=pdb.summary&&typeof pdb.summary==='object'?pdb.summary:{};const effectiveTier=(sum.tier&&sum.tier!=='pending'?sum.tier:sum.provisionalTier)||'';const protonBits=[];if(effectiveTier)protonBits.push(String(effectiveTier));if(sum.confidence)protonBits.push(String(sum.confidence)+' confidence');if(sum.total!==undefined&&sum.total!==null)protonBits.push(String(sum.total)+' reports');const polBits=[];if(pol.title)polBits.push(String(pol.title));if(pol.match_score!==undefined&&pol.match_score!==null)polBits.push(Math.round(Number(pol.match_score)*100)+'% title match');if(pol.approved===true)polBits.push('approved script');else if(pol.approved===false&&pol.title)polBits.push('not approved');if(Array.isArray(pol.wine_versions)&&pol.wine_versions.length)polBits.push('Wine '+pol.wine_versions[0]);const knownBits=[];if(known.title)knownBits.push(String(known.title));if(known.rule)knownBits.push(String(known.rule));if(known.match_basis)knownBits.push(String(known.match_basis));const applied=[];if(p.wine_arch)applied.push(String(p.wine_arch));if(p.windows_version)applied.push(String(p.windows_version));if(Array.isArray(p.winetricks_components)&&p.winetricks_components.length)applied.push('Winetricks: '+p.winetricks_components.join(', '));if(Array.isArray(p.preferred_executables)&&p.preferred_executables.length)applied.push('Executables: '+p.preferred_executables.join(', '));if(p.runtime_environment&&typeof p.runtime_environment==='object'&&Object.keys(p.runtime_environment).length)applied.push('Environment: '+Object.entries(p.runtime_environment).map(([k,v])=>k+'='+v).join(', '));if(Array.isArray(p.launch_arguments)&&p.launch_arguments.length)applied.push('Launch: '+p.launch_arguments.join(' '));if(!applied.length)applied.push('No runtime changes automatically applied');const runner=[];if(Array.isArray(p.recommended_runner_versions)&&p.recommended_runner_versions.length)runner.push('Observed/recommended runners: '+p.recommended_runner_versions.slice(0,5).join(', '));if(Array.isArray(p.recommended_environment)&&p.recommended_environment.length)runner.push('Reported environment hints: '+p.recommended_environment.slice(0,5).join(', '));const warnings=Array.isArray(c.warnings)?c.warnings:[];const conf=c.confidence!==undefined&&c.confidence!==null?` • ${Math.round(Number(c.confidence)*100)}% match confidence`:'';return `<section class="settings-card wide" style="margin-top:18px"><h2>Compatibility</h2><div class="settings-note"><b>Resolver:</b> ${esc(c.status||'not checked')}${conf}<br><b>ProtonDB:</b> ${esc(protonBits.join(' • ')||pdb.summary_status||'no Steam AppID/report match')}<br><b>PlayOnLinux:</b> ${esc(polBits.join(' • ')||pol.status||'no confident match')}${knownBits.length?`<br><b>PCGA known-good:</b> ${esc(knownBits.join(' • '))}`:''}<br><b>PCGA applies:</b> ${esc(applied.join(' • '))}${runner.length?`<br><b>Advisory:</b> ${esc(runner.join(' • '))}`:''}${warnings.length?`<br><b>Notes:</b> ${esc(warnings.join(' '))}`:''}</div></section>`}
async function pcGameCompatRefresh(id){if(!id||!String(id).startsWith('pcga:'))return;showStatus('Refreshing compatibility','Checking ProtonDB and PlayOnLinux for a current high-confidence profile…','info',5000);try{const r=await fetch('/api/pc-games/game/'+encodeURIComponent(id)+'/compatibility/refresh',{method:'POST'}),d=await r.json().catch(()=>({}));if(!r.ok||!d.ok)throw Error(d.detail||d.error||r.status);showStatus('Compatibility refreshed',d.detail||'Compatibility evidence updated.','ok',5000);const idx=pcGameItems.findIndex(x=>x.id===id||x.stream_id===id);if(idx>=0)setTimeout(()=>pcGameDetails(idx),300)}catch(e){showStatus('Compatibility refresh failed',e.message||String(e),'warn',9000)}}
async function pcGameDetails(index){const x=pcGameItems[Number(index)];if(!x)return;const panel=document.getElementById('pc-game-panel');try{await syncPcGameSessionCache()}catch(_){}panel.innerHTML='<div class="library-empty">Loading game profile…</div>';try{const r=await fetch('/api/pc-games/game/'+encodeURIComponent(x.id),{cache:'no-store'}),d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||r.status);const hero=d.hero_url?`style="background-image:linear-gradient(to bottom,rgba(8,12,18,.15),rgba(8,12,18,.95)),url('${esc(d.hero_url)}');background-size:cover;background-position:center"`:'';const cover=artStack(d.cover_url,fallbackMarkup('pcgame',d),'library-art pc-game-detail-cover',d.title||x.title||'PC game cover');const genres=(d.genres||[]).map(g=>`<span class="badge">${esc(g)}</span>`).join(' ');const shots=(d.screenshots||[]).slice(0,4).map(u=>`<img src="${esc(u)}" loading="lazy" alt="Screenshot" style="width:min(360px,80vw);border-radius:12px">`).join('');const streamId=d.stream_id||x.stream_id||'';const variants=Array.isArray(d.launch_variants)?d.launch_variants.filter(v=>v&&v.key):[];const variantActions=variants.length>1?variants.map(v=>`<button class="control-button${v.default?' primary':''} tv-focus" data-pc-stream="${esc(streamId)}" data-pc-stream-variant="${esc(v.key)}" type="button">Play ${esc(v.label||v.key)}</button>`).join(''):'';const active=pcGameOwnedSessionForSet(d.pcga_set_id||streamId);const action=active?`<button class="control-button primary tv-focus" data-pc-session-resume="${esc(active.container_id||'')}" type="button">${active.kind==='setup'?'Resume setup':'Resume game'}</button>`:d.playable?(variantActions||`<button class="control-button primary tv-focus" data-pc-stream="${esc(streamId)}" type="button">Play in portal</button>`):(d.install_status==='ready'&&d.stream_state==='pending-restart')?`<button class="control-button primary tv-focus" data-pc-stream="${esc(streamId)}" type="button">Prepare stream</button>`:d.launchable?`<button class="control-button primary tv-focus" data-pc-stream="${esc(streamId)}" type="button">Retry stream</button>`:(d.setup_required&&d.stream_state==='setup-ready')?`<button class="control-button primary tv-focus" data-pc-stream="${esc(streamId)}" type="button">Install in portal</button>`:d.setup_launchable?`<button class="control-button primary tv-focus" data-pc-stream="${esc(streamId)}" type="button">Retry installer</button>`:'';const retry=d.pcga_set_id&&!d.heroic&&!d.playable&&!active?`<button class="control-button tv-focus" data-pc-retry="${esc(d.stream_id||('pcga:'+d.pcga_set_id))}" type="button">Retry detect/install</button>`:'';const reinstall=d.pcga_set_id&&!d.heroic&&!active?`<button class="control-button tv-focus" data-pc-reinstall="${esc(d.stream_id||('pcga:'+d.pcga_set_id))}" type="button">Reinstall from preserved media</button>`:'';const compatRefresh=d.pcga_set_id&&!d.heroic?`<button class="control-button tv-focus" data-pc-compat-refresh="${esc(d.stream_id||('pcga:'+d.pcga_set_id))}" type="button">Refresh compatibility</button>`:'';const metadataSearch=d.pcga_set_id&&!d.heroic?`<button class="control-button tv-focus" data-pc-metadata-for-game="${esc(d.pcga_set_id)}" data-pc-metadata-query="${esc(d.title||x.title||'')}" type="button">Find metadata</button>`:'';const source=d.metadata_profile||{};const sourceLink=source.source_url?`<br><b>Database source:</b> <a href="${esc(source.source_url)}" target="_blank" rel="noopener">${esc(source.attribution||source.provider||'Metadata')} ↗</a>`:'';const ratings=[d.esrb_rating?`ESRB ${d.esrb_rating}`:'',d.metacritic?`Metacritic ${d.metacritic}`:''].filter(Boolean).join(' • ');const compatMarkup=pcGameCompatibilityMarkup(d.compatibility||{});panel.innerHTML=`<div class="library-head"><div><div class="library-title">${esc(d.title||x.title)}</div><div class="library-sub">${esc([d.release_date||d.year,d.developer,d.publisher].filter(Boolean).join(' • ')||'PC Game')}</div></div><button class="library-close tv-focus" data-pc-game-close>×</button></div><div ${hero} style="padding:22px;${hero?'min-height:280px;':''}"><div style="display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap">${cover}<div style="flex:1;min-width:260px"><div class="control-actions" style="margin-bottom:14px"><button class="control-button tv-focus" data-pc-game-back type="button">← Library</button><button class="control-button tv-focus" data-pc-sessions type="button">Sessions</button>${action}${metadataSearch}${retry}${reinstall}${compatRefresh}</div><div style="margin-bottom:12px">${genres}</div><p>${esc(d.description||d.marketing_description||'No description has been collected yet.')}</p><div class="settings-note"><b>Install:</b> ${esc(d.install_status||'metadata')} ${d.install_detail?'• '+esc(d.install_detail):''}<br><b>Streaming:</b> ${esc(d.stream_state||'not registered')} ${d.stream_app_title?'• '+esc(d.stream_app_title):''}${d.identity_source?`<br><b>Identity:</b> ${esc(d.identity_source)}${d.identity_confidence?` • ${Math.round(Number(d.identity_confidence)*100)}%`:''}`:''}${d.metadata_provider?`<br><b>Metadata:</b> ${esc(d.metadata_provider)}`:''}${sourceLink}${ratings?`<br><b>Ratings:</b> ${esc(ratings)}`:''}${variants.length>1?`<br><b>Launch modes:</b> ${esc(variants.map(v=>v.label||v.key).join(' • '))}`:''}${Number(x.record_count)>1?`<br><b>Catalog:</b> ${Number(x.record_count)} duplicate/source records consolidated`:''}</div>${compatMarkup}</div></div>${shots?`<div style="display:flex;gap:12px;overflow:auto;margin-top:22px">${shots}</div>`:''}</div>`}catch(e){showStatus('Game profile unavailable',e.message||String(e),'warn',9000);openPcGameBrowser(pcGameSearch)}}
async function reviewRequest(path,payload=null){const opt={cache:'no-store'};if(payload!==null){opt.method='POST';opt.headers={'Content-Type':'application/json'};opt.body=JSON.stringify(payload)}const r=await fetch('/api/review/'+path,opt);const d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw Error(d.detail||d.error||`HTTP ${r.status}`);return d}
function reviewDefaultKind(x){const k=String(x?.media_kind||'').toLowerCase();if(k==='tv')return'tv';if(k==='movie'||k==='video')return'movie';if(k==='music'||k==='audio')return'music';if(k==='home-video')return'home';return'home'}
function reviewRoleOptions(selected,labels){labels=labels||{'main-feature':'Main feature','extras':'Extra','featurettes':'Featurette','deleted scenes':'Deleted scene','trailers':'Trailer / preview','behind the scenes':'Behind the scenes','interviews':'Interview','shorts':'Short','archive-only':'Archive only'};return Object.entries(labels).map(([v,l])=>`<option value="${esc(v)}" ${String(selected||'')===String(v)?'selected':''}>${esc(l)}</option>`).join('')}
function reviewOpticalTitlesHtml(x){const rows=x?.optical_titles||[];if(!rows.length)return'';const labels=x.optical_role_labels||{};return `<div class="review-block"><h3>Disc titles</h3><div class="settings-note">Assign each MakeMKV title before routing. Exactly one title should be the main feature; every other title is preserved as a Jellyfin-compatible extra or archive-only item.</div><div class="review-optical-list">${rows.map(r=>`<div class="review-episode-row"><span><strong>${esc(r.name||r.file||'Disc title')}</strong><small>${r.title_index!==null&&r.title_index!==undefined?'Title '+esc(r.title_index)+' • ':''}${r.duration_seconds?fmt(Number(r.duration_seconds)):''}${r.size_bytes?' • '+fmtBytes(Number(r.size_bytes)):''}</small></span><select class="tv-focus" data-review-optical-role="${esc(r.key)}">${reviewRoleOptions(r.role,labels)}</select></div>`).join('')}</div></div>`}
function reviewLibraryQueueButton(x){const selected=x.id===reviewLibrarySelectedId?' selected':'';return `<button class="review-queue-item tv-focus${selected}" data-review-library-item="${esc(x.id)}" type="button"><span class="review-queue-title">${esc(x.title||'Untitled')}</span><span class="review-queue-meta">Existing optical movie • ${Number(x.title_count||0)} disc title${Number(x.title_count||0)===1?'':'s'}</span></button>`}
function renderReviewLibraryDetail(x){if(!x)return'<div class="review-empty">No promoted optical movies were found.</div>';const labels=x.role_labels||{};return `<h2>${esc(x.title||'Untitled')}${x.year?' ('+esc(x.year)+')':''}</h2><div class="review-path">${esc(x.path||'')}</div><div class="settings-note">Reclassify titles from a disc that is already in the movie library. Files are moved only within this movie folder; nothing is deleted.</div><div class="review-block"><h3>Disc titles</h3><div class="review-optical-list">${(x.titles||[]).map(r=>`<div class="review-episode-row"><span><strong>${esc(r.file||'Disc title')}</strong><small>${r.title_index!==null&&r.title_index!==undefined?'Title '+esc(r.title_index)+' • ':''}${r.duration_seconds?fmt(Number(r.duration_seconds)):''}${r.size_bytes?' • '+fmtBytes(Number(r.size_bytes)):''}${r.recovered?' • recovered from existing rip':''}<br>${esc(r.path||'')}</small></span><select class="tv-focus" data-review-library-role="${esc(r.key)}">${reviewRoleOptions(r.role,labels)}</select></div>`).join('')}</div><div class="review-actions"><button class="review-action primary tv-focus" data-review-library-save type="button">Save title roles</button></div></div>`}
function reviewQueueButton(x){const selected=x.id===reviewSelectedId?' selected':'';const conf=Number.isFinite(Number(x.confidence))?` • ${Math.round(Number(x.confidence)*100)}%`:'';return `<button class="review-queue-item tv-focus${selected}" data-review-item="${esc(x.id)}" type="button"><span class="review-queue-title">${esc(x.title||'Untitled')}</span><span class="review-queue-meta">${esc(x.source||'queue')} • ${esc(x.media_kind||'unknown')}${conf} • ${esc(x.size_human||'')}</span></button>`}
function reviewEpisodePlan(x){const p=x?.episode_plan||{},rows=p.rows||[];if(!rows.length)return'';const note=p.mode==='sequential'?'Unnumbered tracks will be assigned sequentially from the season/episode fields below.':p.mode==='mixed'?'Mixed numbered and unnumbered tracks require review before routing.':'Episode numbers were detected in filenames.';return `<div class="review-block"><h3>Episode assignment</h3><div class="settings-note">${esc(note)}</div><div id="review-episode-plan">${rows.map((r,i)=>`<div class="review-episode-row"><span>${esc(r.file||'track')}</span><strong class="review-episode-target" data-review-offset="${Number(r.offset||0)}">${esc(r.target||'Sequential')}</strong></div>`).join('')}</div></div>`}
function reviewMetadataHtml(){if(!reviewMetadataResults.length)return'';return `<div class="review-metadata-results">${reviewMetadataResults.map((r,i)=>`<div class="review-metadata-result"><div><strong>${esc(r.title||'Untitled')}${r.year?' ('+esc(r.year)+')':''}</strong><span>${esc(String(r.kind||'').toUpperCase())} • ${esc(r.source||reviewMetadataSource||'metadata')}${r.provider_id?' • '+esc(r.provider)+':'+esc(r.provider_id):''}</span></div><button class="review-action tv-focus" data-review-use-meta="${i}" type="button">Use metadata</button></div>`).join('')}</div>`}
function reviewPreviewHtml(x){const p=x?.preview||{};if(!p.available)return`<div class="review-block"><h3>Preview</h3><div class="settings-note">No directly previewable audio, video, or image was detected in this review item. Use the file list and classifier evidence below.</div></div>`;const base=`/api/review/preview?item=${encodeURIComponent(x.id)}`;const meta=[p.name,p.size_human,p.duration_seconds?fmt(Number(p.duration_seconds)):null].filter(Boolean).join(' • ');let media='';if(p.kind==='video')media=`<video controls preload="none" poster="${base}&mode=poster" src="${base}&mode=clip"></video>`;else if(p.kind==='audio')media=`<audio controls preload="none" src="${base}&mode=clip"></audio>`;else media=`<img loading="lazy" src="${base}&mode=poster" alt="Review preview">`;return`<div class="review-block"><h3>Preview</h3><div class="review-preview"><div class="review-preview-media">${media}</div><div class="review-preview-meta"><strong>${esc(p.kind==='video'?'Representative video':p.kind==='audio'?'Representative audio':'Image preview')}</strong><div>${esc(meta)}</div>${p.clip_seconds?`<p>Preview playback is a temporary ${esc(p.clip_seconds)} second browser-compatible clip generated from the preserved source. It does not alter the archive.</p>`:''}</div></div></div>`}
function syncReviewFields(){const kind=document.getElementById('review-kind')?.value||'home';for(const el of document.querySelectorAll('[data-review-for]')){const kinds=String(el.dataset.reviewFor||'').split(',');el.style.display=kinds.includes(kind)?'flex':'none'}const item=reviewItems.find(x=>x.id===reviewSelectedId);if(item?.episode_plan?.mode==='sequential'){let season=parseInt(document.getElementById('review-season')?.value||'1',10),episode=parseInt(document.getElementById('review-episode')?.value||'1',10);if(!Number.isFinite(season))season=1;if(!Number.isFinite(episode))episode=1;for(const node of document.querySelectorAll('.review-episode-target')){const off=parseInt(node.dataset.reviewOffset||'0',10)||0;node.textContent=`S${String(season).padStart(2,'0')}E${String(episode+off).padStart(2,'0')}`}}}
function renderReviewDetail(x){if(!x)return'<div class="review-empty">Select an item from the review queue.</div>';const kind=reviewDefaultKind(x),files=(x.files||[]).map(n=>`<li>${esc(n)}</li>`).join('')+(x.files_truncated?`<li>… ${x.files_truncated} more</li>`:'');const evidence=(x.evidence||[]).map(v=>`<li>${esc(v)}</li>`).join('');return `<h2>${esc(x.title||'Untitled')}</h2><div class="review-path">${esc(x.path||'')}</div><div class="settings-note">${esc(x.source||'queue')} • ${esc(x.media_kind||'unknown')} • ${esc(x.size_human||'')} • ${Number(x.file_count||0)} file${Number(x.file_count||0)===1?'':'s'}${x.provider_id?' • '+esc(x.provider||'metadata')+':'+esc(x.provider_id):''}</div>${reviewPreviewHtml(x)}${evidence?`<div class="review-block"><h3>Classifier evidence</h3><ul class="review-list">${evidence}</ul></div>`:''}<div class="review-block"><h3>Files</h3><ul class="review-list">${files}</ul></div>${reviewOpticalTitlesHtml(x)}<div class="review-block"><h3>Search metadata</h3><form id="review-metadata-form" class="review-form-grid"><label class="review-field">Title or series<input class="tv-focus" id="review-meta-query" value="${esc(x.series||x.title||'')}" required></label><label class="review-field">Type<select class="tv-focus" id="review-meta-kind"><option value="all">Movies + TV</option><option value="movie">Movie</option><option value="tv">TV series</option></select></label><div class="review-actions"><button class="review-action tv-focus" type="submit">Search metadata</button></div></form>${reviewMetadataHtml()}</div>${reviewEpisodePlan(x)}<div class="review-block"><h3>Route item</h3><form id="review-route-form"><div class="review-form-grid"><label class="review-field">Destination<select class="tv-focus" id="review-kind"><option value="movie" ${kind==='movie'?'selected':''}>Movie</option><option value="tv" ${kind==='tv'?'selected':''}>TV</option><option value="music" ${kind==='music'?'selected':''}>Music</option><option value="home" ${kind==='home'?'selected':''}>Home video</option><option value="game">PC game</option><option value="software">Software</option><option value="disc">Disc image/data</option></select></label><label class="review-field" data-review-for="movie,home,game,software,disc">Title<input class="tv-focus" id="review-title" value="${esc(x.title||'')}"></label><label class="review-field" data-review-for="movie,tv,music,home,game,software,disc">Year<input class="tv-focus" id="review-year" value="${esc(x.year||'')}" inputmode="numeric"></label><label class="review-field" data-review-for="tv">Series<input class="tv-focus" id="review-series" value="${esc(x.series||x.title||'')}"></label><label class="review-field" data-review-for="tv">Season<input class="tv-focus" id="review-season" value="${esc(x.season||'1')}" inputmode="numeric"></label><label class="review-field" data-review-for="tv">Starting episode<input class="tv-focus" id="review-episode" value="${esc(x.episode||'1')}" inputmode="numeric"></label><label class="review-field" data-review-for="tv">Episode title<input class="tv-focus" id="review-episode-title" value="${esc(x.episode_title||'')}"></label><label class="review-field" data-review-for="music">Artist<input class="tv-focus" id="review-artist"></label><label class="review-field" data-review-for="music">Album<input class="tv-focus" id="review-album" value="${esc(x.title||'')}"></label></div><div class="review-actions"><button class="review-action primary tv-focus" type="submit">Route item</button><button class="review-action tv-focus" data-review-quarantine type="button">Move/leave in quarantine</button><button class="review-action danger tv-focus" data-review-delete type="button">Delete permanently</button></div></form></div>`}
function renderReviewBrowser(){const panel=document.getElementById('review-panel');const queueSelected=reviewItems.find(x=>x.id===reviewSelectedId)||reviewItems[0]||null;if(queueSelected)reviewSelectedId=queueSelected.id;const librarySelected=reviewLibraryItems.find(x=>x.id===reviewLibrarySelectedId)||reviewLibraryItems[0]||null;if(librarySelected)reviewLibrarySelectedId=librarySelected.id;const existing=reviewMode==='library';const count=existing?reviewLibraryItems.length:reviewItems.length;panel.innerHTML=`<div class="library-head"><div><div class="library-title">Manual Review</div><div class="library-sub">${existing?`${count} promoted optical movie${count===1?'':'s'} available for title reclassification`:`${count} item${count===1?'':'s'} awaiting classification`} • music keeps playing while this modal is open</div></div><div class="library-head-actions"><button class="review-action tv-focus ${!existing?'primary':''}" data-review-mode="queue" type="button">Review queue</button><button class="review-action tv-focus ${existing?'primary':''}" data-review-mode="library" type="button">Existing disc titles</button><button class="review-action tv-focus" data-review-reconcile type="button">Scan current rips for missing extras</button><button class="library-close tv-focus" data-review-close aria-label="Close">×</button></div></div>${existing?(reviewLibraryItems.length?`<div class="review-layout"><aside class="review-queue">${reviewLibraryItems.map(reviewLibraryQueueButton).join('')}</aside><section class="review-detail">${renderReviewLibraryDetail(librarySelected)}</section></div>`:`<div class="review-empty"><h2>No promoted optical movies found</h2><p>Movies promoted from optical sources will appear here so their disc-title roles can be changed later.</p></div>`):(reviewItems.length?`<div class="review-layout"><aside class="review-queue">${reviewItems.map(reviewQueueButton).join('')}</aside><section class="review-detail">${renderReviewDetail(queueSelected)}</section></div>`:`<div class="review-empty"><h2>Review queue clear</h2><p>There are no unidentified or ambiguous items awaiting manual review. Use Existing disc titles to revise movies that are already promoted.</p></div>`)}`;if(!existing)syncReviewFields()}
async function loadReviewItems(preferred=''){const [d,l]=await Promise.all([reviewRequest('items'),reviewRequest('library-optical-items')]);reviewItems=d.items||[];reviewLibraryItems=l.items||[];if(preferred&&reviewItems.some(x=>x.id===preferred)){reviewSelectedId=preferred;reviewMode='queue'}else if(!reviewItems.some(x=>x.id===reviewSelectedId))reviewSelectedId=reviewItems[0]?.id||'';if(!reviewLibraryItems.some(x=>x.id===reviewLibrarySelectedId))reviewLibrarySelectedId=reviewLibraryItems[0]?.id||'';renderReviewBrowser()}
async function openReviewBrowser(preferred=''){reviewReturnFocus=document.activeElement?.closest?.('[data-tool]')||document.activeElement||reviewReturnFocus;reviewMetadataResults=[];reviewMetadataSource='';document.getElementById('review-browser').classList.add('show');document.getElementById('review-panel').innerHTML='<div class="review-empty">Loading review queue…</div>';try{await loadReviewItems(preferred);setTimeout(()=>document.querySelector('#review-browser .tv-focus')?.focus(),0)}catch(e){document.getElementById('review-panel').innerHTML=`<div class="library-head"><div><div class="library-title">Manual Review</div></div><button class="library-close tv-focus" data-review-close>×</button></div><div class="review-empty">${esc(e.message||e)}</div>`}}
function closeReviewBrowser(){document.getElementById('review-browser').classList.remove('show');reviewMetadataResults=[];reviewMetadataSource='';(reviewReturnFocus||document.querySelector('[data-tool="review"]'))?.focus?.();reviewReturnFocus=null}
async function reviewSelect(id){reviewSelectedId=id;reviewMetadataResults=[];reviewMetadataSource='';renderReviewBrowser();setTimeout(()=>document.querySelector('#review-browser .review-detail .tv-focus')?.focus(),0)}
async function reviewLibrarySelect(id){reviewLibrarySelectedId=id;renderReviewBrowser();setTimeout(()=>document.querySelector('#review-browser .review-detail .tv-focus')?.focus(),0)}
async function reviewLibrarySave(){const x=reviewLibraryItems.find(v=>v.id===reviewLibrarySelectedId);if(!x)return;const roles=Object.fromEntries([...document.querySelectorAll('[data-review-library-role]')].map(el=>[el.dataset.reviewLibraryRole,el.value]));const d=await reviewRequest('reclassify-optical',{item:x.id,roles});showStatus('Disc title roles updated',d.message||'Optical title roles saved.','good',6000);await loadReviewItems()}
async function reviewReconcileOptical(){showStatus('Scanning existing rips','PCGA is looking for preserved MakeMKV titles that are missing from already-promoted optical movies.','info',6000);const d=await reviewRequest('reconcile-optical',{item:'library:reconcile'});showStatus('Optical reconciliation complete',d.message||`Recovered ${Number(d.imported||0)} title(s).`,Number(d.imported||0)?'good':'info',8000);reviewMode='library';await loadReviewItems()}
async function reviewMetadataSearch(){const x=reviewItems.find(v=>v.id===reviewSelectedId);if(!x)return;const d=await reviewRequest('metadata-search',{item:x.id,query:document.getElementById('review-meta-query')?.value||x.title,kind:document.getElementById('review-meta-kind')?.value||'all',year:x.year||''});reviewMetadataResults=d.results||[];reviewMetadataSource=d.source||'';renderReviewBrowser();setTimeout(()=>document.querySelector('[data-review-use-meta]')?.focus(),0)}
async function reviewApplyMetadata(index){const x=reviewItems.find(v=>v.id===reviewSelectedId),r=reviewMetadataResults[index];if(!x||!r)return;const d=await reviewRequest('metadata-apply',{item:x.id,kind:r.kind,title:r.title,year:r.year||'',provider:r.provider||'',provider_id:r.provider_id||''});showStatus('Metadata applied',d.message||'Review item updated.','good',4500);reviewMetadataResults=[];await loadReviewItems(x.id)}
async function reviewPromote(){const x=reviewItems.find(v=>v.id===reviewSelectedId);if(!x)return;const kind=document.getElementById('review-kind')?.value||reviewDefaultKind(x);const opticalRoles=Object.fromEntries([...document.querySelectorAll('[data-review-optical-role]')].map(el=>[el.dataset.reviewOpticalRole,el.value]));const payload={item:x.id,kind,provider:x.provider||'',provider_id:x.provider_id||'',title:document.getElementById('review-title')?.value||x.title||'',year:document.getElementById('review-year')?.value||'',series:document.getElementById('review-series')?.value||x.series||x.title||'',season:document.getElementById('review-season')?.value||'1',episode:document.getElementById('review-episode')?.value||'',episode_title:document.getElementById('review-episode-title')?.value||'',artist:document.getElementById('review-artist')?.value||'',album:document.getElementById('review-album')?.value||x.title||'',optical_roles:JSON.stringify(opticalRoles)};const d=await reviewRequest('promote',payload);showStatus('Review item routed',d.message||'Item promoted.','good',5000);reviewMetadataResults=[];await loadReviewItems()}
async function reviewQuarantine(){const x=reviewItems.find(v=>v.id===reviewSelectedId);if(!x)return;const d=await reviewRequest('quarantine',{item:x.id});showStatus('Review item quarantined',d.message||'Item moved to quarantine.','good',5000);reviewMetadataResults=[];await loadReviewItems()}
async function reviewDelete(){const x=reviewItems.find(v=>v.id===reviewSelectedId);if(!x)return;const label=x.title||x.path||'this item';if(!confirm(`Permanently delete ${label} and all files in this review item? This cannot be undone.`))return;const d=await reviewRequest('delete',{item:x.id,confirm:'DELETE'});showStatus('Review item deleted',d.message||'Item permanently deleted.','good',5000);reviewMetadataResults=[];await loadReviewItems()}
async function heroicRequest(action){const r=await fetch('/api/control/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action}),cache:'no-store'}),d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw Error(d.detail||d.error||d.stderr||r.status);return d}
async function heroicWaitReady(attempt=0){const d=await heroicRequest('heroic-status');if(d.installed&&String(d.state||'')==='ready')return d;if(String(d.state||'')==='error')throw Error(d.detail||'Heroic preparation failed');if(attempt>=300)throw Error('Heroic is still being prepared. Open PC Games again in a few minutes; the install continues on the appliance.');showStatus('Preparing Heroic',d.detail||`Preparing Heroic ${d.heroic_version||''}…`,'info',5000);await new Promise(resolve=>setTimeout(resolve,2000));return heroicWaitReady(attempt+1)}
async function openHeroicLibrary(){if(!requireSecurePcGameContext())return;try{let d=await heroicRequest('heroic-status');if(!d.installed){showStatus('Preparing Heroic','Downloading and building the isolated Heroic streaming runtime. This is a one-time setup; the rest of PCGA remains usable.','info',9000);await heroicRequest('heroic-install');d=await heroicWaitReady()}else if(String(d.state||'')!=='ready'){d=await heroicWaitReady()}showStatus('Opening Heroic',`Heroic ${d.heroic_version||''} is ready. Store sign-in remains inside the streamed Heroic desktop.`,'good',6000);await heroicRequest('heroic-sync');setTimeout(()=>pcGameStream('pcga:heroic-library-manager'),650)}catch(e){showStatus('Heroic is not ready',e.message||String(e),'warn',12000)}}
async function syncHeroicLibrary(){try{const st=await heroicRequest('heroic-status');if(!st.installed){showStatus('Heroic is not installed','The legacy Heroic compatibility runtime is not prepared. The native Store Library does not require streaming the Heroic desktop.','info',7000);return}const d=await heroicRequest('heroic-sync');showStatus('Refreshing legacy Heroic installs',d.detail||'PCGA is indexing previously installed Heroic games for compatibility and updating Wolf.','good',7000);setTimeout(()=>openPcGameBrowser(pcGameSearch),2200)}catch(e){showStatus('Heroic refresh failed',e.message||String(e),'warn',10000)}}
async function openPcGameBrowser(search=''){pcGameReturnFocus=document.activeElement?.closest?.('[data-tool]')||lastToolFocus||pcGameReturnFocus;const box=document.getElementById('pc-game-browser');box.classList.add('show');document.getElementById('pc-game-panel').innerHTML='<div class="library-empty">Loading PC game catalog…</div>';try{try{await syncPcGameSessionCache()}catch(_){pcGameActiveSessions=[]}const d=await fetchPcGames(search);renderPcGameBrowser(d,search);setTimeout(()=>document.querySelector('#pc-game-browser .tv-focus')?.focus(),0)}catch(e){let detail=String(e.message||e);try{const hr=await fetch('/api/pc-games/health',{cache:'no-store'}),hd=await hr.json();detail=hd.detail||detail;if(hd.catalog_db)detail+=` • DB: ${hd.catalog_db}`}catch(_){}document.getElementById('pc-game-panel').innerHTML=`<div class="library-head"><div><div class="library-title">PC Games</div><div class="library-sub">LANCommander catalog diagnostics</div></div><button class="library-close tv-focus" data-pc-game-close>×</button></div><div class="library-empty">${esc(detail)}<br><br>Native LANCommander remains available under Advanced while PCGA repairs or diagnoses the catalog bridge.</div>`}}
function closePcGameBrowser(){stopStoreInstallPoll();document.getElementById('pc-game-browser').classList.remove('show');(pcGameReturnFocus||document.querySelector('[data-tool="lancommander"]'))?.focus?.()}
function renderJellyfinSeries(data,series,search=''){const panel=document.getElementById('library-panel');libraryItems=data?.items||[];librarySearch=search;libraryFilter='episodes';librarySeries=series;panel.innerHTML=`<div class="library-head"><div><div class="library-title">${esc(series?.name||'TV Series')}</div><div class="library-sub">Episodes • ${esc(data?.user_name||'Jellyfin')}</div></div><div class="library-head-actions"><button class="library-upload tv-focus" data-library-series-back type="button">← TV Series</button><button class="library-close tv-focus" data-library-close aria-label="Close">×</button></div></div><form class="library-search" id="library-series-search-form"><input class="tv-focus" id="library-series-search-input" value="${esc(search)}" placeholder="Search episodes in ${esc(series?.name||'this series')}" autocomplete="off"><button class="tv-focus" type="submit">Search</button></form><div class="library-grid">${libraryItems.length?libraryItems.map((x,i)=>libraryCard(x,i,'library-series-grid')).join(''):`<div class="library-empty">No episodes found for this series.</div>`}</div>`}
async function openJellyfinSeries(series,search=''){if(!series?.id)return;librarySeries=series;document.getElementById('library-panel').innerHTML='<div class="library-empty">Loading series episodes…</div>';try{const d=await fetchJellyfinLibrary(search,'episodes',series.id);renderJellyfinSeries(d,series,search);setTimeout(()=>document.querySelector('#library-browser .tv-focus')?.focus(),0)}catch(e){document.getElementById('library-panel').innerHTML=`<div class="library-head"><div><div class="library-title">${esc(series?.name||'TV Series')}</div><div class="library-sub">Episode browser</div></div><button class="library-close tv-focus" data-library-close>×</button></div><div class="library-empty">${esc(e.message||e)}</div>`}}
function renderJellyfinLibrary(data,search='',filter='all'){const panel=document.getElementById('library-panel');libraryItems=data?.items||[];librarySearch=search;libraryFilter=filter;librarySeries=null;const overview=filter==='all'&&Array.isArray(data?.sections);const content=overview?renderLibraryOverview(data):`<div class="library-grid">${libraryItems.length?libraryItems.map((x,i)=>libraryCard(x,i,'library-grid')).join(''):`<div class="library-empty">No media found.</div>`}</div>`;panel.innerHTML=`<div class="library-head"><div><div class="library-title">Movies & TV</div><div class="library-sub">${search?`Results for “${esc(search)}”`:'Browse visual media by type'} • ${esc(data?.user_name||'Jellyfin')}</div></div><div class="library-head-actions"><button class="library-upload tv-focus" data-upload-kind="movie" type="button">Upload movie</button><button class="library-upload tv-focus" data-upload-kind="tv" type="button">Upload TV</button><button class="library-upload tv-focus" data-upload-kind="home-video" type="button">Home video</button><button class="library-close tv-focus" data-group="library-head" data-library-close aria-label="Close">×</button></div></div><form class="library-search" id="library-search-form"><input class="tv-focus" data-group="library-search" id="library-search-input" value="${esc(search)}" placeholder="Search movies, shows or videos" autocomplete="off"><button class="tv-focus" data-group="library-search" type="submit">Search</button></form><div class="library-filters">${libraryFilterButton('all','Overview')}${libraryFilterButton('movies','Movies')}${libraryFilterButton('tv','TV Series')}${libraryFilterButton('videos','Other Video')}</div>${content}`}
async function openJellyfinLibrary(search='',filter='all'){libraryReturnFocus=document.activeElement?.closest?.('[data-tool]')||lastToolFocus||libraryReturnFocus;const box=document.getElementById('library-browser');box.classList.add('show');document.getElementById('library-panel').innerHTML='<div class="library-empty">Loading media library…</div>';try{const d=await fetchJellyfinLibrary(search,filter);renderJellyfinLibrary(d,search,filter);setTimeout(()=>document.querySelector('#library-browser .tv-focus')?.focus(),0)}catch(e){document.getElementById('library-panel').innerHTML=`<div class="library-head"><div><div class="library-title">Movies & TV</div><div class="library-sub">Portal playback</div></div><button class="library-close tv-focus" data-library-close>×</button></div><div class="library-empty">${esc(e.message||e)}</div>`}}
function closeJellyfinLibrary(){document.getElementById('library-browser').classList.remove('show');(libraryReturnFocus||document.querySelector('[data-tool="jellyfinlibrary"]'))?.focus?.()}
function videoRuntimeSeconds(){const item=videoPortalPlayer.item||{};const ticks=Number(item.runtime_ticks)||0;const sec=Number(item.runtime_seconds)||0;if(ticks>0)return ticks/10000000;if(sec>0)return sec;return 0}
function videoAbsoluteSeconds(){const pos=(Number(videoPortalPlayer.start_ticks)||0)/10000000+(Number(videoPlayer.currentTime)||0),runtime=videoRuntimeSeconds();return runtime>0?Math.max(0,Math.min(runtime,pos)):Math.max(0,pos)}
function videoQualityLabel(id){const x=(videoPortalPlayer.quality_options||[]).find(q=>q.id===id);return x?.label||String(id||'Auto')}
function videoAudioLabel(index){const x=(videoPortalPlayer.audio_streams||[]).find(q=>Number(q.index)===Number(index));return x?.label||'Default audio'}
function videoSubtitleLabel(index){if(index===null||Number(index)<0)return'Off';const x=(videoPortalPlayer.subtitle_streams||[]).find(q=>Number(q.index)===Number(index));return x?.label||`Subtitle ${index}`}
function renderVideoSelectors(){if(videoQuality){const opts=(videoPortalPlayer.quality_options||[]);videoQuality.innerHTML=(opts.length?opts:[{id:'auto',label:'Auto'}]).map(q=>`<option value="${esc(q.id)}">${esc(q.label||q.id)}</option>`).join('');videoQuality.value=videoPortalPlayer.quality||videoPrefs.quality||'auto';videoQuality.disabled=!videoPortalPlayer.active||videoReconfigureBusy}if(videoAudioTrack){const tracks=videoPortalPlayer.audio_streams||[];videoAudioTrack.innerHTML=tracks.length?tracks.map(x=>`<option value="${Number(x.index)}">${esc(x.label||`Audio ${x.index}`)}</option>`).join(''):'<option value="">Default audio</option>';if(videoPortalPlayer.audio_stream_index!==null&&videoPortalPlayer.audio_stream_index!==undefined)videoAudioTrack.value=String(videoPortalPlayer.audio_stream_index);videoAudioTrack.disabled=!videoPortalPlayer.active||videoReconfigureBusy||!tracks.length}if(videoSubtitleTrack){const tracks=videoPortalPlayer.subtitle_streams||[];videoSubtitleTrack.innerHTML='<option value="-1">Off</option>'+tracks.map(x=>`<option value="${Number(x.index)}">${esc(x.label||`Subtitle ${x.index}`)}</option>`).join('');videoSubtitleTrack.value=String(videoPortalPlayer.subtitle_stream_index??-1);videoSubtitleTrack.disabled=!videoPortalPlayer.active||videoReconfigureBusy||!tracks.length}if(videoSpeed){videoSpeed.value=String(videoPrefs.speed||1);videoSpeed.disabled=!videoPortalPlayer.active}if(videoFit){videoFit.textContent=videoPrefs.fit==='cover'?'Fill':'Fit';videoFit.setAttribute('aria-label',videoPrefs.fit==='cover'?'Use fit-to-window video':'Fill the player window')}}
function renderVideoStreamBadge(){if(!videoStreamBadge)return;const v=videoPortalPlayer.video_stream||{};const bits=[];if(v.width&&v.height)bits.push(`${v.width}×${v.height}`);if(v.codec)bits.push(String(v.codec).toUpperCase());bits.push(videoQualityLabel(videoPortalPlayer.quality));if(videoPortalPlayer.audio_streams?.length)bits.push(videoAudioLabel(videoPortalPlayer.audio_stream_index));if(videoPortalPlayer.subtitle_stream_index>=0)bits.push(`CC: ${videoSubtitleLabel(videoPortalPlayer.subtitle_stream_index)}`);videoStreamBadge.textContent=bits.filter(Boolean).join(' • ');videoStreamBadge.hidden=!videoPortalPlayer.active||!bits.length}
function applyVideoFit(){const fill=videoPrefs.fit==='cover';videoPlayer.classList.toggle('video-fill',fill);if(videoFit){videoFit.textContent=fill?'Fill':'Fit';videoFit.setAttribute('aria-pressed',fill?'true':'false')}}
function renderVideoControls(){const runtime=videoRuntimeSeconds(),pos=videoAbsoluteSeconds();if(videoTimeCurrent)videoTimeCurrent.textContent=fmt(pos);if(videoTimeTotal)videoTimeTotal.textContent=runtime>0?fmt(runtime):'—';if(videoSeek&&!videoSeekDragging){videoSeek.disabled=runtime<=0||videoReconfigureBusy;videoSeek.max=runtime>0?String(Math.max(1,Math.round(runtime))):'1';videoSeek.value=runtime>0?String(Math.min(runtime,pos)):'0'}if(videoPlayPause){videoPlayPause.textContent=videoPlayer.paused?'▶':'Ⅱ';videoPlayPause.setAttribute('aria-label',videoPlayer.paused?'Play':'Pause');videoPlayPause.disabled=videoReconfigureBusy}if(videoMute){videoMute.textContent=videoPlayer.muted?'◉':'○';videoMute.setAttribute('aria-label',videoPlayer.muted?'Unmute':'Mute')}if(videoVolume&&!videoSeekDragging)videoVolume.value=String(Math.round(videoPlayer.volume*100));const fs=document.fullscreenElement===document.querySelector('.video-player-panel');const fsb=document.getElementById('video-fullscreen');if(fsb){fsb.textContent=fs?'🗗':'⛶';fsb.setAttribute('aria-label',fs?'Exit fullscreen player':'Fullscreen player')}renderVideoSelectors();renderVideoStreamBadge();applyVideoFit()}
function videoPlaybackPayload(event){return{event,item_id:videoPortalPlayer.item?.id||'',play_session_id:videoPortalPlayer.play_session_id||'',media_source_id:videoPortalPlayer.media_source_id||'',position_ticks:Math.max(0,Math.round(videoAbsoluteSeconds()*10000000)),paused:videoPlayer.paused,muted:videoPlayer.muted,volume:Math.round(videoPlayer.volume*100),play_method:'Transcode'}}
async function reportVideoPortal(event){if(!videoPortalPlayer.active||!videoPortalPlayer.play_session_id)return;try{await fetch('/api/jellyfin/playback/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(videoPlaybackPayload(event)),keepalive:event==='stopped'})}catch(_){}}
async function stopVideoPortal(failed=false,hide=true){if(videoPortalPlayer.active){const payload=videoPlaybackPayload('stopped');payload.failed=!!failed;try{await fetch('/api/jellyfin/playback/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),keepalive:true})}catch(_){}}videoPlayer.pause();videoPlayer.removeAttribute('src');videoPlayer.load();videoPortalPlayer={active:false,item:null,play_session_id:'',media_source_id:'',started:false,start_ticks:0,quality:videoPrefs.quality||'auto',audio_stream_index:null,subtitle_stream_index:-1,audio_streams:[],subtitle_streams:[],quality_options:[],video_stream:null};videoReconfigureBusy=false;renderVideoControls();if(hide){if(document.fullscreenElement===document.querySelector('.video-player-panel')){try{await document.exitFullscreen?.()}catch(_){}}document.getElementById('video-player-modal').classList.remove('show');applyBackgroundVideo();if(homeMediaOpen()&&homeMediaLastFocus&&document.contains(homeMediaLastFocus)){requestAnimationFrame(()=>pcgaSetSelection(homeMediaLastFocus,{focus:true,scroll:true}));homeMediaLastFocus=null}}}
async function playVideoItem(item,forcedStartTicks=null,options={}){if(!item?.id)return;const wasActive=videoPortalPlayer.active;const preservePaused=!!options.preservePaused;const requestedQuality=(options.quality??(wasActive?videoPortalPlayer.quality:videoPrefs.quality))||'auto';const requestedAudio=options.audio_stream_index!==undefined?options.audio_stream_index:(wasActive?videoPortalPlayer.audio_stream_index:null);const requestedSubtitle=options.subtitle_stream_index!==undefined?options.subtitle_stream_index:(wasActive?videoPortalPlayer.subtitle_stream_index:null);const requestedSource=options.media_source_id??(wasActive?videoPortalPlayer.media_source_id:(item.media_source_id||''));if(wasActive)await stopVideoPortal(false,false);if(portalSettings.pattern==='video')stopBackgroundVideo();const resume=Number(item.resume_ticks)||0;const runtime=Number(item.runtime_ticks)||0;const startTicks=forcedStartTicks!==null?Math.max(0,Number(forcedStartTicks)||0):(resume>300000000&&(!runtime||resume<runtime*.95)?resume:0);document.getElementById('video-player-title').textContent=item.name||'Jellyfin Video';document.getElementById('video-player-meta').textContent=[item.subtitle||item.type,startTicks?`Starting at ${fmt(startTicks/10000000)}`:''].filter(Boolean).join(' • ');document.getElementById('video-player-note').innerHTML='<strong>Preparing Jellyfin playback…</strong>';document.getElementById('video-player-modal').classList.add('show');if(!options.reconfigure)document.getElementById('video-player-close').focus();videoReconfigureBusy=true;renderVideoControls();try{const payload={item_id:item.id,start_ticks:startTicks,quality:requestedQuality,media_source_id:requestedSource||'',audio_stream_index:requestedAudio,subtitle_stream_index:requestedSubtitle};const r=await fetch('/api/jellyfin/video/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);videoPortalPlayer={active:true,item:d.item||item,play_session_id:d.play_session_id||'',media_source_id:d.media_source_id||'',started:false,start_ticks:Number(d.start_ticks)||0,quality:d.quality||requestedQuality||'auto',audio_stream_index:d.audio_stream_index??null,subtitle_stream_index:d.subtitle_stream_index??-1,audio_streams:Array.isArray(d.audio_streams)?d.audio_streams:[],subtitle_streams:Array.isArray(d.subtitle_streams)?d.subtitle_streams:[],quality_options:Array.isArray(d.quality_options)?d.quality_options:[],video_stream:d.video_stream||null};videoPrefs.quality=videoPortalPlayer.quality||videoPrefs.quality;saveVideoPrefs();videoPlayer.src=d.stream_url;videoPlayer.load();videoPlayer.playbackRate=Math.max(.25,Math.min(4,Number(videoPrefs.speed)||1));applyVideoFit();videoReconfigureBusy=false;renderVideoControls();const selection=[videoQualityLabel(videoPortalPlayer.quality),videoAudioLabel(videoPortalPlayer.audio_stream_index),videoPortalPlayer.subtitle_stream_index>=0?`Subtitles: ${videoSubtitleLabel(videoPortalPlayer.subtitle_stream_index)}`:'Subtitles off'].filter(Boolean).join(' • ');document.getElementById('video-player-note').textContent=`${selection}. Subtitle changes can require a Jellyfin video transcode.`;if(!preservePaused)await videoPlayer.play();renderVideoControls()}catch(e){videoReconfigureBusy=false;renderVideoControls();document.getElementById('video-player-note').textContent=`Playback error: ${e.message||e}`;showStatus('Jellyfin video playback failed',String(e.message||e),'warn',9000)}}
async function restartVideoWithSettings(changes={}){if(!videoPortalPlayer.active||videoReconfigureBusy)return;const item=videoPortalPlayer.item,posTicks=Math.round(videoAbsoluteSeconds()*10000000),paused=videoPlayer.paused;videoReconfigureBusy=true;renderVideoControls();await playVideoItem(item,posTicks,{reconfigure:true,preservePaused:paused,quality:changes.quality??videoPortalPlayer.quality,audio_stream_index:changes.audio_stream_index!==undefined?changes.audio_stream_index:videoPortalPlayer.audio_stream_index,subtitle_stream_index:changes.subtitle_stream_index!==undefined?changes.subtitle_stream_index:videoPortalPlayer.subtitle_stream_index,media_source_id:videoPortalPlayer.media_source_id})}
async function seekVideoTo(seconds){if(!videoPortalPlayer.active||videoReconfigureBusy)return;const runtime=videoRuntimeSeconds(),target=runtime>0?Math.max(0,Math.min(runtime,Number(seconds)||0)):Math.max(0,Number(seconds)||0),paused=videoPlayer.paused,item=videoPortalPlayer.item;await playVideoItem(item,Math.round(target*10000000),{reconfigure:true,preservePaused:paused,quality:videoPortalPlayer.quality,audio_stream_index:videoPortalPlayer.audio_stream_index,subtitle_stream_index:videoPortalPlayer.subtitle_stream_index,media_source_id:videoPortalPlayer.media_source_id})}
function toggleVideoFit(){videoPrefs.fit=videoPrefs.fit==='cover'?'contain':'cover';saveVideoPrefs();applyVideoFit()}
async function toggleVideoFullscreen(){const panel=document.querySelector('.video-player-panel');if(!panel)return;try{if(document.fullscreenElement)await document.exitFullscreen?.();else await panel.requestFullscreen?.()}catch(e){showStatus('Fullscreen unavailable',String(e.message||e),'warn',5000)}renderVideoControls()}

function playLibraryItem(index){const item=libraryItems[Number(index)];if(!item)return;if(item.kind==='series'||String(item.type||'').toLowerCase()==='series'){openJellyfinSeries(item);return}if(item.kind==='audio'){const audioItems=libraryItems.filter(x=>x.kind==='audio');musicQueue=audioItems;const ai=audioItems.findIndex(x=>x.id===item.id);closeJellyfinLibrary();playPortalItem(item.id,Number(item.resume_ticks)||0,item,ai)}else{playVideoItem(item)}}

function playbackPayload(event){return{event,item_id:portalPlayer.item?.id||'',play_session_id:portalPlayer.play_session_id||'',media_source_id:portalPlayer.media_source_id||'',position_ticks:Math.max(0,Math.round((audio.currentTime||0)*10000000)),paused:audio.paused,muted:audio.muted,volume:Math.round(audio.volume*100)}}
async function reportPortal(event){if(!portalPlayer.active||!portalPlayer.play_session_id)return;try{await fetch('/api/jellyfin/music/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(playbackPayload(event)),keepalive:event==='stopped'})}catch(_){}}
async function preparePortalSession(itemId,startTicks=0){try{const r=await fetch('/api/jellyfin/music/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:itemId,start_ticks:startTicks})});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error||r.status);if(!portalPlayer.active||portalPlayer.item?.id!==itemId)return;portalPlayer.item=d.item||portalPlayer.item;portalPlayer.play_session_id=d.play_session_id||'';portalPlayer.media_source_id=d.media_source_id||'';if(!portalPlayer.started&&!audio.paused){portalPlayer.started=true;reportPortal('start')}renderMusic(externalMusicSession)}catch(e){showStatus('Jellyfin session warning',`Audio is playing locally, but Jellyfin session reporting failed: ${e.message||e}`,'warn',8000)}}
async function stopPortalPlayback(failed=false){if(!portalPlayer.active)return;await reportPortal('stopped');audio.pause();audio.removeAttribute('src');audio.load();portalPlayer={active:false,item:null,play_session_id:'',media_source_id:'',started:false};renderMusic(externalMusicSession)}
function playPortalItem(itemId,startTicks=0,itemHint=null,index=-1){if(!itemId)return;if(portalPlayer.active)reportPortal('stopped');const hint=itemHint||musicQueue.find(x=>x.id===itemId)||{id:itemId,name:externalMusicSession?.title||'Jellyfin audio',artist:externalMusicSession?.artist||'',album:externalMusicSession?.album||'',art_url:externalMusicSession?.art_url||null,runtime_seconds:externalMusicSession?.runtime_seconds||0};portalPlayer={active:true,item:hint,play_session_id:'',media_source_id:'',started:false};if(index>=0)musicQueueIndex=index;audio.src=`/api/jellyfin/audio/${encodeURIComponent(itemId)}`;const seek=()=>{if(startTicks>0&&Number.isFinite(audio.duration)){try{audio.currentTime=Math.min(audio.duration||Infinity,startTicks/10000000)}catch(_){}}};audio.addEventListener('loadedmetadata',seek,{once:true});audio.play().then(()=>{renderMusic(externalMusicSession)}).catch(e=>{showStatus('Playback blocked',String(e.message||e),'warn',8000)});preparePortalSession(itemId,startTicks);renderMusic(externalMusicSession)}
function queueMove(delta){if(!musicQueue.length)return;let i=musicQueueIndex;if(i<0)i=musicQueue.findIndex(x=>x.id===portalPlayer.item?.id);i=(Math.max(0,i<0?0:i)+delta+musicQueue.length)%musicQueue.length;musicQueueIndex=i;const x=musicQueue[i];playPortalItem(x.id,0,x,i)}
async function refreshMusic(){try{const r=await fetch('/api/jellyfin/now-playing',{cache:'no-store'});if(!r.ok)throw Error(r.status);const m=await r.json();renderMusic(m)}catch(e){externalMusicSession=null;renderMusic({available:false,playing:false})}}
async function sendMusic(action){if(action==='browse'){if(pcgaAudioPlayer.active&&pcgaAudioPlayer.kind==='podcast')openPodcastBrowser('');else if(pcgaAudioPlayer.active&&pcgaAudioPlayer.kind==='audiobook')openAudiobookBrowser('');else openMusicBrowser('','home');return}if(pcgaAudioPlayer.active){if(action==='playpause'){audio.paused?audio.play():audio.pause()}else if(action==='previous')pcgaAudioMove(-1);else if(action==='next')pcgaAudioMove(1);else if(action==='volume_down')audio.volume=Math.max(0,audio.volume-.08);else if(action==='volume_up')audio.volume=Math.min(1,audio.volume+.08);else if(action==='mute')audio.muted=!audio.muted;renderMusic(externalMusicSession);savePcgaAudioProgress();return}if(action==='takeover'&&externalMusicSession?.item_id){const old=externalMusicSession;playPortalItem(old.item_id,old.position_ticks||0,{id:old.item_id,name:old.title,artist:old.artist,album:old.album,art_url:old.art_url,runtime_seconds:old.runtime_seconds},-1);if(old.session_id&&!old.paused){fetch('/api/jellyfin/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:old.session_id,action:'playpause'})}).catch(()=>{})}return}if(musicSession?.source==='portal'){if(action==='playpause'){audio.paused?audio.play():audio.pause()}else if(action==='previous')queueMove(-1);else if(action==='next')queueMove(1);else if(action==='volume_down')audio.volume=Math.max(0,audio.volume-.08);else if(action==='volume_up')audio.volume=Math.min(1,audio.volume+.08);else if(action==='mute')audio.muted=!audio.muted;renderMusic(externalMusicSession);reportPortal('progress');return}if(!musicSession?.session_id)return;try{const r=await fetch('/api/jellyfin/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:musicSession.session_id,action})});const out=await r.json().catch(()=>({}));if(!r.ok)throw Error(out.error||r.status);await new Promise(x=>setTimeout(x,250));refreshMusic()}catch(e){showStatus('Jellyfin control failed',String(e.message||e),'warn',7000)}}
document.getElementById('cc-nas-save')?.addEventListener('click',()=>nasConfigure());document.getElementById('cc-game-db-save')?.addEventListener('click',()=>saveGameDbConfig());
document.addEventListener('click',e=>{const tab=e.target.closest('[data-control-tab]');if(tab){e.preventDefault();showControlSection(tab.dataset.controlTab);return}const action=e.target.closest('[data-control-action]');if(action){e.preventDefault();if(action.dataset.controlAction==='nas-archive'&&!confirm('Archive all selected-library files old enough for the NAS policy? PCGA will verify each NAS copy with SHA-256 before removing its local copy.'))return;controlAction(action.dataset.controlAction);return}const storeConnect=e.target.closest('[data-store-account-connect]');if(storeConnect){e.preventDefault();storeAccountConnect(storeConnect.dataset.storeAccountConnect||'');return}const storeLogout=e.target.closest('[data-store-account-logout]');if(storeLogout){e.preventDefault();storeAccountLogout(storeLogout.dataset.storeAccountLogout||'');return}if(e.target.closest('[data-store-auth-submit]')){e.preventDefault();storeAccountComplete();return}if(e.target.closest('[data-store-auth-home]')){e.preventDefault();closeStoreAuth(true);return}if(e.target.closest('[data-store-auth-close]')){e.preventDefault();closeStoreAuth();return}if(e.target.closest('#system-strip')){e.preventDefault();openSettings('system');return}const add=e.target.closest('[data-tool="addmedia"]');if(add){e.preventDefault();lastToolFocus=add;openUploadBrowser();return}if(e.target.closest('[data-open-upload]')){e.preventDefault();closeSettings();setTimeout(()=>openUploadBrowser(),0);return}if(e.target.closest('#settings-open')){e.preventDefault();openSettings('display');return}if(e.target.closest('#settings-close')||e.target.closest('#settings-done')){e.preventDefault();closeSettings();return}if(e.target.closest('#settings-reset')){e.preventDefault();portalSettings={...PORTAL_DEFAULTS};backgroundItems=[];photoItems=[];try{localStorage.removeItem(PORTAL_SETTINGS_KEY)}catch(_){}applyPortalSettings();renderBackgroundResults([]);showStatus('Portal settings reset','This display is back to the release defaults.','good',3500);return}if(e.target.closest('#background-clear-button')){e.preventDefault();portalSettings.videoId='';portalSettings.videoSourceId='';portalSettings.videoName='';if(portalSettings.pattern==='video')portalSettings.pattern='ambient';savePortalSettings();return}if(e.target.closest('#background-search-button')){e.preventDefault();loadBackgroundLibrary(document.getElementById('background-search-input')?.value||'').catch(err=>{document.getElementById('background-results').innerHTML=`<div class="settings-note">${esc(err.message||err)}</div>`});return}const themeChoice=e.target.closest('[data-pcga-theme]');if(themeChoice){e.preventDefault();const id=themeChoice.dataset.pcgaTheme;if(PORTAL_THEMES[id]){portalSettings.uiTheme=id;savePortalSettings();setTimeout(()=>document.querySelector(`[data-pcga-theme="${id}"]`)?.focus(),0);showStatus('Interface theme updated',PORTAL_THEMES[id].name+' is now active on this display.','good',3000)}return}const scheme=e.target.closest('[data-scheme]');if(scheme){e.preventDefault();if(PORTAL_SCHEMES[scheme.dataset.scheme]){const id=scheme.dataset.scheme;portalSettings.scheme=id;savePortalSettings();setTimeout(()=>document.querySelector(`[data-scheme="${id}"]`)?.focus(),0)}return}const item=e.target.closest('[data-bg-item]');if(item){e.preventDefault();selectBackgroundItem(backgroundItems[Number(item.dataset.bgItem)]);return}});
document.addEventListener('click',e=>{const home=e.target.closest?.('[data-home-return]');if(home){e.preventDefault();closeHomeMediaSurface(true);return}const card=e.target.closest?.('[data-home-media-key]');if(card){e.preventDefault();playHomeMediaKey(card.dataset.homeMediaKey);return}});
for(const id of ['setting-layout-mode','setting-appearance-mode','setting-surface-style','setting-font-style','setting-clock','setting-clock-style','setting-clock-face','setting-clock-position','setting-clock-format','setting-clock-boxed','setting-home-media','setting-home-media-games','setting-home-media-continue','setting-home-media-recent','setting-home-media-added','setting-radius','setting-pattern','setting-background-motion','setting-parallax-ambient','setting-parallax-pattern','setting-parallax-media','setting-video-opacity','setting-slideshow-interval','setting-pc-game-transport']){document.getElementById(id)?.addEventListener(id==='setting-radius'||id.startsWith('setting-parallax-')||id==='setting-video-opacity'||id==='setting-slideshow-interval'?'input':'change',()=>updateSettingFromControl(id))}
document.getElementById('diag-refresh')?.addEventListener('click',()=>refreshDiagnostics(true).catch(()=>{}));document.getElementById('diag-download')?.addEventListener('click',downloadDiagnosticSnapshot);document.getElementById('diag-profile')?.addEventListener('change',()=>{diagnosticProfile=document.getElementById('diag-profile').value;diagnosticLogs={};refreshDiagnostics().catch(()=>{})});document.getElementById('diag-window')?.addEventListener('change',()=>refreshDiagnostics().catch(()=>{}));document.getElementById('diag-lines')?.addEventListener('change',()=>refreshDiagnostics().catch(()=>{}));document.getElementById('diag-auto')?.addEventListener('change',startDiagnosticTimer);document.addEventListener('click',e=>{const b=e.target.closest?.('[data-diag-copy]');if(!b)return;const x=diagnosticLogs[b.dataset.diagCopy];navigator.clipboard?.writeText?.(x?.log||'').then(()=>showStatus('Log copied',x?.service?.name||b.dataset.diagCopy,'good',2200)).catch(()=>{})});
document.getElementById('cc-pc-graphics-backend')?.addEventListener('change',e=>patchControl({games:{graphics_backend:e.target.value||'auto'}}));
for(const[id,section,key]of [['cc-auto-rip','ingest','auto_rip'],['cc-keep-raw','ingest','keep_raw'],['cc-auto-classify','review','auto_classify'],['cc-romm-enabled','games','romm_enabled'],['cc-romm-watch','games','filesystem_watch'],['cc-hasheous','games','metadata_hasheous'],['cc-playmatch','games','metadata_playmatch'],['cc-compat-protondb','games','compat_protondb'],['cc-compat-playonlinux','games','compat_playonlinux'],['cc-jellyfin-enabled','media','jellyfin_enabled'],['cc-immich-enabled','photos','immich_enabled'],['cc-sorter-enabled','automation','sorter_enabled'],['cc-classifier-enabled','automation','classifier_enabled'],['cc-dedupe-enabled','automation','dedupe_enabled']]){document.getElementById(id)?.addEventListener('change',e=>patchControl({[section]:{[key]:!!e.target.checked}}))}
document.getElementById('cc-romm-debounce')?.addEventListener('change',e=>patchControl({games:{watch_debounce_seconds:Number(e.target.value)||300}}));document.getElementById('cc-auto-threshold')?.addEventListener('input',e=>{document.getElementById('cc-threshold-value').textContent=`${e.target.value}%`});document.getElementById('cc-auto-threshold')?.addEventListener('change',e=>patchControl({review:{auto_threshold:(Number(e.target.value)||90)/100}}));
let pcgaPatchFile=null,pcgaPatchPoll=null;function renderPatchSelection(){const label=document.getElementById('patch-selected'),button=document.getElementById('patch-install'),state=document.getElementById('patch-state');if(label)label.textContent=pcgaPatchFile?`${pcgaPatchFile.name} • ${(pcgaPatchFile.size/1048576).toFixed(1)} MiB`:'No patch selected';if(button)button.disabled=!pcgaPatchFile||!window.isSecureContext;if(state&&!window.isSecureContext)state.textContent='Patch installation is disabled on the HTTP portal. Open the HTTPS portal first.';else if(state&&pcgaPatchFile)state.textContent='Ready to validate the release manifest and install.'}function setPcgaPatchFile(file){pcgaPatchFile=(file&&String(file.name||'').toLowerCase().endsWith('.zip'))?file:null;if(file&&!pcgaPatchFile)showStatus('Invalid patch file','Choose a PCGA .zip release archive.','warn',6000);renderPatchSelection()}async function pollPcgaPatch(id){if(pcgaPatchPoll)clearTimeout(pcgaPatchPoll);const state=document.getElementById('patch-state'),log=document.getElementById('patch-log');try{const r=await fetch('/api/control/patch/status?id='+encodeURIComponent(id),{cache:'no-store'}),d=await r.json().catch(()=>({}));if(!r.ok||!d.ok)throw Error(d.detail||d.error||`HTTP ${r.status}`);if(state)state.textContent=`Patch v${d.version||'?'}: ${d.state||'running'}`;if(log){log.hidden=!d.log_tail;log.textContent=d.log_tail||'';log.scrollTop=log.scrollHeight}if(!['complete','failed'].includes(d.state))pcgaPatchPoll=setTimeout(()=>pollPcgaPatch(id),1800);else if(d.state==='complete'){showStatus('PCGA patch installed',`v${d.version} installation completed. Reloading the portal…`,'good',7000);setTimeout(()=>location.reload(),2500)}else showStatus('Patch installation failed','Open the patch log in System settings for details.','warn',9000)}catch(e){if(state)state.textContent='Portal temporarily unavailable while services restart; checking again…';pcgaPatchPoll=setTimeout(()=>pollPcgaPatch(id),2500)}}async function installPcgaPatch(){if(!window.isSecureContext)throw Error('Open the HTTPS portal before installing patches');if(!pcgaPatchFile)throw Error('Choose a patch ZIP first');if(!confirm(`Install ${pcgaPatchFile.name}? PCGA services may restart while the patch is applied.`))return;const button=document.getElementById('patch-install'),state=document.getElementById('patch-state');if(button)button.disabled=true;if(state)state.textContent='Uploading and validating patch…';const r=await fetch('/api/control/patch',{method:'POST',headers:{'Content-Type':'application/zip','X-PCGA-Filename':pcgaPatchFile.name},body:pcgaPatchFile}),d=await r.json().catch(()=>({}));if(!r.ok||!d.ok){renderPatchSelection();throw Error(d.detail||d.error||`HTTP ${r.status}`)}if(state)state.textContent=`Patch v${d.version} accepted; installation started.`;pollPcgaPatch(d.job_id)}document.getElementById('patch-file')?.addEventListener('change',e=>setPcgaPatchFile(e.target.files?.[0]||null));document.getElementById('patch-install')?.addEventListener('click',()=>installPcgaPatch().catch(e=>showStatus('Patch install failed',e.message||String(e),'warn',10000)));document.getElementById('patch-drop')?.addEventListener('dragover',e=>{e.preventDefault();e.currentTarget.classList.add('drag')});document.getElementById('patch-drop')?.addEventListener('dragleave',e=>e.currentTarget.classList.remove('drag'));document.getElementById('patch-drop')?.addEventListener('drop',e=>{e.preventDefault();e.currentTarget.classList.remove('drag');setPcgaPatchFile(e.dataTransfer?.files?.[0]||null)});renderPatchSelection();
document.getElementById('background-search-input')?.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();loadBackgroundLibrary(e.currentTarget.value||'').catch(err=>{document.getElementById('background-results').innerHTML=`<div class="settings-note">${esc(err.message||err)}</div>`})}});
document.addEventListener('keydown',e=>{const reviewCard=e.target?.closest?.('[data-pc-review-item]');if(reviewCard&&(e.key==='Enter'||e.key===' ')){e.preventDefault();openReviewBrowser(reviewCard.dataset.pcReviewItem||'');return}const card=e.target?.closest?.('[data-pc-game-open]');if(card&&(e.key==='Enter'||e.key===' ')){e.preventDefault();pcGameDetails(card.dataset.pcGameOpen);return}if(e.key==='Escape'&&document.getElementById('settings-modal').classList.contains('show')&&!document.getElementById('store-auth-modal')?.classList.contains('show')){e.preventDefault();closeSettings()}});
bgVideo.addEventListener('error',()=>{if(portalSettings.pattern==='video'&&portalSettings.videoId)showStatus('Background video unavailable','Jellyfin could not provide a browser-compatible background stream. Check Jellyfin transcoding permissions/logs or try another video.','warn',9000)});
document.addEventListener('click',e=>{const hook=e.target.closest('[data-upload-kind]');if(hook){e.preventDefault();e.stopPropagation();openUploadBrowser(hook.dataset.uploadKind||'auto');return}if(e.target.closest('[data-upload-close]')){e.preventDefault();closeUploadBrowser();return}if(e.target.closest('#upload-start')){e.preventDefault();startUserUpload();return}});
document.addEventListener('click',e=>{if(e.target.closest('#global-search-open')){e.preventDefault();openGlobalSearch();return}if(e.target.closest('[data-global-search-close]')){e.preventDefault();closeGlobalSearch();return}const hit=e.target.closest('[data-global-result]');if(hit){e.preventDefault();const [si,ii]=String(hit.dataset.globalResult||'').split(':').map(Number),section=globalSearchSections[si],item=section?.items?.[ii];if(section&&item)openGlobalResult(section.id,item);return}});
document.getElementById('global-search-form')?.addEventListener('submit',e=>{e.preventDefault();runGlobalSearch(document.getElementById('global-search-input')?.value||'')});
document.addEventListener('keydown',e=>{if(e.defaultPrevented)return;const modal=document.getElementById('global-search-modal');if(e.key==='Escape'&&modal?.classList.contains('show')){e.preventDefault();closeGlobalSearch();return}if(e.key==='/'&&!pcgaTextEditingTarget(e.target)&&!document.querySelector('.library-browser.show,.music-browser.show,.photo-browser.show,.settings-modal.show,.video-player-modal.show')){e.preventDefault();openGlobalSearch()}});
document.addEventListener('change',e=>{if(e.target?.id==='upload-files'){setUploadFiles(e.target.files,false);return}if(e.target?.id==='upload-folder'){setUploadFiles(e.target.files,true);return}if(e.target?.id==='upload-kind'){uploadPreferredKind=e.target.value||'auto';uploadAdvancedOpen=true;renderUploadPanel();return}if(e.target?.id==='upload-platform'){uploadSelectedPlatform=e.target.value||'';return}});document.addEventListener('toggle',e=>{if(e.target?.id==='upload-advanced')uploadAdvancedOpen=!!e.target.open;if(e.target?.id==='upload-history')uploadHistoryOpen=!!e.target.open},true);document.addEventListener('input',e=>{if(e.target?.id==='upload-book-title')uploadAudiobookMeta.title=e.target.value||'';if(e.target?.id==='upload-book-author')uploadAudiobookMeta.author=e.target.value||''});
document.addEventListener('keydown',e=>{const picker=e.target?.closest?.('.upload-picker');if(picker&&(e.key==='Enter'||e.key===' ')){e.preventDefault();picker.querySelector('input[type=file]')?.click()}});document.addEventListener('dragover',e=>{const drop=e.target?.closest?.('#upload-drop');if(drop){e.preventDefault();drop.classList.add('drag')}});document.addEventListener('dragleave',e=>{const drop=e.target?.closest?.('#upload-drop');if(drop)drop.classList.remove('drag')});document.addEventListener('drop',e=>{const drop=e.target?.closest?.('#upload-drop');if(!drop)return;e.preventDefault();drop.classList.remove('drag');if(e.dataTransfer?.files?.length)setUploadFiles(e.dataTransfer.files,false)});
document.addEventListener('click',e=>{const tile=e.target.closest('[data-tool="photos"]');if(tile){e.preventDefault();lastToolFocus=tile;openPhotos('');return}if(e.target.closest('[data-photo-close]')){e.preventDefault();closePhotos();return}const view=e.target.closest('[data-photo-view]');if(view){e.preventDefault();viewPhoto(photoItems[Number(view.dataset.photoView)]);return}const wp=e.target.closest('[data-photo-wallpaper]');if(wp){e.preventDefault();setPhotoWallpaper(photoItems[Number(wp.dataset.photoWallpaper)]);return}if(e.target.closest('[data-photo-slideshow]')){e.preventDefault();startPhotoSlideshow(document.getElementById('photo-search-input')?.value||photoSearch);return}if(e.target.closest('#photo-viewer-close')){e.preventDefault();closePhotoViewer();return}if(e.target.closest('#photo-viewer-wallpaper')){e.preventDefault();setPhotoWallpaper(photoViewerItem);closePhotoViewer();return}if(e.target.closest('#background-photo-button')){e.preventDefault();closeSettings();openPhotos(portalSettings.slideshowQuery||'');return}if(e.target.closest('#background-photo-clear')){e.preventDefault();portalSettings.photoId='';portalSettings.photoName='';portalSettings.slideshowQuery='';if(portalSettings.pattern==='photo'||portalSettings.pattern==='slideshow')portalSettings.pattern='ambient';savePortalSettings();return}});
document.addEventListener('submit',e=>{if(e.target?.id==='photo-search-form'){e.preventDefault();openPhotos(document.getElementById('photo-search-input')?.value||'')}});
document.addEventListener('click',e=>{const tile=e.target.closest('[data-tool="romm"]');if(tile){e.preventDefault();lastToolFocus=tile;if(tile.classList.contains('offline')){showStatus('Console Games is not ready','PCGA has not completed its RomM appliance bootstrap. Native RomM remains under Advanced for diagnosis.','warn',8000);return}openGameBrowser('','');return}if(e.target.closest('[data-game-close]')){e.preventDefault();closeGameBrowser();return}if(e.target.closest('[data-game-back]')){e.preventDefault();openGameBrowser(gameSearch,gamePlatform);return}const gamePlay=e.target.closest('[data-game-play-url]');if(gamePlay){e.preventDefault();window.location.assign(gamePlay.dataset.gamePlayUrl);return}if(e.target.closest('[data-game-rescan]')){e.preventDefault();refreshRomMetadata();return}if(e.target.closest('[data-rom-collection-open]')){e.preventDefault();openRomCollection('','',1);return}if(e.target.closest('[data-rom-collection-back]')){e.preventDefault();stopRomCollectionPolling();openGameBrowser(gameSearch,gamePlatform);return}if(e.target.closest('[data-rom-collection-return]')){e.preventDefault();openRomCollection(romCollectionSearch,romCollectionPlatform,romCollectionPage);return}if(e.target.closest('[data-rom-next]')){e.preventDefault();openRomCollection(romCollectionSearch,romCollectionPlatform,romCollectionPage+1);return}const ri=e.target.closest('[data-rom-item-index]');if(ri){e.preventDefault();openRomCollectionItem(Number(ri.dataset.romItemIndex));return}const imp=e.target.closest('[data-rom-import]');if(imp){e.preventDefault();importRomFile(imp);return}const platform=e.target.closest('[data-game-platform]');if(platform){e.preventDefault();openGameBrowser(document.getElementById('game-search-input')?.value||gameSearch,platform.dataset.gamePlatform||'');return}const item=e.target.closest('[data-game-index]');if(item){e.preventDefault();playGame(Number(item.dataset.gameIndex));return}});
document.addEventListener('submit',e=>{if(e.target?.id==='game-search-form'){e.preventDefault();openGameBrowser(document.getElementById('game-search-input')?.value||'',gamePlatform);return}if(e.target?.id==='rom-collection-search-form'){e.preventDefault();const p=document.getElementById('rom-collection-platform')?.value||'';const q=document.getElementById('rom-collection-search-input')?.value||'';if(!p){showStatus('Choose a console','PCGA needs the target console so it can filter compatible ROM files before import.','warn',6500);return}openRomCollection(q,p,1)}});
document.addEventListener('click',e=>{const tile=e.target.closest('[data-tool="review"]');if(tile){e.preventDefault();lastToolFocus=tile;openReviewBrowser();return}if(e.target.closest('[data-open-review]')){e.preventDefault();closeSettings();setTimeout(()=>openReviewBrowser(),0);return}if(e.target.closest('[data-review-close]')){e.preventDefault();closeReviewBrowser();return}const mode=e.target.closest('[data-review-mode]');if(mode){e.preventDefault();reviewMode=mode.dataset.reviewMode||'queue';renderReviewBrowser();return}if(e.target.closest('[data-review-reconcile]')){e.preventDefault();reviewReconcileOptical().catch(err=>showStatus('Optical reconciliation failed',err.message||String(err),'warn',9000));return}const libItem=e.target.closest('[data-review-library-item]');if(libItem){e.preventDefault();reviewLibrarySelect(libItem.dataset.reviewLibraryItem||'');return}if(e.target.closest('[data-review-library-save]')){e.preventDefault();reviewLibrarySave().catch(err=>showStatus('Disc title update failed',err.message||String(err),'warn',9000));return}const item=e.target.closest('[data-review-item]');if(item){e.preventDefault();reviewSelect(item.dataset.reviewItem||'');return}const meta=e.target.closest('[data-review-use-meta]');if(meta){e.preventDefault();reviewApplyMetadata(Number(meta.dataset.reviewUseMeta)).catch(err=>showStatus('Metadata update failed',err.message||String(err),'warn',8000));return}if(e.target.closest('[data-review-quarantine]')){e.preventDefault();reviewQuarantine().catch(err=>showStatus('Review action failed',err.message||String(err),'warn',8000));return}if(e.target.closest('[data-review-delete]')){e.preventDefault();reviewDelete().catch(err=>showStatus('Delete failed',err.message||String(err),'warn',9000));return}const openReview=e.target.closest('[data-review-open-item]');if(openReview){e.preventDefault();e.stopPropagation();openReviewBrowser(openReview.dataset.reviewOpenItem||'');return}});
document.addEventListener('change',e=>{if(e.target?.id==='review-kind')syncReviewFields()});document.addEventListener('input',e=>{if(e.target?.id==='review-season'||e.target?.id==='review-episode')syncReviewFields()});
document.addEventListener('submit',e=>{if(e.target?.id==='review-metadata-form'){e.preventDefault();reviewMetadataSearch().catch(err=>showStatus('Metadata search failed',err.message||String(err),'warn',8000));return}if(e.target?.id==='review-route-form'){e.preventDefault();reviewPromote().catch(err=>showStatus('Review action failed',err.message||String(err),'warn',8000));return}});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.getElementById('store-compat-modal')?.classList.contains('show')){e.stopImmediatePropagation();e.preventDefault();closeStoreGameCompat()}},true);
let storeCompatGame=null;
async function storeCompatStatus(gameId=''){
  const d=await storeAccountAction('store-compat-status',gameId?{game_id:gameId}:{});
  return d;
}
async function refreshStoreCompat(){
  const note=document.getElementById('cc-store-compat-note');
  try{const d=await storeCompatStatus();document.getElementById('cc-store-compat-mode').value=d.default.mode;document.getElementById('cc-store-compat-proton').value=d.default.proton;note.textContent=d.umu_prepared?`UMU ${d.umu_version} is prepared. Proton/Steam runtime files download on first launch if needed.`:`UMU is not prepared. Automatic mode uses Wine until UMU is prepared. Preparing UMU does not interrupt running games.`;}
  catch(e){if(note)note.textContent=String(e.message||e)}
}
async function saveStoreCompatDefault(){
  const note=document.getElementById('cc-store-compat-note');
  try{await storeAccountAction('store-compat-update',{scope:'default',mode:document.getElementById('cc-store-compat-mode').value,proton:document.getElementById('cc-store-compat-proton').value});await refreshStoreCompat();showStatus('Compatibility saved','New store-game launches will use these defaults. Active sessions are unchanged.','good',6000)}
  catch(e){note.textContent=String(e.message||e);showStatus('Compatibility error',String(e.message||e),'warn',7000)}
}
async function prepareStoreUmu(){const note=document.getElementById('cc-store-compat-note');try{await storeAccountAction('store-umu-prepare');note.textContent='Preparing the integrity-checked UMU launcher in the background. Use Refresh status to check completion.';showStatus('UMU preparation started','UMU is downloaded only when requested. Existing games continue working.','info',6500)}catch(e){note.textContent=String(e.message||e)}}
async function openStoreGameCompat(gameId,title){
  if(!/^store-[0-9a-f]{24}$/.test(String(gameId||'')))return;
  storeCompatGame=gameId;const modal=document.getElementById('store-compat-modal');modal.classList.add('show');document.getElementById('store-compat-title').textContent=title||'Installed store game';document.getElementById('store-compat-info').textContent='Loading compatibility settings…';
  try{const d=await storeCompatStatus(gameId),v=d.settings;document.getElementById('store-compat-mode').value=v.mode;document.getElementById('store-compat-proton').value=v.proton;document.getElementById('store-compat-gameid').value=v.gameid;document.getElementById('store-compat-info').textContent=`Effective runner: ${v.effective_runner==='umu'?'UMU/Proton':'Wine'}. ${v.legacy_wine_prefix?'Existing Wine prefix preserved. ':''}${v.umu_prepared?'UMU ready.':'UMU not yet prepared.'} Switching runners creates/uses a different prefix without removing the original.`;}
  catch(e){document.getElementById('store-compat-info').textContent=String(e.message||e)}
  modal.querySelector('[data-store-compat-close]')?.focus();
}
function closeStoreGameCompat(){document.getElementById('store-compat-modal')?.classList.remove('show');storeCompatGame=null;document.querySelector('[data-store-compat-open]')?.focus()}
async function updateStoreGameCompat(reset=false){if(!storeCompatGame)return;const info=document.getElementById('store-compat-info');try{const p={scope:reset?'reset':'game',game_id:storeCompatGame};if(!reset){p.mode=document.getElementById('store-compat-mode').value;p.proton=document.getElementById('store-compat-proton').value;p.umu_gameid=document.getElementById('store-compat-gameid').value.trim()||'umu-default'}await storeAccountAction('store-compat-update',p);info.textContent='Saved. PCGA will reconcile the Wolf game entry when it can do so without interrupting an active game.';showStatus('Game compatibility saved','Game preferences will apply to the next stream.','good',6000)}catch(e){info.textContent=String(e.message||e)}}
document.addEventListener('click',e=>{if(e.target.closest('[data-store-compat-default-save]')){e.preventDefault();saveStoreCompatDefault();return}if(e.target.closest('[data-store-umu-prepare]')){e.preventDefault();prepareStoreUmu();return}if(e.target.closest('[data-store-compat-status]')){e.preventDefault();refreshStoreCompat();return}const storeCompatOpen=e.target.closest('[data-store-compat-open]');if(storeCompatOpen){e.preventDefault();e.stopPropagation();openStoreGameCompat(storeCompatOpen.dataset.storeCompatOpen,storeCompatOpen.dataset.storeCompatTitle);return}if(e.target.closest('[data-store-compat-close]')){e.preventDefault();closeStoreGameCompat();return}if(e.target.closest('[data-store-compat-game-save]')){e.preventDefault();updateStoreGameCompat();return}if(e.target.closest('[data-store-compat-game-reset]')){e.preventDefault();updateStoreGameCompat(true);return}const streamTab=e.target.closest('[data-pc-stream-tab]');if(streamTab){e.preventDefault();activatePcGameStream(streamTab.dataset.pcStreamTab||'',true);return}const streamDisc=e.target.closest('[data-pc-stream-disc]');if(streamDisc){e.preventDefault();switchCurrentPcGameDisc(streamDisc.dataset.pcStreamDisc);return}if(e.target.closest('[data-pc-stream-close]')){e.preventDefault();closePcGameStream();return}if(e.target.closest('[data-pc-stream-end]')){e.preventDefault();endCurrentPcGameSession();return}if(e.target.closest('[data-pc-stream-diagnostics]')){e.preventDefault();closePcGameStream();setTimeout(()=>openSettings('diagnostics'),0);return}if(e.target.closest('[data-pc-stream-reload]')){e.preventDefault();const active=activePcGameStream();if(active?.url){active.frame.src=active.url;showStatus('Reconnecting video','The Wine/game container is being kept alive while the browser stream reconnects.','info',6000)}return}const maintenance=e.target.closest('[data-store-maintain]');if(maintenance){e.preventDefault();e.stopPropagation();openStoreMaintenance(maintenance.dataset.storeMaintain||'',maintenance.dataset.storeMaintainOperation||'');return}if(e.target.closest('[data-store-maintain-close]')){e.preventDefault();closeStoreMaintenance();return}if(e.target.closest('[data-store-maintain-confirm]')){e.preventDefault();confirmStoreMaintenance();return}const installGame=e.target.closest('[data-store-install]');if(installGame){e.preventDefault();openStoreInstall(installGame.dataset.storeInstall);return}if(e.target.closest('[data-store-install-close]')){e.preventDefault();closeStoreInstall();return}if(e.target.closest('[data-store-install-confirm]')){e.preventDefault();confirmStoreInstall();return}if(e.target.closest('[data-store-jobs]')){e.preventDefault();openStoreJobs();return}if(e.target.closest('[data-store-jobs-close]')){e.preventDefault();closeStoreJobs();return}if(e.target.closest('[data-store-jobs-refresh]')){e.preventDefault();refreshStoreJobs();return}if(e.target.closest('[data-store-jobs-library]')){e.preventDefault();closeStoreJobs();openStoreLibrary(storeLibrarySearch||'',storeLibraryProvider||'all',false);return}const jobFilter=e.target.closest('[data-store-job-filter]');if(jobFilter){e.preventDefault();storeJobsView=jobFilter.dataset.storeJobFilter||'all';if(storeJobsLastData)renderStoreJobs(storeJobsLastData);return}const jobOpen=e.target.closest('[data-store-job-open]');if(jobOpen){e.preventDefault();storeJobsView='all';openStoreJobs(jobOpen.dataset.storeJobOpen||'');return}const sjCancel=e.target.closest('[data-store-job-cancel]');if(sjCancel){e.preventDefault();storeJobAction('store-job-cancel',sjCancel.dataset.storeJobCancel);return}const sjRetry=e.target.closest('[data-store-job-retry]');if(sjRetry){e.preventDefault();storeJobAction('store-job-retry',sjRetry.dataset.storeJobRetry);return}const sjDelete=e.target.closest('[data-store-job-delete]');if(sjDelete){e.preventDefault();storeJobAction('store-job-delete',sjDelete.dataset.storeJobDelete);return}if(e.target.closest('[data-store-backends]')){e.preventDefault();closePcGameBrowser();setTimeout(()=>openSettings('games'),0);return}if(e.target.closest('[data-store-library]')){e.preventDefault();openStoreLibrary('',storeLibraryProvider||'all',false);return}if(e.target.closest('[data-store-library-back]')){e.preventDefault();openPcGameBrowser(pcGameSearch);return}if(e.target.closest('[data-store-refresh]')){e.preventDefault();openStoreLibrary(storeLibrarySearch,storeLibraryProvider,true);return}const storeProvider=e.target.closest('[data-store-provider]');if(storeProvider){e.preventDefault();openStoreLibrary(storeLibrarySearch,storeProvider.dataset.storeProvider||'all',false);return}if(e.target.closest('[data-heroic-library]')){e.preventDefault();openHeroicLibrary();return}if(e.target.closest('[data-heroic-sync]')){e.preventDefault();syncHeroicLibrary();return}if(e.target.closest('[data-pc-discs]')){e.preventDefault();openPcGameDiscs('');return}if(e.target.closest('[data-pc-sessions]')){e.preventDefault();openPcGameSessions('');return}if(e.target.closest('[data-pc-session-close]')){e.preventDefault();closePcGameSessions();return}const resumeSession=e.target.closest('[data-pc-session-resume]');if(resumeSession){e.preventDefault();e.stopPropagation();resumePcGameSession(resumeSession.dataset.pcSessionResume||'');return}const stopSession=e.target.closest('[data-pc-session-stop]');if(stopSession){e.preventDefault();stopPcGameSession(stopSession.dataset.pcSessionStop||'',stopSession.dataset.pcSessionSet||'');return}if(e.target.closest('[data-pc-session-end-all]')){e.preventDefault();stopAllPcGameSessions();return}const tile=e.target.closest('[data-tool="lancommander"]');if(tile){e.preventDefault();lastToolFocus=tile;if(tile.classList.contains('offline')){showStatus('PC Games is not ready','PCGA has not completed the LANCommander appliance bootstrap or cannot read its game catalog. Native LANCommander remains under Advanced for diagnosis.','warn',8000);return}openPcGameBrowser('');return}if(e.target.closest('[data-pc-game-close]')){e.preventDefault();closePcGameBrowser();return}if(e.target.closest('[data-pc-game-back]')){e.preventDefault();openPcGameBrowser(pcGameSearch);return}if(e.target.closest('[data-pc-disc-back]')){e.preventDefault();openPcGameDiscs(pcGameDiscSearch);return}if(e.target.closest('[data-pc-metadata-back]')){e.preventDefault();returnFromPcGameMetadata();return}if(e.target.closest('[data-pc-metadata-for-disc]')){e.preventDefault();const disc=pcGameDiscItems.find(x=>String(x.fingerprint||'')===pcGameDiscSelectedFingerprint);const owner=(disc?.game_set_ids||[])[0]||'';const title=pcGameDiscSets.find(x=>String(x.id||'')===String(owner))?.title||disc?.volume_label||'';openPcGameMetadataSearch({setId:owner,fingerprint:pcGameDiscSelectedFingerprint,returnMode:'disc',query:title});return}const gameMeta=e.target.closest('[data-pc-metadata-for-game]');if(gameMeta){e.preventDefault();openPcGameMetadataSearch({setId:gameMeta.dataset.pcMetadataForGame||'',returnMode:'game',query:gameMeta.dataset.pcMetadataQuery||''});return}const metaSelect=e.target.closest('[data-pc-metadata-select]');if(metaSelect){e.preventDefault();pcGameMetadataSelect(metaSelect.dataset.pcMetadataSelect);return}if(e.target.closest('[data-pc-metadata-apply-selected]')){e.preventDefault();pcGameMetadataApply();return}const metaUse=e.target.closest('[data-pc-metadata-use]');if(metaUse){e.preventDefault();pcGameMetadataApply(metaUse.dataset.pcMetadataUse);return}const discCard=e.target.closest('[data-pc-disc-index]');if(discCard){e.preventDefault();pcGameDiscDetails(discCard.dataset.pcDiscIndex);return}const stream=e.target.closest('[data-pc-stream]');if(stream){e.preventDefault();e.stopPropagation();pcGameStream(stream.dataset.pcStream,stream.dataset.pcStreamVariant||'');return}const compat=e.target.closest('[data-pc-compat-refresh]');if(compat){e.preventDefault();e.stopPropagation();pcGameCompatRefresh(compat.dataset.pcCompatRefresh);return}const reinstall=e.target.closest('[data-pc-reinstall]');if(reinstall){e.preventDefault();e.stopPropagation();pcGameReinstall(reinstall.dataset.pcReinstall);return}const retry=e.target.closest('[data-pc-retry]');if(retry){e.preventDefault();e.stopPropagation();pcGameRetry(retry.dataset.pcRetry);return}const detail=e.target.closest('[data-pc-game-detail]');if(detail){e.preventDefault();e.stopPropagation();pcGameDetails(detail.dataset.pcGameDetail);return}const reviewCard=e.target.closest('[data-pc-review-item]');if(reviewCard){e.preventDefault();openReviewBrowser(reviewCard.dataset.pcReviewItem||'');return}const open=e.target.closest('[data-pc-game-open]');if(open){e.preventDefault();pcGameDetails(open.dataset.pcGameOpen);return}});
document.getElementById('store-jobs-search')?.addEventListener('input',e=>{storeJobsSearch=String(e.target.value||'');if(storeJobsLastData)renderStoreJobs(storeJobsLastData)});
document.addEventListener('submit',e=>{if(e.target?.id==='store-library-search-form'){e.preventDefault();openStoreLibrary(document.getElementById('store-library-search-input')?.value||'',storeLibraryProvider,false);return}if(e.target?.id==='pc-game-search-form'){e.preventDefault();openPcGameBrowser(document.getElementById('pc-game-search-input')?.value||'');return}if(e.target?.id==='pc-game-disc-search-form'){e.preventDefault();openPcGameDiscs(document.getElementById('pc-game-disc-search-input')?.value||'');return}if(e.target?.id==='pc-game-metadata-search-form'){e.preventDefault();pcGameMetadataSearch();return}if(e.target?.id==='pc-game-disc-assign-form'){e.preventDefault();submitPcGameDiscAssignment(e.target);return}if(e.target?.id==='pc-game-title-create-form'){e.preventDefault();createPcGameTitle();return}});
document.addEventListener('click',e=>{const libraryTile=e.target.closest('[data-tool="jellyfinlibrary"]');if(libraryTile){e.preventDefault();lastToolFocus=libraryTile;openJellyfinLibrary('','all');return}const close=e.target.closest('[data-library-close]');if(close){e.preventDefault();closeJellyfinLibrary();return}if(e.target.closest('[data-library-series-back]')){e.preventDefault();openJellyfinLibrary('','tv');return}const filter=e.target.closest('[data-library-filter]');if(filter){e.preventDefault();openJellyfinLibrary(document.getElementById('library-search-input')?.value||librarySearch,filter.dataset.libraryFilter||'all');return}const item=e.target.closest('[data-library-index]');if(item){e.preventDefault();playLibraryItem(Number(item.dataset.libraryIndex));return}if(e.target.closest('#video-player-close')){e.preventDefault();stopVideoPortal(false,true);setTimeout(()=>document.querySelector('#library-browser .tv-focus')?.focus(),0);return}if(e.target.closest('#video-skip-back')){e.preventDefault();seekVideoTo(videoAbsoluteSeconds()-10);return}if(e.target.closest('#video-playpause')){e.preventDefault();videoPlayer.paused?videoPlayer.play():videoPlayer.pause();return}if(e.target.closest('#video-skip-forward')){e.preventDefault();seekVideoTo(videoAbsoluteSeconds()+10);return}if(e.target.closest('#video-mute')){e.preventDefault();videoPlayer.muted=!videoPlayer.muted;renderVideoControls();return}if(e.target.closest('#video-fit')){e.preventDefault();toggleVideoFit();return}if(e.target.closest('#video-fullscreen')){e.preventDefault();toggleVideoFullscreen();return}});
document.addEventListener('submit',e=>{if(e.target?.id==='library-series-search-form'){e.preventDefault();if(librarySeries)openJellyfinSeries(librarySeries,document.getElementById('library-series-search-input')?.value||'');return}if(e.target?.id==='library-search-form'){e.preventDefault();openJellyfinLibrary(document.getElementById('library-search-input')?.value||'',libraryFilter)}});
document.addEventListener('click',e=>{const hub=e.target.closest('[data-audio-hub]');if(hub){e.preventDefault();const mode=hub.dataset.audioHub;if(mode==='podcasts')openPodcastBrowser('');else if(mode==='audiobooks')openAudiobookBrowser('');else openMusicBrowser('','home');return}const pi=e.target.closest('[data-podcast-index]');if(pi){e.preventDefault();openPodcastFeed(podcastResults[Number(pi.dataset.podcastIndex)]);return}const ps=e.target.closest('[data-podcast-sub-index]');if(ps){e.preventDefault();openPodcastFeed(podcastSubscriptions[Number(ps.dataset.podcastSubIndex)]);return}const ep=e.target.closest('[data-podcast-episode]');if(ep&&podcastFeed){e.preventDefault();const q=(podcastFeed.episodes||[]).map(x=>({...x,feed_url:x.feed_url||podcastFeed.feed_url||'',author:podcastFeed.author||'',show:podcastFeed.title||'',art_url:x.art_url||podcastFeed.art_url||null})),i=Number(ep.dataset.podcastEpisode)||0;playPcgaAudio(q[i],'podcast',q,i);return}if(e.target.closest('[data-podcast-subscribe]')){e.preventDefault();podcastSubscribe();return}const ai=e.target.closest('[data-audiobook-index]');if(ai){e.preventDefault();openAudiobookDetail(audiobookResults[Number(ai.dataset.audiobookIndex)]);return}const ac=e.target.closest('[data-audiobook-col-index]');if(ac){e.preventDefault();openAudiobookDetail(audiobookCollection[Number(ac.dataset.audiobookColIndex)]);return}const ch=e.target.closest('[data-audiobook-chapter]');if(ch&&audiobookDetail){e.preventDefault();const q=(audiobookDetail.sections||[]).map(x=>({...x,author:audiobookDetail.author||'',book:audiobookDetail.title||'',art_url:audiobookDetail.art_url||null})),i=Number(ch.dataset.audiobookChapter)||0;playPcgaAudio(q[i],'audiobook',q,i);return}if(e.target.closest('[data-audiobook-collect]')){e.preventDefault();collectAudiobook();return}});
document.addEventListener('submit',e=>{if(e.target?.id==='podcast-search-form'){e.preventDefault();const q=document.getElementById('podcast-search-input')?.value?.trim()||'';if(/^https?:\/\//i.test(q)){openPodcastFeed({feed_url:q,title:'Podcast feed'});return}openPodcastBrowser(q);return}if(e.target?.id==='audiobook-search-form'){e.preventDefault();openAudiobookBrowser(document.getElementById('audiobook-search-input')?.value||'',document.getElementById('audiobook-search-field')?.value||'title');return}});
document.addEventListener('click',e=>{const close=e.target.closest('[data-music-close]');if(close){e.preventDefault();closeMusicBrowser();return}const track=e.target.closest('[data-music-item]');if(track){e.preventDefault();const id=track.dataset.musicItem;const i=musicQueue.findIndex(x=>x.id===id);const x=i>=0?musicQueue[i]:null;closeMusicBrowser();if(x)playPortalItem(x.id,0,x,i);return}const album=e.target.closest('[data-music-album]');if(album){e.preventDefault();openMusicBrowser('','album',album.dataset.musicAlbum||'',album.dataset.musicAlbumName||'Album');return}const artist=e.target.closest('[data-music-artist]');if(artist){e.preventDefault();openMusicBrowser(artist.dataset.musicArtist||'','home');return}const view=e.target.closest('[data-music-view]');if(view){e.preventDefault();musicParentId='';musicParentName='';openMusicBrowser('',view.dataset.musicView||'home');return}if(e.target.closest('[data-music-back]')){e.preventDefault();musicParentId='';musicParentName='';openMusicBrowser('','home');return}const tile=e.target.closest('[data-tool="musicplayer"]');if(tile){e.preventDefault();lastToolFocus=tile;openMusicBrowser('','home');return}const b=e.target.closest('[data-action]');if(b&&!b.disabled){e.preventDefault();sendMusic(b.dataset.action)}});document.addEventListener('submit',e=>{if(e.target?.id==='music-search-form'){e.preventDefault();musicParentId='';musicParentName='';openMusicBrowser(document.getElementById('music-search-input')?.value||'','home')}});
document.addEventListener('keydown',e=>{if(e.defaultPrevented)return;if(e.key!=='Escape'&&!(document.getElementById('store-auth-modal')?.classList.contains('show')&&(e.key==='BrowserBack'||(e.key==='Backspace'&&!pcgaTextEditingTarget(e.target)))))return;if(document.getElementById('store-auth-modal')?.classList.contains('show')){e.preventDefault();e.stopImmediatePropagation();closeStoreAuth();return}if(document.getElementById('store-maintain-modal')?.classList.contains('show')){e.preventDefault();e.stopImmediatePropagation();closeStoreMaintenance();return}if(document.getElementById('store-install-modal')?.classList.contains('show')){e.preventDefault();e.stopImmediatePropagation();closeStoreInstall();return}if(document.getElementById('store-jobs-modal')?.classList.contains('show')){e.preventDefault();e.stopImmediatePropagation();closeStoreJobs();return}if(document.getElementById('store-auth-modal')?.classList.contains('show')){e.preventDefault();closeStoreAuth();return}if(document.getElementById('pc-game-sessions-modal').classList.contains('show')){e.preventDefault();closePcGameSessions();return}if(document.getElementById('pc-game-stream').classList.contains('show')){e.preventDefault();closePcGameStream();return}if(document.getElementById('photo-viewer').classList.contains('show')){e.preventDefault();closePhotoViewer();return}if(document.getElementById('photo-browser').classList.contains('show')){e.preventDefault();closePhotos();return}if(document.getElementById('video-player-modal').classList.contains('show')){e.preventDefault();if(document.fullscreenElement){document.exitFullscreen?.();renderVideoControls();return}stopVideoPortal(false,true);return}if(document.getElementById('game-browser').classList.contains('show')){e.preventDefault();closeGameBrowser();return}if(document.getElementById('pc-game-browser').classList.contains('show')){e.preventDefault();closePcGameBrowser();return}if(document.getElementById('upload-browser').classList.contains('show')){e.preventDefault();closeUploadBrowser();return}if(document.getElementById('review-browser').classList.contains('show')){e.preventDefault();closeReviewBrowser();return}if(document.getElementById('library-browser').classList.contains('show')){e.preventDefault();closeJellyfinLibrary();return}});
const PCGA_NAV_SELECTOR='a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
let pcgaNavSelected=null;
function pcgaNavVisible(el){if(!el||el.disabled||el.getAttribute?.('aria-hidden')==='true')return false;const style=getComputedStyle(el);if(style.display==='none'||style.visibility==='hidden'||Number(style.opacity)===0)return false;const r=el.getBoundingClientRect();return r.width>0&&r.height>0&&el.getClientRects().length>0}
function pcgaNavigationScope(){const ids=['settings-modal','store-auth-modal','store-maintain-modal','store-install-modal','store-jobs-modal','global-search-modal','photo-viewer','video-player-modal','upload-browser','review-browser','game-browser','pc-game-sessions-modal','pc-game-stream','pc-game-browser','library-browser','photo-browser','music-browser'];let best=null,bestZ=-Infinity;for(const id of ids){const el=document.getElementById(id);if(!el?.classList.contains('show'))continue;const z=Number.parseInt(getComputedStyle(el).zIndex,10);const score=Number.isFinite(z)?z:0;if(score>=bestZ){best=el;bestZ=score}}const home=document.getElementById('home-media-surface');return best||(home?.classList.contains('show')||homeMediaOpen()?home:document.body)}
function pcgaNavElements(scope=pcgaNavigationScope()){return[...scope.querySelectorAll(PCGA_NAV_SELECTOR)].filter(pcgaNavVisible)}
function pcgaSetSelection(el,{focus=false,scroll=false}={}){if(!pcgaNavVisible(el))return false;if(pcgaNavSelected&&pcgaNavSelected!==el)pcgaNavSelected.classList.remove('pcga-nav-selected');pcgaNavSelected=el;el.classList.add('pcga-nav-selected');if(focus&&document.activeElement!==el){try{el.focus({preventScroll:true})}catch(_){el.focus()}}if(scroll)el.scrollIntoView({behavior:'smooth',block:'nearest',inline:'nearest'});const r=el.getBoundingClientRect();setParallaxFromPoint(r.left+r.width/2,r.top+r.height/2);if(el.dataset?.group==='tools'||el.closest?.('[data-tool]'))lastToolFocus=el.closest?.('[data-tool]')||el;return true}
function pcgaLauncherBottomRow(el){const launcher=document.getElementById('launcher');if(!el||!launcher?.contains(el))return false;const a=el.getBoundingClientRect(),ay=a.top+a.height/2;return ![...launcher.querySelectorAll(PCGA_NAV_SELECTOR)].filter(x=>x!==el&&pcgaNavVisible(x)).some(x=>{const r=x.getBoundingClientRect();return r.top+r.height/2>ay+4})}
function pcgaTextEditingTarget(el){if(!el)return false;const tag=String(el.tagName||'').toUpperCase(),type=String(el.type||'').toLowerCase();if(el.isContentEditable)return true;if(tag==='TEXTAREA')return true;if(tag!=='INPUT')return false;return['text','search','email','password','number','tel','url'].includes(type||'text')}
function pcgaEditableArrow(el,key){if(!el)return false;const tag=el.tagName,type=String(el.type||'').toLowerCase();if(pcgaTextEditingTarget(el))return true;if(tag==='SELECT')return key==='ArrowUp'||key==='ArrowDown';if(type==='range')return key==='ArrowLeft'||key==='ArrowRight';return false}
function pcgaDirectionalCandidate(current,key){const scope=pcgaNavigationScope(),els=pcgaNavElements(scope).filter(el=>el!==current);if(!els.length)return null;const a=current?.getBoundingClientRect?.();if(!a)return els[0]||null;const ax=a.left+a.width/2,ay=a.top+a.height/2;let best=null,bestScore=Infinity;for(const el of els){const b=el.getBoundingClientRect(),bx=b.left+b.width/2,by=b.top+b.height/2,dx=bx-ax,dy=by-ay;let primary,cross;if(key==='ArrowRight'){if(dx<=4)continue;primary=dx;cross=Math.abs(dy)}else if(key==='ArrowLeft'){if(dx>=-4)continue;primary=-dx;cross=Math.abs(dy)}else if(key==='ArrowDown'){if(dy<=4)continue;primary=dy;cross=Math.abs(dx)}else{if(dy>=-4)continue;primary=-dy;cross=Math.abs(dx)}const aligned=key==='ArrowLeft'||key==='ArrowRight'?Math.max(0,Math.max(a.top,b.top)-Math.min(a.bottom,b.bottom)):Math.max(0,Math.max(a.left,b.left)-Math.min(a.right,b.right));const score=primary+cross*2.25+aligned*3;if(score<bestScore){bestScore=score;best=el}}return best}
function pcgaMoveSelection(key){const scope=pcgaNavigationScope();let current=document.activeElement;if(!pcgaNavVisible(current)||!scope.contains(current)){current=pcgaNavSelected&&scope.contains(pcgaNavSelected)&&pcgaNavVisible(pcgaNavSelected)?pcgaNavSelected:pcgaNavElements(scope)[0]}if(!current)return false;const next=pcgaDirectionalCandidate(current,key);return next?pcgaSetSelection(next,{focus:true,scroll:true}):false}
function pcgaTrapModalTab(e){if(e.key!=='Tab'||e.defaultPrevented)return;const scope=pcgaNavigationScope();if(!scope||scope===document.body)return;const els=pcgaNavElements(scope);if(!els.length)return;const current=document.activeElement,idx=els.indexOf(current);if(idx<0){e.preventDefault();pcgaSetSelection(e.shiftKey?els[els.length-1]:els[0],{focus:true,scroll:true});return}if(!e.shiftKey&&idx===els.length-1){e.preventDefault();pcgaSetSelection(els[0],{focus:true,scroll:true})}else if(e.shiftKey&&idx===0){e.preventDefault();pcgaSetSelection(els[els.length-1],{focus:true,scroll:true})}}
document.addEventListener('keydown',pcgaTrapModalTab);
document.addEventListener('focusin',e=>{const el=e.target?.closest?.(PCGA_NAV_SELECTOR);if(el)pcgaSetSelection(el);});
document.addEventListener('pointerover',e=>{if(e.pointerType&&e.pointerType!=='mouse'&&e.pointerType!=='pen')return;const scope=pcgaNavigationScope(),el=e.target?.closest?.(PCGA_NAV_SELECTOR),active=document.activeElement;if(pcgaTextEditingTarget(active)&&active!==el)return;if(el&&scope.contains(el)&&pcgaNavVisible(el))pcgaSetSelection(el,{focus:!pcgaTextEditingTarget(el),scroll:false})});document.addEventListener('pointerdown',e=>{const el=e.target?.closest?.('input,textarea,[contenteditable="true"]');if(pcgaTextEditingTarget(el)){try{el.focus({preventScroll:true})}catch(_){el.focus()}pcgaSetSelection(el,{focus:false,scroll:false})}},true);document.addEventListener('pointermove',e=>{if(e.pointerType&&e.pointerType!=='mouse'&&e.pointerType!=='pen')return;setParallaxFromPoint(e.clientX,e.clientY)},{passive:true});window.addEventListener('blur',resetParallax);document.addEventListener('mouseleave',resetParallax);
document.addEventListener('keydown',e=>{if(e.defaultPrevented)return;if(e.key==='Escape'&&document.getElementById('music-browser').classList.contains('show')){e.preventDefault();closeMusicBrowser();return}if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;const active=document.activeElement;if(pcgaEditableArrow(active,e.key))return;const scope=pcgaNavigationScope();if(homeMediaOpen()&&scope===document.getElementById('home-media-surface')&&e.key==='ArrowUp'){const current=pcgaNavVisible(active)&&scope.contains(active)?active:null;if(!current||!pcgaDirectionalCandidate(current,'ArrowUp')){e.preventDefault();closeHomeMediaSurface(true);return}}if(!homeMediaOpen()&&portalSettings.homeMediaEnabled&&scope===document.body&&e.key==='ArrowDown'){const current=pcgaNavVisible(active)&&scope.contains(active)?active:null;if(current&&pcgaLauncherBottomRow(current)){e.preventDefault();openHomeMediaSurface();return}}if(pcgaMoveSelection(e.key))e.preventDefault()});
videoPlayer.addEventListener('play',()=>{renderVideoControls();if(videoPortalPlayer.active){if(videoPortalPlayer.play_session_id&&!videoPortalPlayer.started){videoPortalPlayer.started=true;reportVideoPortal('start')}else reportVideoPortal('progress')}});videoPlayer.addEventListener('pause',()=>{renderVideoControls();if(videoPortalPlayer.active)reportVideoPortal('progress')});videoPlayer.addEventListener('timeupdate',renderVideoControls);videoPlayer.addEventListener('loadedmetadata',()=>{videoPlayer.playbackRate=Math.max(.25,Math.min(4,Number(videoPrefs.speed)||1));renderVideoControls()});videoPlayer.addEventListener('ratechange',()=>{if(Math.abs(videoPlayer.playbackRate-(Number(videoPrefs.speed)||1))>.001){videoPrefs.speed=videoPlayer.playbackRate;saveVideoPrefs()}renderVideoControls()});videoPlayer.addEventListener('volumechange',()=>{renderVideoControls();if(videoPortalPlayer.active)reportVideoPortal('progress')});videoPlayer.addEventListener('seeked',()=>{renderVideoControls();if(videoPortalPlayer.active)reportVideoPortal('progress')});videoPlayer.addEventListener('ended',()=>{if(videoPortalPlayer.active)stopVideoPortal(false,true)});videoPlayer.addEventListener('error',()=>{if(videoPortalPlayer.active&&!videoReconfigureBusy){showStatus('Video playback error','The portal could not continue this Jellyfin video stream.','warn',9000);reportVideoPortal('stopped')}});if(videoSeek){videoSeek.addEventListener('pointerdown',()=>{videoSeekDragging=true});videoSeek.addEventListener('input',()=>{videoSeekDragging=true;if(videoTimeCurrent)videoTimeCurrent.textContent=fmt(Number(videoSeek.value)||0)});videoSeek.addEventListener('change',()=>{const target=Math.max(0,Number(videoSeek.value)||0);videoSeekDragging=false;seekVideoTo(target)});videoSeek.addEventListener('blur',()=>{videoSeekDragging=false;renderVideoControls()})}if(videoVolume){videoVolume.addEventListener('input',()=>{videoPlayer.volume=Math.max(0,Math.min(1,(Number(videoVolume.value)||0)/100))})}if(videoQuality){videoQuality.addEventListener('change',()=>{const quality=videoQuality.value||'auto';videoPrefs.quality=quality;saveVideoPrefs();restartVideoWithSettings({quality})})}if(videoAudioTrack){videoAudioTrack.addEventListener('change',()=>restartVideoWithSettings({audio_stream_index:Number(videoAudioTrack.value)}))}if(videoSubtitleTrack){videoSubtitleTrack.addEventListener('change',()=>restartVideoWithSettings({subtitle_stream_index:Number(videoSubtitleTrack.value)}))}if(videoSpeed){videoSpeed.addEventListener('change',()=>{const speed=Math.max(.25,Math.min(4,Number(videoSpeed.value)||1));videoPrefs.speed=speed;saveVideoPrefs();videoPlayer.playbackRate=speed;renderVideoControls()})}document.addEventListener('fullscreenchange',renderVideoControls);videoPlayer.addEventListener('dblclick',()=>toggleVideoFullscreen());document.addEventListener('keydown',e=>{if(!document.getElementById('video-player-modal').classList.contains('show'))return;if(pcgaTextEditingTarget(document.activeElement)||document.activeElement?.tagName==='SELECT')return;const key=String(e.key||'').toLowerCase();if(key===' '||key==='k'){e.preventDefault();videoPlayer.paused?videoPlayer.play():videoPlayer.pause()}else if(key==='f'){e.preventDefault();toggleVideoFullscreen()}else if(key==='m'){e.preventDefault();videoPlayer.muted=!videoPlayer.muted;renderVideoControls()}else if((key==='arrowleft'||key==='arrowright')&&(document.activeElement===document.body||document.activeElement===videoPlayer)){e.preventDefault();seekVideoTo(videoAbsoluteSeconds()+(key==='arrowleft'?-10:10))}});setInterval(()=>{if(videoPortalPlayer.active&&!videoPlayer.paused)reportVideoPortal('progress')},10000);window.addEventListener('beforeunload',()=>{if(videoPortalPlayer.active&&videoPortalPlayer.play_session_id){navigator.sendBeacon('/api/jellyfin/playback/event',new Blob([JSON.stringify(videoPlaybackPayload('stopped'))],{type:'application/json'}))}});
audio.addEventListener('play',()=>{if(portalPlayer.active){if(portalPlayer.play_session_id&&!portalPlayer.started){portalPlayer.started=true;reportPortal('start')}else reportPortal('progress')}if(pcgaAudioPlayer.active)savePcgaAudioProgress();if(portalPlayer.active||pcgaAudioPlayer.active)renderMusic(externalMusicSession)});audio.addEventListener('pause',()=>{if(portalPlayer.active)reportPortal('progress');if(pcgaAudioPlayer.active)savePcgaAudioProgress(true);if(portalPlayer.active||pcgaAudioPlayer.active)renderMusic(externalMusicSession)});audio.addEventListener('timeupdate',()=>{if(portalPlayer.active||pcgaAudioPlayer.active)renderMusic(externalMusicSession);if(pcgaAudioPlayer.active)savePcgaAudioProgress()});audio.addEventListener('volumechange',()=>{if(portalPlayer.active)reportPortal('progress');if(portalPlayer.active||pcgaAudioPlayer.active)renderMusic(externalMusicSession)});audio.addEventListener('seeked',()=>{if(portalPlayer.active)reportPortal('progress');if(pcgaAudioPlayer.active)savePcgaAudioProgress(true)});audio.addEventListener('ended',()=>{if(pcgaAudioPlayer.active){savePcgaAudioProgress(true);if((pcgaAudioPlayer.queue||[]).length>1)pcgaAudioMove(1);else stopPcgaAudio();return}if(!portalPlayer.active)return;if(musicQueue.length>1)queueMove(1);else stopPortalPlayback()});audio.addEventListener('error',()=>{if(portalPlayer.active||pcgaAudioPlayer.active)showStatus('Audio playback error','The portal could not continue this audio stream.','warn',9000)});setInterval(()=>{if(portalPlayer.active&&!audio.paused)reportPortal('progress');if(pcgaAudioPlayer.active&&!audio.paused)savePcgaAudioProgress()},10000);window.addEventListener('beforeunload',()=>{if(pcgaAudioPlayer.active)savePcgaAudioProgress(true);if(portalPlayer.active&&portalPlayer.play_session_id){navigator.sendBeacon('/api/jellyfin/music/event',new Blob([JSON.stringify(playbackPayload('stopped'))],{type:'application/json'}))}});updateSecureContextBanner();refreshStatus();refreshMusic();if(location.hash==='#games')setTimeout(()=>openGameBrowser('',''),120);if(location.hash==='#pc-games')setTimeout(()=>openPcGameBrowser(''),120);if(location.hash==='#review')setTimeout(()=>openReviewBrowser(),120);if(location.hash==='#audio'||location.hash==='#music')setTimeout(()=>openMusicBrowser('','home'),120);setInterval(refreshStatus,4000);setInterval(refreshMusic,2000);
</script>
</body>
</html>
'''


class Handler(BaseHTTPRequestHandler):
    server_version = f"PCGAStatus/{VERSION}"

    def log_message(self, fmt: str, *args) -> None:
        # Keep Docker logs useful without logging every 3-second browser poll.
        if urlparse(self.path).path not in {"/api/status", "/health", "/api/jellyfin/now-playing", "/api/jellyfin/music/library", "/api/jellyfin/library", "/api/jellyfin/home-media", "/api/jellyfin/background/library", "/api/photos/library", "/api/games/collection/jobs", "/api/review/items", "/api/diagnostics/catalog", "/api/diagnostics/logs"}:
            super().log_message(fmt, *args)

    def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Permissions-Policy", "gamepad=*, fullscreen=*, autoplay=*")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; media-src 'self'; img-src 'self' data:; frame-src http: https:")
        self.end_headers()
        self.wfile.write(body)

    def send_player(self, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self' blob: data:; script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; worker-src 'self' blob:; connect-src 'self' blob:; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline';")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_local_file(self, path: Path, content_type: str = "application/octet-stream", filename: str | None = None, head_only: bool = False, cache_control: str = "private, max-age=0, must-revalidate") -> None:
        try:
            size = path.stat().st_size
        except OSError:
            self.send_bytes(HTTPStatus.NOT_FOUND, b"file unavailable\n", "text/plain; charset=utf-8")
            return
        start, end = 0, max(0, size - 1)
        status = HTTPStatus.OK
        range_header = self.headers.get("Range", "").strip()
        if range_header:
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
            if not m or (not m.group(1) and not m.group(2)):
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            if m.group(1):
                start = int(m.group(1)); end = int(m.group(2)) if m.group(2) else end
            else:
                suffix = int(m.group(2)); start = max(0, size - suffix); end = max(0, size - 1)
            if start >= size or start < 0 or end < start:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            end = min(end, size - 1); status = HTTPStatus.PARTIAL_CONTENT
        length = 0 if size == 0 else end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if filename:
            safe = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
            self.send_header("Content-Disposition", f'attachment; filename="{safe}"')
        self.end_headers()
        if head_only or self.command == "HEAD" or length <= 0:
            return
        remaining = length
        try:
            with path.open("rb") as fh:
                fh.seek(start)
                while remaining > 0:
                    chunk = fh.read(min(1024 * 1024, remaining))
                    if not chunk: break
                    self.wfile.write(chunk); remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def proxy_romm_stream(self, upstream_path: str, head_only: bool = False, cache_control: str = "private, max-age=0, must-revalidate", public: bool = False) -> None:
        try:
            headers = {"Accept": "*/*"} if public else romm_headers()
        except Exception as exc:
            self.send_bytes(HTTPStatus.SERVICE_UNAVAILABLE, f"RomM authentication unavailable: {type(exc).__name__}\n".encode(), "text/plain; charset=utf-8")
            return
        for name in ("Range", "If-None-Match", "If-Modified-Since"):
            if self.headers.get(name):
                headers[name] = self.headers[name]
        method = "HEAD" if head_only else "GET"
        req = urllib.request.Request(f"http://{TOOL_HOST}:{ROMM_PORT}{upstream_path}", headers=headers, method=method)
        try:
            response = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as exc:
            response = exc
        except Exception as exc:
            self.send_bytes(HTTPStatus.BAD_GATEWAY, f"RomM proxy unavailable: {type(exc).__name__}\n".encode(), "text/plain; charset=utf-8")
            return
        try:
            self.send_response(response.status)
            for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "ETag", "Last-Modified", "Content-Disposition"):
                value = response.headers.get(name)
                if value:
                    self.send_header(name, value)
            self.send_header("Cache-Control", cache_control)
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head_only and response.status not in {204, 304}:
                try:
                    shutil.copyfileobj(response, self.wfile, length=256 * 1024)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        finally:
            try:
                response.close()
            except Exception:
                pass

    def send_photo_path(self, photo: Path) -> None:
        try:
            st = photo.stat()
            content_type = mimetypes.guess_type(photo.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(st.st_size))
            self.send_header("Cache-Control", "private, max-age=3600")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.end_headers()
            with photo.open("rb") as fh:
                try:
                    shutil.copyfileobj(fh, self.wfile, length=256 * 1024)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        except OSError:
            self.send_bytes(HTTPStatus.NOT_FOUND, b"photo not found\n", "text/plain; charset=utf-8")

    def proxy_review_preview(self) -> None:
        token = review_token()
        if not token:
            self.send_bytes(HTTPStatus.SERVICE_UNAVAILABLE, b'review token unavailable\n', 'text/plain; charset=utf-8')
            return
        parsed=urlparse(self.path)
        target=REVIEW_UPSTREAM + '/api/preview' + (('?' + parsed.query) if parsed.query else '')
        req=urllib.request.Request(target,headers={'X-PCGA-Review-Token':token,'Accept':'image/*,video/*,audio/*,*/*;q=0.5','User-Agent':f'PCGameArchive/{VERSION}'},method='GET')
        try:
            upstream=urllib.request.urlopen(req,timeout=45)
        except urllib.error.HTTPError as exc:
            upstream=exc
        except Exception as exc:
            self.send_bytes(HTTPStatus.BAD_GATEWAY,f'review preview upstream error: {type(exc).__name__}\n'.encode(),'text/plain; charset=utf-8')
            return
        try:
            self.send_response(upstream.status)
            for name in ('Content-Type','Content-Length','Content-Range','Accept-Ranges'):
                value=upstream.headers.get(name)
                if value: self.send_header(name,value)
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.end_headers()
            try:
                shutil.copyfileobj(upstream,self.wfile,length=128*1024)
            except (BrokenPipeError,ConnectionResetError):
                pass
        finally:
            try: upstream.close()
            except Exception: pass

    def proxy_review(self) -> None:
        suffix = self.path[len("/review"):]
        if not suffix:
            suffix = "/"
        target = REVIEW_UPSTREAM + suffix
        data = None
        if self.command in {"POST", "PUT", "PATCH"}:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length < 0 or length > 256 * 1024:
                self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid request size\n", "text/plain; charset=utf-8")
                return
            data = self.rfile.read(length) if length else b""
        headers = {}
        for name in ("Content-Type", "Cookie", "User-Agent"):
            value = self.headers.get(name)
            if value:
                headers[name] = value
        req = urllib.request.Request(target, data=data, headers=headers, method=self.command)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        try:
            response = opener.open(req, timeout=10)
            status = response.status
            upstream_headers = response.headers
            body = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            upstream_headers = exc.headers
            body = exc.read()
        except Exception as exc:
            message = (
                '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<style>body{background:#1a110b;color:#fff4e6;font:15px system-ui;padding:24px}'
                'code{color:#e8a15e}</style>'
                '<h2>Manual review service unavailable</h2>'
                f'<p>The portal could not reach <code>{html.escape(REVIEW_UPSTREAM)}</code>.</p>'
                '<p>On the server, check <code>sudo game-archive manual-review-status</code>.</p>'
                f'<p>{html.escape(type(exc).__name__)}</p>'
            ).encode()
            self.send_response(HTTPStatus.BAD_GATEWAY)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.end_headers()
            self.wfile.write(message)
            return

        content_type = upstream_headers.get("Content-Type", "application/octet-stream")
        if "text/html" in content_type.lower():
            text = body.decode("utf-8", "replace")
            text = text.replace('action=/login', 'action=/review/login')
            text = text.replace('action="/promote"', 'action="/review/promote"')
            text = text.replace('action="/quarantine"', 'action="/review/quarantine"')
            tv_style = r"""<style id=pcga-tv>
body{font-size:clamp(18px,1.5vw,26px)!important;padding-bottom:70px!important}header,main{max-width:1500px!important}.card,.empty{padding:28px!important}input{font-size:1em!important;min-height:58px!important}button{font-size:1em!important;min-height:62px!important;padding:14px 22px!important}label{gap:9px!important}.type-row label{min-height:58px;padding:8px 14px}
</style><a class=pcga-home href="/">← Portal Home</a>"""
            if "</head>" in text:
                text = text.replace("</head>", tv_style + "</head>", 1)
            else:
                text = tv_style + text
            body = text.encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; media-src 'self'; form-action 'self'; frame-ancestors 'self'")
        location = upstream_headers.get("Location")
        if location:
            if location.startswith("/"):
                location = "/review" + location
            self.send_header("Location", location)
        for cookie in upstream_headers.get_all("Set-Cookie", []):
            if "Path=/;" in cookie:
                cookie = cookie.replace("Path=/;", "Path=/review/;", 1)
            elif "Path=/" in cookie and "Path=/review/" not in cookie:
                cookie = cookie.replace("Path=/", "Path=/review/", 1)
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def proxy_jellyfin_audio(self, item_id: str, head_only: bool = False) -> None:
        if not valid_jellyfin_id(item_id):
            self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid item id\n", "text/plain; charset=utf-8")
            return
        query = parse_qs(urlparse(self.path).query)
        play_session_id = str((query.get("play_session_id") or [""])[0])
        media_source_id = str((query.get("media_source_id") or [""])[0])
        if len(play_session_id) > 200:
            self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid play session\n", "text/plain; charset=utf-8")
            return
        params = {
            "static": "true",
            "deviceId": JELLYFIN_DEVICE_ID,
        }
        if play_session_id:
            params["playSessionId"] = play_session_id
        if media_source_id:
            params["mediaSourceId"] = media_source_id
        headers = jellyfin_headers()
        headers["Accept-Encoding"] = "identity"
        if self.headers.get("Range"):
            headers["Range"] = self.headers.get("Range")
        req = urllib.request.Request(
            f"http://{TOOL_HOST}:{JELLYFIN_PORT}/Audio/{quote(item_id, safe='')}/stream?{urlencode(params)}",
            headers=headers,
            method="HEAD" if head_only else "GET",
        )
        try:
            upstream = urllib.request.urlopen(req, timeout=15)
        except urllib.error.HTTPError as exc:
            upstream = exc
        except Exception as exc:
            self.send_bytes(HTTPStatus.BAD_GATEWAY, f"audio upstream error: {type(exc).__name__}\n".encode(), "text/plain; charset=utf-8")
            return
        try:
            self.send_response(upstream.status)
            for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "ETag", "Last-Modified"):
                value = upstream.headers.get(name)
                if value:
                    self.send_header(name, value)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head_only:
                try:
                    shutil.copyfileobj(upstream, self.wfile, length=256 * 1024)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        finally:
            try:
                upstream.close()
            except Exception:
                pass

    def proxy_jellyfin_video(self, item_id: str, head_only: bool = False) -> None:
        """Proxy a browser-compatible Jellyfin MP4 stream for portal video playback.

        Jellyfin is asked for H.264/AAC in an MP4 container with stream-copy
        permitted. Compatible sources can therefore be remuxed cheaply while
        HEVC/AV1/unsupported containers are transcoded for the browser.
        """
        if not valid_jellyfin_id(item_id):
            self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid item id\n", "text/plain; charset=utf-8")
            return
        query = parse_qs(urlparse(self.path).query)
        media_source_id = str((query.get("media_source_id") or [""])[0])
        play_session_id = str((query.get("play_session_id") or [""])[0])
        try:
            start_ticks = max(0, int((query.get("start_ticks") or ["0"])[0] or 0))
        except (TypeError, ValueError):
            start_ticks = 0
        quality = str((query.get("quality") or ["auto"])[0] or "auto").strip().lower()
        quality, _ = jellyfin_video_quality(quality)
        audio_stream_index = _stream_index((query.get("audio_stream_index") or [None])[0])
        subtitle_stream_index = _stream_index((query.get("subtitle_stream_index") or [None])[0])
        if media_source_id and not valid_jellyfin_id(media_source_id):
            self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid media source id\n", "text/plain; charset=utf-8")
            return
        if len(play_session_id) > 200:
            self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid play session\n", "text/plain; charset=utf-8")
            return
        params = jellyfin_video_stream_params(
            media_source_id=media_source_id,
            play_session_id=play_session_id,
            start_ticks=start_ticks,
            quality=quality,
            audio_stream_index=audio_stream_index,
            subtitle_stream_index=subtitle_stream_index,
        )
        headers = jellyfin_headers()
        headers["Accept-Encoding"] = "identity"
        # Do not forward browser byte ranges to a freshly generated transcode.
        # Jellyfin emits a fragmented/progressive MP4 that can be consumed as a
        # normal streaming response and stopped when the browser disconnects.
        req = urllib.request.Request(
            f"http://{TOOL_HOST}:{JELLYFIN_PORT}/Videos/{quote(item_id, safe='')}/stream.mp4?{urlencode(params)}",
            headers=headers,
            method="HEAD" if head_only else "GET",
        )
        stream_mode = "h264-aac-mp4"
        try:
            upstream = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as exc:
            # If subtitles are selected we cannot silently fall back to a raw
            # direct stream because the browser would lose the chosen subtitle
            # track. Keep the Jellyfin transcode error visible instead.
            if subtitle_stream_index is not None and subtitle_stream_index >= 0:
                upstream = exc
                stream_mode = "subtitle-transcode-failed"
            else:
                # If transcoding/remuxing is disabled by Jellyfin policy, retain a
                # last-chance direct path for files the browser can already decode.
                try:
                    exc.close()
                except Exception:
                    pass
                direct_params = {"static": "true", "deviceId": JELLYFIN_DEVICE_ID}
                if media_source_id:
                    direct_params["mediaSourceId"] = media_source_id
                if play_session_id:
                    direct_params["playSessionId"] = play_session_id
                if audio_stream_index is not None and audio_stream_index >= 0:
                    direct_params["audioStreamIndex"] = str(audio_stream_index)
                direct_headers = jellyfin_headers()
                direct_headers["Accept-Encoding"] = "identity"
                if self.headers.get("Range"):
                    direct_headers["Range"] = self.headers.get("Range")
                direct_req = urllib.request.Request(
                    f"http://{TOOL_HOST}:{JELLYFIN_PORT}/Videos/{quote(item_id, safe='')}/stream?{urlencode(direct_params)}",
                    headers=direct_headers,
                    method="HEAD" if head_only else "GET",
                )
                try:
                    upstream = urllib.request.urlopen(direct_req, timeout=20)
                    stream_mode = "direct-fallback"
                except urllib.error.HTTPError as direct_exc:
                    upstream = direct_exc
                    stream_mode = "failed"
                except Exception as direct_exc:
                    self.send_bytes(HTTPStatus.BAD_GATEWAY, f"video upstream error: {type(direct_exc).__name__}\n".encode(), "text/plain; charset=utf-8")
                    return
        except Exception as exc:
            self.send_bytes(HTTPStatus.BAD_GATEWAY, f"video upstream error: {type(exc).__name__}\n".encode(), "text/plain; charset=utf-8")
            return
        try:
            self.send_response(upstream.status)
            for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "ETag", "Last-Modified"):
                value = upstream.headers.get(name)
                if value:
                    self.send_header(name, value)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-PCGA-Video-Stream", stream_mode)
            self.end_headers()
            if not head_only:
                try:
                    shutil.copyfileobj(upstream, self.wfile, length=512 * 1024)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        finally:
            try:
                upstream.close()
            except Exception:
                pass

    def proxy_diagnostics(self) -> None:
        if not isinstance(self.connection, ssl.SSLSocket):
            self.send_bytes(HTTPStatus.UPGRADE_REQUIRED, b'{"ok":false,"error":"secure-context-required","detail":"Open the HTTPS PCGA portal to view appliance logs."}\n', "application/json; charset=utf-8")
            return
        parsed = urlparse(self.path)
        suffix = parsed.path[len("/api/diagnostics"):] or "/catalog"
        if suffix == "/catalog":
            target = CONTROL_UPSTREAM + "/logs/catalog"
        elif suffix == "/logs":
            target = CONTROL_UPSTREAM + "/logs" + (("?" + parsed.query) if parsed.query else "")
        else:
            self.send_bytes(HTTPStatus.NOT_FOUND, b'{"ok":false,"error":"not-found"}\n', "application/json; charset=utf-8")
            return
        try:
            token = CONTROL_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            self.send_bytes(HTTPStatus.SERVICE_UNAVAILABLE, b'{"ok":false,"error":"control-token-unavailable"}\n', "application/json; charset=utf-8")
            return
        req = urllib.request.Request(target, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, method="GET")
        try:
            response = urllib.request.urlopen(req, timeout=25)
            status, upstream_headers, body = response.status, response.headers, response.read()
        except urllib.error.HTTPError as exc:
            status, upstream_headers, body = exc.code, exc.headers, exc.read()
        except Exception as exc:
            detail = f"{type(exc).__name__}: {str(exc)[:240]}"
            body = json.dumps({"ok": False, "error": "diagnostics-unavailable", "detail": detail, "upstream": CONTROL_UPSTREAM}).encode()
            self.send_bytes(HTTPStatus.BAD_GATEWAY, body, "application/json; charset=utf-8")
            return
        self.send_response(status)
        self.send_header("Content-Type", upstream_headers.get("Content-Type", "application/json; charset=utf-8"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _audio_remote_target(self) -> str:
        query = parse_qs(urlparse(self.path).query)
        encoded = str((query.get("u") or [""])[0])[:8192]
        supplied = str((query.get("sig") or [""])[0])[:128]
        if not encoded or not supplied:
            raise ValueError("missing signed audio target")
        try:
            token = CONTROL_TOKEN_FILE.read_text(encoding="utf-8").strip().encode()
        except OSError as exc:
            raise RuntimeError("control token unavailable") from exc
        expected = hmac.new(token, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            raise PermissionError("invalid audio media signature")
        try:
            padding = "=" * ((4 - len(encoded) % 4) % 4)
            url = base64.urlsafe_b64decode((encoded + padding).encode()).decode("utf-8")
        except Exception as exc:
            raise ValueError("invalid audio target encoding") from exc
        return self._validate_public_audio_url(url)

    @staticmethod
    def _validate_public_audio_url(url: str) -> str:
        url = str(url or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("invalid public audio URL")
        if parsed.port not in {None, 80, 443}:
            raise ValueError("unsupported public audio port")
        host = parsed.hostname.rstrip(".").lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise ValueError("local-network audio URLs are blocked")
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("audio host could not be resolved") from exc
        for info in infos:
            addr = ipaddress.ip_address(info[4][0].split("%", 1)[0])
            if not addr.is_global:
                raise ValueError("private or reserved audio target blocked")
        return url

    def proxy_audio_remote(self, head_only: bool = False) -> None:
        try:
            target = self._audio_remote_target()
        except PermissionError as exc:
            self.send_bytes(HTTPStatus.FORBIDDEN, (str(exc) + "\n").encode(), "text/plain; charset=utf-8"); return
        except (ValueError, RuntimeError) as exc:
            self.send_bytes(HTTPStatus.BAD_REQUEST, (str(exc) + "\n").encode(), "text/plain; charset=utf-8"); return
        handler_self = self
        class SafeRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                handler_self._validate_public_audio_url(newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)
        headers = {"User-Agent": f"PCGameArchive/{VERSION}", "Accept": self.headers.get("Accept", "audio/*,image/*,*/*")}
        for name in ("Range", "If-None-Match", "If-Modified-Since"):
            if self.headers.get(name): headers[name] = self.headers[name]
        req = urllib.request.Request(target, headers=headers, method="HEAD" if head_only else "GET")
        try:
            response = urllib.request.build_opener(SafeRedirect()).open(req, timeout=45)
        except urllib.error.HTTPError as exc:
            response = exc
        except Exception as exc:
            self.send_bytes(HTTPStatus.BAD_GATEWAY, f"Audio provider unavailable: {type(exc).__name__}\n".encode(), "text/plain; charset=utf-8"); return
        try:
            self.send_response(response.status)
            for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "ETag", "Last-Modified"):
                value = response.headers.get(name)
                if value: self.send_header(name, value)
            self.send_header("Cache-Control", "private, max-age=300")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head_only and response.status not in {204, 304}:
                try: shutil.copyfileobj(response, self.wfile, length=256 * 1024)
                except (BrokenPipeError, ConnectionResetError): pass
        finally:
            try: response.close()
            except Exception: pass

    def serve_audio_local(self, head_only: bool = False) -> None:
        query = parse_qs(urlparse(self.path).query)
        rel = unquote(str((query.get("path") or [""])[0]))
        if not rel or "\x00" in rel:
            self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid audio path\n", "text/plain; charset=utf-8"); return
        base = (LIBRARY / "audio").resolve()
        target = (LIBRARY / rel).resolve()
        if target == base or base not in target.parents or not target.is_file():
            self.send_bytes(HTTPStatus.NOT_FOUND, b"audio file unavailable\n", "text/plain; charset=utf-8"); return
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_local_file(target, ctype, head_only=head_only, cache_control="private, max-age=3600")

    def _gpodder_session_token(self, username: str) -> str:
        try:
            secret = CONTROL_TOKEN_FILE.read_text(encoding="utf-8").strip().encode()
        except OSError:
            return ""
        return hmac.new(secret, ("gpodder:" + username).encode(), hashlib.sha256).hexdigest()

    def _gpodder_auth(self, username: str) -> bool:
        creds = romm_credentials()
        if not creds or username != creds[0]:
            return False
        supplied = self.headers.get("Authorization", "")
        if supplied.startswith("Basic "):
            try:
                raw = base64.b64decode(supplied[6:].strip(), validate=True).decode("utf-8")
                user, password = raw.split(":", 1)
                if hmac.compare_digest(user, creds[0]) and hmac.compare_digest(password, creds[1]):
                    return True
            except Exception:
                pass
        expected = self._gpodder_session_token(username)
        if expected:
            for part in self.headers.get("Cookie", "").split(";"):
                key, sep, value = part.strip().partition("=")
                if sep and key == "sessionid" and hmac.compare_digest(value, expected):
                    return True
        return False

    def _gpodder_unauthorized(self) -> None:
        body=b'{"detail":"AntennaPod sync authentication required"}\n'
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("WWW-Authenticate", 'Basic realm="PCGA AntennaPod Sync"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)

    def proxy_gpodder(self) -> None:
        """Minimal gPodder API used by AntennaPod synchronization."""
        parsed=urlparse(self.path); path=parsed.path
        if path == "/clientconfig.json":
            self.send_bytes(HTTPStatus.OK, b'{}\n', "application/json; charset=utf-8"); return
        m=re.fullmatch(r"/api/2/auth/([^/]+)/(login|logout)\.json", path)
        if m:
            username=unquote(m.group(1)); action=m.group(2)
            if not self._gpodder_auth(username): self._gpodder_unauthorized(); return
            body=b""
            self.send_response(HTTPStatus.OK)
            if action == "login":
                token=self._gpodder_session_token(username)
                self.send_header("Set-Cookie", f"sessionid={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000")
            else:
                self.send_header("Set-Cookie", "sessionid=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
            self.send_header("Content-Length", "0"); self.send_header("Cache-Control", "no-store"); self.end_headers(); return
        username=""; target=""; post_kind=""
        m=re.fullmatch(r"/api/2/devices/([^/]+)\.json", path)
        if m and self.command == "GET":
            username=unquote(m.group(1)); target=CONTROL_UPSTREAM+"/audio/gpodder/devices"
        mdev=re.fullmatch(r"/api/2/devices/([^/]+)/([^/]+)\.json", path)
        if mdev and self.command == "POST":
            username=unquote(mdev.group(1)); device=unquote(mdev.group(2)); target=CONTROL_UPSTREAM+"/audio/gpodder/device"; post_kind="device"
        msub=re.fullmatch(r"/api/2/subscriptions/([^/]+)/([^/]+)\.json", path)
        if msub:
            username=unquote(msub.group(1)); device=unquote(msub.group(2))
            if self.command == "GET":
                q=parse_qs(parsed.query); since=str((q.get("since") or ["0"])[0]); target=CONTROL_UPSTREAM+"/audio/gpodder/subscriptions?"+urlencode({"device":device,"since":since})
            elif self.command == "POST":
                target=CONTROL_UPSTREAM+"/audio/gpodder/subscriptions"; post_kind="subscriptions"
        mep=re.fullmatch(r"/api/2/episodes/([^/]+)\.json", path)
        if mep:
            username=unquote(mep.group(1))
            if self.command == "GET": target=CONTROL_UPSTREAM+"/audio/gpodder/episodes"+("?"+parsed.query if parsed.query else "")
            elif self.command == "POST": target=CONTROL_UPSTREAM+"/audio/gpodder/episodes"; post_kind="episodes"
        if not username or not target:
            self.send_bytes(HTTPStatus.NOT_FOUND,b'{"detail":"gPodder endpoint not implemented"}\n',"application/json; charset=utf-8"); return
        if not self._gpodder_auth(username): self._gpodder_unauthorized(); return
        try: token=CONTROL_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            self.send_bytes(HTTPStatus.SERVICE_UNAVAILABLE,b'{"detail":"PCGA podcast sync unavailable"}\n',"application/json; charset=utf-8"); return
        data=None
        if self.command == "POST":
            try: length=int(self.headers.get("Content-Length","0"))
            except ValueError: length=0
            if length < 0 or length > 512*1024:
                self.send_bytes(HTTPStatus.BAD_REQUEST,b'{"detail":"invalid request size"}\n',"application/json; charset=utf-8"); return
            raw=self.rfile.read(length) if length else b"{}"
            try: payload=json.loads(raw.decode("utf-8","replace") or "{}")
            except Exception:
                self.send_bytes(HTTPStatus.BAD_REQUEST,b'{"detail":"invalid JSON"}\n',"application/json; charset=utf-8"); return
            if post_kind == "episodes": payload={"actions":payload}
            elif not isinstance(payload,dict):
                self.send_bytes(HTTPStatus.BAD_REQUEST,b'{"detail":"JSON object required"}\n',"application/json; charset=utf-8"); return
            if post_kind in {"device","subscriptions"}: payload["_device"]=device
            data=json.dumps(payload,separators=(",",":")).encode()
        req=urllib.request.Request(target,data=data,headers={"Authorization":f"Bearer {token}","Accept":"application/json","Content-Type":"application/json"},method=self.command)
        try:
            response=urllib.request.urlopen(req,timeout=60); status=response.status; body=response.read(); headers=response.headers
        except urllib.error.HTTPError as exc:
            status=exc.code; body=exc.read(); headers=exc.headers
        except Exception as exc:
            self.send_bytes(HTTPStatus.BAD_GATEWAY,(json.dumps({"detail":f"podcast sync unavailable: {type(exc).__name__}"})+"\n").encode(),"application/json; charset=utf-8"); return
        self.send_response(status); self.send_header("Content-Type",headers.get("Content-Type","application/json; charset=utf-8")); self.send_header("Content-Length",str(len(body))); self.send_header("Cache-Control","no-store"); self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)

    def proxy_open_podcast(self) -> None:
        """Expose PCGA's single-user Open Podcast API subscription profile."""
        parsed = urlparse(self.path)
        suffix = parsed.path[len("/api/open-podcast"):] or "/v1/subscriptions"
        target = CONTROL_UPSTREAM + "/audio/open-podcast" + suffix + (("?" + parsed.query) if parsed.query else "")
        try:
            token = CONTROL_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            self.send_bytes(HTTPStatus.SERVICE_UNAVAILABLE, b'{"code":503,"message":"Podcast synchronization unavailable"}\n', "application/json; charset=utf-8")
            return
        data = None
        if self.command in {"POST", "PUT", "PATCH"}:
            try: length = int(self.headers.get("Content-Length", "0"))
            except ValueError: length = 0
            if length < 0 or length > 128 * 1024:
                self.send_bytes(HTTPStatus.BAD_REQUEST, b'{"code":405,"message":"Invalid request size"}\n', "application/json; charset=utf-8")
                return
            data = self.rfile.read(length) if length else b""
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if data is not None: headers["Content-Type"] = self.headers.get("Content-Type", "application/json")
        req = urllib.request.Request(target, data=data, headers=headers, method=self.command)
        try:
            response = urllib.request.urlopen(req, timeout=60)
            status, upstream_headers, body = response.status, response.headers, response.read()
        except urllib.error.HTTPError as exc:
            status, upstream_headers, body = exc.code, exc.headers, exc.read()
        except Exception as exc:
            body = json.dumps({"code": 502, "message": f"Podcast synchronization unavailable: {type(exc).__name__}"}).encode()
            self.send_bytes(HTTPStatus.BAD_GATEWAY, body, "application/json; charset=utf-8")
            return
        self.send_response(status)
        self.send_header("Content-Type", upstream_headers.get("Content-Type", "application/json; charset=utf-8"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)

    def proxy_control(self) -> None:
        suffix = self.path[len("/api/control"):] or "/state"
        target = CONTROL_UPSTREAM + suffix
        try:
            token = CONTROL_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            self.send_bytes(HTTPStatus.SERVICE_UNAVAILABLE, b'{"ok":false,"error":"control-token-unavailable"}\n', "application/json; charset=utf-8")
            return
        data = None
        patch_upload = self.command == "POST" and urlparse(self.path).path == "/api/control/patch"
        if patch_upload and not isinstance(self.connection, ssl.SSLSocket):
            self.send_bytes(HTTPStatus.UPGRADE_REQUIRED, b'{"ok":false,"error":"https-required","detail":"Patch uploads are accepted only through the HTTPS portal."}\n', "application/json; charset=utf-8")
            return
        if self.command in {"POST", "PUT", "PATCH"}:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            max_size = 128 * 1024 * 1024 if patch_upload else 128 * 1024
            if length < 0 or length > max_size:
                self.send_bytes(HTTPStatus.BAD_REQUEST, b'{"ok":false,"error":"invalid-request-size"}\n', "application/json; charset=utf-8")
                return
            data = self.rfile.read(length) if length else b""
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = self.headers.get("Content-Type", "application/json")
            if patch_upload:
                headers["X-PCGA-Filename"] = self.headers.get("X-PCGA-Filename", "pcga-patch.zip")[:240]
        req = urllib.request.Request(target, data=data, headers=headers, method=self.command)
        try:
            response = urllib.request.urlopen(req, timeout=90 if patch_upload else 300)
            status, upstream_headers, body = response.status, response.headers, response.read()
        except urllib.error.HTTPError as exc:
            status, upstream_headers, body = exc.code, exc.headers, exc.read()
        except Exception as exc:
            body = json.dumps({"ok":False,"error":"control-unavailable","detail":type(exc).__name__}).encode()
            self.send_bytes(HTTPStatus.BAD_GATEWAY, body, "application/json; charset=utf-8")
            return
        self.send_response(status)
        self.send_header("Content-Type", upstream_headers.get("Content-Type", "application/json; charset=utf-8"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def proxy_public_media_path(self, upstream_path: str) -> None:
        if not upstream_path.startswith("/"):
            self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid upstream path\n", "text/plain; charset=utf-8")
            return
        target = PUBLIC_MEDIA_UPSTREAM + upstream_path
        data = None
        if self.command in {"POST", "PUT", "PATCH"}:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length < 0 or length > 256 * 1024:
                self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid request size\n", "text/plain; charset=utf-8")
                return
            data = self.rfile.read(length) if length else b""
        headers = {}
        for name in ("Content-Type", "User-Agent"):
            value = self.headers.get(name)
            if value:
                headers[name] = value
        req = urllib.request.Request(target, data=data, headers=headers, method=self.command)
        try:
            response = urllib.request.urlopen(req, timeout=30)
            status, upstream_headers, body = response.status, response.headers, response.read()
        except urllib.error.HTTPError as exc:
            status, upstream_headers, body = exc.code, exc.headers, exc.read()
        except Exception as exc:
            body = json.dumps({"error":"public-media-unavailable","detail":type(exc).__name__}).encode()
            self.send_bytes(HTTPStatus.BAD_GATEWAY, body, "application/json; charset=utf-8")
            return
        content_type = upstream_headers.get("Content-Type", "application/octet-stream")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        if "text/html" in content_type.lower():
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data: https://archive.org; frame-ancestors 'self'")
        self.end_headers()
        self.wfile.write(body)

    def proxy_public_media_upload(self, upstream_path: str) -> None:
        """Stream a browser upload to the host intake service without buffering it.

        The portal remains a read-only sidecar for the archive itself. Uploaded
        bytes are passed directly to pcga-public-media on the host, which owns
        the narrow archive write path and classification workflow.
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        max_len = int(os.environ.get("PCGA_MAX_UPLOAD_BYTES", str(128 * 1024**3)))
        if length <= 0 or length > max_len:
            self.send_bytes(HTTPStatus.REQUEST_ENTITY_TOO_LARGE if length > max_len else HTTPStatus.BAD_REQUEST,
                            b'{"error":"invalid-upload-size"}\n', "application/json; charset=utf-8")
            return
        target = urlparse(PUBLIC_MEDIA_UPSTREAM)
        if target.scheme != "http" or not target.hostname:
            self.send_bytes(HTTPStatus.SERVICE_UNAVAILABLE, b'{"error":"upload-upstream-invalid"}\n', "application/json; charset=utf-8")
            return
        path = upstream_path if upstream_path.startswith("/") else "/" + upstream_path
        conn = http.client.HTTPConnection(target.hostname, target.port or 80, timeout=120)
        try:
            conn.putrequest("POST", path, skip_accept_encoding=True)
            conn.putheader("Content-Length", str(length))
            conn.putheader("Content-Type", self.headers.get("Content-Type", "application/octet-stream"))
            conn.putheader("User-Agent", self.headers.get("User-Agent", f"PCGameArchive/{VERSION}"))
            conn.endheaders()
            remaining = length
            while remaining:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ConnectionError("client upload ended early")
                conn.send(chunk)
                remaining -= len(chunk)
            response = conn.getresponse()
            body = response.read(2 * 1024 * 1024)
            ctype = response.getheader("Content-Type", "application/json; charset=utf-8")
            self.send_response(response.status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            self.close_connection = True
            body = json.dumps({"error":"upload-upstream-unavailable","detail":type(exc).__name__}).encode()
            self.send_bytes(HTTPStatus.BAD_GATEWAY, body, "application/json; charset=utf-8")
        finally:
            try: conn.close()
            except Exception: pass

    def proxy_public_media(self) -> None:
        suffix = self.path[len("/public-media"):]
        if not suffix:
            suffix = "/"
        self.proxy_public_media_path(suffix)

    def do_HEAD(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/games/ejs/"):
            suffix = path[len("/api/games/ejs/"):]
            decoded = unquote(suffix)
            if not suffix or ".." in decoded or "\\" in decoded or decoded.startswith("/"):
                self.send_response(HTTPStatus.BAD_REQUEST); self.end_headers(); return
            self.proxy_romm_stream("/assets/emulatorjs/data/" + suffix, head_only=True, cache_control="public, max-age=300, must-revalidate", public=True)
        elif re.match(r"^/api/games/rom/[0-9]+/content/.+", path):
            m = re.match(r"^/api/games/rom/([0-9]+)/content/(.+)$", path)
            if not m: self.send_response(HTTPStatus.BAD_REQUEST); self.end_headers(); return
            decoded_name = unquote(m.group(2))
            if ".." in decoded_name or "/" in decoded_name or "\\" in decoded_name:
                self.send_response(HTTPStatus.BAD_REQUEST); self.end_headers(); return
            query = urlparse(self.path).query
            upstream = f"/api/roms/{m.group(1)}/content/{m.group(2)}" + (("?" + query) if query else "")
            self.proxy_romm_stream(upstream, head_only=True)
        elif re.match(r"^/api/games/firmware/[0-9]+/content/.+", path):
            m = re.match(r"^/api/games/firmware/([0-9]+)/content/(.+)$", path)
            if not m: self.send_response(HTTPStatus.BAD_REQUEST); self.end_headers(); return
            decoded_name = unquote(m.group(2))
            if ".." in decoded_name or "/" in decoded_name or "\\" in decoded_name:
                self.send_response(HTTPStatus.BAD_REQUEST); self.end_headers(); return
            self.proxy_romm_stream(f"/api/firmware/{m.group(1)}/content/{m.group(2)}", head_only=True)
        elif re.fullmatch(r"/api/pc-games/game/[^/]+/download", path):
            game_id = unquote(path.split("/")[-2])
            try:
                file_path, filename, ctype = lancommander_archive_file(game_id)
                self.send_local_file(file_path, ctype, filename=filename, head_only=True)
            except (KeyError, FileNotFoundError, sqlite3.Error) as exc:
                self.send_bytes(HTTPStatus.NOT_FOUND, (str(exc) + "\n").encode(), "text/plain; charset=utf-8")
        elif re.fullmatch(r"/api/pc-games/game/[^/]+/asset/(?:hero|screenshot-[1-4])", path):
            parts=path.split("/"); game_id=unquote(parts[-3]); key=parts[-1]
            try:
                file_path,ctype=pcga_asset_file(game_id,key)
                self.send_local_file(file_path,ctype,head_only=True,cache_control="private, max-age=3600")
            except FileNotFoundError as exc:
                self.send_bytes(HTTPStatus.NOT_FOUND,(str(exc)+"\n").encode(),"text/plain; charset=utf-8")
        elif re.fullmatch(r"/api/pc-games/game/[^/]+/cover", path):
            game_id = unquote(path.split("/")[-2])
            try:
                file_path, ctype = lancommander_cover_file(game_id)
                self.send_local_file(file_path, ctype, head_only=True, cache_control="private, max-age=3600")
            except (KeyError, FileNotFoundError, sqlite3.Error) as exc:
                self.send_bytes(HTTPStatus.NOT_FOUND, (str(exc) + "\n").encode(), "text/plain; charset=utf-8")
        elif path == "/api/audio/remote":
            self.proxy_audio_remote(head_only=True)
        elif path == "/api/audio/local":
            self.serve_audio_local(head_only=True)
        elif path.startswith("/api/jellyfin/audio/"):
            self.proxy_jellyfin_audio(path.rsplit("/", 1)[-1], head_only=True)
        elif path.startswith("/api/jellyfin/video/"):
            self.proxy_jellyfin_video(path.rsplit("/", 1)[-1], head_only=True)
        else:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/review/preview":
            self.proxy_review_preview()
        elif path == "/api/review/items":
            status, result = review_api("/api/items")
            self.send_bytes(status, (json.dumps(result, separators=(",", ":"), default=str) + "\n").encode(), "application/json; charset=utf-8")
        elif path == "/api/review/library-optical-items":
            status, result = review_api("/api/library-optical-items")
            self.send_bytes(status, (json.dumps(result, separators=(",", ":"), default=str) + "\n").encode(), "application/json; charset=utf-8")
        elif path.startswith("/review"):
            self.proxy_review()
        elif path == "/api/audio/remote":
            self.proxy_audio_remote()
        elif path == "/api/audio/local":
            self.serve_audio_local()
        elif path == "/clientconfig.json" or path.startswith("/api/2/"):
            self.proxy_gpodder()
        elif path.startswith("/api/open-podcast/"):
            self.proxy_open_podcast()
        elif path.startswith("/api/control"):
            self.proxy_control()
        elif path.startswith("/public-media"):
            self.proxy_public_media()
        elif path == "/api/uploads/platforms":
            self.proxy_public_media_path("/api/user-upload/platforms")
        elif path == "/api/uploads/jobs":
            self.proxy_public_media_path("/api/user-upload/jobs")
        elif path == "/api/games/collection/platforms":
            self.proxy_public_media_path("/api/rom/platforms")
        elif path == "/api/games/collection/search":
            query = urlparse(self.path).query
            self.proxy_public_media_path("/api/rom/search" + (("?" + query) if query else ""))
        elif path == "/api/games/collection/item":
            query = urlparse(self.path).query
            self.proxy_public_media_path("/api/rom/item" + (("?" + query) if query else ""))
        elif path == "/api/games/collection/jobs":
            self.proxy_public_media_path("/api/rom/jobs")
        elif path == "/api/pc-games/health":
            result = lancommander_health()
            status = HTTPStatus.OK if result.get("available") else HTTPStatus.SERVICE_UNAVAILABLE
            self.send_bytes(status, (json.dumps(result, separators=(",", ":"), default=str) + "\n").encode(), "application/json; charset=utf-8")
        elif path == "/api/pc-games/capabilities":
            result = lancommander_capabilities()
            self.send_bytes(HTTPStatus.OK, (json.dumps(result, separators=(",", ":"), default=str) + "\n").encode(), "application/json; charset=utf-8")
        elif path == "/api/pc-games/library":
            query = parse_qs(urlparse(self.path).query)
            search = str((query.get("search") or [""])[0]).strip()[:120]
            try:
                limit = int((query.get("limit") or ["80"])[0]); offset = int((query.get("offset") or ["0"])[0])
                result = lancommander_library(search, limit, offset)
                self.send_bytes(HTTPStatus.OK, (json.dumps(result, separators=(",", ":"), default=str) + "\n").encode(), "application/json; charset=utf-8")
            except Exception as exc:
                result = {"available": False, "error": type(exc).__name__, "detail": str(exc)[:240], "items": []}
                self.send_bytes(HTTPStatus.BAD_GATEWAY, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
        elif re.fullmatch(r"/api/pc-games/game/[^/]+/stream", path):
            game_id = unquote(path.split("/")[-2])
            query = parse_qs(urlparse(self.path).query)
            try:
                lane=max(1,min(MOONLIGHT_WEB_LANES,int((query.get("lane") or ["1"])[0])))
            except (TypeError,ValueError):
                lane=1
            variant=str((query.get("variant") or [""])[0]).strip().casefold() or None
            try:
                result = pcga_stream_info(game_id,lane,variant)
                status = HTTPStatus.OK if result.get("available") or result.get("setup_required") else HTTPStatus.CONFLICT
                self.send_bytes(status, (json.dumps(result,separators=(",",":"),default=str)+"\n").encode(), "application/json; charset=utf-8")
            except ValueError as exc:
                self.send_bytes(HTTPStatus.BAD_REQUEST, (json.dumps({"available":False,"error":"invalid-variant","detail":str(exc)})+"\n").encode(), "application/json; charset=utf-8")
            except KeyError as exc:
                self.send_bytes(HTTPStatus.NOT_FOUND, (json.dumps({"available":False,"error":"not-found","detail":str(exc)})+"\n").encode(), "application/json; charset=utf-8")
        elif re.fullmatch(r"/api/pc-games/game/[^/]+", path):
            game_id = unquote(path.rsplit("/", 1)[-1])
            try:
                result = lancommander_game(game_id)
                self.send_bytes(HTTPStatus.OK, (json.dumps(result, separators=(",", ":"), default=str) + "\n").encode(), "application/json; charset=utf-8")
            except KeyError as exc:
                self.send_bytes(HTTPStatus.NOT_FOUND, (json.dumps({"available": False, "error": "not-found", "detail": str(exc)}) + "\n").encode(), "application/json; charset=utf-8")
            except Exception as exc:
                result = {"available": False, "error": type(exc).__name__, "detail": str(exc)[:240]}
                self.send_bytes(HTTPStatus.BAD_GATEWAY, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
        elif re.fullmatch(r"/api/pc-games/game/[^/]+/asset/(?:hero|screenshot-[1-4])", path):
            parts=path.split("/"); game_id=unquote(parts[-3]); key=parts[-1]
            try:
                file_path,ctype=pcga_asset_file(game_id,key)
                self.send_local_file(file_path,ctype,cache_control="private, max-age=3600")
            except FileNotFoundError as exc:
                self.send_bytes(HTTPStatus.NOT_FOUND,(str(exc)+"\n").encode(),"text/plain; charset=utf-8")
        elif re.fullmatch(r"/api/pc-games/game/[^/]+/cover", path):
            game_id = unquote(path.split("/")[-2])
            try:
                file_path, ctype = lancommander_cover_file(game_id)
                self.send_local_file(file_path, ctype, cache_control="private, max-age=3600")
            except (KeyError, FileNotFoundError, sqlite3.Error) as exc:
                self.send_bytes(HTTPStatus.NOT_FOUND, (str(exc) + "\n").encode(), "text/plain; charset=utf-8")
        elif re.fullmatch(r"/api/pc-games/game/[^/]+/download", path):
            game_id = unquote(path.split("/")[-2])
            try:
                file_path, filename, ctype = lancommander_archive_file(game_id)
                self.send_local_file(file_path, ctype, filename=filename)
            except (KeyError, FileNotFoundError, sqlite3.Error) as exc:
                self.send_bytes(HTTPStatus.NOT_FOUND, (str(exc) + "\n").encode(), "text/plain; charset=utf-8")
        elif path == "/api/games/health":
            query = parse_qs(urlparse(self.path).query)
            force = str((query.get("refresh") or [""])[0]).strip().lower() in {"1", "true", "yes"}
            result = romm_pipeline_health(force=force)
            status = HTTPStatus.OK if result.get("available") else HTTPStatus.SERVICE_UNAVAILABLE
            self.send_bytes(status, (json.dumps(result, separators=(",", ":"), default=str) + "\n").encode(), "application/json; charset=utf-8")
        elif path == "/api/games/emulators":
            result = emulator_capabilities()
            self.send_bytes(HTTPStatus.OK, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
        elif path == "/api/games/platforms":
            try:
                result = romm_platforms()
                self.send_bytes(HTTPStatus.OK, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
            except Exception as exc:
                result = {"available": False, "error": type(exc).__name__, "detail": str(exc)[:240], "items": []}
                self.send_bytes(HTTPStatus.BAD_GATEWAY, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
        elif path == "/api/games/library":
            query = parse_qs(urlparse(self.path).query)
            search = str((query.get("search") or [""])[0]).strip()[:120]
            platform_id = str((query.get("platform_id") or [""])[0]).strip()[:20]
            try:
                limit = int((query.get("limit") or ["80"])[0]); offset = int((query.get("offset") or ["0"])[0])
                result = romm_library(search, platform_id, limit, offset)
                self.send_bytes(HTTPStatus.OK, (json.dumps(result, separators=(",", ":"), default=str) + "\n").encode(), "application/json; charset=utf-8")
            except Exception as exc:
                result = {"available": False, "error": type(exc).__name__, "detail": str(exc)[:240], "items": []}
                self.send_bytes(HTTPStatus.BAD_GATEWAY, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
        elif re.fullmatch(r"/api/games/rom/[0-9]+", path):
            try:
                result = romm_rom(int(path.rsplit("/", 1)[-1]))
                self.send_bytes(HTTPStatus.OK, (json.dumps(result, separators=(",", ":"), default=str) + "\n").encode(), "application/json; charset=utf-8")
            except Exception as exc:
                result = {"available": False, "error": type(exc).__name__, "detail": str(exc)[:240]}
                self.send_bytes(HTTPStatus.BAD_GATEWAY, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
        elif re.fullmatch(r"/api/games/cover/[0-9]+", path):
            try:
                target = romm_cover_target(int(path.rsplit("/", 1)[-1]))
                if not target:
                    self.send_bytes(HTTPStatus.NOT_FOUND, b"cover unavailable\n", "text/plain; charset=utf-8")
                else:
                    self.proxy_romm_stream(target, cache_control="private, max-age=3600")
            except Exception as exc:
                self.send_bytes(HTTPStatus.BAD_GATEWAY, f"cover unavailable: {type(exc).__name__}\n".encode(), "text/plain; charset=utf-8")
        elif path == "/api/games/firmware":
            query = parse_qs(urlparse(self.path).query)
            raw_platform = str((query.get("platform_id") or [""])[0]).strip()
            if not raw_platform.isdigit():
                self.send_bytes(HTTPStatus.BAD_REQUEST, b'{"available":false,"error":"platform_id required"}\n', "application/json; charset=utf-8")
            else:
                try:
                    result = romm_firmware(int(raw_platform))
                    self.send_bytes(HTTPStatus.OK, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
                except Exception as exc:
                    result = {"available": False, "error": type(exc).__name__, "detail": str(exc)[:240], "items": []}
                    self.send_bytes(HTTPStatus.BAD_GATEWAY, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
        elif re.match(r"^/api/games/firmware/[0-9]+/content/.+", path):
            m = re.match(r"^/api/games/firmware/([0-9]+)/content/(.+)$", path)
            if not m:
                self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid firmware path\n", "text/plain; charset=utf-8")
            else:
                decoded_name = unquote(m.group(2))
                if ".." in decoded_name or "/" in decoded_name or "\\" in decoded_name:
                    self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid firmware filename\n", "text/plain; charset=utf-8")
                else:
                    self.proxy_romm_stream(f"/api/firmware/{m.group(1)}/content/{m.group(2)}")
        elif path.startswith("/api/games/ejs/"):
            suffix = path[len("/api/games/ejs/"):]
            decoded = unquote(suffix)
            if not suffix or ".." in decoded or "\\" in decoded or decoded.startswith("/") or len(suffix) > 500:
                self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid emulator asset path\n", "text/plain; charset=utf-8")
            else:
                query = urlparse(self.path).query
                upstream = "/assets/emulatorjs/data/" + suffix + (("?" + query) if query else "")
                self.proxy_romm_stream(upstream, cache_control="public, max-age=300, must-revalidate", public=True)
        elif re.match(r"^/api/games/rom/[0-9]+/content/.+", path):
            m = re.match(r"^/api/games/rom/([0-9]+)/content/(.+)$", path)
            if not m:
                self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid ROM path\n", "text/plain; charset=utf-8")
            else:
                decoded_name = unquote(m.group(2))
                if ".." in decoded_name or "/" in decoded_name or "\\" in decoded_name:
                    self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid ROM filename\n", "text/plain; charset=utf-8")
                else:
                    query = urlparse(self.path).query
                    upstream = f"/api/roms/{m.group(1)}/content/{m.group(2)}" + (("?" + query) if query else "")
                    self.proxy_romm_stream(upstream)
        elif re.fullmatch(r"/games/play/[0-9]+", path):
            self.send_player(emulator_player_html(int(path.rsplit("/", 1)[-1])))
        elif path == "/pcga-ca.crt":
            if TLS_CA_FILE.is_file():
                self.send_local_file(TLS_CA_FILE, "application/x-x509-ca-cert", cache_control="no-store")
            else:
                self.send_bytes(HTTPStatus.NOT_FOUND, b"PCGA local CA is not provisioned\n", "text/plain; charset=utf-8")
        elif path.startswith("/api/diagnostics"):
            self.proxy_diagnostics()
        elif path == "/api/secure-context":
            body=json.dumps({"available":STATUS_TLS_CERT.is_file() and STATUS_TLS_KEY.is_file() and TLS_CA_FILE.is_file(),"https_port":STATUS_TLS_PORT,"ca_url":"/pcga-ca.crt","moonlight_https_port":MOONLIGHT_WEB_PORT,"lan_dns_name":PORTAL_DNS_NAME,"lan_https_port":LAN_HTTPS_PORT,"lan_portal_url":(f"https://{PORTAL_DNS_NAME}/" if LAN_HTTPS_PORT==443 else f"https://{PORTAL_DNS_NAME}:{LAN_HTTPS_PORT}/")},separators=(",",":")).encode()
            self.send_bytes(HTTPStatus.OK,body,"application/json; charset=utf-8")
        elif path == "/":
            self.send_bytes(HTTPStatus.OK, INDEX_HTML.encode(), "text/html; charset=utf-8")
        elif path == "/api/store/art":
            query=parse_qs(urlparse(self.path).query); url=str((query.get("url") or [""])[0])[:4096]
            try:
                data,ctype=fetch_store_art(url)
                self.send_bytes(HTTPStatus.OK,data,ctype,cache_control="public, max-age=86400")
            except ValueError as exc:
                self.send_bytes(HTTPStatus.BAD_REQUEST,str(exc).encode(),"text/plain; charset=utf-8")
            except Exception as exc:
                self.send_bytes(HTTPStatus.BAD_GATEWAY,f"store artwork unavailable: {type(exc).__name__}".encode(),"text/plain; charset=utf-8")
        elif path == "/api/status":
            body = json.dumps(build_status(), separators=(",", ":"), default=str).encode()
            self.send_bytes(HTTPStatus.OK, body, "application/json; charset=utf-8")
        elif path == "/api/search/global":
            query=parse_qs(urlparse(self.path).query)
            q=str((query.get("q") or [""])[0]).strip()[:120]
            try: limit=int((query.get("limit") or ["8"])[0])
            except (TypeError,ValueError): limit=8
            try:
                result=portal_global_search(q,limit)
                self.send_bytes(HTTPStatus.OK,(json.dumps(result,separators=(",",":"),default=str)+"\n").encode(),"application/json; charset=utf-8")
            except Exception as exc:
                result={"available":False,"query":q,"sections":[],"error":type(exc).__name__,"detail":str(exc)[:240]}
                self.send_bytes(HTTPStatus.BAD_GATEWAY,(json.dumps(result,separators=(",",":"))+"\n").encode(),"application/json; charset=utf-8")
        elif path == "/api/jellyfin/now-playing":
            body = json.dumps(jellyfin_now_playing(), separators=(",", ":"), default=str).encode()
            self.send_bytes(HTTPStatus.OK, body, "application/json; charset=utf-8")
        elif path == "/api/jellyfin/music/library":
            query = parse_qs(urlparse(self.path).query)
            search = str((query.get("search") or [""])[0]).strip()[:120]
            view = str((query.get("view") or ["home"])[0]).strip().lower()[:24]
            parent_id = str((query.get("parent_id") or [""])[0]).strip()[:160]
            try:
                limit = int((query.get("limit") or ["24"])[0])
                result = jellyfin_music_items(search, limit, view, parent_id)
                self.send_bytes(HTTPStatus.OK, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
            except Exception as exc:
                result = {"available": False, "error": type(exc).__name__, "detail": str(exc)[:240], "items": []}
                self.send_bytes(HTTPStatus.BAD_GATEWAY, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
        elif path == "/api/jellyfin/library":
            query = parse_qs(urlparse(self.path).query)
            search = str((query.get("search") or [""])[0]).strip()[:120]
            media_filter = str((query.get("filter") or ["all"])[0]).strip().lower()[:24]
            parent_id = str((query.get("parent_id") or [""])[0]).strip()[:80]
            try:
                limit = int((query.get("limit") or ["48"])[0])
                result = jellyfin_library_items(search, media_filter, limit, parent_id)
                self.send_bytes(HTTPStatus.OK, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
            except Exception as exc:
                result = {"available": False, "error": type(exc).__name__, "detail": str(exc)[:240], "items": []}
                self.send_bytes(HTTPStatus.BAD_GATEWAY, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
        elif path == "/api/jellyfin/home-media":
            query = parse_qs(urlparse(self.path).query)
            try:
                limit = int((query.get("limit") or ["12"])[0])
                include_games = str((query.get("include_games") or ["1"])[0]).strip().lower() not in {"0", "false", "no", "off"}
                result = jellyfin_home_media_items(limit, include_games=include_games)
                self.send_bytes(HTTPStatus.OK, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
            except Exception as exc:
                result = {"available": False, "error": type(exc).__name__, "detail": str(exc)[:240], "sections": []}
                self.send_bytes(HTTPStatus.BAD_GATEWAY, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
        elif path == "/api/photos/library":
            query = parse_qs(urlparse(self.path).query)
            search = str((query.get("search") or [""])[0]).strip()[:120]
            try:
                limit = int((query.get("limit") or ["80"])[0])
                result = photo_library_items(search, limit)
                self.send_bytes(HTTPStatus.OK, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
            except Exception as exc:
                result = {"available": False, "error": type(exc).__name__, "detail": str(exc)[:240], "items": []}
                self.send_bytes(HTTPStatus.INTERNAL_SERVER_ERROR, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
        elif path.startswith("/api/photos/file/"):
            token = path.rsplit("/", 1)[-1]
            try:
                photo = photo_path_from_token(token)
                self.send_photo_path(photo)
            except ValueError:
                self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid photo path\n", "text/plain; charset=utf-8")
            except FileNotFoundError:
                self.send_bytes(HTTPStatus.NOT_FOUND, b"photo not found\n", "text/plain; charset=utf-8")
        elif path == "/api/jellyfin/background/library":
            query = parse_qs(urlparse(self.path).query)
            search = str((query.get("search") or [""])[0]).strip()[:120]
            try:
                limit = int((query.get("limit") or ["30"])[0])
                result = jellyfin_background_items(search, limit)
                self.send_bytes(HTTPStatus.OK, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
            except Exception as exc:
                result = {"available": False, "error": type(exc).__name__, "detail": str(exc)[:240], "items": []}
                self.send_bytes(HTTPStatus.BAD_GATEWAY, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
        elif path.startswith("/api/jellyfin/audio/"):
            self.proxy_jellyfin_audio(path.rsplit("/", 1)[-1])
        elif path.startswith("/api/jellyfin/video/"):
            self.proxy_jellyfin_video(path.rsplit("/", 1)[-1])
        elif path.startswith("/api/jellyfin/art/"):
            item_id = path.rsplit("/", 1)[-1]
            if not item_id or len(item_id) > 160 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in item_id):
                self.send_bytes(HTTPStatus.BAD_REQUEST, b"invalid item id\n", "text/plain; charset=utf-8")
                return
            try:
                status, headers, body = jellyfin_request(f"/Items/{quote(item_id, safe='')}/Images/Primary?maxWidth=320&quality=90", timeout=4.0)
            except Exception:
                self.send_bytes(HTTPStatus.BAD_GATEWAY, b"jellyfin image unavailable\n", "text/plain; charset=utf-8")
                return
            if status < 200 or status >= 300:
                self.send_bytes(status, body or b"image unavailable\n", headers.get("Content-Type", "text/plain; charset=utf-8"))
                return
            self.send_bytes(HTTPStatus.OK, body, headers.get("Content-Type", "image/jpeg"))
        elif path == "/health":
            self.send_bytes(HTTPStatus.OK, b'{"status":"ok"}\n', "application/json; charset=utf-8")
        else:
            self.send_bytes(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/open-podcast/"):
            self.proxy_open_podcast()
        elif path.startswith("/api/control"):
            self.proxy_control()
        else:
            self.send_bytes(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/control"):
            self.proxy_control()
        else:
            self.send_bytes(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        m_compat = re.fullmatch(r"/api/pc-games/game/([^/]+)/compatibility/refresh", path)
        if m_compat:
            game_id = unquote(m_compat.group(1))
            if not game_id.startswith("pcga:"):
                self.send_bytes(HTTPStatus.BAD_REQUEST, b'{"ok":false,"error":"not-pcga-managed"}\n', "application/json; charset=utf-8"); return
            sid = game_id.split(":", 1)[1]
            if not re.fullmatch(r"[0-9A-Za-z._-]{8,80}", sid):
                self.send_bytes(HTTPStatus.BAD_REQUEST, b'{"ok":false,"error":"invalid-game-id"}\n', "application/json; charset=utf-8"); return
            try:
                token = CONTROL_TOKEN_FILE.read_text(encoding="utf-8").strip()
                if not token: raise RuntimeError("empty control token")
                payload = json.dumps({"action":"pc-game-compat-refresh","game_set_id":sid}, separators=(",",":")).encode()
                req = urllib.request.Request(CONTROL_UPSTREAM + "/action", data=payload, headers={"Authorization":f"Bearer {token}","Accept":"application/json","Content-Type":"application/json"}, method="POST")
                try:
                    response = urllib.request.urlopen(req, timeout=85); status, body = response.status, response.read()
                except urllib.error.HTTPError as exc:
                    status, body = exc.code, exc.read()
                try: result = json.loads(body.decode("utf-8","replace"))
                except Exception: result = {"ok":False,"error":"invalid-control-response","detail":body[:240].decode("utf-8","replace")}
                self.send_bytes(HTTPStatus.OK if 200 <= status < 300 and result.get("ok") else (HTTPStatus.BAD_GATEWAY if status >= 500 else status), (json.dumps(result,separators=(",",":"))+"\n").encode(), "application/json; charset=utf-8")
            except Exception as exc:
                self.send_bytes(HTTPStatus.BAD_GATEWAY, (json.dumps({"ok":False,"error":type(exc).__name__,"detail":str(exc)[:300]},separators=(",",":"))+"\n").encode(), "application/json; charset=utf-8")
            return

        m_reinstall = re.fullmatch(r"/api/pc-games/game/([^/]+)/reinstall", path)
        if m_reinstall:
            game_id = unquote(m_reinstall.group(1))
            if not game_id.startswith("pcga:"):
                self.send_bytes(HTTPStatus.BAD_REQUEST, b'{"ok":false,"error":"not-pcga-managed"}\n', "application/json; charset=utf-8"); return
            sid = game_id.split(":", 1)[1]
            if not re.fullmatch(r"[0-9A-Za-z._-]{8,80}", sid):
                self.send_bytes(HTTPStatus.BAD_REQUEST, b'{"ok":false,"error":"invalid-game-id"}\n', "application/json; charset=utf-8"); return
            try:
                token = CONTROL_TOKEN_FILE.read_text(encoding="utf-8").strip()
                if not token:
                    raise RuntimeError("empty control token")
                payload = json.dumps({"action":"pc-game-reinstall","game_set_id":sid}, separators=(",",":")).encode()
                req = urllib.request.Request(
                    CONTROL_UPSTREAM + "/action",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                try:
                    response = urllib.request.urlopen(req, timeout=10)
                    status, body = response.status, response.read()
                except urllib.error.HTTPError as exc:
                    status, body = exc.code, exc.read()
                try:
                    result = json.loads(body.decode("utf-8", "replace"))
                except Exception:
                    result = {"ok": False, "error": "invalid-control-response", "detail": body[:240].decode("utf-8", "replace")}
                if status < 200 or status >= 300 or not result.get("ok"):
                    self.send_bytes(HTTPStatus.BAD_GATEWAY if status >= 500 else status, (json.dumps(result,separators=(",",":"))+"\n").encode(), "application/json; charset=utf-8")
                    return
                self.send_bytes(HTTPStatus.ACCEPTED, (json.dumps(result,separators=(",",":"))+"\n").encode(), "application/json; charset=utf-8")
            except OSError as exc:
                self.send_bytes(HTTPStatus.BAD_GATEWAY, (json.dumps({"ok":False,"error":type(exc).__name__,"detail":str(exc)[:300]},separators=(",",":"))+"\n").encode(), "application/json; charset=utf-8")
            except Exception as exc:
                self.send_bytes(HTTPStatus.INTERNAL_SERVER_ERROR, (json.dumps({"ok":False,"error":type(exc).__name__,"detail":str(exc)[:300]},separators=(",",":"))+"\n").encode(), "application/json; charset=utf-8")
            return

        m_retry = re.fullmatch(r"/api/pc-games/game/([^/]+)/retry", path)
        if m_retry:
            game_id = unquote(m_retry.group(1))
            if not game_id.startswith("pcga:"):
                self.send_bytes(HTTPStatus.BAD_REQUEST, b'{"ok":false,"error":"not-pcga-managed"}\n', "application/json; charset=utf-8"); return
            sid = game_id.split(":", 1)[1]
            if not re.fullmatch(r"[0-9A-Za-z._-]{8,80}", sid):
                self.send_bytes(HTTPStatus.BAD_REQUEST, b'{"ok":false,"error":"invalid-game-id"}\n', "application/json; charset=utf-8"); return
            # pcga-status runs inside a container and must never try to execute
            # /usr/local/sbin host tools directly. Route the install/retry action
            # through the authenticated host-side pcga-control service instead.
            try:
                token = CONTROL_TOKEN_FILE.read_text(encoding="utf-8").strip()
                if not token:
                    raise RuntimeError("empty control token")
                payload = json.dumps({"action":"pc-game-retry","game_set_id":sid}, separators=(",",":")).encode()
                req = urllib.request.Request(
                    CONTROL_UPSTREAM + "/action",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                try:
                    response = urllib.request.urlopen(req, timeout=10)
                    status, body = response.status, response.read()
                except urllib.error.HTTPError as exc:
                    status, body = exc.code, exc.read()
                try:
                    result = json.loads(body.decode("utf-8", "replace"))
                except Exception:
                    result = {"ok": False, "error": "invalid-control-response", "detail": body[:240].decode("utf-8", "replace")}
                if status < 200 or status >= 300 or not result.get("ok"):
                    self.send_bytes(HTTPStatus.BAD_GATEWAY if status >= 500 else status, (json.dumps(result,separators=(",",":"))+"\n").encode(), "application/json; charset=utf-8")
                    return
                self.send_bytes(HTTPStatus.ACCEPTED, (json.dumps(result,separators=(",",":"))+"\n").encode(), "application/json; charset=utf-8")
            except OSError as exc:
                result={"ok":False,"error":"control-token-unavailable","detail":str(exc)[:240]}
                self.send_bytes(HTTPStatus.SERVICE_UNAVAILABLE, (json.dumps(result,separators=(",",":"))+"\n").encode(), "application/json; charset=utf-8")
            except Exception as exc:
                result={"ok":False,"error":"control-unavailable","detail":f"{type(exc).__name__}: {str(exc)[:200]}"}
                self.send_bytes(HTTPStatus.BAD_GATEWAY, (json.dumps(result,separators=(",",":"))+"\n").encode(), "application/json; charset=utf-8")
        elif path.startswith("/api/review/"):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > 128 * 1024:
                self.send_bytes(HTTPStatus.BAD_REQUEST, b'{"ok":false,"error":"invalid-request"}\n', "application/json; charset=utf-8"); return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8", "replace"))
                if not isinstance(payload, dict): raise ValueError("object required")
            except Exception:
                self.send_bytes(HTTPStatus.BAD_REQUEST, b'{"ok":false,"error":"invalid-json"}\n', "application/json; charset=utf-8"); return
            action = path[len("/api/review/"):].strip("/")
            if action not in {"metadata-search", "metadata-apply", "promote", "quarantine", "delete", "reclassify-optical", "reconcile-optical"}:
                self.send_bytes(HTTPStatus.NOT_FOUND, b'{"ok":false,"error":"not-found"}\n', "application/json; charset=utf-8"); return
            status, result = review_api("/api/" + action, payload)
            self.send_bytes(status, (json.dumps(result, separators=(",", ":"), default=str) + "\n").encode(), "application/json; charset=utf-8")
        elif path.startswith("/review"):
            self.proxy_review()
        elif path.startswith("/api/2/"):
            self.proxy_gpodder()
        elif path.startswith("/api/open-podcast/"):
            self.proxy_open_podcast()
        elif path.startswith("/api/control"):
            self.proxy_control()
        elif path.startswith("/public-media"):
            self.proxy_public_media()
        elif path == "/api/uploads/file":
            query = urlparse(self.path).query
            self.proxy_public_media_upload("/api/user-upload/file" + (("?" + query) if query else ""))
        elif path == "/api/uploads/session":
            self.proxy_public_media_path("/api/user-upload/session")
        elif path == "/api/uploads/commit":
            self.proxy_public_media_path("/api/user-upload/commit")
        elif path == "/api/games/collection/import":
            self.proxy_public_media_path("/api/rom/import")
        elif path == "/api/games/rescan":
            try:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length > 16384:
                    self.send_bytes(HTTPStatus.BAD_REQUEST, b'{"ok":false,"error":"invalid-request"}\n', "application/json; charset=utf-8")
                    return
                if length:
                    self.rfile.read(length)
                result = romm_trigger_scan()
                self.send_bytes(HTTPStatus.ACCEPTED, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
            except Exception as exc:
                result = {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:320]}
                self.send_bytes(HTTPStatus.BAD_GATEWAY, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
        elif path in {"/api/jellyfin/control", "/api/jellyfin/music/prepare", "/api/jellyfin/video/prepare", "/api/jellyfin/music/event", "/api/jellyfin/playback/event"}:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > 16384:
                self.send_bytes(HTTPStatus.BAD_REQUEST, b'{"ok":false,"error":"invalid-request"}\n', "application/json; charset=utf-8")
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8", "replace"))
            except Exception:
                self.send_bytes(HTTPStatus.BAD_REQUEST, b'{"ok":false,"error":"invalid-json"}\n', "application/json; charset=utf-8")
                return
            if path == "/api/jellyfin/control":
                status, result = jellyfin_control(str(payload.get("session_id") or ""), str(payload.get("action") or ""))
            elif path == "/api/jellyfin/music/prepare":
                try:
                    result = jellyfin_prepare_audio(str(payload.get("item_id") or ""), int(payload.get("start_ticks") or 0))
                    status = HTTPStatus.OK
                except ValueError as exc:
                    status, result = HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)}
                except Exception as exc:
                    status, result = HTTPStatus.BAD_GATEWAY, {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:240]}
            elif path == "/api/jellyfin/video/prepare":
                try:
                    result = jellyfin_prepare_video(
                        str(payload.get("item_id") or ""),
                        int(payload.get("start_ticks") or 0),
                        media_source_id=str(payload.get("media_source_id") or ""),
                        quality=str(payload.get("quality") or "auto"),
                        audio_stream_index=payload.get("audio_stream_index"),
                        subtitle_stream_index=payload.get("subtitle_stream_index"),
                    )
                    status = HTTPStatus.OK
                except ValueError as exc:
                    status, result = HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)}
                except Exception as exc:
                    status, result = HTTPStatus.BAD_GATEWAY, {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:240]}
            else:
                status, result = jellyfin_report_portal_playback(str(payload.get("event") or ""), payload)
            self.send_bytes(status, (json.dumps(result, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8")
        else:
            self.send_bytes(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="PC Game Archive pipeline status and manual-classification portal")
    parser.add_argument("--bind", default=os.environ.get("PCGA_STATUS_BIND", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PCGA_STATUS_PORT", "8098")))
    parser.add_argument("--tls-port", type=int, default=STATUS_TLS_PORT)
    parser.add_argument("--tls-cert", default=str(STATUS_TLS_CERT))
    parser.add_argument("--tls-key", default=str(STATUS_TLS_KEY))
    args = parser.parse_args()

    http_server = ThreadingHTTPServer((args.bind, args.port), Handler)
    http_server.daemon_threads = True
    tls_server = None
    http_thread = None
    cert=Path(args.tls_cert); key=Path(args.tls_key)
    if args.tls_port and cert.is_file() and key.is_file():
        tls_server = ThreadingHTTPServer((args.bind, args.tls_port), Handler)
        tls_server.daemon_threads = True
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=str(cert), keyfile=str(key))
        tls_server.socket=context.wrap_socket(tls_server.socket, server_side=True)
        http_thread=threading.Thread(target=http_server.serve_forever,kwargs={"poll_interval":0.5},daemon=True)
        http_thread.start()
        print(f"PCGA pipeline portal v{VERSION} listening on http://{args.bind}:{args.port} and https://{args.bind}:{args.tls_port}", flush=True)
        primary=tls_server
    else:
        print(f"PCGA pipeline portal v{VERSION} listening on http://{args.bind}:{args.port} (TLS certificate unavailable)", flush=True)
        primary=http_server
    try:
        primary.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        try: primary.shutdown()
        except Exception: pass
        primary.server_close()
        if tls_server is not None:
            try: http_server.shutdown()
            except Exception: pass
            http_server.server_close()


if __name__ == "__main__":
    main()
