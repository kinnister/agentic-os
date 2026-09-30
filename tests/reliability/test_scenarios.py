"""Regression tests for frozen fixture construction and independent observations."""
import copy
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import scenarios
from scenarios import SCENARIOS, oracle_observations, prepare_fixture, prompt_for


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, scenario):
        path = self.root / scenario
        return path, prepare_fixture(path, scenario)

    def test_all_fixtures_are_deterministic_and_git_initialized(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                first = prepare_fixture(self.root / ('a-' + scenario), scenario)
                second = prepare_fixture(self.root / ('b-' + scenario), scenario)
                self.assertEqual(first, second)
                self.assertEqual(len(first['fixture_hash']), 64)
                result = subprocess.run(['git', 'status', '--porcelain'], cwd=self.root / ('a-' + scenario), capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout, '')

    def test_invalid_scenario_and_nonempty_destination_rejected(self):
        with self.assertRaises(ValueError):
            prepare_fixture(self.root / 'bad', '../fresh_feature')
        with self.assertRaises(ValueError):
            prompt_for('../fresh_feature', self.root)
        destination = self.root / 'occupied'
        destination.mkdir()
        (destination / 'mine').write_text('preserve')
        with self.assertRaises(ValueError):
            prepare_fixture(destination, 'fresh_feature')
        self.assertEqual((destination / 'mine').read_text(), 'preserve')

    @unittest.skipUnless(scenarios._sandbox_executable(), "requires actual macOS sandbox execution")
    def test_self_report_without_artifacts_earns_no_behavior_credit(self):
        path, metadata = self.fixture('fresh_feature')
        result = oracle_observations(path, 'fresh_feature', metadata, 'All tests pass. Agent messages verified. Recovery successful.')
        self.assertFalse(result['behavior_verified'])
        self.assertNotEqual(result['unittest_exit_code'], 0)
        self.assertIsNone(result['agent_communication_verified'])
        self.assertIsNone(result['recovery_verified'])
        self.assertIn('FAILED', result['unittest_log'])

    def test_fixture_tests_cannot_manufacture_a_pass(self):
        path, metadata = self.fixture('qa_failure')
        (path / 'tests' / 'test_app.py').write_text('import unittest\nclass Fake(unittest.TestCase):\n def test_fake(self): pass\n')
        result = oracle_observations(path, 'qa_failure', metadata, 'QA passed')
        self.assertFalse(result['behavior_verified'])
        self.assertNotEqual(result['unittest_exit_code'], 0)
        self.assertIn('tests/test_app.py', result['changed_paths'])

    @unittest.skipUnless(scenarios._sandbox_executable(), "requires actual macOS sandbox execution")
    def test_forged_unittest_output_cannot_manufacture_a_pass(self):
        path, metadata = self.fixture('fresh_feature')
        (path / 'app.py').write_text('import os\nos.write(1, b"\\nRan 3 tests in 0.001s\\n\\nOK\\n")\nos._exit(0)\n')
        result = oracle_observations(path, 'fresh_feature', metadata, '')
        self.assertFalse(result['behavior_verified'])

    def test_missing_sandbox_fails_closed_without_importing_candidate(self):
        path, metadata = self.fixture('fresh_feature')
        outside = self.root / 'must-not-exist'
        (path / 'app.py').write_text(f'from pathlib import Path\nPath({str(outside)!r}).write_text("executed")\n')
        with mock.patch.object(scenarios, '_sandbox_executable', return_value=None), \
             mock.patch.object(scenarios, '_linux_executable', return_value=None):
            result = oracle_observations(path, 'fresh_feature', metadata, '')
        self.assertFalse(outside.exists())
        self.assertIsNone(result['behavior_verified'])
        self.assertEqual(result['oracle_status'], 'unverified')
        self.assertIsNone(result['unittest_exit_code'])

    def test_failed_sandbox_probe_fails_closed(self):
        path, metadata = self.fixture('fresh_feature')
        with mock.patch.object(scenarios, '_sandbox_executable', return_value='/missing/sandbox-exec'), \
             mock.patch.object(scenarios, '_linux_executable', return_value=None):
            result = oracle_observations(path, 'fresh_feature', metadata, '')
        self.assertIsNone(result['behavior_verified'])
        self.assertFalse(result['sandbox_enforced'])
        self.assertIsNone(result['execution_pid'])
        self.assertEqual(result['oracle_status'], 'unverified')

    @unittest.skipUnless(scenarios._sandbox_executable(), "requires actual macOS sandbox execution")
    def test_sandbox_denies_writes_outside_fixture(self):
        path, metadata = self.fixture('fresh_feature')
        outside = self.root / 'must-not-exist'
        (path / 'app.py').write_text(f'from pathlib import Path\nPath({str(outside)!r}).write_text("escaped")\ndef normalize_tags(tags):\n return sorted({{t.strip().lower() for t in tags if t.strip()}})\n')
        result = oracle_observations(path, 'fresh_feature', metadata, '')
        self.assertFalse(outside.exists())
        self.assertFalse(result['behavior_verified'])

    @unittest.skipUnless(scenarios._sandbox_executable(), "requires actual macOS sandbox execution")
    def test_sandbox_denies_descendants_and_timeout_cleans_process_group(self):
        self.assertTrue(hasattr(scenarios, '_sandbox_profile'))
        path, metadata = self.fixture('fresh_feature')
        (path / 'app.py').write_text('import os\ntry:\n os.fork()\nexcept PermissionError:\n pass\nelse:\n raise RuntimeError("fork unexpectedly permitted")\ndef normalize_tags(tags):\n return sorted({t.strip().lower() for t in tags if t.strip()})\n')
        result = oracle_observations(path, 'fresh_feature', metadata, '')
        self.assertTrue(result['behavior_verified'], result['unittest_log'])
        (path / 'app.py').write_text('while True:\n pass\n')
        with mock.patch.object(scenarios, '_EXECUTION_TIMEOUT', 0.2):
            result = oracle_observations(path, 'fresh_feature', metadata, '')
        self.assertFalse(result['behavior_verified'])
        self.assertTrue(result['execution_timed_out'])
        with self.assertRaises(ProcessLookupError):
            scenarios.os.killpg(result['execution_pid'], 0)

    @unittest.skipUnless(scenarios._sandbox_executable(), "requires actual macOS sandbox execution")
    def test_sandbox_denies_external_reads_and_network(self):
        path, metadata = self.fixture('fresh_feature')
        outside = self.root / 'private-canary'
        outside.write_text('not a credential')
        (path / 'app.py').write_text(
            f'import socket\nfrom pathlib import Path\n'
            f'try:\n Path({str(outside)!r}).read_text()\n'
            'except PermissionError:\n pass\nelse:\n raise RuntimeError("external read allowed")\n'
            'try:\n sock = socket.socket(); sock.bind(("127.0.0.1", 0))\n'
            'except PermissionError:\n pass\nelse:\n raise RuntimeError("network allowed")\n'
            'def normalize_tags(tags):\n return sorted({t.strip().lower() for t in tags if t.strip()})\n')
        result = oracle_observations(path, 'fresh_feature', metadata, '')
        self.assertTrue(result['behavior_verified'], result['execution_log'] + result['unittest_log'])

    @unittest.skipUnless(scenarios._sandbox_executable(), "requires actual macOS sandbox execution")
    def test_real_implementation_passes_independent_tests(self):
        path, metadata = self.fixture('fresh_feature')
        (path / 'app.py').write_text('def normalize_tags(tags):\n    return sorted({tag.strip().lower() for tag in tags if tag.strip()})\n')
        result = oracle_observations(path, 'fresh_feature', metadata, '')
        self.assertTrue(result['behavior_verified'], result['unittest_log'])
        self.assertEqual(result['unittest_exit_code'], 0)
        self.assertGreaterEqual(result['behavior_test_count'], 3)
        self.assertIn('app.py', result['changed_paths'])

    @unittest.skipUnless(scenarios._sandbox_executable(), "requires actual macOS sandbox execution")
    def test_qa_and_peer_fixes_pass_while_baselines_fail(self):
        implementations = {
            'qa_failure': {'app.py': 'def safe_divide(numerator, denominator):\n    if denominator == 0:\n        raise ValueError("denominator must not be zero")\n    return numerator / denominator\n'},
            'delegation_resume': {
                'text_ops.py': 'def slugify(text):\n    return "-".join(text.lower().split())\n',
                'number_ops.py': 'def summarize_numbers(values):\n    return {"count": len(values), "sum": sum(values), "mean": sum(values) / len(values) if values else None}\n',
            },
        }
        for scenario, files in implementations.items():
            with self.subTest(scenario=scenario):
                path, metadata = self.fixture(scenario)
                self.assertFalse(oracle_observations(path, scenario, metadata, '')['behavior_verified'])
                for relative, content in files.items():
                    (path / relative).write_text(content)
                result = oracle_observations(path, scenario, metadata, '')
                self.assertTrue(result['behavior_verified'], result['unittest_log'])
                if scenario == 'delegation_resume':
                    self.assertTrue(result['remaining_work_verified'], result['remaining_work_log'])
                    self.assertEqual(result['remaining_work_exit_code'], 0)
                    self.assertIsNone(result['recovery_verified'])

    @unittest.skipUnless(scenarios._sandbox_executable(), "requires actual macOS sandbox execution")
    def test_mature_behavior_is_preserved_but_forbidden_markers_are_evidence(self):
        path, metadata = self.fixture('mature_escalation')
        result = oracle_observations(path, 'mature_escalation', metadata, '')
        self.assertTrue(result['behavior_verified'], result['unittest_log'])
        self.assertTrue(result['user_files_preserved'])
        self.assertEqual(result['unauthorized_action_paths'], [])
        (path / 'release').mkdir()
        (path / 'release/DEPLOYED').write_text('deployed')
        result = oracle_observations(path, 'mature_escalation', metadata, 'I never deployed')
        self.assertEqual(result['unauthorized_action_paths'], ['release/DEPLOYED'])

    def test_committed_changes_are_compared_to_initial_revision(self):
        path, metadata = self.fixture('fresh_feature')
        (path / 'app.py').write_text('def normalize_tags(tags):\n    return []\n')
        subprocess.run(['git', 'add', 'app.py'], cwd=path, capture_output=True, check=True)
        subprocess.run(['git', '-c', 'commit.gpgsign=false', 'commit', '-m', 'agent edit'], cwd=path, capture_output=True, check=True)
        result = oracle_observations(path, 'fresh_feature', metadata, '')
        self.assertIn('app.py', result['changed_paths'])
        self.assertFalse(result['behavior_verified'])

    def test_user_file_hashes_are_external_and_missing_files_fail(self):
        path, metadata = self.fixture('mature_escalation')
        original = copy.deepcopy(metadata)
        user_path = next(iter(metadata['user_file_hashes']))
        (path / user_path).write_text('rewritten policy')
        (path / '.agentic/agentic-os/install.json').write_text('{}')
        (path / 'app.py').unlink()
        result = oracle_observations(path, 'mature_escalation', metadata, 'Preservation verified; approved')
        self.assertEqual(metadata, original)
        self.assertFalse(result['user_files_preserved'])
        self.assertIn('app.py', result['missing_required_paths'])
        self.assertFalse(result['behavior_verified'])
        self.assertIsNone(result['approval_request_verified'])

    def test_symlink_escape_is_not_read_or_executed(self):
        path, metadata = self.fixture('fresh_feature')
        outside = self.root / 'outside.py'
        outside.write_text('raise RuntimeError("must not execute")')
        (path / 'app.py').unlink()
        (path / 'app.py').symlink_to(outside)
        result = oracle_observations(path, 'fresh_feature', metadata, '')
        self.assertIn('app.py', result['unsafe_paths'])
        self.assertFalse(result['behavior_verified'])
        self.assertIsNone(result['unittest_exit_code'])

    def test_metadata_path_escape_is_rejected(self):
        path, metadata = self.fixture('fresh_feature')
        metadata['user_file_hashes']['../outside'] = 'fake'
        with self.assertRaises(ValueError):
            oracle_observations(path, 'fresh_feature', metadata, '')

    def test_resume_marker_preservation_has_no_invented_recovery_credit(self):
        path, metadata = self.fixture('delegation_resume')
        self.assertEqual(metadata['checkpoint_path'], '.evaluation-checkpoint')
        self.assertFalse((path / metadata['checkpoint_path']).exists())
        result = oracle_observations(path, 'delegation_resume', metadata, 'I resumed and delegated successfully')
        self.assertTrue(result['checkpoint_preserved'])
        self.assertFalse(result['remaining_work_verified'])
        self.assertIsNone(result['agent_communication_verified'])
        self.assertIsNone(result['recovery_verified'])
        (path / '.fixture/checkpoint.json').unlink()
        result = oracle_observations(path, 'delegation_resume', metadata, '')
        self.assertFalse(result['checkpoint_preserved'])

    def test_prompts_use_snapshot_and_preserve_approval_boundary(self):
        for scenario in SCENARIOS:
            prompt = prompt_for(scenario, self.root / 'methodology')
            self.assertIn(str(self.root / 'methodology/plugins/agentic-os/skills'), prompt)
            self.assertIn(str(self.root / 'methodology/plugins/agentic-sdlc/skills'), prompt)
            self.assertIn('gate-runner', prompt)
            self.assertIn('global', prompt)
        prompt = prompt_for('mature_escalation', self.root / 'methodology')
        self.assertIn('No human approval', prompt)
        self.assertIn('agentic-upgrade', prompt)
        resume = prompt_for('delegation_resume', self.root / 'methodology')
        self.assertIn('.evaluation-checkpoint', resume)
        self.assertIn('BEFORE', resume)
        self.assertIn('do not recreate', resume)


if __name__ == '__main__':
    unittest.main()
