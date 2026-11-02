#!/usr/bin/env python3
"""Install semantic Wolf catalog reconciliation with backup and rollback."""
from __future__ import annotations

import ast
from collections import Counter
import datetime
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import time
import tomllib
import urllib.request

HERE = Path(__file__).resolve().parent
SBIN = Path('/usr/local/sbin')
STACK = Path('/opt/pc-game-archive')
VERSION = '0.19.42'
TIMERS = ['pcga-game-orchestrator.timer', 'pcga-heroic-sync.timer', 'pcga-service-auth.timer']
WOLF_CONFIG = Path('/etc/wolf/cfg/config.toml')


def log(message):
    print('[pcga-catalog] ' + message, flush=True)


def run(args, timeout=30, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'{args[0]} failed: {(result.stderr or result.stdout)[-1500:]}')
    return result


def patch_functions(source, replacement, baselines):
    old = {n.name: n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    new = {n.name: n for n in ast.parse(replacement).body if isinstance(n, ast.FunctionDef)}
    lines = source.splitlines(keepends=True)
    for name in sorted(baselines, key=lambda name: old[name].lineno, reverse=True):
        node = old[name]
        existing = ast.get_source_segment(source, node)
        target = ast.get_source_segment(replacement, new[name])
        if hashlib.sha256(existing.encode()).hexdigest() != baselines[name] and existing != target:
            raise ValueError(f'unsupported locally modified {name}; no files changed')
        lines[node.lineno - 1:node.end_lineno] = [target + '\n']
    result = ''.join(lines)
    compile(result, '<patched-component>', 'exec')
    return result


def patch_version(source, portal=False):
    pattern = r'(?m)^VERSION = "(?:0\.19\.40|0\.19\.41|0\.19\.42)"$'
    if len(re.findall(pattern, source)) != 1:
        raise ValueError('v0.19.42 requires installed v0.19.40, v0.19.41 or v0.19.42')
    result = re.sub(pattern, f'VERSION = "{VERSION}"', source, count=1)
    if portal:
        marker = r"const PORTAL_BUILD_VERSION='(?:0\.19\.40|0\.19\.41|0\.19\.42)'"
        if len(re.findall(marker, result)) != 1:
            raise ValueError('unsupported portal build marker')
        result = re.sub(marker, f"const PORTAL_BUILD_VERSION='{VERSION}'", result, count=1)
    compile(result, '<versioned-component>', 'exec')
    return result


def patch_control(source):
    """Expose the opt-in NetBird Compose peer through existing Control Center actions."""
    result = patch_version(source)
    tree = ast.parse(result)
    maps = [node for node in tree.body if isinstance(node, ast.Assign) and
            any(isinstance(target, ast.Name) and target.id == 'DOCKER_SERVICES' for target in node.targets)]
    if len(maps) != 1 or not isinstance(maps[0].value, ast.Dict):
        raise ValueError('unsupported Control Center Docker service map')
    mapping = maps[0]
    mapping_text = ast.get_source_segment(result, mapping)
    values = ast.literal_eval(mapping.value)
    if 'netbird' in values:
        if values['netbird'] != 'pcga-netbird':
            raise ValueError('unsupported existing NetBird Docker service mapping')
    else:
        anchor = '    "wolf": "wolf",\n'
        if mapping_text.count(anchor) != 1:
            raise ValueError('unsupported Control Center Docker service map')
        updated = mapping_text.replace(anchor, anchor + '    "netbird": "pcga-netbird",\n', 1)
        result = result.replace(mapping_text, updated, 1)

    tree = ast.parse(result)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'compose_files']
    if len(functions) != 1:
        raise ValueError('unsupported Control Center Compose file list')
    function_text = ast.get_source_segment(result, functions[0])
    if '"compose.netbird.yml"' not in function_text:
        compose = '"compose.nas.yml"]'
        if function_text.count(compose) != 1:
            raise ValueError('unsupported Control Center Compose file list')
        updated = function_text.replace(compose, '"compose.nas.yml", "compose.netbird.yml"]', 1)
        result = result.replace(function_text, updated, 1)
    compile(result, '<patched-control>', 'exec')
    return result


