#!/usr/bin/env python3
"""Install a small, reversible PCGA streaming health hotfix."""
from __future__ import annotations

import datetime
import ast
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import ssl
import urllib.request

HERE = Path(__file__).resolve().parent
SBIN = Path('/usr/local/sbin')
STACK = Path('/opt/pc-game-archive')
DEN_ENTRY = Path('/etc/pc-game-archive/wolf-den-entrypoint.sh')
DEN_MOUNT = '/etc/pc-game-archive/wolf-den-entrypoint.sh:/entrypoint.sh:ro'
VERSION = '0.19.38'


def log(message):
    print('[pcga-runtime-health] ' + message, flush=True)


def run(args, timeout=30, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'{args[0]} failed: {(result.stderr or result.stdout)[-1000:]}')
    return result


def patch_den_entrypoint(source: str) -> str:
    marker = '# PCGA: force the .NET client to use the private Unix socket relay.'
    if marker in source:
        return source
    relay = re.compile(r'(?m)^socat\s+UNIX-LISTEN:/app/wolf\.sock,[^\n]+\s&\s*$')
    if len(list(relay.finditer(source))) != 1:
        raise ValueError('unsupported Wolf Den entrypoint: expected private socket relay')
    pattern = r'(?m)^(?P<line>[^\n#]*\bdotnet\s+WolfLeash\.dll[^\n]*)$'
    if len(list(re.finditer(pattern, source))) != 1:
        raise ValueError('unsupported Wolf Den entrypoint: expected one .NET launch')
    def relay_options(match):
        line = match[0].replace('UNIX-LISTEN:/app/wolf.sock,',
                                'UNIX-LISTEN:/app/wolf.sock,unlink-early,', 1)
        line = re.sub(r'\s+2>\s*/dev/null', '', line)
        return line + '\npcga_wolf_relay_pid=$!'
    source = relay.sub(relay_options, source, count=1)
    boundary = '''# PCGA: force the .NET client to use the private Unix socket relay.
pcga_relay_ready=0
for ((pcga_probe=0; pcga_probe<20; pcga_probe++)); do
  kill -0 "$pcga_wolf_relay_pid" 2>/dev/null || break
  if curl -fsS --max-time 2 --unix-socket /app/wolf.sock http://localhost/api/v1/profiles >/dev/null 2>&1; then
    pcga_relay_ready=1
    break
  fi
  sleep .1
done
[[ $pcga_relay_ready -eq 1 ]] || { echo '[pcga-wolf-den] private API relay did not become ready' >&2; exit 1; }
export WOLF_SOCKET_PATH=unix:///app/wolf.sock
'''
    return re.sub(pattern, lambda match: boundary + match['line'], source, count=1)


def patch_compose(source: str) -> str:
    match = re.search(r'(?m)^  wolf-den:\s*\n', source)
    if not match:
        raise ValueError('Wolf Den service not found in compose.wolf.yml')
    next_service = re.search(r'(?m)^  [A-Za-z0-9_-]+:\s*(?:\n|$)', source[match.end():])
    end = match.end() + next_service.start() if next_service else len(source)
    block = source[match.start():end]
    if DEN_MOUNT in block:
        return source
    if 'wolf-den-entrypoint.sh' in block or re.search(r':/entrypoint\.sh(?::|\s|$)', block):
        raise ValueError('Wolf Den already has a different entrypoint mount')
    volume = re.search(r'(?m)^    volumes:\s*$', block)
    if not volume:
        raise ValueError('Wolf Den volumes list not found')
    block = block[:volume.end()] + '\n      - ' + DEN_MOUNT + block[volume.end():]
    return source[:match.start()] + block + source[end:]


def patch_auth(source: str) -> str:
    if "Moonlight Web live connection is healthy" in source:
        return source
    old = 'if [[ "$moon_state" != ready ]]; then'
    if source.count(old) != 1:
        raise ValueError('unsupported service-auth streaming readiness block')
    replacement = '''if /usr/local/sbin/pcga-stream-health >/dev/null 2>&1; then
      log 'Moonlight Web live connection is healthy'
    elif ! /usr/local/sbin/pcga-stream-health --safe-to-repair; then
      log 'Deferring browser pairing repair until game sessions and pending launches are idle'
      failed=1
    else
      log 'Moonlight Web live trust/identity check failed; reconciling appliance pairing'
      /usr/local/sbin/pcga-moonlight-web-bootstrap || { log 'Moonlight Web reconciliation failed; timer will retry'; failed=1; }
      /usr/local/sbin/pcga-stream-health || { log 'Moonlight Web is still unhealthy after reconciliation; timer will retry'; failed=1; }
    fi'''
    original = '''if [[ "$moon_state" != ready ]]; then
    /usr/local/sbin/pcga-moonlight-web-bootstrap || { log 'Moonlight Web reconciliation failed; timer will retry'; failed=1; }
  fi'''
    if source.count(original) != 1:
        raise ValueError('unsupported service-auth pairing repair block')
    return source.replace(original, replacement, 1)


