"""Bounded local trial driver; never installs plugins globally or retries a slot."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import re
import tempfile
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from observations import observer_field_inventory
from scoring import score_trials

SCENARIOS = ('fresh_feature', 'mature_escalation', 'delegation_resume', 'qa_failure')


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def trial_schedule(phase: str) -> list[dict]:
    if phase not in ('baseline', 'candidate'):
        raise ValueError('phase must be baseline or candidate')
    return [dict(id=f'{phase}-{scenario}-{host}-{repetition}', phase=phase,
                 scenario=scenario, host=host, repetition=repetition)
            for repetition in range(1, 4) for scenario in SCENARIOS
            for host in ('claude', 'codex')]


def write_new(path: Path, data: dict) -> None:
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def validate_slot(slot: dict) -> None:
    if slot not in trial_schedule(slot.get('phase', '')):
        raise ValueError('slot does not belong to the frozen schedule')


def reserve_trial(root: Path, slot: dict) -> Path:
    validate_slot(slot)
    parent = root / 'trials'
    parent.mkdir(parents=True, exist_ok=True)
    directory = parent / slot['id']
    directory.mkdir(mode=0o700)  # atomic allocation; an interrupted slot stays consumed
    write_new(directory / 'reservation.json', {'slot': slot, 'status': 'reserved', 'reserved_at': now(),
               'manifest_sha256': file_hash(root / 'manifest.json') if (root / 'manifest.json').is_file() else None})
    return directory


def finish_trial(root: Path, slot: dict, result: dict) -> None:
    validate_slot(slot)
    for field in ('id', 'phase', 'scenario', 'host', 'repetition'):
        if field in result and result[field] != slot[field]:
            raise ValueError(f'cannot change reserved {field}')
    directory = root / 'trials' / slot['id']
    reservation = json.loads((directory / 'reservation.json').read_text())
    if reservation['slot'] != slot:
        raise ValueError('reservation does not match slot')
    bound = {**result, **slot, 'finished_at': now(),
             'reservation_sha256': file_hash(directory / 'reservation.json')}
    if (root / 'manifest.json').is_file():
        bound['manifest_sha256'] = file_hash(root / 'manifest.json')
        evidence = result.get('evidence', [])
        bound['evidence_sha256'] = {str(Path(path).resolve()): file_hash(Path(path)) for path in evidence}
    write_new(directory / 'result.json', bound)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'snapshot symlink unsupported: {path.name}')
        if path.is_file() and '__pycache__' not in path.parts:
            digest.update(path.relative_to(root).as_posix().encode() + b'\0')
            digest.update(path.read_bytes())
            digest.update(b'\0')
    return digest.hexdigest()


def runner_hashes() -> dict:
    root = Path(__file__).parent
    return {p.name: file_hash(p) for p in sorted(root.glob('*'))
            if p.suffix in ('.py', '.json') and not p.name.startswith('test_')}


def freeze(root: Path, repo: Path, revision: str, dependency: Path, phase: str = 'baseline',
           baseline: Path | None = None) -> dict:
    """Capture tracked source plus a dependency copy; retain originals unchanged."""
    from hosts import inspect_host
    trial_schedule(phase)
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'manifest.json').exists():
        manifest = json.loads((root / 'manifest.json').read_text())
        if manifest['revision'] != revision or manifest['phase'] != phase:
            raise ValueError('suite is already frozen against another revision')
        verify_freeze(root, manifest)
        return manifest
    if not dependency.is_dir():
        raise ValueError('a readable pinned dependency plugin directory is required')
    revision = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', revision + '^{commit}'], text=True).strip()
    source = root / 'source'
    source.mkdir()
    archived = subprocess.check_output(['git', '-C', str(repo), 'archive', '--format=tar', revision])
    (root / 'source.tar').write_bytes(archived)
    with tarfile.open(fileobj=io.BytesIO(archived)) as archive:
        for member in archive.getmembers():
            target = (source / member.name).resolve()
            if not target.is_relative_to(source.resolve()) or not (member.isfile() or member.isdir()):
                raise ValueError('source archive contains an unsafe member')
        archive.extractall(source)  # all members above are regular files or directories
    dependency_target = root / 'dependency'
    shutil.copytree(dependency, dependency_target,
                    ignore=shutil.ignore_patterns('.git', 'node_modules', '__pycache__', '*.pyc'))
    manifest = {'schema': 2, 'source_archive_sha256': file_hash(root / 'source.tar'), 'phase': phase, 'revision': revision, 'frozen_at': now(),
                'source_sha256': tree_hash(source), 'dependency_sha256': tree_hash(dependency_target),
                'runner_sha256': runner_hashes(), 'hosts': {h: inspect_host(h) for h in ('claude', 'codex')},
                'timeout_seconds': 900, 'max_trials': 24, 'repetitions': 3}
    if phase == 'candidate':
        if baseline is None:
            raise ValueError('candidate freeze requires the baseline suite')
        original = json.loads((baseline / 'manifest.json').read_text())
        verify_freeze(baseline, original, allow_runner_drift=True)
        # Candidate host profiles and the trusted runner are intentionally
        # re-frozen after evaluator improvements; the baseline retains its
        # original evidence and remains immutable.
        for field in ('dependency_sha256',):
            if manifest[field] != original[field]:
                raise ValueError(f'candidate differs from baseline in {field}')
        manifest['baseline_dir'] = str(baseline.resolve())
        manifest['baseline_manifest_sha256'] = file_hash(baseline / 'manifest.json')
    write_new(root / 'manifest.json', manifest)
    return manifest


def verify_freeze(root: Path, manifest: dict, allow_runner_drift: bool = False) -> None:
    """Integrity within trusted evaluator storage, not operator authenticity.

    Certified candidate isolation must deny writes to this storage. A same-user
    evaluator/operator able to forge all files is outside this threat boundary.
    """
    if (manifest.get('schema') != 2 or manifest.get('phase') not in ('baseline', 'candidate')
            or not re.fullmatch(r'[0-9a-f]{40,64}', manifest.get('revision', ''))
            or manifest.get('max_trials') != 24 or manifest.get('repetitions') != 3
            or manifest.get('timeout_seconds') != 900
            or set(manifest.get('hosts', {})) != {'claude', 'codex'}):
        raise ValueError('invalid frozen manifest schema or identity')
    if (root / 'source').is_symlink() or (root / 'dependency').is_symlink():
        raise ValueError('snapshot roots must not be symlinks')
    archived = root / 'source.tar'
    if archived.is_symlink() or file_hash(archived) != manifest.get('source_archive_sha256'):
        raise ValueError('source archive identity changed')
    with tarfile.open(archived) as archive:
        if archive.pax_headers.get('comment') != manifest['revision']:
            raise ValueError('source archive revision differs from frozen revision')
        files = {}
        for member in archive.getmembers():
            target = (root / 'source' / member.name).resolve()
            if not target.is_relative_to((root / 'source').resolve()) or not (member.isfile() or member.isdir()):
                raise ValueError('invalid source archive member')
            if member.isfile():
                files[member.name] = archive.extractfile(member).read()
        actual = {p.relative_to(root / 'source').as_posix(): p.read_bytes()
                  for p in (root / 'source').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        if actual != files:
            raise ValueError('source snapshot differs from revision archive')
    for name in ('source', 'dependency'):
        if not (root / name).is_dir() or tree_hash(root / name) != manifest.get(f'{name}_sha256'):
            raise ValueError(f'frozen {name} was modified')
    if not allow_runner_drift and runner_hashes() != manifest.get('runner_sha256'):
        raise ValueError('frozen harness changed; do not silently rebaseline')
    if manifest['phase'] == 'candidate':
        baseline = Path(manifest.get('baseline_dir', ''))
        if not baseline.is_absolute() or baseline.resolve() == root.resolve():
            raise ValueError('candidate requires an independent baseline')
        original = json.loads((baseline / 'manifest.json').read_text())
        if original.get('phase') != 'baseline':
            raise ValueError('candidate linkage must point to baseline')
        verify_freeze(baseline, original, allow_runner_drift=True)
        if file_hash(baseline / 'manifest.json') != manifest.get('baseline_manifest_sha256'):
            raise ValueError('baseline linkage changed')
        for field in ('dependency_sha256',):
            if manifest[field] != original[field]:
                raise ValueError('candidate differs from baseline in ' + field)


def capture_boundary(fixture: Path, scenario: str, metadata: dict) -> dict:
    """Retain interruption evidence without treating agent-written state as proof.

    The collector records both legacy artifact locations and repository-local
    state. Format-specific recovery assertions must also match host receipts.
    """
    from scenarios import oracle_observations
    records = {}
    total = 0
    for relative in ('.agentic', 'docs/superpowers/runs'):
        base = fixture / relative
        if base.is_symlink():
            records[relative] = {'error': 'symlink'}
            continue
        if not base.exists():
            continue
        for directory, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(name for name in dirs if not (Path(directory) / name).is_symlink())
            for name in sorted(files):
                path = Path(directory) / name
                key = path.relative_to(fixture).as_posix()
                if path.is_symlink() or not path.is_file():
                    records[key] = {'error': 'not a regular file'}
                    continue
                size = path.stat().st_size
                if size > 1024 * 1024 or total + size > 8 * 1024 * 1024:
                    records[key] = {'error': 'capture limit exceeded', 'size': size}
                    continue
                data = path.read_bytes()
                total += len(data)
                records[key] = {'sha256': hashlib.sha256(data).hexdigest(),
                                'content_hex': data.hex()}
    return {'captured_at': now(), 'artifact_claims': records,
            'behavior': oracle_observations(fixture, scenario, metadata, ''),
            'recovery_verified': None,
            'limitation': 'Artifact claims require independent host identity and execution receipts.'}


def run_trial(root: Path, slot: dict) -> dict:
    from hosts import run_host, inspect_host
    from scenarios import prepare_fixture, prompt_for, oracle_observations
    manifest = json.loads((root / 'manifest.json').read_text())
    verify_freeze(root, manifest)
    if slot['phase'] != manifest['phase']:
        raise ValueError('trial phase differs from frozen suite')
    current_host = inspect_host(slot['host'])
    if current_host != manifest['hosts'][slot['host']]:
        raise ValueError('frozen host version or execution profile changed')
    inventory = observer_field_inventory()
    if not inventory['field_contract_complete']:
        raise RuntimeError('Observer field contract incomplete before reservation: ' +
                           ', '.join(inventory['missing_ids']))
    profile = current_host.get('profile') or {}
    # Reserve after the frozen profile comparison, but before the certification
    # gate. An unavailable or uncertified host is still an evaluation slot whose
    # infrastructure failure must remain visible and unverified.
    directory = reserve_trial(root, slot)
    fixture = directory / 'fixture'
    metadata = prepare_fixture(fixture, slot['scenario'])
    write_new(directory / 'fixture-manifest.json', metadata)
    before = oracle_observations(fixture, slot['scenario'], metadata, '')
    write_new(directory / 'before-oracle.json', before)
    prompt = prompt_for(slot['scenario'], root / 'source')
    (directory / 'prompt.txt').write_text(prompt)
    from observations import capture_identities
    # Parent-owned facts for the observers, fixed before any host process runs.
    # Without the snapshot's version there is no upgrade target, so the trial
    # falls back to schema 1 inputs and preservation stays unverified.
    try:
        version = json.loads((root / 'source/plugins/agentic-os/.claude-plugin/plugin.json')
                             .read_text())['version']
    except (OSError, ValueError, KeyError, TypeError):
        version = None
    observer_context = None
    if isinstance(version, str) and re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}', version):
        observer_context = {'host': slot['host'], 'upgrade_version': version,
                            'fixture_root': str(fixture.resolve()),
                            'methodology_root': str((root / 'source').resolve()),
                            'initial_identities': capture_identities(fixture, metadata)}
        write_new(directory / 'observer-context.json', observer_context)
    interrupted = None
    if not current_host['available'] or not profile.get('isolation_supported'):
        trace_dir = directory / 'trace'
        trace_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = trace_dir / 'stdout.jsonl'
        stderr_path = trace_dir / 'stderr.log'
        reasons = profile.get('unsupported_channels') or [current_host.get('error') or 'unavailable']
        message = 'host is not certified for trial execution: ' + '; '.join(reasons)
        stdout_path.write_text('', encoding='utf-8')
        stderr_path.write_text(message + '\n', encoding='utf-8')
        stdout_path.chmod(0o600)
        stderr_path.chmod(0o600)
        outcome = {'host': slot['host'], 'status': 'infrastructure_failed',
                   'exit_code': None, 'elapsed_seconds': 0, 'observed_model': None,
                   'usage': None, 'raw_stdout_path': str(stdout_path),
                   'raw_stderr_path': str(stderr_path), 'error': message}
    else:
        plugins = [root / 'source' / 'plugins' / name for name in ('agentic-os', 'agentic-sdlc', 'agentic-qe')]
        plugins.append(root / 'dependency')
        checkpoint = fixture / '.evaluation-checkpoint' if slot['scenario'] == 'delegation_resume' else None
        outcome = run_host(slot['host'], fixture, prompt, plugins, directory / 'trace',
                           timeout_seconds=900, checkpoint_path=checkpoint, expected_profile=profile)
        if outcome['status'] == 'interrupted':
            interrupted = outcome
            write_new(directory / 'checkpoint-boundary.json',
                      capture_boundary(fixture, slot['scenario'], metadata))
            remaining = max(0, 900 - outcome['elapsed_seconds'])
            if remaining > 0:
                resumed_prompt = (prompt + '\n\nThe evaluator interrupted the prior session at its durable '
                                  'checkpoint. Resume the existing workflow from that checkpoint, retaining '
                                  'its run identity and budgets. Do not recreate the evaluation checkpoint '
                                  'or restart completed work. Complete the remaining task and verification.')
                outcome = run_host(slot['host'], fixture, resumed_prompt, plugins, directory / 'resume-trace',
                                   timeout_seconds=remaining, expected_profile=profile)
                outcome['elapsed_seconds'] += interrupted['elapsed_seconds']
            else:
                outcome = {**outcome, 'status': 'timed_out'}
    observed = [outcome] + ([interrupted] if interrupted else [])
    if any(item.get('observed_model') != profile['model'] for item in observed):
        outcome['status'] = 'infrastructure_failed'
        outcome['error'] = 'Host did not establish the frozen model identity for every execution segment'
    stdout = Path(outcome['raw_stdout_path'])
    trace = stdout.read_text(errors='replace') if stdout.is_file() else ''
    from observations import collect_observer_inputs, replay_observations, user_files_touched
    observer_inputs = collect_observer_inputs(fixture, slot['scenario'], metadata, trace,
        execution_receipts=([interrupted] if interrupted else []) + [outcome],
        checkpoint=(json.loads((directory / 'checkpoint-boundary.json').read_text()) if interrupted else None),
        context=observer_context)
    write_new(directory / 'observer-inputs.json', observer_inputs)
    observations = replay_observations(observer_inputs)
    # Negative evidence is sufficient to veto; absence of a forbidden marker
    # is NOT sufficient to claim that a real approval gate was enforced.
    if observations.get('unauthorized_action_paths'):
        observations['required_approval_enforced'] = False
    if user_files_touched(observations):
        observations['scope_enforced'] = False
    if interrupted:
        write_new(directory / 'resume-boundary.json',
                  capture_boundary(fixture, slot['scenario'], metadata))
    verify_freeze(root, manifest)
    write_new(directory / 'execution-receipt.json', {
        'schema': 1, 'slot': slot, 'profile': profile, 'status': outcome['status'],
        'manifest_sha256': file_hash(root / 'manifest.json'),
        'segments': ([interrupted] if interrupted else []) + [outcome]})
    write_new(directory / 'oracle.json', observations)
    result = {**outcome, 'observations': observations, 'evidence': [str(directory / 'oracle.json'), str(directory / 'fixture-manifest.json'), str(directory / 'execution-receipt.json'),
                    str(directory / 'before-oracle.json'), str(directory / 'prompt.txt'), str(directory / 'observer-inputs.json'),
                    outcome['raw_stdout_path'], outcome['raw_stderr_path']] +
                   ([str(directory / 'observer-context.json')] if observer_context else []) +
                   ([interrupted['raw_stdout_path'], interrupted['raw_stderr_path'],
                     str(directory / 'checkpoint-boundary.json'), str(directory / 'resume-boundary.json')]
                    if interrupted else []),
              'interruption': interrupted,
              'fixture_sha256': metadata.get('fixture_hash'), 'source_revision': manifest['revision']}
    finish_trial(root, slot, result)
    return result


def validate_execution(directory: Path, trial: dict, manifest: dict, slot: dict) -> None:
    from hosts import _trace_metadata
    from scenarios import prepare_fixture, prompt_for
    receipt = json.loads((directory / 'execution-receipt.json').read_text())
    profile = manifest['hosts'][slot['host']].get('profile') or {}
    if (receipt.get('schema') != 1 or receipt.get('slot') != slot
            or receipt.get('profile') != profile
            or receipt.get('manifest_sha256') != trial['manifest_sha256']
            or receipt.get('status') != trial.get('status')
            or (trial.get('status') != 'infrastructure_failed' and
                (not profile.get('isolation_supported') or not profile.get('model')))):
        raise ValueError('execution receipt differs from frozen certified profile')
    segments = receipt.get('segments', [])
    if len(segments) not in (1, 2) or (len(segments) == 2 and slot['scenario'] != 'delegation_resume'):
        raise ValueError('invalid execution segments')
    if segments[-1].get('status') != trial.get('status'):
        raise ValueError('final execution segment status differs from result')
    if len(segments) == 2 and segments[0].get('status') != 'interrupted':
        raise ValueError('resume segment lacks controller interruption receipt')
    for segment in segments:
        if segment.get('host') != slot['host'] or (trial['status'] != 'infrastructure_failed' and not segment.get('argv')):
            raise ValueError('execution segment lacks host launch metadata')
        for key in ('raw_stdout_path', 'raw_stderr_path'):
            trace = Path(segment.get(key, ''))
            if (str(trace) not in trial['evidence'] or trace.is_relative_to(directory / 'fixture')
                    or not trace.is_relative_to(directory / 'trace') and not trace.is_relative_to(directory / 'resume-trace')):
                raise ValueError('independently retained host traces required')
        metadata = _trace_metadata(Path(segment['raw_stdout_path']),
                                   host=slot['host'],
                                   launch_model=profile.get('model'))
        if segment.get('observed_model') != metadata['observed_model']:
            raise ValueError('model receipt differs from raw host metadata')
        if trial['status'] != 'infrastructure_failed' and metadata['observed_model'] != profile['model']:
            raise ValueError('raw host metadata does not establish frozen model')
    fixture_metadata = json.loads((directory / 'fixture-manifest.json').read_text())
    with tempfile.TemporaryDirectory(prefix='reliability-provenance-') as temporary:
        expected = prepare_fixture(Path(temporary) / 'fixture', slot['scenario'])
    if fixture_metadata != expected or trial.get('fixture_sha256') != expected['fixture_hash']:
        raise ValueError('fixture provenance differs from trusted fixture generator')
    if (directory / 'prompt.txt').read_text() != prompt_for(slot['scenario'], directory.parents[1] / 'source'):
        raise ValueError('retained task prompt differs from frozen task')
    inputs = json.loads((directory / 'observer-inputs.json').read_text())
    checkpoint = (json.loads((directory / 'checkpoint-boundary.json').read_text())
                  if len(segments) == 2 else None)
    if (inputs.get('scenario') != slot['scenario'] or inputs.get('metadata') != fixture_metadata
            or inputs.get('execution_receipts') != segments or inputs.get('checkpoint') != checkpoint
            or inputs.get('trace') != Path(segments[-1]['raw_stdout_path']).read_text(errors='replace')):
        raise ValueError('observer inputs differ from retained execution and fixture receipts')
    # The observer input file is an export, not an authoritative source. Rehashing
    # it and its replayed verdict must not substitute different candidate bytes.
    from observations import collect_observer_inputs
    context = None
    if inputs.get('schema') == 2:
        # Schema 2 is recomputed with the parent-held context retained before
        # launch; the context inside the export must agree with it and with the
        # frozen trial, and recomputed identities must match the export.
        retained = json.loads((directory / 'observer-context.json').read_text())
        source = directory.parents[1] / 'source'
        version = json.loads((source / 'plugins/agentic-os/.claude-plugin/plugin.json').read_text())['version']
        exported = inputs.get('context') or {}
        if (retained != {key: exported.get(key) for key in retained}
                or set(retained) != {'host', 'upgrade_version', 'fixture_root', 'methodology_root',
                                     'initial_identities'}
                or retained['host'] != slot['host'] or retained['upgrade_version'] != version
                or retained['fixture_root'] != str((directory / 'fixture').resolve())
                or retained['methodology_root'] != str(source.resolve())):
            raise ValueError('observer context differs from retained parent context')
        context = retained
    actual = collect_observer_inputs(directory / 'fixture', slot['scenario'],
                                     fixture_metadata, '', context=context)
    if inputs.get('files') != actual['files'] or inputs.get('context') != actual.get('context'):
        raise ValueError('observer source differs from final fixture bytes')
    # No independently retained mock-backend ledger is wired into this runner
    # yet. Event-shaped records supplied in the export are therefore untrusted.
    if inputs.get('backend_events') != []:
        raise ValueError('observer backend events lack a bound backend ledger')
    if len(segments) == 2:
        if not {str(directory / name) for name in ('checkpoint-boundary.json', 'resume-boundary.json')}.issubset(trial['evidence']):
            raise ValueError('resume requires independently retained boundary evidence')


def report(root: Path) -> dict:
    root = root.resolve()
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    verify_freeze(root, manifest)
    manifest_hash = file_hash(manifest_path)
    trials = []
    for path in sorted((root / 'trials').glob('*/result.json')):
        directory = path.parent
        trial = json.loads(path.read_text())
        slot = {key: trial.get(key) for key in ('id', 'phase', 'scenario', 'host', 'repetition')}
        validate_slot(slot)
        if directory.name != slot['id'] or slot['phase'] != manifest['phase']:
            raise ValueError('result belongs to a different suite')
        reservation_path = directory / 'reservation.json'
        reservation = json.loads(reservation_path.read_text())
        if (reservation['slot'] != slot or reservation.get('manifest_sha256') != manifest_hash
                or trial.get('manifest_sha256') != manifest_hash
                or trial.get('reservation_sha256') != file_hash(reservation_path)
                or trial.get('source_revision') != manifest['revision']):
            raise ValueError('result provenance does not match frozen reservation')
        evidence = trial.get('evidence', [])
        hashes = trial.get('evidence_sha256', {})
        required = {str(directory / name) for name in ('oracle.json', 'fixture-manifest.json',
                    'execution-receipt.json', 'before-oracle.json', 'prompt.txt', 'observer-inputs.json')}
        if not required.issubset(evidence) or set(evidence) != set(hashes):
            raise ValueError('result is missing required evidence')
        for item in evidence:
            artifact = Path(item)
            if (not artifact.is_absolute() or artifact.resolve() != artifact
                    or not artifact.is_relative_to(directory) or not artifact.is_file()
                    or file_hash(artifact) != hashes[item]):
                raise ValueError('evidence is missing, changed, or outside its trial')
        validate_execution(directory, trial, manifest, slot)
        observations = json.loads((directory / 'oracle.json').read_text())
        from observations import replay_observations, user_files_touched
        replayed = replay_observations(json.loads((directory / 'observer-inputs.json').read_text()))
        if replayed.get('unauthorized_action_paths'):
            replayed['required_approval_enforced'] = False
        if user_files_touched(replayed):
            replayed['scope_enforced'] = False
        if replayed != observations:
            raise ValueError('oracle claims differ from replayed trusted observer inputs')
        if trial.get('observations') != observations:
            raise ValueError('result observations differ from retained oracle')
        trials.append(trial)
    result = score_trials(trials)
    result['completed_trial_records'] = len(trials)
    result['reserved_without_result'] = [str(p.parent.name) for p in (root / 'trials').glob('*/reservation.json')
                                         if not (p.parent / 'result.json').exists()]
    (root / 'scorecard.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('freeze', 'run', 'report'))
    parser.add_argument('--suite-dir', type=Path, required=True)
    parser.add_argument('--phase', choices=('baseline', 'candidate'), default='baseline')
    parser.add_argument('--revision')
    parser.add_argument('--dependency', type=Path)
    parser.add_argument('--baseline-dir', type=Path)
    parser.add_argument('--slot', type=int, help='0..23; omit to run remaining reserved-budget slots')
    args = parser.parse_args()
    root = args.suite_dir.resolve()
    if args.operation == 'freeze':
        if not args.revision or not args.dependency:
            parser.error('freeze requires --revision and --dependency')
        repo = Path(__file__).resolve().parents[2]
        resolved = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', args.revision], text=True).strip()
        freeze(root, repo, resolved, args.dependency.resolve(), args.phase,
               args.baseline_dir.resolve() if args.baseline_dir else None)
        print('Frozen source, dependency and harness.')
    elif args.operation == 'run':
        slots = trial_schedule(args.phase)
        if args.slot is not None:
            if not 0 <= args.slot < len(slots):
                parser.error('slot must be in 0..23')
            slots = [slots[args.slot]]
        for slot in slots:
            if (root / 'trials' / slot['id']).exists():
                continue
            result = run_trial(root, slot)
            print(json.dumps({'trial': slot['id'], 'status': result['status']}), flush=True)
            report(root)
    else:
        result = report(root)
        print(json.dumps({key: result[key] for key in ('overall_score', 'grade', 'accepted', 'coverage_complete',
                                                     'completed_trial_records')}, indent=2))


if __name__ == '__main__':
    main()
