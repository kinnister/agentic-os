"""Contract tests, executable with unittest discovery and no dependencies."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))
from agentic_runtime.contracts import (load_registry, resolve_policy, normalize_input,
                                      validate_transition, retry_allowed, validate_identifier)


class ContractTests(unittest.TestCase):
    def test_registry(self):
        registry = load_registry()
        self.assertEqual(registry['contract_version'], '1.0.0')
        self.assertEqual(list(registry['phases']), [str(n) for n in range(13)])
        self.assertEqual(len(registry['gates']), 11)
        self.assertEqual(len(registry['loops']), 8)
        registry['phases'].clear()
        self.assertEqual(len(load_registry()['phases']), 13)

    def test_policy_defaults_and_class_ceiling(self):
        for name in ('sdlc-auto', 'sdlc-guided', 'sdlc-brief', 'sdlc-direct'):
            policy = resolve_policy(name)
            self.assertEqual(policy['max_dispatches'], 64)
            self.assertEqual(policy['active_run_minutes'], 120)
            self.assertEqual(policy['max_concurrent_workers'], 3)
        self.assertEqual(resolve_policy('sdlc-auto', {'classification': 'hotfix'})['max_concurrent_workers'], 1)
        self.assertEqual(resolve_policy('sdlc-auto', {'classification': 'bug'})['max_concurrent_workers'], 2)
        self.assertEqual(resolve_policy('sdlc-auto', {'max_dispatches': 5})['max_dispatches'], 5)

    def test_policy_rejects_unknown_and_invalid(self):
        for entrypoint, overrides in [('unknown', None), ('sdlc-auto', {'oops': 1}),
            ('sdlc-auto', {'max_dispatches': True}), ('sdlc-auto', {'max_dispatches': 0}),
            ('sdlc-auto', {'max_dispatches': 1.5}), ('sdlc-auto', {'classification': 'unknown'})]:
            with self.subTest(entrypoint=entrypoint, overrides=overrides), self.assertRaises(ValueError):
                resolve_policy(entrypoint, overrides)

    def test_normalize_and_explicit_legacy(self):
        payload = {'contract_version': '1.0.0', 'task_input': 'Fix the parser'}
        self.assertEqual(normalize_input(payload), payload)
        self.assertEqual(normalize_input({'contract_version': '1.0.0', 'raw_input': 'Fix'}, legacy=True)['task_input'], 'Fix')
        for payload in [{}, {'task_input': 'Fix'}, {'contract_version': '2.0.0', 'task_input': 'Fix'},
            {'contract_version': '1.0.0', 'task_input': ' '}, {'contract_version': '1.0.0', 'task_input': True},
            {'contract_version': '1.0.0', 'raw_input': 'Fix'},
            {'contract_version': '1.0.0', 'task_input': 'Fix', 'surprise': 1}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                normalize_input(payload)
        with self.assertRaises(ValueError):
            normalize_input({'contract_version': '1.0.0', 'raw_input': 'a', 'task_input': 'b'}, legacy=True)

    def test_transitions(self):
        self.assertTrue(validate_transition('pending', 'running'))
        self.assertTrue(validate_transition('running', 'completed'))
        for state in ('completed', 'failed', 'cancelled'):
            for target in load_registry()['run_states']:
                with self.assertRaises(ValueError):
                    validate_transition(state, target)
        with self.assertRaises(ValueError):
            validate_transition('unknown', 'running')

    def test_retry_caps_allow_final_success(self):
        # Cap=2 means initial attempt plus two retries. This only admits new attempts;
        # a successful third attempt can still transition to completed.
        self.assertEqual([retry_allowed('code-review.fixup', n) for n in range(4)], [True, True, True, False])
        self.assertTrue(validate_transition('running', 'completed'))
        self.assertTrue(retry_allowed('evidence.retry:task-1', 2))
        for loop, count in [('unknown', 0), ('evidence.retry:', 0), ('code-review.fixup', True), ('code-review.fixup', -1)]:
            with self.assertRaises(ValueError):
                retry_allowed(loop, count)

    def test_identifiers(self):
        self.assertEqual(validate_identifier('run-123'), 'run-123')
        for value in ('', '../run', 'a/b', 'a b', True, None):
            with self.assertRaises(ValueError):
                validate_identifier(value)

    def test_optional_envelope_fields_are_strict(self):
        base = {'contract_version': '1.0.0', 'task_input': 'Fix'}
        valid = dict(base, mode='autonomous', mode_flag='--greenfield', escalate_on=['security'],
                     entrypoint='sdlc-engine', classification='bug', run_id='run-1', policy={'max_dispatches': 2})
        self.assertEqual(normalize_input(valid), valid)
        for extra in [{'mode': 'auto'}, {'mode_flag': True}, {'escalate_on': ['unknown']},
                      {'escalate_on': ['security', 'security']}, {'escalate_on': [True]},
                      {'entrypoint': 'unknown'}, {'classification': 'unknown'}, {'run_id': '../x'},
                      {'policy': None}, {'policy': {'unknown': 1}},
                      {'mode': 'hitl', 'policy': {'mode': 'autonomous'}}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                normalize_input(dict(base, **extra))

    def test_budget_boundaries_and_registry_facts(self):
        registry = load_registry()
        expected = {'max_dispatches': 64, 'active_run_minutes': 120, 'max_concurrent_workers': 3,
                    'worker_minutes': 15, 'max_messages_per_worker': 8, 'max_message_bytes': 8192,
                    'max_outstanding_questions': 1, 'question_reply_seconds': 300, 'max_question_rounds': 2}
        for key, ceiling in expected.items():
            self.assertEqual(registry['policy_defaults'][key], ceiling)
            for value in (True, 0, -1, ceiling + 1, '1', 1.0):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    resolve_policy('sdlc-guided', {key: value})
        for entrypoint in registry['entrypoints']:
            self.assertEqual(resolve_policy(entrypoint)['max_dispatches'], 64)
        self.assertEqual(registry['artifacts']['database'], '.agentic/state/runtime.sqlite3')
        self.assertEqual(registry['artifacts']['run_exports'], '.agentic/runs/<run-id>/')
        for classification, ceiling in [('story',3), ('bug',2), ('hotfix',1), ('spike',1), ('epic',1)]:
            self.assertEqual(resolve_policy('sdlc-auto', {'classification': classification})['max_concurrent_workers'], ceiling)
        self.assertFalse(retry_allowed('arbiter.malformed.retry', 2))

    def test_entrypoint_modes_and_canonical_capabilities(self):
        for entrypoint in ('sdlc-brief', 'sdlc-direct', 'sdlc-guided', 'qa-baseline',
                           'qa-scoping', 'qa-case-generator', 'qa-e2e-generator',
                           'agentic-init', 'agentic-upgrade', 'agentic-doctor',
                           'agentic-uninstall'):
            with self.assertRaises(ValueError):
                resolve_policy(entrypoint, {'mode': 'autonomous'})
            with self.assertRaises(ValueError):
                normalize_input({'contract_version':'1.0.0', 'task_input':'Fix', 'entrypoint':entrypoint, 'mode':'autonomous'})
        self.assertEqual(resolve_policy('sdlc-engine', {'mode':'autonomous'})['mode'], 'autonomous')
        self.assertEqual(resolve_policy('sdlc-auto')['escalate_on'], load_registry()['risk_classes'])
        self.assertEqual(load_registry()['phases']['2']['name'], 'feature-branch')
        self.assertNotIn('resolve_gate', load_registry()['role_capabilities']['resolver'])
