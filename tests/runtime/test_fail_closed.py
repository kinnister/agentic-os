import json
import math
import sqlite3
import tempfile
import unittest

from runtime.agentic_runtime.store import RuntimeStore
from runtime.agentic_runtime.contracts import load_registry
from runtime.agentic_runtime.host import sign_dispatch


class FailClosedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 100.0
        self.store = RuntimeStore(self.tmp.name, clock=lambda: self.now, host_key=b'message-key')
        self.make_run('r')

    def make_run(self, name):
        self.store.create_run(name)
        self.store.transition(name, 'running')
        self.store.create_assignment(name, 'a', 'worker', owned_paths=[], context_refs=[], acceptance=[])

    def send(self, run='r', **changes):
        args = dict(message_id=run+'q', assignment_id='a', assignment_revision=0,
                    correlation_id='shared', sender='worker', recipient='peer',
                    message_type='question.request', deadline=200, payload={})
        args.update(changes)
        args.setdefault('host_record', sign_dispatch({
            'record_id': args['message_id'], 'purpose': 'message.send', 'run_id': run,
            'assignment_id': args['assignment_id'], 'assignment_revision': args['assignment_revision'],
            'identity': args['sender'], 'issued_at': 0, 'expires_at': 9999999999,
        }, b'message-key'))
        return self.store.send_peer_message(run, **args)

    def test_completion_denied_even_with_caller_written_evidence(self):
        with self.assertRaisesRegex(RuntimeError, 'completion'):
            self.store.transition('r', 'completed')
        rev = self.store.get_run('r')['revision']
        self.store.record_evidence('r', 'e', kind='host-certification', source_revision=rev,
                                   command='true', cwd='/', source_hash='claimed', exit_status=0)
        with self.assertRaisesRegex(RuntimeError, 'completion'):
            self.store.transition('r', 'completed')
        rev = self.store.get_run('r')['revision']
        self.store.record_evidence('r', 'optional', kind='acceptance', source_revision=rev,
                                   command='false', cwd='/', source_hash='claimed', exit_status=1, required=False)
        with self.assertRaisesRegex(RuntimeError, 'completion'):
            self.store.transition('r', 'completed')
        self.assertEqual(self.store.transition('r', 'cancelled')['state'], 'cancelled')

    def test_mailbox_identity_strings_never_unlock_delivery(self):
        self.send()
        for reader in ('peer', 'worker', 'forged'):
            with self.assertRaisesRegex(RuntimeError, 'host-issued'):
                self.store.receive_peer_messages('r', 'peer', reader_id=reader)
        self.assertEqual(len(self.store._inspect_peer_messages('r', 'peer')), 1)

    def test_unsigned_worker_sender_cannot_publish_peer_message(self):
        with self.assertRaisesRegex(RuntimeError, 'host-issued sender identity'):
            self.store.send_peer_message(
                'r', message_id='unsigned', assignment_id='a', assignment_revision=0,
                correlation_id='unsigned-correlation', sender='worker', recipient='peer',
                message_type='task.progress', deadline=200, payload={},
                coordinator_id='coord', lease_epoch=self.store.get_run('r')['lease_epoch'],
                expected_revision=self.store.get_run('r')['revision'])

    def test_dispatch_ceiling_survives_reopen_and_resume(self):
        self.assertTrue(self.store.reserve_dispatch('r', 'one', max_dispatches=1)['reserved'])
        self.store.transition('r', 'interrupted')
        self.store = RuntimeStore(self.tmp.name, clock=lambda: self.now)
        self.store.transition('r', 'running')
        for ceiling in (None, 64):
            self.assertFalse(self.store.reserve_dispatch('r', 'two', max_dispatches=ceiling)['reserved'])
        self.assertTrue(self.store.reserve_dispatch('r', 'one')['reserved'])

    def test_run_cancellation_closes_inflight_dispatch_leases(self):
        self.assertTrue(self.store.reserve_dispatch('r', 'cancel-me')['reserved'])
        run = self.store.get_run('r')
        self.store.start_dispatch('r', 'cancel-me', 'worker',
                                  expected_revision=run['revision'])
        run = self.store.get_run('r')
        cancelled = self.store.transition('r', 'cancelled',
                                          expected_revision=run['revision'])
        self.assertEqual(cancelled['state'], 'cancelled')
        with self.store._connect() as db:
            lease = db.execute(
                "SELECT finished_at,outcome FROM dispatch_leases WHERE run_id=? AND reservation_id=?",
                ('r', 'cancel-me')).fetchone()
        self.assertIsNotNone(lease['finished_at'])
        self.assertEqual(lease['outcome'], 'cancelled')

    def test_versions_rejected_on_open_and_before_existing_handle_mutation(self):
        for key in ('schema_version', 'registry_contract_version'):
            with sqlite3.connect(self.store.db_path) as db:
                old = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()[0]
                db.execute('UPDATE metadata SET value=? WHERE key=?', ('unsupported', key))
            before = self.store.db_path.read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'version'):
                RuntimeStore(self.tmp.name)
            with self.assertRaisesRegex(RuntimeError, 'version'):
                self.store.record_decision('r', 'plan.approved', {'decision': 'approve', 'source': 'hitl', 'artifact_hashes': {'plan': 'sha256:plan'}})
            self.assertEqual(before, self.store.db_path.read_bytes())
            with sqlite3.connect(self.store.db_path) as db:
                db.execute('UPDATE metadata SET value=? WHERE key=?', (old, key))

    def test_interrupted_initialization_repairs_on_reopen(self):
        # A partially-created metadata table is recoverable; a mismatched
        # declared version still remains fail-closed.
        with sqlite3.connect(self.store.db_path) as db:
            db.execute('DROP TABLE runs')
        reopened = RuntimeStore(self.tmp.name, clock=lambda: self.now)
        run = reopened.create_run('recovered')
        self.assertEqual(run['state'], 'pending')

    def test_partial_version_marker_repairs_on_reopen(self):
        with sqlite3.connect(self.store.db_path) as db:
            db.execute("DELETE FROM metadata WHERE key='registry_contract_version'")
        reopened = RuntimeStore(self.tmp.name, clock=lambda: self.now)
        self.assertEqual(reopened.get_run('r')['state'], 'running')

    def test_deadline_must_be_finite_and_question_bounded(self):
        for deadline in (math.inf, -math.inf, math.nan, 401):
            with self.assertRaises(ValueError):
                self.send(deadline=deadline)
        self.send(deadline=400)

    def test_other_run_response_does_not_answer_question(self):
        self.send()
        self.make_run('other')
        self.send('other', sender='worker', recipient='worker')
        self.send('other', message_id='reply', message_type='question.response', recipient='worker')
        ceiling = load_registry()['policy_defaults']['max_outstanding_questions']
        for index in range(1, ceiling):
            self.send(message_id='extra'+str(index), correlation_id='extra'+str(index))
        with self.assertRaisesRegex(RuntimeError, 'question budget'):
            self.send(message_id='overflow', correlation_id='overflow')
        self.now = 201
        self.assertEqual(self.store.recover_timeouts('r')['escalated_assignments'], ['a'])

    def test_terminal_assignment_cannot_be_resurrected_by_expired_message(self):
        self.store.assignment_transition('r', 'a', 'cancelled', expected_assignment_revision=0)
        with self.assertRaises(RuntimeError):
            self.send(assignment_revision=1, deadline=99)
        self.assertEqual(self.store.assignment('r', 'a')['state'], 'cancelled')

    def test_recovery_is_idempotent(self):
        self.send()
        self.now = 201
        self.assertEqual(self.store.recover_timeouts('r')['escalated_assignments'], ['a'])
        before = self.store.get_run('r')['revision'], self.store.assignment('r', 'a')['revision']
        self.assertEqual(self.store.recover_timeouts('r')['escalated_assignments'], [])
        self.assertEqual(before, (self.store.get_run('r')['revision'], self.store.assignment('r', 'a')['revision']))

    def test_run_cancellation_cascades_unfinished_assignments(self):
        self.store.create_assignment('r', 'b', 'worker', owned_paths=[], context_refs=[], acceptance=[])
        self.store.assignment_transition('r', 'b', 'running', expected_assignment_revision=0)
        self.store.assignment_transition('r', 'b', 'failed', expected_assignment_revision=1)
        self.store.transition('r', 'cancelled')
        self.assertEqual(self.store.assignment('r', 'a')['state'], 'cancelled')
        self.assertEqual(self.store.assignment('r', 'b')['state'], 'failed')

    def test_question_correlations_cannot_be_reused_or_answered_twice(self):
        self.send(recipient='worker')
        with self.assertRaises(ValueError):
            self.send(message_id='duplicate')
        self.send(message_id='response', recipient='worker', message_type='question.response')
        with self.assertRaises(ValueError):
            self.send(message_id='response-two', recipient='worker', message_type='question.response')
        self.now = 201
        self.assertEqual(self.store.recover_timeouts('r')['escalated_assignments'], [])

    def test_question_correlation_allows_two_bounded_rounds(self):
        self.store = RuntimeStore(self.tmp.name, clock=lambda: self.now, host_key=b'round-key')
        self.store.create_run('rounds')
        self.store.transition('rounds', 'running')
        self.store.create_assignment('rounds', 'peer-task', 'peer', owned_paths=[], context_refs=[], acceptance=[])
        self.store.create_assignment('rounds', 'worker-task', 'worker', owned_paths=[], context_refs=[], acceptance=[])
        base = dict(assignment_id='peer-task', assignment_revision=0, correlation_id='rounds-correlation',
                    deadline=200, payload={})
        def reply_record(record_id, identity='worker', assignment_id='peer-task'):
            return sign_dispatch({'record_id': record_id, 'purpose': 'message.send', 'run_id': 'rounds',
                                  'assignment_id': assignment_id, 'assignment_revision': 0,
                                  'identity': identity, 'issued_at': 99, 'expires_at': 200}, b'round-key')
        self.store.send_peer_message('rounds', message_id='q1', sender='peer', recipient='worker',
                                     host_record=reply_record('q1', 'peer'),
                                     message_type='question.request', **base)
        response_base = dict(base, assignment_id='worker-task')
        self.store.send_peer_message('rounds', message_id='a1', sender='worker', recipient='peer',
                                     message_type='question.response', host_record=reply_record('reply-1', assignment_id='worker-task'), **response_base)
        self.store.send_peer_message('rounds', message_id='q2', sender='peer', recipient='worker',
                                     host_record=reply_record('q2', 'peer'),
                                     message_type='question.request', **base)
        self.store.send_peer_message('rounds', message_id='a2', sender='worker', recipient='peer',
                                     message_type='question.response', host_record=reply_record('reply-2', assignment_id='worker-task'), **response_base)
        with self.assertRaises(ValueError):
            self.store.send_peer_message('rounds', message_id='a3', sender='worker', recipient='peer',
                                         message_type='question.response', host_record=reply_record('reply-3', assignment_id='worker-task'), **response_base)

    def test_ceiling_tightening_persists_on_denial_and_idempotent_reservation(self):
        for name in ('first', 'second'):
            self.store.reserve_dispatch('r', name, max_dispatches=5)
        self.assertFalse(self.store.reserve_dispatch('r', 'denied', max_dispatches=1)['reserved'])
        self.assertFalse(RuntimeStore(self.tmp.name).reserve_dispatch('r', 'third')['reserved'])
        self.make_run('other')
        self.store.reserve_dispatch('other', 'first', max_dispatches=5)
        self.assertTrue(self.store.reserve_dispatch('other', 'first', max_dispatches=1)['reserved'])
        self.assertFalse(RuntimeStore(self.tmp.name).reserve_dispatch('other', 'second')['reserved'])

    def test_signed_host_dispatch_unlocks_mailbox_with_bound_identity(self):
        key = b'test-host-key'
        sender = sign_dispatch({
            'record_id': 'send-1', 'purpose': 'message.send', 'run_id': 'r',
            'assignment_id': 'a', 'assignment_revision': 0, 'identity': 'worker',
            'issued_at': 99, 'expires_at': 200,
        }, key)
        self.store = RuntimeStore(self.tmp.name, clock=lambda: self.now, host_key=key)
        self.store.send_peer_message('r', message_id='signed', assignment_id='a',
                                     assignment_revision=0, correlation_id='signed-correlation',
                                     sender='worker', recipient='peer', message_type='task.progress',
                                     deadline=200, payload={'ok': True}, host_record=sender)
        receiver = sign_dispatch({
            'record_id': 'receive-1', 'purpose': 'message.receive', 'run_id': 'r',
            'identity': 'peer', 'issued_at': 99, 'expires_at': 200,
        }, key)
        messages = self.store.receive_peer_messages('r', 'peer', host_record=receiver)
        self.assertEqual(messages[0]['message_id'], 'signed')

    def test_trusted_completion_requires_signed_gate_and_evidence(self):
        key = b'test-host-key'
        self.store = RuntimeStore(self.tmp.name, clock=lambda: self.now, host_key=key)
        self.store.assignment_transition('r', 'a', 'running', expected_assignment_revision=0)
        assignment = self.store.assignment_transition('r', 'a', 'completed', expected_assignment_revision=1)
        run = self.store.get_run('r')
        evidence_record = sign_dispatch({
            'record_id': 'evidence-1', 'purpose': 'evidence.record', 'run_id': 'r',
            'identity': 'worker', 'evidence_id': 'verified', 'source_revision': run['revision'],
            'source_hash': 'source', 'exit_status': 0, 'kind': 'host.command',
            'command': 'true', 'cwd': '/', 'required': True,
            'issued_at': 99, 'expires_at': 200,
        }, key)
        evidence = self.store.record_evidence('r', 'verified', kind='host.command',
                                              source_revision=run['revision'], command='true', cwd='/',
                                              source_hash='source', exit_status=0, host_record=evidence_record)
        stale_record = sign_dispatch({
            'record_id': 'complete-stale', 'purpose': 'run.complete', 'run_id': 'r',
            'identity': 'coordinator', 'gate_decision': 'approved',
            'evidence_ids': [evidence['evidence_id']], 'artifact_hashes': {'verified': 'old-source'},
            'issued_at': 99, 'expires_at': 200,
        }, key)
        with self.assertRaisesRegex(RuntimeError, 'evidence'):
            self.store.complete_run('r', host_record=stale_record)
        record = sign_dispatch({
            'record_id': 'complete-1', 'purpose': 'run.complete', 'run_id': 'r',
            'identity': 'coordinator', 'gate_decision': 'approved',
            'evidence_ids': [evidence['evidence_id']], 'artifact_hashes': {'verified': 'source'},
            'issued_at': 99, 'expires_at': 200,
        }, key)
        completed = self.store.complete_run('r', host_record=record)
        self.assertEqual(completed['state'], 'completed')

    def test_caller_only_evidence_cannot_satisfy_trusted_completion(self):
        key = b'test-host-key'
        self.store = RuntimeStore(self.tmp.name, clock=lambda: self.now, host_key=key)
        run = self.store.get_run('r')
        evidence = self.store.record_evidence('r', 'caller-only', kind='test', source_revision=run['revision'],
                                              command='true', cwd='/', source_hash='claimed', exit_status=0)
        gate = sign_dispatch({'record_id': 'caller-gate', 'purpose': 'run.complete', 'run_id': 'r',
                              'identity': 'coordinator', 'gate_decision': 'approved',
                              'evidence_ids': [evidence['evidence_id']], 'artifact_hashes': {'caller-only': 'claimed'},
                              'issued_at': 99, 'expires_at': 200}, key)
        with self.assertRaisesRegex(RuntimeError, 'evidence'):
            self.store.complete_run('r', host_record=gate)

    def test_failed_required_check_cannot_be_omitted_from_completion_gate(self):
        key = b'test-host-key'
        self.store = RuntimeStore(self.tmp.name, clock=lambda: self.now, host_key=key)
        self.store.assignment_transition('r', 'a', 'running', expected_assignment_revision=0)
        self.store.assignment_transition('r', 'a', 'completed', expected_assignment_revision=1)

        def record(evidence_id, command, exit_status):
            run = self.store.get_run('r')
            claim = sign_dispatch({
                'record_id': evidence_id, 'purpose': 'evidence.record', 'run_id': 'r',
                'identity': 'worker', 'evidence_id': evidence_id,
                'source_revision': run['revision'], 'source_hash': 'source',
                'exit_status': exit_status, 'command': command, 'cwd': '/',
                'kind': 'host.command', 'required': True,
                'issued_at': 99, 'expires_at': 200,
            }, key)
            return self.store.record_evidence(
                'r', evidence_id, kind='host.command', source_revision=run['revision'],
                command=command, cwd='/', source_hash='source', exit_status=exit_status,
                host_record=claim)

        failed = record('failed-test', 'pytest', 1)
        self.assertEqual(failed['exit_status'], 1)
        lint = record('passing-lint', 'ruff check', 0)
        self.store = RuntimeStore(self.tmp.name, clock=lambda: self.now, host_key=key)

        def gate(record_id, evidence_ids):
            return sign_dispatch({
                'record_id': record_id, 'purpose': 'run.complete', 'run_id': 'r',
                'identity': 'coordinator', 'gate_decision': 'approved',
                'evidence_ids': evidence_ids,
                'artifact_hashes': {name: 'source' for name in evidence_ids},
                'issued_at': 99, 'expires_at': 200,
            }, key)

        with self.assertRaisesRegex(RuntimeError, 'required completion evidence'):
            self.store.complete_run('r', host_record=gate('early-gate', [lint['evidence_id']]))
        with self.store._connect() as db:
            db.execute("UPDATE evidence SET required=0 WHERE run_id='r' AND evidence_id='failed-test'")
        with self.assertRaisesRegex(RuntimeError, 'required completion evidence'):
            self.store.complete_run('r', host_record=gate('damaged-projection', [lint['evidence_id']]))
        with self.store._connect() as db:
            db.execute("UPDATE evidence SET required=1 WHERE run_id='r' AND evidence_id='failed-test'")
        passing = record('passing-test', 'pytest', 0)
        completed = self.store.complete_run(
            'r', host_record=gate('final-gate', [lint['evidence_id'], passing['evidence_id']]))
        self.assertEqual(completed['state'], 'completed')

    def test_legacy_receipt_without_signed_command_identity_cannot_complete(self):
        key = b'test-host-key'
        self.store = RuntimeStore(self.tmp.name, clock=lambda: self.now, host_key=key)
        self.store.assignment_transition('r', 'a', 'running', expected_assignment_revision=0)
        self.store.assignment_transition('r', 'a', 'completed', expected_assignment_revision=1)
        run = self.store.get_run('r')
        legacy_claim = sign_dispatch({
            'record_id': 'legacy-evidence', 'purpose': 'evidence.record', 'run_id': 'r',
            'identity': 'worker', 'evidence_id': 'legacy-evidence',
            'source_revision': run['revision'], 'source_hash': 'source',
            'exit_status': 0, 'issued_at': 99, 'expires_at': 200,
        }, key)
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO host_dispatches(record_id,run_id,purpose,identity,claims_json,accepted_at) VALUES(?,?,?,?,?,?)',
                       ('legacy-evidence', 'r', 'evidence.record', 'worker',
                        json.dumps(legacy_claim, sort_keys=True, separators=(',', ':')), self.now))
            db.execute('INSERT INTO evidence(run_id,evidence_id,kind,source_revision,command,cwd,source_hash,exit_status,required,created_at,host_record_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       ('r', 'legacy-evidence', 'host.command', run['revision'], 'pytest', '/',
                        'source', 0, 1, self.now, 'legacy-evidence'))
            db.commit()
        gate = sign_dispatch({
            'record_id': 'legacy-gate', 'purpose': 'run.complete', 'run_id': 'r',
            'identity': 'coordinator', 'gate_decision': 'approved',
            'evidence_ids': ['legacy-evidence'],
            'artifact_hashes': {'legacy-evidence': 'source'},
            'issued_at': 99, 'expires_at': 200,
        }, key)
        with self.assertRaisesRegex(RuntimeError, 'required completion evidence'):
            self.store.complete_run('r', host_record=gate)

    def test_named_optional_failure_does_not_block_but_cannot_prove_completion(self):
        key = b'test-host-key'
        self.store = RuntimeStore(self.tmp.name, clock=lambda: self.now, host_key=key)
        self.store.assignment_transition('r', 'a', 'running', expected_assignment_revision=0)
        self.store.assignment_transition('r', 'a', 'completed', expected_assignment_revision=1)

        def record(evidence_id, command, exit_status, required):
            run = self.store.get_run('r')
            claim = sign_dispatch({
                'record_id': evidence_id, 'purpose': 'evidence.record', 'run_id': 'r',
                'identity': 'worker', 'evidence_id': evidence_id,
                'source_revision': run['revision'], 'source_hash': 'source',
                'exit_status': exit_status, 'kind': 'host.command',
                'command': command, 'cwd': '/', 'required': required,
                'issued_at': 99, 'expires_at': 200,
            }, key)
            return self.store.record_evidence(
                'r', evidence_id, kind='host.command', source_revision=run['revision'],
                command=command, cwd='/', source_hash='source', exit_status=exit_status,
                required=required, host_record=claim)

        def gate(record_id, evidence_ids):
            return sign_dispatch({
                'record_id': record_id, 'purpose': 'run.complete', 'run_id': 'r',
                'identity': 'coordinator', 'gate_decision': 'approved',
                'evidence_ids': evidence_ids,
                'artifact_hashes': {name: 'source' for name in evidence_ids},
                'issued_at': 99, 'expires_at': 200,
            }, key)

        optional = record('optional-failure', 'exploratory probe', 1, False)
        with self.assertRaisesRegex(RuntimeError, 'required completion evidence'):
            self.store.complete_run('r', host_record=gate('optional-only', [optional['evidence_id']]))
        optional_pass = record('optional-pass', 'informational probe', 0, False)
        with self.assertRaisesRegex(RuntimeError, 'required completion evidence'):
            self.store.complete_run('r', host_record=gate('optional-pass-only', [optional_pass['evidence_id']]))
        with self.assertRaisesRegex(RuntimeError, 'required completion evidence'):
            self.store.complete_run('r', host_record=gate(
                'optional-pair', [optional['evidence_id'], optional_pass['evidence_id']]))
        required = record('required-pass', 'pytest', 0, True)
        result = self.store.complete_run(
            'r', host_record=gate('with-success', [optional['evidence_id'],
                                               optional_pass['evidence_id'], required['evidence_id']]))
        self.assertEqual(result['state'], 'completed')

    def test_dispatch_leases_enforce_concurrency_and_timeout_without_refund(self):
        reservations = []
        for index in range(4):
            reservation = f'dispatch-{index}'
            self.store.reserve_dispatch('r', reservation)
            reservations.append(reservation)
        for reservation in reservations[:3]:
            self.store.start_dispatch('r', reservation, 'worker-' + reservation)
        with self.assertRaisesRegex(RuntimeError, 'concurrent worker'):
            self.store.start_dispatch('r', reservations[3], 'worker-four')
        self.store.finish_dispatch('r', reservations[0], outcome='succeeded')
        self.store.start_dispatch('r', reservations[3], 'worker-four')
        self.now = 100 + 901
        expired = self.store.recover_dispatches('r')
        self.assertEqual({row['reservation_id'] for row in expired}, set(reservations[1:]))
        self.assertFalse(self.store.reserve_dispatch('r', 'dispatch-4', max_dispatches=4)['reserved'])

    def test_active_budget_exhaustion_escalates_run_for_user(self):
        self.store.reserve_dispatch('r', 'budgeted')
        self.now = 100 + 120 * 60
        with self.assertRaisesRegex(RuntimeError, 'active execution budget'):
            self.store.start_dispatch('r', 'budgeted', 'worker-budgeted')
        self.assertEqual(self.store.get_run('r')['state'], 'waiting_for_user')