def patch_version(source: str, *, portal: bool = False) -> str:
    match = re.search(r'(?m)^VERSION = "([0-9.]+)"$', source)
    if not match or match[1] not in {'0.19.37', VERSION}:
        raise ValueError('this focused upgrade requires installed PCGA v0.19.37 or v0.19.38')
    source = source[:match.start()] + f'VERSION = "{VERSION}"' + source[match.end():]
    if portal:
        pattern = r"const PORTAL_BUILD_VERSION='(?:0\.19\.37|0\.19\.38)'"
        if len(re.findall(pattern, source)) != 1:
            raise ValueError('unsupported installed portal build marker')
        source = re.sub(pattern, f"const PORTAL_BUILD_VERSION='{VERSION}'", source, count=1)
    compile(source, 'installed-portal' if portal else 'installed-control', 'exec')
    return source


def patch_control_status(source: str) -> str:
    """Replace only the supported patch-status function, retaining local changes."""
    def function(text):
        node = next((node for node in ast.parse(text).body
                     if isinstance(node, ast.FunctionDef) and node.name == 'patch_status'), None)
        if node is None:
            raise ValueError('installed control plane has no patch_status function')
        return node, ast.get_source_segment(text, node)
    node, existing = function(source)
    if 'exit_path.is_file()' not in existing or 'systemctl' not in existing:
        raise ValueError('unsupported installed patch-status implementation')
    _, replacement = function((HERE / 'components/pcga-control').read_text(encoding='utf-8'))
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1:node.end_lineno] = [replacement + '\n']
    result = ''.join(lines)
    compile(result, 'patched-control', 'exec')
    return result


def validate_portal():
    context = ssl.create_default_context(cafile='/etc/pc-game-archive/tls/pcga-ca.crt')
    last_error = ''
    for _ in range(30):
        try:
            with urllib.request.urlopen('https://127.0.0.1:8443/api/status', context=context, timeout=3) as response:
                if json.load(response).get('version') != VERSION:
                    raise ValueError('portal API is serving an old version')
            with urllib.request.urlopen('https://127.0.0.1:8443/', context=context, timeout=3) as response:
                if f"const PORTAL_BUILD_VERSION='{VERSION}'" not in response.read().decode():
                    raise ValueError('portal HTML is serving an old build')
            return
        except Exception as exc:
            last_error = str(exc)
            time.sleep(1)
    raise RuntimeError('portal validation failed: ' + last_error)


def compose_command():
    result = ['docker', 'compose']
    for name in ('compose.yml', 'compose.jellyfin-gpu.yml', 'compose.immich.yml',
                 'compose.romm.yml', 'compose.arm.yml', 'compose.status.yml',
                 'compose.wolf.yml', 'compose.moonlight-web.yml',
                 'compose.game-lan.yml', 'compose.nas.yml'):
        if (STACK / name).is_file():
            result.extend(['-f', str(STACK / name)])
    return result


def atomic_write(path: Path, text: str, mode: int):
    temp = path.with_name(path.name + '.pcga-runtime-health.tmp')
    temp.write_text(text, encoding='utf-8')
    temp.chmod(mode)
    os.replace(temp, path)


