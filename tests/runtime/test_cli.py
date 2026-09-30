"""Public CLI rejects malformed requests and resolves policies without writes."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class CLITests(unittest.TestCase):
    def request(self, operation, **payload):
        response = subprocess.run([sys.executable, str(ROOT / 'runtime/run.py')],
            input=json.dumps({'api_version': '1.0.0', 'operation': operation, **payload}),
            text=True, capture_output=True)
        self.assertNotIn('Traceback', response.stderr)
        return response.returncode, json.loads(response.stdout)

    def test_policy_resolves(self):
        code, result = self.request('policy.resolve', entrypoint='sdlc-auto')
        self.assertEqual(code, 0, result)
        self.assertTrue(result['ok'])
        self.assertEqual(result['result']['max_dispatches'], 64)

    def test_host_preflight_reports_capabilities_without_claiming_sandbox(self):
        code, result = self.request('host.preflight')
        self.assertEqual(code, 0, result)
        self.assertIn('enforcement', result['result'])
        self.assertEqual(result['result']['enforcement']['os_sandbox'], 'unsupported')
        matrix = result['result']['control_matrix']
        self.assertEqual(matrix['state_protocol']['boundary'], 'runtime')
        self.assertEqual(matrix['artifact_integrity']['boundary'], 'before_integration')
        self.assertEqual(matrix['os_sandbox']['status'], 'unsupported')

    def test_host_preflight_blocks_unavailable_required_controls(self):
        code, result = self.request('host.preflight', required_capabilities=['os_sandbox'])
        self.assertEqual(code, 2)
        self.assertIn('required host capabilities unavailable', result['error']['message'])

    def test_host_preflight_accepts_enforced_runtime_controls(self):
        code, result = self.request('host.preflight', required_capabilities=['sqlite_protocol', 'dispatch_leases'])
        self.assertEqual(code, 0, result)
        self.assertTrue(result['result']['ready'])

    def test_trace_adapt_requires_key_and_returns_signed_event(self):
        event = {'type': 'agentic.command.completed', 'evidence_id': 'e1', 'run_id': 'r',
                 'source_revision': 1, 'command': 'pytest', 'cwd': '.',
                 'source_hash': 'sha256:abc', 'exit_status': 0}
        payload = {'api_version': '1.0.0', 'operation': 'trace.adapt', 'event': event,
                   'identity': 'codex', 'issued_at': 10, 'expires_at': 20}
        # Pass an explicit environment so a key exported in the caller's shell
        # cannot leak in; os.environ itself is never mutated.
        keyless = {k: v for k, v in os.environ.items() if k != 'AGENTIC_HOST_KEY'}
        missing = subprocess.run([sys.executable, str(ROOT / 'runtime/run.py')],
            input=json.dumps(payload), text=True, capture_output=True, env=keyless)
        self.assertEqual(missing.returncode, 2, missing.stdout)
        self.assertIn('host signing key is required', missing.stdout)
        env = dict(keyless, AGENTIC_HOST_KEY='test-key')
        response = subprocess.run([sys.executable, str(ROOT / 'runtime/run.py')],
            input=json.dumps(payload), text=True, capture_output=True, env=env)
        self.assertEqual(response.returncode, 0, response.stderr)
        result = json.loads(response.stdout)
        self.assertTrue(result['ok'])
        self.assertEqual(result['result']['host_record']['identity'], 'codex')

    def test_unknown_request_field_is_rejected(self):
        code, result = self.request('registry.get', ignored=True)
        self.assertEqual(code, 2)
        self.assertFalse(result['ok'])

    def test_duplicate_json_keys_are_rejected(self):
        response = subprocess.run([sys.executable, str(ROOT / 'runtime/run.py')],
            input='{"api_version":"2.0.0","api_version":"1.0.0","operation":"registry.get"}',
            text=True, capture_output=True)
        self.assertEqual(response.returncode, 2)
        self.assertFalse(json.loads(response.stdout)['ok'])

    def test_unknown_operation_is_rejected(self):
        code, result = self.request('run.complete')
        self.assertEqual(code, 2)
        self.assertFalse(result['ok'])

    def test_normalization_requires_explicit_legacy_adapter(self):
        payload = {'contract_version': '1.0.0', 'raw_input': 'fix fixture'}
        code, _ = self.request('input.normalize', payload=payload)
        self.assertEqual(code, 2)
        code, result = self.request('input.normalize', payload=payload, legacy=True)
        self.assertEqual(code, 0, result)
        self.assertEqual(result['result']['task_input'], 'fix fixture')

    def test_transition_and_retry_validation(self):
        code, result = self.request('transition.validate', source='running', target='completed')
        self.assertEqual(code, 0, result)
        code, _ = self.request('transition.validate', source='completed', target='running')
        self.assertEqual(code, 2)
        code, result = self.request('retry.allowed', loop_id='gate-runner.retry', attempts_used=3)
        self.assertEqual(code, 0, result)
        self.assertFalse(result['result'])

    def test_lookup_rejects_unknown_contract_ids(self):
        code, result = self.request('contract.lookup', section='gates', identifier='plan.approved')
        self.assertEqual(code, 0, result)
        self.assertEqual(result['result']['phase'], 5)
        for section, identifier in [('gates', 'invented'), ('phases', '13'), ('unknown', 'x')]:
            code, _ = self.request('contract.lookup', section=section, identifier=identifier)
            self.assertEqual(code, 2)

    def test_run_start_status_dispatch_and_cancel_are_versioned(self):
        with tempfile.TemporaryDirectory() as root:
            worktree = pathlib.Path(root) / 'work-x'
            subprocess.run(['git', 'init', '-q', str(worktree)], check=True)
            subprocess.run(['git', '-C', str(worktree), 'checkout', '-q', '-b', 'feature/x'], check=True)
            def request(operation, **payload):
                payload['root'] = root
                return self.request(operation, **payload)
            code, result = request('run.start', task_input='bounded task', coordinator_id='c1',
                                   branch='feature/x', worktree=str(worktree), run_id='run-x',
                                   precondition={'ownership': 'verified'})
            self.assertEqual(code, 0, result)
            self.assertEqual(result['result']['state'], 'running')
            self.assertEqual(result['result']['metadata']['task_input'], 'bounded task')
            epoch = result['result']['lease_epoch']
            code, status = request('run.status', run_id='run-x')
            self.assertEqual(code, 0, status)
            self.assertEqual(status['result']['metadata']['task_input'], 'bounded task')
            code, dispatched = request('task.dispatch', run_id='run-x', reservation_id='d1', max_dispatches=1, lease_epoch=epoch,
                                       coordinator_id='c1', expected_revision=status['result']['revision'])
            self.assertEqual(code, 0, dispatched)
            self.assertTrue(dispatched['result']['reserved'])
            code, status = request('run.status', run_id='run-x')
            self.assertEqual(code, 0, status)
            code, legacy = request('legacy.export', run_id='run-x', destination=str(pathlib.Path(root) / 'legacy-view'))
            self.assertEqual(code, 0, legacy)
            self.assertEqual(json.loads((pathlib.Path(root) / 'legacy-view' / 'meta.json').read_text())['status'], 'running')
            code, waiting = request('run.transition', run_id='run-x', target='waiting_for_user', coordinator_id='c1', lease_epoch=epoch,
                                    expected_revision=status['result']['revision'])
            self.assertEqual(code, 0, waiting)
            code, resumed = request('run.transition', run_id='run-x', target='running', coordinator_id='c1', lease_epoch=epoch, expected_revision=waiting['result']['revision'])
            self.assertEqual(code, 0, resumed)
            code, cancelled = request('run.cancel', run_id='run-x', coordinator_id='c1')
            self.assertEqual(code, 0, cancelled)
            self.assertEqual(cancelled['result']['state'], 'cancelled')

    def test_run_start_rejects_conflicting_task_input_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            code, result = self.request('run.start', root=root, task_input='authoritative input',
                                        coordinator_id='c1', branch='feature/x', worktree='unused',
                                        metadata={'task_input': 'conflicting input'})
            self.assertEqual(code, 2)
            self.assertIn('task_input metadata conflicts', result['error']['message'])
            self.assertFalse((pathlib.Path(root) / '.agentic').exists())

    def test_run_start_rejects_wrong_branch_before_creating_runtime_state(self):
        with tempfile.TemporaryDirectory() as root:
            worktree = pathlib.Path(root) / 'worktree'
            subprocess.run(['git', 'init', '-q', str(worktree)], check=True)
            subprocess.run(['git', '-C', str(worktree), 'checkout', '-q', '-b', 'feature/actual'], check=True)
            code, result = self.request('run.start', root=root, task_input='work',
                                        coordinator_id='coordinator', branch='feature/requested',
                                        worktree=str(worktree), precondition={'ownership': 'verified'})
            self.assertEqual(code, 2, result)
            self.assertIn('worktree branch does not match', result['error']['message'])
            self.assertFalse((pathlib.Path(root) / '.agentic').exists())

    def test_run_start_rejects_missing_ownership_before_creating_runtime_state(self):
        with tempfile.TemporaryDirectory() as root:
            worktree = pathlib.Path(root) / 'worktree'
            subprocess.run(['git', 'init', '-q', str(worktree)], check=True)
            subprocess.run(['git', '-C', str(worktree), 'checkout', '-q', '-b', 'feature/actual'], check=True)
            code, result = self.request('run.start', root=root, task_input='work',
                                        coordinator_id='coordinator', branch='feature/actual',
                                        worktree=str(worktree))
            self.assertEqual(code, 2, result)
            self.assertIn('ownership must be verified', result['error']['message'])
            self.assertFalse((pathlib.Path(root) / '.agentic').exists())

    def test_run_start_rejects_malformed_coordinator_without_pending_run(self):
        for identity in ({'bad': True}, ['bad']):
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as root:
                code, result = self.request('run.start', root=root, task_input='work',
                                            coordinator_id=identity, branch=None, worktree=None)
                self.assertEqual(code, 2, result)
                self.assertIn('coordinator_id', result['error']['message'])
                self.assertFalse((pathlib.Path(root) / '.agentic').exists())

    def test_run_start_requires_owned_branch_and_worktree(self):
        with tempfile.TemporaryDirectory() as root:
            code, result = self.request('run.start', root=root, task_input='work',
                                        coordinator_id='coordinator', branch=None, worktree=None)
            self.assertEqual(code, 2, result)
            self.assertIn('branch and worktree', result['error']['message'])
            self.assertFalse((pathlib.Path(root) / '.agentic').exists())

    def test_run_start_rejects_nested_directory_claimed_as_worktree(self):
        with tempfile.TemporaryDirectory() as root:
            worktree = pathlib.Path(root) / 'worktree'
            nested = worktree / 'nested'
            subprocess.run(['git', 'init', '-q', str(worktree)], check=True)
            subprocess.run(['git', '-C', str(worktree), 'checkout', '-q', '-b', 'feature/actual'], check=True)
            nested.mkdir()
            code, result = self.request('run.start', root=root, task_input='work',
                                        coordinator_id='coordinator', branch='feature/actual',
                                        worktree=str(nested), precondition={'ownership': 'verified'})
            self.assertEqual(code, 2, result)
            self.assertIn('worktree root', result['error']['message'])
            self.assertFalse((pathlib.Path(root) / '.agentic').exists())

    def test_interrupted_run_resumes_under_a_new_fenced_coordinator(self):
        with tempfile.TemporaryDirectory() as root:
            worktree = pathlib.Path(root) / 'work-resume'
            subprocess.run(['git', 'init', '-q', str(worktree)], check=True)
            subprocess.run(['git', '-C', str(worktree), 'checkout', '-q', '-b', 'feature/resume'], check=True)
            def request(operation, **payload):
                payload['root'] = root
                return self.request(operation, **payload)
            code, started = request('run.start', task_input='resume me', coordinator_id='c1',
                                    branch='feature/resume', worktree=str(worktree), run_id='run-resume',
                                    precondition={'ownership': 'verified'})
            self.assertEqual(code, 0, started)
            code, interrupted = request('run.transition', run_id='run-resume', target='interrupted',
                                        reason='host restart', coordinator_id='c1',
                                        lease_epoch=started['result']['lease_epoch'],
                                        expected_revision=started['result']['revision'])
            self.assertEqual(code, 0, interrupted)
            code, resumed = request('run.resume', run_id='run-resume', coordinator_id='c2')
            self.assertEqual(code, 0, resumed)
            self.assertEqual(resumed['result']['state'], 'running')
            self.assertGreater(resumed['result']['lease_epoch'], started['result']['lease_epoch'])

    def test_task_result_is_the_versioned_public_completion_operation(self):
        with tempfile.TemporaryDirectory() as root:
            worktree = pathlib.Path(root) / 'work-task-result'
            subprocess.run(['git', 'init', '-q', str(worktree)], check=True)
            subprocess.run(['git', '-C', str(worktree), 'checkout', '-q', '-b', 'feature/task-result'], check=True)
            def request(operation, **payload):
                payload['root'] = root
                return self.request(operation, **payload)
            code, started = request('run.start', task_input='task result', coordinator_id='c1',
                                    branch='feature/task-result', worktree=str(worktree),
                                    run_id='run-task-result', precondition={'ownership': 'verified'})
            self.assertEqual(code, 0, started)
            epoch = started['result']['lease_epoch']
            revision = started['result']['revision']
            code, reserved = request('task.dispatch', run_id='run-task-result',
                                     reservation_id='reservation-1', coordinator_id='c1',
                                     lease_epoch=epoch, expected_revision=revision)
            self.assertEqual(code, 0, reserved)
            code, status = request('run.status', run_id='run-task-result')
            self.assertEqual(code, 0, status)
            code, started_dispatch = request('dispatch.start', run_id='run-task-result',
                                             reservation_id='reservation-1', worker_id='worker-1',
                                             coordinator_id='c1', lease_epoch=epoch,
                                             expected_revision=status['result']['revision'])
            self.assertEqual(code, 0, started_dispatch)
            code, status = request('run.status', run_id='run-task-result')
            self.assertEqual(code, 0, status)
            code, result = request('task.result', run_id='run-task-result',
                                   reservation_id='reservation-1', outcome='succeeded',
                                   coordinator_id='c1', lease_epoch=epoch,
                                   expected_revision=status['result']['revision'])
            self.assertEqual(code, 0, result)
            self.assertEqual(result['result']['outcome'], 'succeeded')
            self.assertIsNotNone(result['result']['finished_at'])

    def test_legacy_import_is_reachable_through_versioned_runtime(self):
        with tempfile.TemporaryDirectory() as root:
            source = pathlib.Path(root) / 'legacy.json'
            source.write_bytes(b'legacy fixture')
            worktree = pathlib.Path(root) / 'work-import'
            subprocess.run(['git', 'init', '-q', str(worktree)], check=True)
            subprocess.run(['git', '-C', str(worktree), 'checkout', '-q', '-b', 'feature/import'], check=True)
            def request(operation, **payload):
                payload['root'] = root
                return self.request(operation, **payload)
            code, _ = request('run.start', task_input='import', coordinator_id='c1',
                              branch='feature/import', worktree=str(worktree), run_id='run-import',
                              precondition={'ownership': 'verified'})
            self.assertEqual(code, 0)
            code, result = request('legacy.import', run_id='run-import', source=str(source))
            self.assertEqual(code, 0, result)
            self.assertEqual(result['result']['bytes'], len(b'legacy fixture'))

    def test_invalid_resume_and_cancel_do_not_mutate_terminal_runs(self):
        with tempfile.TemporaryDirectory() as root:
            worktree = pathlib.Path(root) / 'work'
            subprocess.run(['git', 'init', '-q', str(worktree)], check=True)
            subprocess.run(['git', '-C', str(worktree), 'checkout', '-q', '-b', 'feature/work'], check=True)
            def request(operation, **payload):
                payload['root'] = root
                return self.request(operation, **payload)
            code, started = request('run.start', task_input='done', coordinator_id='c1',
                                    branch='feature/work', worktree=str(worktree), run_id='run-terminal',
                                    precondition={'ownership': 'verified'})
            self.assertEqual(code, 0, started)
            code, terminal = request('run.transition', run_id='run-terminal', target='completed',
                                     coordinator_id='c1', lease_epoch=started['result']['lease_epoch'],
                                     expected_revision=started['result']['revision'])
            self.assertEqual(code, 2, terminal)
            self.assertIn('completion', terminal['error']['message'])
            code, terminal = request('run.cancel', run_id='run-terminal', coordinator_id='c1')
            self.assertEqual(code, 0, terminal)
            revision = terminal['result']['revision']
            code, result = request('run.resume', run_id='run-terminal', coordinator_id='c2')
            self.assertEqual(code, 2)
            self.assertFalse(result['ok'])
            code, result = request('run.cancel', run_id='run-terminal', coordinator_id='c2')
            self.assertEqual(code, 2)
            self.assertFalse(result['ok'])
            code, status = request('run.status', run_id='run-terminal')
            self.assertEqual(code, 0, status)
            self.assertEqual(status['result']['revision'], revision)

    def test_mailbox_caller_identity_never_discloses_messages(self):
        from runtime.agentic_runtime.store import RuntimeStore
        from runtime.agentic_runtime.host import sign_dispatch
        with tempfile.TemporaryDirectory() as root:
            key = b'mailbox-message-key'
            store = RuntimeStore(root, clock=lambda: 100, host_key=key)
            store.create_run('mailbox')
            store.create_assignment('mailbox', 'a', 'worker', owned_paths=[], context_refs=[], acceptance=[])
            store.send_peer_message('mailbox', message_id='secret', assignment_id='a', assignment_revision=0,
                                    correlation_id='c', sender='worker', recipient='victim',
                                    message_type='task.progress', deadline=110, payload={'private': 'mailbox-content'},
                                    host_record=sign_dispatch({'record_id': 'send-secret', 'purpose': 'message.send',
                                        'run_id': 'mailbox', 'assignment_id': 'a', 'assignment_revision': 0,
                                        'identity': 'worker', 'issued_at': 0, 'expires_at': 200}, key))
            for reader in ('victim', 'attacker'):
                code, result = self.request('message.receive', root=root, run_id='mailbox', recipient='victim', reader_id=reader)
                self.assertEqual(code, 2)
                self.assertIn('host-issued', result['error']['message'])
                self.assertNotIn('result', result)
                self.assertNotIn('mailbox-content', json.dumps(result))

    def test_public_message_send_rejects_unsigned_worker_identity(self):
        from runtime.agentic_runtime.store import RuntimeStore
        with tempfile.TemporaryDirectory() as root:
            store = RuntimeStore(root)
            store.create_run('message-cli')
            run = store.acquire_lease('message-cli', 'coord')
            run = store.transition('message-cli', 'running', expected_revision=run['revision'],
                                   lease_epoch=run['lease_epoch'], coordinator_id='coord')
            store.create_assignment('message-cli', 'a', 'worker', owned_paths=[],
                                    context_refs=[], acceptance=[],
                                    coordinator_id='coord', lease_epoch=run['lease_epoch'],
                                    expected_revision=run['revision'])
            run = store.get_run('message-cli')
            code, result = self.request(
                'message.send', root=root, run_id='message-cli', message_id='unsigned-cli',
                assignment_id='a', assignment_revision=0, correlation_id='c',
                sender='worker', recipient='coord', message_type='task.progress',
                deadline=run['updated_at'] + 30, payload={'step': 1},
                coordinator_id='coord', lease_epoch=run['lease_epoch'],
                expected_revision=run['revision'])
            self.assertEqual(code, 2)
            self.assertIn('host-issued sender identity', result['error']['message'])

    def test_decision_record_accepts_registry_gate_and_rejects_unknown_gate(self):
        from runtime.agentic_runtime.store import RuntimeStore
        with tempfile.TemporaryDirectory() as root:
            store = RuntimeStore(root)
            store.create_run('decision-cli')
            run = store.acquire_lease('decision-cli', 'coord')
            run = store.transition('decision-cli', 'running', expected_revision=run['revision'],
                                   lease_epoch=run['lease_epoch'], coordinator_id='coord')
            code, accepted = self.request(
                'decision.record', root=root, run_id='decision-cli',
                decision_key='plan.approved', value={'decision': 'approve', 'source': 'hitl',
                                                    'artifact_hashes': {'plan': 'sha256:plan'}},
                coordinator_id='coord', lease_epoch=run['lease_epoch'],
                expected_revision=run['revision'])
            self.assertEqual(code, 0, accepted)
            code, rejected = self.request(
                'decision.record', root=root, run_id='decision-cli',
                decision_key='invented.gate', value={'decision': 'approve'},
                coordinator_id='coord', lease_epoch=run['lease_epoch'],
                expected_revision=accepted['result']['revision'])
            self.assertEqual(code, 2)
            self.assertIn('unknown gate identifier', rejected['error']['message'])
            code, malformed = self.request(
                'decision.record', root=root, run_id='decision-cli',
                decision_key='plan.approved', value=True,
                coordinator_id='coord', lease_epoch=run['lease_epoch'],
                expected_revision=accepted['result']['revision'])
            self.assertEqual(code, 2)
            self.assertIn('allowed decision', malformed['error']['message'])
            code, missing_hashes = self.request(
                'decision.record', root=root, run_id='decision-cli',
                decision_key='plan.approved', value={'decision': 'approve', 'source': 'hitl'},
                coordinator_id='coord', lease_epoch=run['lease_epoch'],
                expected_revision=accepted['result']['revision'])
            self.assertEqual(code, 2)
            self.assertIn('artifact hashes', missing_hashes['error']['message'])
            code, risk_fast_path = self.request(
                'decision.record', root=root, run_id='decision-cli',
                decision_key='plan.approved', value={
                    'decision': 'approve', 'source': 'fast-path',
                    'risk_flags': ['migration'],
                    'artifact_hashes': {'plan': 'sha256:plan'},
                }, coordinator_id='coord', lease_epoch=run['lease_epoch'],
                expected_revision=accepted['result']['revision'])
            self.assertEqual(code, 2)
            self.assertIn('human escalation', risk_fast_path['error']['message'])
