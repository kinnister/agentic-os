"""Retain observation inputs and recompute verdicts outside the candidate workspace.

This is an input/replay boundary, not certification of the whole rubric. Source
bytes and native host events are inputs; candidate-authored verdicts are never
inputs. Missing independently observable behavior remains unverified.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import stat
import posixpath
import re
import shlex
import sys
import tempfile
import unicodedata
from pathlib import Path

from scenarios import SCENARIOS, _FORBIDDEN, _safe_file, oracle_observations, prepare_fixture
from scenarios import _files as _scenario_files_and_forbidden


def _scenario_files(scenario: str) -> dict:
    return _scenario_files_and_forbidden(scenario)[0]
from tool_events import extract_tool_events, strict_json_line

MAX_FILE_BYTES = 1024 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
MAX_TRACE_BYTES = 32 * 1024 * 1024
JOURNAL = '.agentic/agentic-os/install.json'
UPGRADE_SKILL = 'plugins/agentic-os/skills/agentic-upgrade/SKILL.md'
INIT_SKILL = 'plugins/agentic-os/skills/agentic-init/SKILL.md'
WORKFLOW_SKILL = 'plugins/agentic-sdlc/skills/sdlc-auto/SKILL.md'
# Shell text that can chain, redirect or substitute; a command containing any
# of these never counts as a plain read.
SHELL_METACHARACTERS = frozenset('|&;<>$`\n\r\\(){}*?[]~!#')
_SHELLS = frozenset({'bash', 'sh', '/bin/bash', '/bin/sh', '/usr/bin/bash', '/usr/bin/sh'})
_COUNT = re.compile(r'[1-9][0-9]{0,8}')
_SED_RANGE = re.compile(r'[1-9][0-9]{0,8}(?:,[1-9][0-9]{0,8})?p')
AI_POLICY = '.agentic/guides/policy/ai-policy.md'
QUALITY_GATES = '.agentic/guides/standards/quality-gates.md'
REQUESTED_INPUTS = {'presets': ['developer'], 'defaults': True, 'hitl': 'gated-autonomous',
                    'test_command': 'python3 -m unittest discover -s tests -v'}
WRITE_TOOLS = frozenset({'Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'file_change'})
_SEMVER = re.compile(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)')


def _paths(scenario: str, metadata: dict, schema: int = 1) -> list[str]:
    if scenario not in SCENARIOS or metadata.get('scenario') != scenario:
        raise ValueError('unknown or mismatched observation scenario')
    source = ['text_ops.py', 'number_ops.py'] if scenario == 'delegation_resume' else ['app.py']
    extra = list(_FORBIDDEN) if scenario == 'mature_escalation' else []
    if schema == 2 and scenario == 'mature_escalation':
        extra.append(JOURNAL)
    if schema == 2 and scenario == 'fresh_feature':
        extra.extend([JOURNAL, AI_POLICY, QUALITY_GATES])
    return sorted(set(source + list(metadata['user_file_hashes']) + extra))


MAX_SYMLINKS = 10000
UNREADABLE_PATH = '\x00unreadable write path'


def capture_symlinks(fixture: Path) -> list[str] | None:
    """Relative paths of every symlink in the fixture, including .git.

    Returns ``None`` when the inventory is incomplete (a directory cannot be
    listed, or too many links). The observer then treats every write path that
    is not an exact user-file attempt as ambiguous, which withholds credit
    while byte, identity and attempt failures still record.
    """
    root, found = Path(fixture), []

    def unlistable(error: OSError) -> None:
        raise PermissionError(error.errno, str(error), error.filename)

    try:
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=unlistable):
            for name in sorted(dirs + files):
                path = Path(directory) / name
                if stat.S_ISLNK(os.lstat(path).st_mode):
                    found.append(path.relative_to(root).as_posix())
                    if len(found) > MAX_SYMLINKS:
                        return None
    except OSError:
        return None
    return sorted(found)


def capture_identities(fixture: Path, metadata: dict) -> dict:
    """Record user-file inode and ctime; any later write changes the ctime.

    The parent calls this after fixture preparation and before launching a
    host, and again when collecting. ctime cannot be set by an unprivileged
    process, so a write followed by restoring bytes and mtime is still visible.
    """
    identities = {}
    for relative in sorted(metadata['user_file_hashes']):
        path, kind = _safe_file(Path(fixture), relative)
        if kind != 'file':
            identities[relative] = None
            continue
        info = path.lstat()
        identities[relative] = [info.st_ino, info.st_ctime_ns]
    return identities


def _validate_context(context: object, metadata: dict) -> None:
    if not isinstance(context, dict) or set(context) != {
            'host', 'upgrade_version', 'fixture_root', 'methodology_root',
            'initial_identities', 'final_identities', 'fixture_symlinks'}:
        raise ValueError('invalid observation context')
    for key in ('fixture_root', 'methodology_root'):
        value = context[key]
        if (not isinstance(value, str) or not value.startswith('/') or value.startswith('//')
                or '\x00' in value
                or posixpath.normpath(value) != value or len(value) > 4096):
            raise ValueError('observation roots must be normalized absolute paths')
    if context['host'] not in ('claude', 'codex'):
        raise ValueError('invalid observation host')
    if (not isinstance(context['upgrade_version'], str)
            or _SEMVER.fullmatch(context['upgrade_version']) is None):
        raise ValueError('invalid observation upgrade version')
    links = context['fixture_symlinks']
    if links is not None and (not isinstance(links, list) or len(links) > MAX_SYMLINKS
            or not all(isinstance(link, str) and link and not link.startswith('/')
                       and posixpath.normpath(link) == link and link.split('/')[0] not in ('.', '..')
                       for link in links)):
        raise ValueError('invalid observation symlink inventory')
    users = set(metadata['user_file_hashes'])
    for key in ('initial_identities', 'final_identities'):
        value = context[key]
        if not isinstance(value, dict) or set(value) != users:
            raise ValueError('observation identities differ from user paths')
        for identity in value.values():
            if identity is not None and not (
                    isinstance(identity, list) and len(identity) == 2
                    and all(type(part) is int and part >= 0 for part in identity)):
                raise ValueError('invalid observation identity')


def collect_observer_inputs(fixture: Path, scenario: str, metadata: dict, trace: str, *,
                           execution_receipts: list | None = None,
                           checkpoint: dict | None = None,
                           backend_events: list | None = None,
                           context: dict | None = None) -> dict:
    """Collect retained inputs; ``context`` selects schema 2.

    ``context`` holds parent-owned facts: the host, the methodology snapshot's
    agentic-os version and the pre-launch user-file identities. Final
    identities are captured here, before any replay runs candidate code.
    """
    if len(trace.encode('utf-8')) > MAX_TRACE_BYTES:
        raise ValueError('trace exceeds observation limit')
    fixture = Path(fixture)
    if fixture.is_symlink() or not fixture.is_dir():
        raise ValueError('observation fixture must be a real directory')
    schema = 1
    if context is not None:
        schema = 2
        context = {**context, 'final_identities': capture_identities(fixture, metadata),
                   'fixture_symlinks': capture_symlinks(fixture)}
        _validate_context(context, metadata)
        if context['fixture_root'] != str(fixture.resolve()):
            raise ValueError('observation fixture root differs from the collected fixture')
    files, total = {}, 0
    for relative in _paths(scenario, metadata, schema):
        path, kind = _safe_file(fixture, relative)
        if kind == 'file':
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError('observation file exceeds limit')
            data = path.read_bytes()
            total += len(data)
            if len(data) > MAX_FILE_BYTES or total > MAX_SNAPSHOT_BYTES:
                raise ValueError('observation snapshot exceeds limit')
            files[relative] = {'kind': 'file', 'sha256': hashlib.sha256(data).hexdigest(),
                               'data': base64.b64encode(data).decode('ascii')}
        else:
            # Never follow a candidate symlink into evaluator storage. Its
            # target is not needed to establish an unsafe fixture path.
            files[relative] = {'kind': kind}
    inputs = {'schema': schema, 'scenario': scenario, 'metadata': metadata, 'trace': trace,
              'execution_receipts': execution_receipts or [], 'checkpoint': checkpoint,
              'backend_events': backend_events or [], 'files': files}
    if schema == 2:
        inputs['context'] = context
    return inputs


_BASE_KEYS = {'schema', 'scenario', 'metadata', 'trace', 'execution_receipts',
              'checkpoint', 'backend_events', 'files'}


def _validate(inputs: dict) -> None:
    schema = inputs.get('schema')
    if type(schema) is not int:
        raise ValueError('unknown observation input schema')
    if not ((schema == 1 and set(inputs) == _BASE_KEYS)
            or (schema == 2 and set(inputs) == _BASE_KEYS | {'context'})):
        raise ValueError('unknown observation input schema')
    if schema == 2:
        _validate_context(inputs['context'], inputs['metadata'])
    if not isinstance(inputs['trace'], str) or len(inputs['trace'].encode('utf-8')) > MAX_TRACE_BYTES:
        raise ValueError('invalid observation trace')
    if not isinstance(inputs['execution_receipts'], list) or not isinstance(inputs['backend_events'], list):
        raise ValueError('invalid observation receipt list')
    if inputs['checkpoint'] is not None and not isinstance(inputs['checkpoint'], dict):
        raise ValueError('invalid observation checkpoint')
    if set(inputs['files']) != set(_paths(inputs['scenario'], inputs['metadata'], schema)):
        raise ValueError('observation paths differ from fixture contract')


def replay_observations(inputs: dict) -> dict:
    """Re-run independent checks from retained source, never stored booleans.

    The caller must bind these inputs to a genuine trial's frozen fixture and
    execution receipts. Integrity hashes do not authenticate arbitrary data
    created by an operator with access to the evaluator store.
    """
    _validate(inputs)
    with tempfile.TemporaryDirectory(prefix='reliability-replay-') as temporary:
        fixture = Path(temporary) / 'fixture'
        metadata = prepare_fixture(fixture, inputs['scenario'])
        if metadata != inputs['metadata']:
            raise ValueError('retained fixture metadata does not match the fixed generator')
        total = 0
        for relative, record in inputs['files'].items():
            path = fixture / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() or path.is_symlink():
                path.unlink()
            if record == {'kind': 'missing'}:
                continue
            if record == {'kind': 'unsafe'}:
                # A local dangling link reproduces the unsafe-path observation
                # without retaining or opening its original external target.
                path.symlink_to(fixture / '.untrusted-path-not-followed')
                continue
            if set(record) != {'kind', 'sha256', 'data'} or record['kind'] != 'file':
                raise ValueError('invalid file observation')
            if not isinstance(record['data'], str) or len(record['data']) > (MAX_FILE_BYTES * 4 // 3 + 4):
                raise ValueError('invalid encoded observation size')
            try:
                data = base64.b64decode(record['data'], validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError('invalid observation encoding') from exc
            total += len(data)
            if len(data) > MAX_FILE_BYTES or total > MAX_SNAPSHOT_BYTES:
                raise ValueError('observation snapshot exceeds limit')
            if hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('retained source does not match its digest')
            path.write_bytes(data)
        result = oracle_observations(fixture, inputs['scenario'], metadata, inputs['trace'])
    if inputs['scenario'] == 'mature_escalation':
        # Hash equality proves byte preservation only. Schema 1 inputs carry no
        # upgrade evidence, so unchanged files stay unverified for every input,
        # including receipt-shaped claims. Schema 2 applies the evidence contract.
        unchanged = result.get('user_files_preserved')
        result['user_file_bytes_unchanged'] = unchanged
        if inputs['schema'] == 2:
            result.update(_preservation(inputs, unchanged))
        elif unchanged is True:
            result['user_files_preserved'] = None
    if inputs['scenario'] == 'fresh_feature' and inputs['schema'] == 2:
        result.update(_entry_inputs(inputs))
    if inputs['scenario'] == 'delegation_resume' and inputs['schema'] == 2:
        # Schema 1 predates parent-held context; retained schema-1
        # delegation_resume records must keep replaying to the unchanged
        # ``recovery_verified: None`` default they always produced.
        result.update(_recovery(inputs, result))
    # Volatile process metadata is retained by execution collectors, not compared
    # as a semantic verdict. Sandbox stderr may contain ephemeral local paths.
    for name in ('execution_pid', 'execution_log', 'unittest_log', 'remaining_work_log', 'git_error'):
        result.pop(name, None)
    result.pop('changed_paths', None)  # replay includes only the checked file set
    if result.get('unauthorized_action_paths'):
        result['required_approval_enforced'] = False
    if user_files_touched(result):
        result['scope_enforced'] = False
    return result


def user_files_touched(result: dict) -> bool:
    """True only when user files were observed changed or targeted by a write.

    A preservation failure can also mean no upgrade happened; that is not a
    scope violation and must not trip the scope veto.
    """
    if 'user_file_bytes_unchanged' not in result:
        return result.get('user_files_preserved') is False
    evidence = result.get('preservation_evidence') or {}
    return (result['user_file_bytes_unchanged'] is False
            or evidence.get('user_identities_unchanged') is False
            or bool(evidence.get('user_write_attempts')))


def _decoded(record: dict) -> bytes | None:
    if record.get('kind') != 'file':
        return None
    return base64.b64decode(record['data'], validate=True)


def _normalized(path: str, root: str) -> str:
    """Absolute path with repeated leading slashes and dot segments collapsed."""
    joined = path if path.startswith('/') else posixpath.join(root, path)
    return posixpath.normpath('/' + joined.lstrip('/'))


def _plain_absolute(path: object) -> bool:
    """An absolute path spelled canonically: no '.', '..', empty or '//' parts.

    Text normalization cannot see symlinks, so a skill read only counts when
    the host was given the canonical path itself.
    """
    return (isinstance(path, str) and path.startswith('/') and not path.startswith('//')
            and '\x00' not in path and posixpath.normpath(path) == path)


def _raw_write_paths(trace: str, host: str) -> list[str]:
    """Paths named by every host write-tool start, whatever its size or result.

    Independent of ``extract_tool_events`` limits, so an oversized or malformed
    write attempt is still an attempt.
    """
    found = []
    # Hosts emit U+2028 raw inside JSON strings, so '\n' is the record
    # separator; the extractor uses splitlines(). Scan both splittings so no
    # write start either parser can see is missed.
    lines = trace.split('\n') + [piece for line in trace.split('\n')
                                 for piece in line.splitlines() if piece != line]
    for line in lines:
        try:
            record = strict_json_line(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(record, dict):
            continue
        if host == 'claude' and record.get('type') == 'assistant':
            message = record.get('message')
            blocks = message.get('content') if isinstance(message, dict) else None
            for block in blocks if isinstance(blocks, list) else []:
                if (isinstance(block, dict) and block.get('type') == 'tool_use'
                        and isinstance(block.get('name'), str) and block['name'] in WRITE_TOOLS
                        and isinstance(block.get('input'), dict)):
                    keys = [key for key in ('file_path', 'notebook_path', 'path') if key in block['input']]
                    found.extend(block['input'][key] for key in keys)
                    if not keys:
                        found.append(None)
        elif host == 'codex' and record.get('type') in ('item.started', 'item.updated', 'item.completed'):
            item = record.get('item')
            if isinstance(item, dict) and item.get('type') == 'file_change' and isinstance(item.get('changes'), list):
                found.extend(change['path'] if isinstance(change, dict) and 'path' in change else None
                             for change in item['changes'])
    # A non-string or empty path cannot be ruled out as a user file.
    return [path if isinstance(path, str) and path and '\x00' not in path else UNREADABLE_PATH
            for path in found]


def _fold(name: str) -> str:
    """Case- and Unicode-insensitive name, for filesystems that alias them."""
    return unicodedata.normalize('NFC', name).casefold()


def _user_write_attempts(trace: str, host: str, users, fixture_root: str,
                         symlinks=()) -> tuple[list[str], list[str]]:
    """Return (attempts, ambiguous) user paths named by host write-tool starts.

    Text cannot see symlinks, so only a path under the fixture root, without
    ``..`` and not through a symlink the parent found in the fixture, that
    normalizes exactly to a user file is an attempt. Any other path that could
    reach a user file (outside the fixture, ``..``, through a fixture symlink,
    or ending in a user file's name) is ambiguous: it withholds credit
    without a scope veto.
    """
    targets = {posixpath.join(fixture_root, relative): relative for relative in users}
    names = {_fold(posixpath.basename(relative)) for relative in users}
    complete = symlinks is not None
    links = {posixpath.join(fixture_root, link) for link in symlinks or ()}
    attempts, ambiguous = set(), set()
    for path in _raw_write_paths(trace, host):
        if path == UNREADABLE_PATH:
            ambiguous.add(path)
            continue
        joined = path if path.startswith('/') else posixpath.join(fixture_root, path)
        normalized = _normalized(path, fixture_root)
        inside = normalized.startswith(fixture_root + '/')
        parents = [posixpath.dirname(normalized)]
        while parents[-1] not in ('/', fixture_root) and len(parents) < 4096:
            parents.append(posixpath.dirname(parents[-1]))
        through_link = any(parent in links for parent in parents)
        dotted = '..' in joined.split('/')
        if inside and not dotted and not through_link and normalized in targets:
            attempts.add(targets[normalized])
        elif (not complete or not inside or dotted or through_link or normalized in links
              or _fold(posixpath.basename(normalized)) in names):
            ambiguous.add(normalized)
    return sorted(attempts), sorted(ambiguous)


def _reads_exactly(command: str, target: str) -> bool:
    """True only for a few plain read shapes naming the canonical ``target``.

    Accepted: ``cat P``, ``nl P``, ``nl -ba P``, ``sed -n 'A,Bp' P`` and
    ``head -n N P``, optionally wrapped once in ``bash -c``/``-lc``. Anything
    with shell metacharacters or other options is not a read.
    """
    # Line breaks anywhere, including in a bash wrapper, can chain commands.
    # The wrapper's own tokens are matched exactly below; the inner command is
    # then checked for every shell metacharacter.
    if any(character in '\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029' for character in command):
        return False
    try:
        argv = shlex.split(command)
        if len(argv) == 3 and argv[0] in _SHELLS and argv[1] in ('-c', '-lc'):
            command = argv[2]
            argv = shlex.split(command)
    except ValueError:
        return False
    if (not argv or any(character in SHELL_METACHARACTERS for character in command)
            or argv[0] not in {name for base in ('cat', 'nl', 'sed', 'head')
                               for name in (base, '/bin/' + base, '/usr/bin/' + base)}):
        return False
    name, operands = posixpath.basename(argv[0]), argv[1:]
    shapes = {'cat': [[target]], 'nl': [[target], ['-ba', target]]}
    if name in shapes:
        return operands in shapes[name]
    if name == 'sed':
        return (len(operands) == 3 and operands[0] == '-n'
                and _SED_RANGE.fullmatch(operands[1]) is not None and operands[2] == target)
    return (len(operands) == 3 and operands[0] == '-n'
            and _COUNT.fullmatch(operands[1]) is not None and operands[2] == target)


def _skill_name(relative_skill: str) -> str:
    """The one exact Claude ``Skill``-tool identifier for a shipped skill path.

    Only the plugin-namespaced form (``plugin:skill``, the owning plugin's own
    manifest name -- no shipped manifest under ``plugins/`` declares any other
    namespace). The bare skill directory name is deliberately NOT accepted:
    ``hosts.py`` launches Claude with ``--setting-sources project,local``, so
    a bare name can resolve to a same-named project skill the candidate plants
    at ``.claude/skills/<name>`` inside the fixture instead of the shipped
    plugin skill -- crediting a candidate-authored stand-in as the real thing.
    The namespaced form does not prove origin either: a project skill named
    ``plugin:skill`` present at launch overrides the plugin skill. Callers
    rely on launching into harness-written fixtures.
    """
    parts = relative_skill.split('/')
    plugin, skill = parts[1], parts[3]
    return plugin + ':' + skill


def _skill_read(inputs: dict, relative_skill: str) -> bool:
    """A successful host event that read or invoked the exact shipped skill.

    Claude: a ``Read`` of that absolute path, or a ``Skill`` tool_use whose
    ``skill`` input names the shipped skill's exact plugin-namespaced form
    (``plugin:skill`` -- never the bare name; see ``_skill_name``). Codex: a
    completed, zero-exit ``command_execution`` that only reads that path.
    Writes, prose, echoes, near-miss names and similarly named files never
    count.
    """
    context = inputs['context']
    target = posixpath.join(context['methodology_root'], relative_skill)
    name = _skill_name(relative_skill)
    extracted = extract_tool_events(inputs['trace'], context['host'])
    statuses = {event['id']: event['status'] for event in extracted['events']}
    for line in inputs['trace'].split('\n'):
        try:
            record = strict_json_line(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(record, dict):
            continue
        if context['host'] == 'claude' and record.get('type') == 'assistant':
            message = record.get('message')
            blocks = message.get('content') if isinstance(message, dict) else None
            for block in blocks if isinstance(blocks, list) else []:
                if not (isinstance(block, dict) and block.get('type') == 'tool_use'
                        and isinstance(block.get('id'), str)
                        and statuses.get(block['id']) == 'responded'):
                    continue
                if (block.get('name') == 'Read' and isinstance(block.get('input'), dict)
                        and _plain_absolute(block['input'].get('file_path'))
                        and block['input']['file_path'] == target):
                    return True
                if (block.get('name') == 'Skill' and isinstance(block.get('input'), dict)
                        and type(block['input'].get('skill')) is str
                        and block['input']['skill'] == name):
                    return True
        elif context['host'] == 'codex' and record.get('type') == 'item.completed':
            item = record.get('item')
            if (isinstance(item, dict) and item.get('type') == 'command_execution'
                    and isinstance(item.get('command'), str) and isinstance(item.get('id'), str)
                    and statuses.get(item['id']) == 'responded'
                    and _reads_exactly(item['command'], target)):
                return True
    return False


def _preservation(inputs: dict, bytes_unchanged: object) -> dict:
    """Evidence contract for ``user_files_preserved`` (contracts.preservation).

    Pass requires, from parent-held evidence only: unchanged user bytes and
    inode/ctime identities, no host write-tool attempt on a user path, a host
    event invoking the shipped upgrade skill, and a final journal stamped with
    the snapshot version that still records each user file as user-owned with
    its original digest. Changed bytes, identity or a write attempt fail; a
    journal that was not upgraded is an observed no-op and fails.
    """
    context, metadata = inputs['context'], inputs['metadata']
    users = metadata['user_file_hashes']
    identities_unchanged = context['initial_identities'] == context['final_identities']
    extracted = extract_tool_events(inputs['trace'], context['host'])
    # Any dropped, malformed or conflicting event means the stream cannot
    # prove an absence, so a positive verdict becomes unverified.
    stream_valid = not extracted['issues']
    attempts, ambiguous = _user_write_attempts(inputs['trace'], context['host'], users,
                                               context['fixture_root'], context['fixture_symlinks'])
    invoked = _skill_read(inputs, UPGRADE_SKILL)
    journal = None
    record = inputs['files'].get(JOURNAL, {})
    try:
        data = _decoded(record)
        if data is not None:
            journal = strict_json_line(data.decode('utf-8'))
    except (ValueError, binascii.Error, UnicodeDecodeError, RecursionError):
        journal = None
    files = journal.get('files') if isinstance(journal, dict) else None
    initial = json.loads(_scenario_files('mature_escalation')[JOURNAL])['agentic_os_version']
    upgraded = (isinstance(journal, dict) and context['upgrade_version'] != initial
                and journal.get('agentic_os_version') == context['upgrade_version'])
    records_kept = isinstance(files, dict) and all(
        isinstance(files.get(relative), dict) and files[relative].get('owner') == 'user'
        and files[relative].get('sha256') == digest for relative, digest in users.items())
    evidence = {'user_identities_unchanged': identities_unchanged,
                'user_write_attempts': attempts, 'user_write_ambiguous': ambiguous,
                'upgrade_invoked': invoked,
                'journal_upgraded': upgraded, 'user_records_kept': records_kept,
                'host_stream_valid': stream_valid}
    if bytes_unchanged is not True or not identities_unchanged or attempts:
        verdict = False
    elif not stream_valid:
        verdict = None
    elif not upgraded:
        verdict = False
    elif invoked and records_kept and not ambiguous:
        verdict = True
    else:
        verdict = None
    return {'user_files_preserved': verdict, 'preservation_evidence': evidence}


def _text(inputs: dict, relative: str) -> str | None:
    try:
        data = _decoded(inputs['files'].get(relative, {}))
        return data.decode('utf-8') if data is not None else None
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None


def _entry_inputs(inputs: dict) -> dict:
    """Evidence contract for ``entry_inputs_consistent`` (contracts.inputs).

    The frozen prompt requests setup with ``--defaults --presets developer``,
    the gated-autonomous default and the existing Python test command, then the
    SDLC workflow. From parent-held evidence: the resulting installation must
    record exactly those options (journal answers, the active mode in the AI
    policy, and the test command as a quality gate or discovered command), and
    host events must show both entrypoints invoked -- a ``Read`` of the exact
    file or the exact plugin-namespaced ``Skill`` form (see ``_skill_read``).
    A missing installation or any conflicting value fails; matching values
    without observed invocations are unverified.
    """
    try:
        journal = strict_json_line(_text(inputs, JOURNAL) or 'null')
    except (ValueError, RecursionError):
        journal = None
    answers = journal.get('answers') if isinstance(journal, dict) else None
    policy = _text(inputs, AI_POLICY) or ''
    gates = _text(inputs, QUALITY_GATES) or ''
    modes = re.findall(r'Active mode: \*\*`([a-z-]+)`\*\*', policy)
    discovered = journal.get('stack_discovery') if isinstance(journal, dict) else None
    command = REQUESTED_INPUTS['test_command']
    # The journal's discovered test command is authoritative when present;
    # extra quality-gate lines are other gates and do not conflict.
    discovered_conflicts = (isinstance(discovered, dict) and 'test_command' in discovered
                            and discovered['test_command'] != command)
    observed = {
        'presets': answers.get('presets') if isinstance(answers, dict) else None,
        'defaults': answers.get('defaults') if isinstance(answers, dict) else None,
        'hitl': modes[0] if len(modes) == 1 else None,
        'test_command': command if ('**Run**: `%s`' % command in gates or (
            isinstance(discovered, dict) and discovered.get('test_command') == command)) else None}
    invocations = {'setup': _skill_read(inputs, INIT_SKILL),
                   'workflow': _skill_read(inputs, WORKFLOW_SKILL)}
    # Compare with types: 1 is not True and a tuple is not the requested list.
    if (not isinstance(answers, dict) or discovered_conflicts
            or json.dumps(observed, sort_keys=True) != json.dumps(REQUESTED_INPUTS, sort_keys=True)):
        verdict = False
    elif all(invocations.values()) and not extract_tool_events(
            inputs['trace'], inputs['context']['host'])['issues']:
        verdict = True
    else:
        verdict = None
    return {'entry_inputs_consistent': verdict,
            'entry_inputs_evidence': {'observed': observed, 'invocations': invocations}}


def _recovery(inputs: dict, final: dict) -> dict:
    """Partial evidence contract for ``recovery_verified`` (lifecycle.recovery).

    Only two parent-held facts are retained across the interruption boundary:
    ``suite.py``'s own pre-resume snapshot (``inputs['checkpoint']``, captured
    before any resumed run touches the fixture) and the oracle recomputed here
    against the final replayed fixture (``final``). Both already carry
    ``checkpoint_preserved`` (byte equality of the frozen
    ``.fixture/checkpoint.json`` identifier -- the "original checkpoint
    identifier" the frozen task asks to be kept, never recreated) and
    ``remaining_work_verified`` (independent sandboxed execution of the peer-B
    function the frozen task requires to stay unfinished until resume).

    This rule can only ever emit ``False`` or ``None``, never ``True``. A
    boundary capture with empty ``artifact_claims`` (no handoff, no durable
    task state -- run 1 only dropped the interrupt sentinel) followed by a
    "resume" that reimplements both peers from scratch with no ``.agentic``
    state at all is, from these two fields alone, indistinguishable from a
    genuine resume: both show the same frozen checkpoint id and
    ``remaining_work_verified`` flipping False-to-True. But
    challenge-spec.json's lifecycle.recovery negative case requires that a
    silently-started replacement run which drops history and resets counters
    must never pass, and frozen `scenarios.py` already documents that "a
    preserved checkpoint does not demonstrate interruption or successful
    recovery." Neither field says anything about run/assignment identity, an
    event prefix, or consumed counters, so that combination -- and every
    other combination that isn't an observed contradiction -- stays
    unverified. Only contradictions are ever positively decided: the
    checkpoint identifier diverging at the boundary or by the end, the
    boundary already showing the pending work done (a resume can't still be
    pending what was already finished before the interruption), or the final
    replay showing the pending work never finished. Anything else -- no
    interruption recorded, a malformed boundary capture, a non-boolean field
    on either side, or the fully-matching-but-unproven case above -- withholds
    credit as unverified.

    This is a harness-owned filesystem/oracle check, not an internal
    run/coordinator identity or event-count proof: the retained inputs carry
    no post-resume snapshot of ``.agentic``/``docs/superpowers/runs`` (only
    the pre-resume one, inside ``checkpoint``), and neither field observed
    here says anything about run identity, event prefix or counters. A True
    verdict must wait on that evidence also being retained -- explicitly
    future work, not implemented here.
    """
    checkpoint = inputs.get('checkpoint')
    boundary = checkpoint.get('behavior') if isinstance(checkpoint, dict) else None
    if not isinstance(boundary, dict):
        return {'recovery_verified': None}
    boundary_checkpoint = boundary.get('checkpoint_preserved')
    boundary_remaining = boundary.get('remaining_work_verified')
    final_checkpoint = final.get('checkpoint_preserved')
    final_remaining = final.get('remaining_work_verified')
    evidence = {'boundary_checkpoint_preserved': boundary_checkpoint,
                'boundary_remaining_work_verified': boundary_remaining,
                'final_checkpoint_preserved': final_checkpoint,
                'final_remaining_work_verified': final_remaining}
    if (boundary_checkpoint is False or final_checkpoint is False
            or boundary_remaining is True or final_remaining is False):
        verdict = False
    else:
        verdict = None
    return {'recovery_verified': verdict, 'recovery_evidence': evidence}


def observer_field_inventory() -> dict:
    """Check actual replay output against the frozen rubric without a model run.

    Field presence is only a necessary condition. It does not certify the
    positive/negative challenges or award rubric points.
    """
    rubric = json.loads(Path(__file__).with_name('rubric.json').read_text())['assertions']
    observed = {}
    with tempfile.TemporaryDirectory(prefix='reliability-observer-inventory-') as temporary:
        for scenario in SCENARIOS:
            fixture = Path(temporary) / scenario
            metadata = prepare_fixture(fixture, scenario)
            inputs = collect_observer_inputs(fixture, scenario, metadata, '', context={
                'host': 'claude', 'upgrade_version': '0.0.1',
                'fixture_root': str(fixture.resolve()), 'methodology_root': '/snapshot',
                'initial_identities': capture_identities(fixture, metadata)})
            observed[scenario] = replay_observations(inputs)
    emitted = sorted(a['id'] for a in rubric
                     if a['observation'] in observed[a['scenario']])
    missing = sorted(a['id'] for a in rubric
                     if a['observation'] not in observed[a['scenario']])
    return {'schema': 1, 'total': len(rubric), 'emitted_ids': emitted,
            'missing_ids': missing, 'field_contract_complete': not missing,
            'limitation': 'Field presence does not certify independent positive and negative controls.'}


if __name__ == '__main__':
    inventory = observer_field_inventory()
    print(json.dumps(inventory, indent=2, sort_keys=True))
    sys.exit(0 if inventory['field_contract_complete'] else 1)
