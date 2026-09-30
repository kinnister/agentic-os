"""Normalize native host tool events without trusting model prose or tool output.

These records show tool attempts and host responses. They do not establish actor
identity, actual filesystem effects, or a successful product control by themselves.
The caller must bind the trace to a launched host and frozen fixture separately.
"""
from __future__ import annotations

import hashlib
import json

MAX_EVENTS = 8192
MAX_PATH_LENGTH = 4096
MAX_TRACE_BYTES = 32 * 1024 * 1024


def _reject_constant(value: str) -> None:
    raise ValueError('non-finite JSON constant: ' + value)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def strict_json_line(line: str) -> object:
    return json.loads(line, parse_constant=_reject_constant,
                      object_pairs_hook=_unique_pairs)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _paths(tool: str, payload: object) -> list[str]:
    if tool == 'file_change' and isinstance(payload, list):
        values = [change.get('path') for change in payload if isinstance(change, dict)]
    elif isinstance(payload, dict):
        values = [payload.get('file_path'), payload.get('path')]
    else:
        values = []
    return sorted({value for value in values if isinstance(value, str)
                   and 0 < len(value) <= MAX_PATH_LENGTH})


def _valid_payload(tool: str, payload: object) -> bool:
    if len(json.dumps(payload, sort_keys=True, separators=(',', ':'))) > 32768:
        return False
    if tool == 'command_execution':
        return isinstance(payload, str) and bool(payload)
    if tool == 'file_change':
        return (isinstance(payload, list) and bool(payload)
                and len(_paths(tool, payload)) == len(payload))
    if not isinstance(payload, dict):
        return False
    if tool == 'Bash':
        return isinstance(payload.get('command'), str) and bool(payload['command'])
    if tool in ('Write', 'Edit', 'Read'):
        return bool(_paths(tool, payload))
    return True


def _valid_claude_result(block: dict) -> bool:
    content = block.get('content')
    return (('is_error' not in block or type(block['is_error']) is bool)
            and (isinstance(content, str)
                 or (isinstance(content, list)
                     and all(isinstance(part, dict)
                             and isinstance(part.get('type'), str)
                             and bool(part['type']) for part in content))))