def main():
    lock = open('/run/pcga-game-stack-start.lock', 'a')
    deadline = time.monotonic() + 60
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise RuntimeError('game-stack reconciliation is busy; retry later')
            time.sleep(.5)
    if shutil.disk_usage('/').free < 128 * 1024 * 1024:
        raise RuntimeError('less than 128 MiB free; no files changed')
    run(['python3', str(HERE / 'components/pcga-stream-health'), '--safe-to-repair'])
    compose = STACK / 'compose.wolf.yml'
    auth = SBIN / 'pcga-service-auth'
    control = SBIN / 'pcga-control'
    portal = STACK / 'status/server.py'
    log('Validating existing startup configuration before changing files')
    for attempt in range(10):
        copied = run(['docker', 'exec', 'wolf-den', 'cat', '/entrypoint.sh'], check=False)
        if copied.returncode == 0:
            break
        time.sleep(.5)
    else:
        raise RuntimeError('could not read the restarting Wolf Den entrypoint; no files changed')
    entry = copied.stdout
    patched_entry = patch_den_entrypoint(entry)
    patched_compose = patch_compose(compose.read_text(encoding='utf-8'))
    patched_auth = patch_auth(auth.read_text(encoding='utf-8'))
    patched_control = patch_control_status(patch_version(control.read_text(encoding='utf-8')))
    patched_portal = patch_version(portal.read_text(encoding='utf-8'), portal=True)
    for text in (patched_entry, patched_auth):
        result = subprocess.run(['/bin/bash', '-n'], input=text, text=True, capture_output=True)
        if result.returncode:
            raise ValueError('generated shell source failed validation: ' + result.stderr)
    compile((HERE / 'components/pcga-stream-health').read_text(encoding='utf-8'), 'pcga-stream-health', 'exec')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = Path('/var/backups/pc-game-archive') / ('v' + VERSION + '-' + stamp)
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.mkdir(mode=0o700)
    paths = [compose, auth, DEN_ENTRY, SBIN / 'pcga-stream-health', control, portal]
    metadata = []
    for path in paths:
        dest = backup / path.name
        if path.exists():
            shutil.copy2(path, dest)
        metadata.append({'path': str(path), 'backup': str(dest) if path.exists() else None})
    (backup / 'restore.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    (backup / 'vendor-wolf-den-entrypoint.sh').write_text(entry, encoding='utf-8')
    log('Backup: ' + str(backup))
    changed = False
    try:
        changed = True
        atomic_write(DEN_ENTRY, patched_entry, 0o755)
        atomic_write(SBIN / 'pcga-stream-health', (HERE / 'components/pcga-stream-health').read_text(encoding='utf-8'), 0o755)
        atomic_write(auth, patched_auth, auth.stat().st_mode & 0o777)
        atomic_write(compose, patched_compose, compose.stat().st_mode & 0o777)
        atomic_write(control, patched_control, control.stat().st_mode & 0o777)
        atomic_write(portal, patched_portal, portal.stat().st_mode & 0o777)
        run(compose_command() + ['config', '--quiet'])
        log('Recreating Wolf Den with normalized Unix socket configuration')
        run(compose_command() + ['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--force-recreate', 'wolf-den'], timeout=90)
        log('Refreshing the portal certificate and v' + VERSION + ' build')
        run(compose_command() + ['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--force-recreate', 'pcga-status'], timeout=90)
        run(['systemctl', 'restart', 'pcga-control.service'], timeout=30)
        time.sleep(25)
        raw = json.loads(run(['docker', 'inspect', 'wolf-den']).stdout)[0]
        if not raw['State']['Running'] or raw['RestartCount']:
            raise RuntimeError('Wolf Den restarted during its first 25 seconds')
        log_result = run(['docker', 'logs', '--tail', '100', 'wolf-den'])
        logs = log_result.stdout + log_result.stderr
        if 'Connection refused (localhost:80)' in logs or "Can't connect to Socket" in logs:
            raise RuntimeError('Wolf Den still cannot connect to its API socket')
        run([str(SBIN / 'pcga-stream-health')])
        validate_portal()
        log('Wolf Den remained running without restarts; all four browser lanes passed live trust checks')
        log('No runtime images, game prefixes, media, or SSH access settings were changed')
    except Exception:
        if changed:
            log('Validation failed; restoring previous files and Wolf Den configuration')
            for record in metadata:
                path = Path(record['path'])
                if record['backup']:
                    shutil.copy2(record['backup'], path)
                else:
                    path.unlink(missing_ok=True)
            run(compose_command() + ['up', '-d', '--no-deps', '--force-recreate', 'wolf-den'], timeout=90, check=False)
            run(compose_command() + ['up', '-d', '--no-deps', '--force-recreate', 'pcga-status'], timeout=90, check=False)
            run(['systemctl', 'restart', 'pcga-control.service'], timeout=30, check=False)
        raise


if __name__ == '__main__':
    main()
