"""Freeze behavioral definitions and original sources; observers are a later gate.

Run `freeze --dependency PATH` once; `verify` checks retained bytes without
requiring the original dependency path. The checked-in record is the trust anchor.
No model calls, source execution, archive extraction or global writes occur.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile

BASELINE = 'dabd182e049cc6fb52007da988bf03762130c459'
FILES = ('rubric.json', 'scenarios.py', 'challenge-spec.json')
MAX_BYTES = 64 * 1024 * 1024
MAX_FILES = 10000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args):
    env = {k: os.environ[k] for k in ('PATH', 'SYSTEMROOT') if k in os.environ}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0', LC_ALL='C')
    return subprocess.run(['git', '--no-optional-locks', '-c', 'core.hooksPath=' + os.devnull,
                           '-c', 'core.fsmonitor=false', *args], cwd=root, env=env,
                          check=True, capture_output=True, timeout=30).stdout


def dependency_archive(root):
    """Actual dependency files, including local changes; never Git config/credentials."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Dependency must be a real directory')
    entries = []
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != '.git')
        for name in dirs + sorted(files):
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError('Dependency symlinks are unsupported')
        for name in sorted(files):
            if name == '.git':
                continue
            path = Path(directory) / name
            if not path.is_file():
                raise ValueError('Dependency special files are unsupported')
            total += path.stat().st_size
            entries.append(path)
            if total > MAX_BYTES or len(entries) > MAX_FILES:
                raise ValueError('Dependency exceeds archive limits')
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for path in sorted(entries):
            data = path.read_bytes()
            item = tarfile.TarInfo(path.relative_to(root).as_posix())
            item.size = len(data)
            item.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            archive.addfile(item, io.BytesIO(data))
    return output.getvalue()


def definitions(root):
    folder = Path(root) / 'tests/reliability'
    rubric = json.loads((folder / 'rubric.json').read_text())
    spec = json.loads((folder / 'challenge-spec.json').read_text())
    assertions = rubric['assertions']
    if len(assertions) != 25 or len({a['id'] for a in assertions}) != 25:
        raise ValueError('Expected 25 unique assertions')
    if set(spec['assertions']) != {a['id'] for a in assertions}:
        raise ValueError('Challenge IDs do not match rubric')
    for assertion in assertions:
        case = spec['assertions'][assertion['id']]
        if not all(case.get(k) for k in ('positive', 'negative', 'independent_evidence')):
            raise ValueError('Incomplete behavioral definition')
    if set(spec['scenarios']) != {a['scenario'] for a in assertions}:
        raise ValueError('Scenario coverage mismatch')
    return {name: digest((folder / name).read_bytes()) for name in FILES}


def freeze(root, dependency, snapshot, record, baseline=BASELINE):
    root, dependency, snapshot, record = map(Path, (root, dependency, snapshot, record))
    if record.exists() or snapshot.exists():
        raise ValueError('Freeze destinations must not exist; refusing to replace a freeze')
    hashes = definitions(root)
    resolved = git(root, 'rev-parse', '--verify', baseline + '^{commit}').decode().strip()
    source = git(root, 'archive', '--format=tar', resolved)
    if len(source) > MAX_BYTES:
        raise ValueError('Source exceeds archive limit')
    dep = dependency_archive(dependency)
    version = json.loads((dependency / '.claude-plugin/plugin.json').read_text())['version']
    revision = git(dependency, 'rev-parse', 'HEAD').decode().strip()
    result = {'schema': 1, 'stage': 'behavioral-definitions-only', 'baseline_revision': resolved,
              'definitions': hashes,
              'archives': {'baseline.tar': digest(source), 'superpowers.tar': digest(dep)},
              'dependency': {'name': 'superpowers', 'version': version, 'revision': revision,
                             'snapshot_kind': 'actual-files-excluding-git-metadata',
                             'tracked_changes': git(dependency, 'diff', '--name-status', 'HEAD', '--').decode().splitlines()},
              'deferred': ['executable observer freeze', 'host certification', '48 scored live trials'],
              'live_trials_consumed': 0}
    snapshot.mkdir(parents=True)
    for name, data in (('baseline.tar', source), ('superpowers.tar', dep)):
        (snapshot / name).write_bytes(data)
        (snapshot / name).chmod(0o444)
    record.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    verify(root, snapshot, record)
    return result


def verify(root, snapshot, record):
    result = json.loads(Path(record).read_text())
    if result.get('schema') != 1 or result.get('stage') != 'behavioral-definitions-only':
        raise ValueError('Invalid freeze record')
    if definitions(root) != result['definitions']:
        raise ValueError('Frozen behavioral definitions changed')
    if set(result['archives']) != {'baseline.tar', 'superpowers.tar'}:
        raise ValueError('Archive inventory changed')
    for name, expected in result['archives'].items():
        path = Path(snapshot) / name
        if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != expected:
            raise ValueError('Frozen snapshot changed: ' + name)
    source = git(Path(root), 'archive', '--format=tar', result['baseline_revision'])
    if digest(source) != result['archives']['baseline.tar']:
        raise ValueError('Baseline archive does not match original revision')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'verify'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--dependency', type=Path)
    args = parser.parse_args()
    snapshot = args.root / '.agentic/work/framework-reliability/frozen-baseline'
    record = args.root / 'tests/reliability/frozen-definitions.json'
    if args.action == 'freeze':
        if args.dependency is None:
            parser.error('freeze requires --dependency')
        result = freeze(args.root, args.dependency, snapshot, record)
    else:
        result = verify(args.root, snapshot, record)
    print(json.dumps({'status': 'verified', 'baseline_revision': result['baseline_revision'],
                      'definitions': result['definitions'], 'archives': result['archives']}, indent=2))


if __name__ == '__main__':
    main()