def load_component(name):
    loader = importlib.machinery.SourceFileLoader('pcga_upgrade_' + name.replace('-', '_'), str(SBIN / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def reconcile_catalog(recover=False):
    """Use prepared runtime state; never run builds, installers or media intake."""
    orchestrator = load_component('pcga-game-orchestrator')
    heroic = load_component('pcga-heroic-sync')
    selected = []
    for path in sorted(orchestrator.STATE_ROOT.glob('*.json')):
        sid = path.stem
        state = orchestrator.load_json(path)
        game = orchestrator.load_json(orchestrator.SETS / (sid + '.json'))
        if any(state.get(key) for key in ('catalog_hidden', 'duplicate_of')) or any(game.get(key) for key in ('catalog_hidden', 'superseded_by')):
            continue
        if not ((state.get('status') == 'ready' and state.get('runtime_image')) or
                (state.get('status') == 'setup-required' and state.get('setup_runtime_image'))):
            continue
        force = recover and state.get('wolf_registration_quarantine_reason') == 'managed-app-block-dropped-after-two-reloads'
        orchestrator.wolf_sync(sid, game or {'title': state.get('title') or sid}, state, force_retry=bool(force))
        selected.append(sid)
    if not heroic.CATALOG.is_file():
        raise RuntimeError('prepared Heroic catalog is missing; not guessing installed games')
    catalog = json.loads(heroic.CATALOG.read_text(encoding='utf8'))
    result = heroic.reconcile_wolf(catalog.get('items', []), heroic.root(), defer_reload=True)
    if result.get('detail', '').startswith('Heroic image unavailable'):
        raise RuntimeError(result['detail'])
    if not orchestrator._wolf_reconcile_batched_restart():
        raise RuntimeError('catalog reload was deferred; streaming state is busy or unavailable')
    (heroic.STATE / 'wolf-reload-pending.json').unlink(missing_ok=True)
    for sid in selected:
        state = orchestrator.load_json(orchestrator.state_path(sid))
        if state.get('stream_state') not in ('ready', 'setup-ready'):
            raise RuntimeError(f'game registration still failed: {sid}: {state.get("stream_detail")}')
    log(f'Reconciled {len(selected)} prepared game/setup registrations and the Heroic catalog')


def pool_ready():
    for _ in range(5):
        result = run([str(SBIN / 'pcga-stream-health')], check=False)
        if result.returncode == 0:
            return
        time.sleep(1)
    run([str(SBIN / 'pcga-stream-health'), '--safe-to-repair'])
    log('Reconciling browser trust after the single catalog reload')
    run([str(SBIN / 'pcga-moonlight-web-bootstrap')], timeout=240)
    run([str(SBIN / 'pcga-stream-health')])


def validate_live_apps():
    from pcga_wolf_config import profile
    expected = Counter(app['title'] for app in profile(tomllib.loads(WOLF_CONFIG.read_text(encoding='utf8'))).get('apps', []))
    state = json.loads(Path('/var/lib/pc-game-archive/bootstrap/moonlight-web.json').read_text())
    context = ssl.create_default_context(cafile='/etc/pc-game-archive/tls/pcga-ca.crt')
    if len(state.get('lanes', [])) != 4:
        raise RuntimeError('expected four browser lanes')
    for lane in state['lanes']:
        url = f'https://127.0.0.1:{int(lane["web_port"])}/api/apps?host_id={int(lane["host_id"])}'
        with urllib.request.urlopen(url, context=context, timeout=5) as response:
            apps = json.load(response)['apps']
        actual = Counter(app['title'] for app in apps)
        if actual != expected:
            raise RuntimeError(f'lane {lane["lane"]} app catalog differs from Wolf configuration')
    log(f'All four live lanes expose the same {sum(expected.values())} app entries without duplicates')


def wolf_started():
    return run(['docker', 'inspect', '-f', '{{.State.StartedAt}}', 'wolf']).stdout.strip()


def compose():
    command = ['docker', 'compose']
    for name in ('compose.yml', 'compose.jellyfin-gpu.yml', 'compose.immich.yml', 'compose.romm.yml',
                 'compose.arm.yml', 'compose.status.yml', 'compose.wolf.yml', 'compose.moonlight-web.yml',
                 'compose.game-lan.yml', 'compose.nas.yml', 'compose.netbird.yml'):
        if (STACK / name).is_file():
            command += ['-f', str(STACK / name)]
    return command


def refresh_portal():
    run(['systemctl', 'restart', 'pcga-control.service'])
    run(compose() + ['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--force-recreate', 'pcga-status'], timeout=90)


def validate_portal():
    context = ssl.create_default_context(cafile='/etc/pc-game-archive/tls/pcga-ca.crt')
    for attempt in range(30):
        try:
            with urllib.request.urlopen('https://127.0.0.1:8443/api/status', context=context, timeout=3) as response:
                if json.load(response).get('version') != VERSION:
                    raise ValueError('portal version did not refresh')
            return
        except Exception:
            if attempt == 29:
                raise
            time.sleep(1)


def atomic_write(path, payload, mode):
    temporary = path.with_name(path.name + '.pcga-1942.tmp')
    temporary.write_bytes(payload)
    temporary.chmod(mode)
    os.replace(temporary, path)


def main():
    if os.geteuid() != 0:
        raise RuntimeError('run the standard upgrade entrypoint with sudo')
    sys.dont_write_bytecode = True
    baselines = json.loads((HERE / 'tools/catalog-baseline.json').read_text())
    native = run(['systemctl', 'is-active', 'netbird'], check=False).stdout.strip()
    if native == 'active':
        raise RuntimeError('a native NetBird service is active; stop it before switching PCGA to the container peer')
    updates = {}
    for name, functions in baselines.items():
        path = SBIN / name
        updates[path] = patch_functions(path.read_text(encoding='utf8'),
                                        (HERE / 'components' / name).read_text(encoding='utf8'), functions).encode()
    module = (HERE / 'components/pcga_wolf_config.py').read_bytes()
    compile(module, 'pcga_wolf_config.py', 'exec')
    updates[SBIN / 'pcga_wolf_config.py'] = module
    control = SBIN / 'pcga-control'
    portal = STACK / 'status/server.py'
    updates[control] = patch_control(control.read_text(encoding='utf8')).encode()
    updates[portal] = patch_version(portal.read_text(encoding='utf8'), portal=True).encode()
    netbird = (HERE / 'components/pcga-netbird-remote').read_bytes()
    compile(netbird, 'pcga-netbird-remote', 'exec')
    updates[SBIN / 'pcga-netbird-remote'] = netbird
    entrypoint = (HERE / 'components/pcga-netbird-container-entrypoint').read_bytes()
    updates[SBIN / 'pcga-netbird-container-entrypoint'] = entrypoint
    updates[STACK / 'compose.netbird.yml'] = (HERE / 'components/compose.netbird.yml').read_bytes()
    run([str(SBIN / 'pcga-stream-health'), '--safe-to-repair'])
    active_timers = [unit for unit in TIMERS if run(['systemctl', 'is-active', unit], check=False).stdout.strip() == 'active']
    metadata = []
    changed = False
    try:
        if active_timers:
            log('Pausing catalog and authentication timers during the upgrade')
            run(['systemctl', 'stop'] + active_timers)
        deadline = time.monotonic() + 180
        while any(run(['systemctl', 'is-active', unit.replace('.timer', '.service')], check=False).stdout.strip()
                  in ('active', 'activating', 'deactivating') for unit in TIMERS):
            if time.monotonic() > deadline:
                raise RuntimeError('an existing reconciliation job did not finish; no files changed')
            time.sleep(1)
        sys.path.insert(0, str(HERE / 'components'))
        from pcga_wolf_config import stack_lock
        with stack_lock(timeout=60):
            sys.path.insert(0, str(SBIN))
            run([str(SBIN / 'pcga-stream-health'), '--safe-to-repair'])
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup = Path('/var/backups/pc-game-archive') / ('v' + VERSION + '-' + stamp)
            backup.mkdir(parents=True, mode=0o700)
            paths = list(updates) + [WOLF_CONFIG,
                Path('/var/lib/pc-game-archive/game-runtime/wolf-restart-pending.json'),
                Path('/var/lib/pc-game-archive/heroic/wolf-reload-pending.json')]
            paths += sorted(Path('/var/lib/pc-game-archive/game-installs').glob('*.json'))
            for index, path in enumerate(paths):
                saved = backup / (str(index) + '-' + path.name)
                exists = path.exists()
                if exists:
                    shutil.copy2(path, saved)
                metadata.append({'path': str(path), 'backup': str(saved) if exists else None})
            (backup / 'restore.json').write_text(json.dumps(metadata, indent=2), encoding='utf8')
            log('Backup: ' + str(backup))
            changed = True
            for path, payload in updates.items():
                if path.exists():
                    mode = path.stat().st_mode & 0o777
                else:
                    mode = 0o755 if path in (SBIN / 'pcga-netbird-remote',
                                              SBIN / 'pcga-netbird-container-entrypoint') else 0o644
                atomic_write(path, payload, mode)
            reconcile_catalog(recover=True)
            pool_ready()
            validate_live_apps()
            before = WOLF_CONFIG.read_bytes()
            started = wolf_started()
            reconcile_catalog()
            if WOLF_CONFIG.read_bytes() != before or wolf_started() != started:
                raise RuntimeError('a second reconciliation changed the configuration or restarted Wolf')
            run([str(SBIN / 'pcga-stream-health')])
            refresh_portal()
            validate_portal()
            log('Validation passed: second reconciliation made no config changes and did not restart Wolf')
    except BaseException:
        if changed:
            log('Validation failed; restoring previous scripts, game states and Wolf configuration')
            for record in metadata:
                path = Path(record['path'])
                if record['backup']:
                    shutil.copy2(record['backup'], path)
                else:
                    path.unlink(missing_ok=True)
            if run([str(SBIN / 'pcga-stream-health'), '--safe-to-repair'], check=False).returncode == 0:
                run(['docker', 'restart', 'wolf'], timeout=90, check=False)
            refresh_portal()
        raise
    finally:
        if active_timers:
            run(['systemctl', 'start'] + active_timers)
    log('v' + VERSION + ' installed; prior timer settings restored')


if __name__ == '__main__':
    main()