def extract_tool_events(trace: str, host: str) -> dict:
    """Return bounded tool attempts paired with native results when available.

    Only top-level Claude assistant/user tool blocks and Codex item lifecycle
    events are parsed. Nested JSON in a tool result or aggregated output is data.
    Incomplete or conflicting event pairs remain unverified.
    """
    if host not in ('claude', 'codex') or not isinstance(trace, str):
        raise ValueError('unknown host or invalid trace')
    try:
        trace_size = len(trace.encode('utf-8'))
    except UnicodeEncodeError:
        return {'events': [], 'issues': ['invalid host stream encoding']}
    if trace_size > MAX_TRACE_BYTES:
        raise ValueError('host trace exceeds tool event limit')
    events: list[dict] = []
    by_id: dict[str, dict] = {}
    poisoned_ids: set[str] = set()
    issues: list[str] = []
    stream_valid = True

    def issue(message: str) -> None:
        if len(issues) >= MAX_EVENTS:
            raise ValueError('host tool issue limit exceeded')
        issues.append(message)

    def poison(identifier: object) -> None:
        if not isinstance(identifier, str) or not identifier or len(identifier) > 256:
            return
        if identifier not in poisoned_ids and len(poisoned_ids) >= MAX_EVENTS:
            raise ValueError('host tool identity limit exceeded')
        poisoned_ids.add(identifier)
        if identifier in by_id:
            by_id[identifier]['status'] = 'unverified'
            by_id[identifier]['_invalid'] = True

    def start(identifier: object, tool: object, payload: object, parent: object = None) -> None:
        if (not isinstance(identifier, str) or not identifier or len(identifier) > 256
                or not isinstance(tool, str) or not tool or len(tool) > 100):
            poison(identifier)
            issue('invalid tool start identity')
            return
        if identifier in poisoned_ids:
            issue('poisoned tool start')
            return
        if not _valid_payload(tool, payload):
            poison(identifier)
            issue('invalid tool start payload')
            return
        if identifier in by_id:
            poison(identifier)
            issue('duplicate tool start')
            return
        if len(events) >= MAX_EVENTS:
            raise ValueError('host tool event limit exceeded')
        event = {'id': identifier, 'tool': tool, 'status': 'unverified',
                 'input_sha256': _digest(payload), 'paths': _paths(tool, payload),
                 'parent_tool_use_id': parent if isinstance(parent, str) else None,
                 'exit_code': None}
        by_id[identifier] = event
        events.append(event)

    def finish(identifier: object, tool: object, payload: object, status: str,
               exit_code: object = None, *, require_payload: bool = False) -> None:
        if not isinstance(identifier, str) or identifier not in by_id:
            poison(identifier)
            issue('tool result without start')
            return
        event = by_id[identifier]
        if (identifier in poisoned_ids or event.get('_invalid')
                or event['status'] != 'unverified' or event.get('_finished')):
            poison(identifier)
            issue('duplicate tool result')
            return
        if tool is not None and tool != event['tool']:
            poison(identifier)
            issue('tool result type differs from start')
            return
        if ((require_payload and not _valid_payload(event['tool'], payload))
                or (payload is not None and _digest(payload) != event['input_sha256'])):
            poison(identifier)
            issue('tool result input differs from start')
            return
        if exit_code is not None and (type(exit_code) is not int or exit_code < 0):
            poison(identifier)
            issue('invalid tool exit code')
            return
        event['exit_code'] = exit_code
        event['status'] = status
        event['_finished'] = True

    for line in trace.splitlines():
        try:
            record = strict_json_line(line)
        except (ValueError, RecursionError):
            issue('invalid host stream line')
            stream_valid = False
            continue
        if not isinstance(record, dict):
            issue('invalid host stream event')
            stream_valid = False
            continue
        kind = record.get('type')
        if host == 'claude' and kind == 'assistant':
            message = record.get('message')
            blocks = message.get('content') if isinstance(message, dict) else None
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if isinstance(block, dict) and block.get('type') == 'tool_use':
                    start(block.get('id'), block.get('name'), block.get('input'),
                          record.get('parent_tool_use_id'))
        elif host == 'claude' and kind == 'user':
            message = record.get('message')
            blocks = message.get('content') if isinstance(message, dict) else None
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if isinstance(block, dict) and block.get('type') == 'tool_result':
                    if not _valid_claude_result(block):
                        poison(block.get('tool_use_id'))
                        issue('invalid Claude tool result')
                        continue
                    result_status = 'failed' if block.get('is_error', False) else 'responded'
                    finish(block.get('tool_use_id'), None, None, result_status)
        elif host == 'codex' and kind in ('item.started', 'item.completed'):
            item = record.get('item')
            if not isinstance(item, dict):
                issue('invalid Codex lifecycle item')
                stream_valid = False
                continue
            if item.get('type') not in ('command_execution', 'file_change'):
                identifier = item.get('id')
                if isinstance(identifier, str) and identifier in by_id:
                    issue('Codex lifecycle type differs from start')
                poison(identifier)
                continue
            tool = item['type']
            payload = item.get('command') if tool == 'command_execution' else item.get('changes')
            if kind == 'item.started':
                if item.get('status') != 'in_progress':
                    poison(item.get('id'))
                    issue('invalid Codex tool start status')
                    continue
                start(item.get('id'), tool, payload)
            else:
                exit_code = item.get('exit_code') if tool == 'command_execution' else None
                native_status = item.get('status')
                if native_status not in ('completed', 'failed'):
                    issue('unknown tool result status')
                    result_status = 'unverified'
                elif tool == 'command_execution' and exit_code is None:
                    issue('missing command exit code')
                    result_status = 'unverified'
                elif tool == 'command_execution' and native_status == 'failed' and exit_code == 0:
                    issue('contradictory command result')
                    result_status = 'unverified'
                elif tool == 'command_execution':
                    result_status = 'failed' if exit_code != 0 else 'responded'
                else:
                    result_status = 'failed' if native_status == 'failed' else 'responded'
                finish(item.get('id'), tool, payload, result_status, exit_code,
                       require_payload=True)

    for event in events:
        if not stream_valid:
            event['status'] = 'unverified'
        event.pop('_finished', None)
        event.pop('_invalid', None)
    return {'events': events, 'issues': issues}
