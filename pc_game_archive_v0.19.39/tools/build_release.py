#!/usr/bin/env python3
"""Build a reproducible Linux release and verify its embedded checksum manifest."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {'.sh', '.py', '.md', '.yml', '.yaml', '.service', '.timer', '.path', '.sha256', '.json', '.txt'}


def validate_payload(name: str, payload: bytes) -> None:
    path = Path(name)
    text = path.suffix in TEXT_SUFFIXES or 'components' in path.parts or payload.startswith(b'#!')
    if not text:
        return
    if b'\r' in payload:
        raise ValueError(f'{name}: Windows/CR line endings are not allowed in Linux release files')
    if payload.startswith(b'\xef\xbb\xbf'):
        raise ValueError(f'{name}: UTF-8 BOM is not allowed in executable release sources')
    payload.decode('utf-8')


def release_files(root: Path):
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if '__pycache__' in relative.parts or '.git' in relative.parts or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            raise ValueError(f'{relative}: symbolic links are not allowed in release archives')
        if path.is_file() and path.name != 'MANIFEST.sha256':
            yield path


def build(root: Path, output: Path) -> str:
    if not re.fullmatch(r'pc_game_archive_v\d+(?:\.\d+){2,3}', root.name):
        raise ValueError('release root must use the versioned pc_game_archive_v<version> name')
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError('write the archive outside the release source directory')
    payloads = []
    for path in release_files(root):
        name = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        validate_payload(name, payload)
        if path.suffix == '.py' or payload.startswith(b'#!/usr/bin/env python3'):
            compile(payload, name, 'exec')
        payloads.append((name, payload))
    manifest = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                       for name, data in payloads).encode('utf-8')
    (root / 'MANIFEST.sha256').write_bytes(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, payload in payloads + [('MANIFEST.sha256', manifest)]:
            info = zipfile.ZipInfo(root.name + '/' + name)
            info.compress_type = zipfile.ZIP_DEFLATED
            executable = name.endswith('.sh') or payload.startswith(b'#!')
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            archive.writestr(info, payload)
    with zipfile.ZipFile(output) as archive:
        for name, payload in payloads:
            actual = archive.read(root.name + '/' + name)
            if actual != payload:
                raise ValueError('archive bytes differ from release source: ' + name)
            validate_payload(name, actual)
        for line in archive.read(root.name + '/MANIFEST.sha256').decode('utf-8').splitlines():
            digest, name = line.split('  ', 1)
            if hashlib.sha256(archive.read(root.name + '/' + name)).hexdigest() != digest:
                raise ValueError('archive checksum failed: ' + name)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name(output.name + '.sha256').write_bytes((digest + '  ' + output.name + '\n').encode())
    return digest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='ZIP path outside the versioned source directory')
    args = parser.parse_args()
    print('Verified LF-only release and embedded manifest:', build(ROOT, args.output))
