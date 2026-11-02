"""Compare PCGA Wolf apps by settings, preserving unrelated TOML verbatim."""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import copy
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import time
import tomllib
import uuid

PROFILE = 'moonlight-profile-id'
HEADERS = re.compile(r'(?m)^[ \t]*(\[\[?)([^\]\n]+)\]\]?[ \t]*(?:#[^\n]*)?$')


def owns(app: dict, owner: str) -> bool:
    runner = app.get('runner', {})
    if runner.get('type') != 'docker':
        return False
    env = runner.get('env', [])
    if not isinstance(env, list):
        return False
    if owner == 'heroic':
        return any(isinstance(x, str) and x.startswith('PCGA_GAME_SET_ID=heroic-') for x in env) and any(
            isinstance(x, str) and x.startswith('PCGA_HEROIC_MODE=') for x in env)
    uuid.UUID(owner)
    return 'PCGA_GAME_SET_ID=' + owner in env


def normalized(value):
    if isinstance(value, dict):
        result = {key: normalized(item) for key, item in value.items()}
        if isinstance(result.get('base_create_json'), str):
            result['base_create_json'] = json.loads(result['base_create_json'])
        return result
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


def signature(apps):
    return Counter(json.dumps(normalized(app), sort_keys=True, separators=(',', ':')) for app in apps)


def profile(document):
    profiles = document.get('profiles', [])
    matches = [p for p in profiles if p.get('id') == PROFILE]
    if len(matches) != 1:
        raise ValueError('expected exactly one Wolf moonlight-profile-id profile')
    return matches[0]


def desired_apps(block: str, owner: str):
    desired = profile(tomllib.loads('[[profiles]]\nid = "' + PROFILE + '"\n' + block)).get('apps', [])
    if not all(owns(app, owner) for app in desired):
        raise ValueError('desired Wolf apps do not belong to this PCGA owner')
    return desired


def apps_match(text: str, block: str, owner: str) -> bool:
    apps = profile(tomllib.loads(text)).get('apps', [])
    return signature([app for app in apps if owns(app, owner)]) == signature(desired_apps(block, owner))


def reconcile_apps(text: str, block: str, owner: str) -> str:
    """Replace only this owner's app tables when their effective settings differ.

    Comments, quoting, key order and JSON whitespace do not request a reload.
    Duplicate owned tables do. Source ranges are accepted only when they agree
    with tomllib's parsed structure; unusual/ambiguous syntax fails closed.
    """
    document = tomllib.loads(text)
    target = profile(document)
    desired = desired_apps(block, owner)
    existing = target.get('apps', [])
    if signature([app for app in existing if owns(app, owner)]) == signature(desired):
        return text
    headers = [(m, m[2].strip()) for m in HEADERS.finditer(text)]
    profiles = [i for i, (m, name) in enumerate(headers) if name == 'profiles' and m[1] == '[[']
    if len(profiles) != len(document['profiles']):
        raise ValueError('ambiguous Wolf profile source ranges')
    position = next(i for i, item in enumerate(document['profiles']) if item.get('id') == PROFILE)
    begin = profiles[position]
    end = profiles[position + 1] if position + 1 < len(profiles) else len(headers)
    indices = [i for i in range(begin + 1, end) if headers[i][1] == 'profiles.apps' and headers[i][0][1] == '[[']
    if len(indices) != len(existing):
        raise ValueError('ambiguous Wolf app source ranges')
    spans = []
    for i in indices:
        next_i = i + 1
        while next_i < len(headers) and headers[next_i][1].startswith('profiles.apps.'):
            next_i += 1
        stop = headers[next_i][0].start() if next_i < len(headers) else len(text)
        spans.append((headers[i][0].start(), stop))
    owned_spans = [span for app, span in zip(existing, spans) if owns(app, owner)]
    if owned_spans:
        insert_at = owned_spans[0][0]
    elif indices:
        insert_at = headers[indices[0]][0].start()
    else:
        next_i = begin + 1
        while next_i < len(headers) and headers[next_i][1].startswith('profiles.'):
            next_i += 1
        insert_at = headers[next_i][0].start() if next_i < len(headers) else len(text)
    replacement = block.strip() + '\n\n' if desired else ''
    updated = text
    for start, stop in reversed(owned_spans):
        updated = updated[:start] + (replacement if start == insert_at else '') + updated[stop:]
    if not owned_spans:
        updated = updated[:insert_at] + replacement + updated[insert_at:]
    result = tomllib.loads(updated)
    # All global configuration, other profiles and unowned apps must survive.
    def unowned(document):
        document = copy.deepcopy(document)
        p = profile(document)
        p['apps'] = [app for app in p.get('apps', []) if not owns(app, owner)]
        return document
    if unowned(document) != unowned(result) or not apps_match(updated, block, owner):
        raise ValueError('Wolf edit would change unrelated settings or app ownership')
    return updated


@contextmanager
def stack_lock(timeout=180):
    if os.environ.get('PCGA_GAME_STACK_LOCK_HELD') == '1':
        yield
        return
    import fcntl
    with Path('/run/pcga-game-stack-start.lock').open('a') as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('game-stack reconciliation is busy')
                time.sleep(.25)
        os.environ['PCGA_GAME_STACK_LOCK_HELD'] = '1'
        try:
            yield
        finally:
            os.environ.pop('PCGA_GAME_STACK_LOCK_HELD', None)


def load_orchestrator():
    path = Path('/usr/local/sbin/pcga-game-orchestrator')
    loader = importlib.machinery.SourceFileLoader('pcga_catalog_orchestrator', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
