#!/usr/bin/env python3
"""Read one versioned JSON request; emit one JSON result without repository writes."""
import json
import os
import sqlite3
import sys

from agentic_runtime.contracts import load_registry, resolve_policy, normalize_input, validate_identifier, validate_transition, retry_allowed, lookup_contract
from agentic_runtime.store import RuntimeStore, validate_run_ownership
from agentic_runtime.host import preflight, require_capabilities
from agentic_runtime.trace import ingest_command_event
from agentic_runtime.host import adapt_command_event
from agentic_runtime.installer import plan_install, apply_install, remove_install, merge_settings_file, record_journal


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field: " + key)
        result[key] = value
    return result


def main():
    try:
        request = json.load(sys.stdin, object_pairs_hook=unique_object)
        if not isinstance(request, dict) or request.get('api_version') != '1.0.0':
            raise ValueError('unsupported api_version')
        operation = request.get('operation')
        common = {'root'}
        fields = {'registry.get': ({'api_version', 'operation'}, set()),
                  'policy.resolve': ({'api_version', 'operation', 'entrypoint'}, {'overrides'}),
                  'contract.lookup': ({'api_version', 'operation', 'section', 'identifier'}, set()),
                  'input.normalize': ({'api_version', 'operation', 'payload'}, {'legacy'}),
                  'transition.validate': ({'api_version', 'operation', 'source', 'target'}, set()),
                  'retry.allowed': ({'api_version', 'operation', 'loop_id', 'attempts_used'}, set()),
                  'run.start': ({'api_version', 'operation', 'task_input', 'coordinator_id', 'branch', 'worktree'}, {'run_id', 'metadata', 'precondition', 'root'}),
                  'run.status': ({'api_version', 'operation', 'run_id'}, {'root'}),
                  'run.resume': ({'api_version', 'operation', 'run_id', 'coordinator_id'}, {'root'}),
                  'run.cancel': ({'api_version', 'operation', 'run_id', 'coordinator_id'}, {'root'}),
                  'run.transition': ({'api_version', 'operation', 'run_id', 'target', 'coordinator_id', 'lease_epoch'}, {'expected_revision', 'reason', 'root'}),
                  'run.complete': ({'api_version', 'operation', 'run_id', 'host_record', 'coordinator_id', 'lease_epoch'}, {'expected_revision', 'root'}),
                  'task.dispatch': ({'api_version', 'operation', 'run_id', 'reservation_id', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'max_dispatches', 'root'}),
                  'task.result': ({'api_version', 'operation', 'run_id', 'reservation_id', 'outcome', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'root'}),
                  'dispatch.start': ({'api_version', 'operation', 'run_id', 'reservation_id', 'worker_id', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'timeout_seconds', 'root'}),
                  'dispatch.finish': ({'api_version', 'operation', 'run_id', 'reservation_id', 'outcome', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'root'}),
                  'dispatch.recover': ({'api_version', 'operation', 'run_id', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'root'}),
                  'decision.record': ({'api_version', 'operation', 'run_id', 'decision_key', 'value', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'root'}),
                  'event.record': ({'api_version', 'operation', 'run_id', 'event_id', 'event_type', 'payload', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'root'}),
                  'message.deliver': ({'api_version', 'operation', 'run_id', 'body', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'sender', 'root'}),
                  'external.intent': ({'api_version', 'operation', 'run_id', 'idempotency_key', 'action', 'request', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'root'}),
                  'external.reconcile': ({'api_version', 'operation', 'run_id', 'idempotency_key', 'status', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'result', 'root'}),
                  'assignment.create': ({'api_version', 'operation', 'run_id', 'assignment_id', 'worker_id', 'owned_paths', 'context_refs', 'acceptance', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'limits', 'depends_on', 'root'}),
                  'assignment.transition': ({'api_version', 'operation', 'run_id', 'assignment_id', 'target', 'expected_assignment_revision', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'worker_id', 'root'}),
                  'message.send': ({'api_version', 'operation', 'run_id', 'message_id', 'assignment_id', 'assignment_revision', 'correlation_id', 'sender', 'recipient', 'message_type', 'deadline', 'payload', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'host_record', 'root'}),
                  'runtime.recover': ({'api_version', 'operation', 'run_id', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'root'}),
                  'message.receive': ({'api_version', 'operation', 'run_id', 'recipient'}, {'reader_id', 'host_record', 'limit', 'after_message_id', 'root'}),
                  'host.preflight': ({'api_version', 'operation'}, {'root', 'required_capabilities'}),
                  'evidence.record': ({'api_version', 'operation', 'run_id', 'evidence_id', 'kind', 'source_revision', 'command', 'cwd', 'source_hash', 'exit_status', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'required', 'host_record', 'root'}),
                  'evidence.ingest': ({'api_version', 'operation', 'event', 'coordinator_id', 'lease_epoch', 'expected_revision'}, {'root'}),
                  'trace.adapt': ({'api_version', 'operation', 'event', 'identity', 'issued_at', 'expires_at'}, set()),
                  'install.plan': ({'api_version', 'operation', 'target', 'files'}, set()),
                  'install.apply': ({'api_version', 'operation', 'target', 'files'}, {'agentic_os_version'}),
                  'install.merge-settings': ({'api_version', 'operation', 'target', 'path', 'fragment'}, {'agentic_os_version'}),
                  'install.remove': ({'api_version', 'operation', 'target'}, {'paths', 'confirm'}),
                  'install.record': ({'api_version', 'operation', 'target', 'fields'}, set()),
                  'run.export': ({'api_version', 'operation', 'run_id'}, {'root'})}
        fields['legacy.export'] = ({'api_version', 'operation', 'run_id', 'destination'}, {'root'})
        fields['legacy.import'] = ({'api_version', 'operation', 'run_id', 'source'}, {'root'})
        if not isinstance(operation, str) or operation not in fields:
            raise ValueError('unknown operation')
        required, optional = fields[operation]
        if not required <= set(request) or set(request) - required - optional:
            raise ValueError('unknown or missing request fields')
        if operation == 'registry.get':
            value = load_registry()
        elif operation == 'policy.resolve':
            value = resolve_policy(request['entrypoint'], request.get('overrides'))
        elif operation == 'contract.lookup':
            value = lookup_contract(request['section'], request['identifier'])
        elif operation == 'input.normalize':
            value = normalize_input(request['payload'], request.get('legacy', False))
        elif operation == 'transition.validate':
            value = validate_transition(request['source'], request['target'])
        elif operation == 'retry.allowed':
            value = retry_allowed(request['loop_id'], request['attempts_used'])
        elif operation == 'host.preflight':
            value = preflight(request.get('root', os.getcwd()))
            if 'required_capabilities' in request:
                value = require_capabilities(value, request['required_capabilities'])
        elif operation == 'trace.adapt':
            key = os.environ.get('AGENTIC_HOST_KEY')
            if not key:
                raise RuntimeError('host signing key is required')
            value = adapt_command_event(request['event'], key, identity=request['identity'],
                                        issued_at=request['issued_at'], expires_at=request['expires_at'])
        elif operation == 'install.plan':
            value = plan_install(request['target'], request['files'])
        elif operation == 'install.apply':
            value = apply_install(request['target'], request['files'],
                                  agentic_os_version=request.get('agentic_os_version'))
        elif operation == 'install.merge-settings':
            value = merge_settings_file(request['target'], request['path'], request['fragment'],
                                        agentic_os_version=request.get('agentic_os_version'))
        elif operation == 'install.remove':
            value = remove_install(request['target'], request.get('paths'),
                                   confirm=request.get('confirm'))
        elif operation == 'install.record':
            value = record_journal(request['target'], request['fields'])
        else:
            root = request.get('root', os.getcwd())
            if operation == 'run.start':
                # RuntimeStore initializes SQLite in its constructor. Validate
                # every start precondition that can fail without state first.
                normalized = normalize_input({'contract_version': '1.0.0', 'task_input': request['task_input']})
                metadata = dict(request.get('metadata') or {})
                if 'task_input' in metadata and metadata['task_input'] != normalized['task_input']:
                    raise ValueError('task_input metadata conflicts with the authoritative run input')
                metadata['task_input'] = normalized['task_input']
                if 'run_id' in request:
                    validate_identifier(request['run_id'])
                try:
                    validate_identifier(request['coordinator_id'])
                except ValueError as exc:
                    raise ValueError('invalid coordinator_id') from exc
                if (not isinstance(request['branch'], str) or not request['branch']
                        or not isinstance(request['worktree'], str) or not request['worktree']):
                    raise ValueError('branch and worktree are required for run.start')
                validate_run_ownership(request['branch'], request['worktree'], request.get('precondition'))
            store = RuntimeStore(root, host_key=os.environ.get('AGENTIC_HOST_KEY'))
            if operation == 'run.start':
                value = store.create_run(request.get('run_id'), branch=request['branch'], worktree=request['worktree'], metadata=metadata, precondition=request.get('precondition'))
                value = store.acquire_lease(value['run_id'], request['coordinator_id'])
                value = store.transition(value['run_id'], 'running', expected_revision=value['revision'], lease_epoch=value['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation == 'run.status':
                value = store.get_run(request['run_id'])
            elif operation == 'run.resume':
                current = store.get_run(request['run_id'])
                if current['state'] not in {'interrupted', 'waiting_for_user', 'reconciliation_required'}:
                    raise ValueError('run cannot be resumed from ' + current['state'])
                value = store.acquire_lease(request['run_id'], request['coordinator_id'], expected_revision=current['revision'])
                value = store.transition(request['run_id'], 'running', expected_revision=value['revision'], lease_epoch=value['lease_epoch'], coordinator_id=request['coordinator_id'], reason='resumed')
            elif operation == 'run.cancel':
                current = store.get_run(request['run_id'])
                if current['state'] not in {'pending', 'running', 'waiting_for_user', 'interrupted', 'reconciliation_required'}:
                    raise ValueError('run cannot be cancelled from ' + current['state'])
                value = store.acquire_lease(request['run_id'], request['coordinator_id'], expected_revision=current['revision'])
                value = store.transition(request['run_id'], 'cancelled', expected_revision=value['revision'], lease_epoch=value['lease_epoch'], coordinator_id=request['coordinator_id'], reason='cancelled')
            elif operation == 'run.transition':
                value = store.transition(request['run_id'], request['target'], expected_revision=request.get('expected_revision'), lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'], reason=request.get('reason'))
            elif operation == 'run.complete':
                value = store.complete_run(request['run_id'], host_record=request['host_record'], expected_revision=request.get('expected_revision'), lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation == 'task.dispatch':
                value = store.reserve_dispatch(request['run_id'], request['reservation_id'], max_dispatches=request.get('max_dispatches'), expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation == 'dispatch.start':
                value = store.start_dispatch(request['run_id'], request['reservation_id'], request['worker_id'], timeout_seconds=request.get('timeout_seconds'), expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation in {'dispatch.finish', 'task.result'}:
                value = store.finish_dispatch(request['run_id'], request['reservation_id'], outcome=request['outcome'], expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation == 'dispatch.recover':
                value = store.recover_dispatches(request['run_id'], expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation == 'decision.record':
                value = store.record_decision(request['run_id'], request['decision_key'], request['value'], expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation == 'event.record':
                value = store.record_event(request['run_id'], request['event_id'], request['event_type'], request['payload'], expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation == 'message.deliver':
                value = store.record_message(request['run_id'], request['body'], sender=request.get('sender'), expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation == 'external.intent':
                value = store.record_external_intent(request['run_id'], request['idempotency_key'], request['action'], request['request'], expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation == 'external.reconcile':
                value = store.reconcile_external(request['run_id'], request['idempotency_key'], status=request['status'], result=request.get('result'), expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation == 'assignment.create':
                value = store.create_assignment(request['run_id'], request['assignment_id'], request['worker_id'], owned_paths=request['owned_paths'], context_refs=request['context_refs'], acceptance=request['acceptance'], limits=request.get('limits'), depends_on=request.get('depends_on'), expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation == 'assignment.transition':
                value = store.assignment_transition(request['run_id'], request['assignment_id'], request['target'], expected_assignment_revision=request['expected_assignment_revision'], worker_id=request.get('worker_id'), expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation == 'message.send':
                value = store.send_peer_message(request['run_id'], message_id=request['message_id'], assignment_id=request['assignment_id'], assignment_revision=request['assignment_revision'], correlation_id=request['correlation_id'], sender=request['sender'], recipient=request['recipient'], message_type=request['message_type'], deadline=request['deadline'], payload=request['payload'], expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'], host_record=request.get('host_record'))
            elif operation == 'runtime.recover':
                value = store.recover_timeouts(request['run_id'], expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation == 'message.receive':
                value = store.receive_peer_messages(request['run_id'], request['recipient'], reader_id=request.get('reader_id'), host_record=request.get('host_record'), limit=request.get('limit', 8), after_message_id=request.get('after_message_id'))
            elif operation == 'evidence.record':
                value = store.record_evidence(request['run_id'], request['evidence_id'], kind=request['kind'], source_revision=request['source_revision'], command=request['command'], cwd=request['cwd'], source_hash=request['source_hash'], exit_status=request['exit_status'], required=request.get('required', True), expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'], host_record=request.get('host_record'))
            elif operation == 'evidence.ingest':
                value = ingest_command_event(store, request['event'], expected_revision=request['expected_revision'], lease_epoch=request['lease_epoch'], coordinator_id=request['coordinator_id'])
            elif operation == 'legacy.import':
                value = store.import_legacy(request['run_id'], request['source'])
            elif operation == 'legacy.export':
                value = store.export_legacy(request['run_id'], request['destination']).as_posix()
            else:
                value = store.export_run(request['run_id']).as_posix()
        result = {'api_version': '1.0.0', 'ok': True, 'result': value}
        status = 0
    except (ValueError, TypeError, KeyError, RuntimeError, OSError, sqlite3.Error) as error:
        result = {'api_version': '1.0.0', 'ok': False,
                  'error': {'code': 'invalid_request', 'message': str(error)}}
        status = 2
    print(json.dumps(result, sort_keys=True))
    return status


if __name__ == '__main__':
    sys.exit(main())
