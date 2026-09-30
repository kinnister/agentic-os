"""Offline host adapter tests: fake CLIs never contact a model provider."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from runtime.agentic_runtime.store import RuntimeStore


HOSTS_PATH = Path(__file__).with_name("hosts.py")
if HOSTS_PATH.exists():
    spec = importlib.util.spec_from_file_location("reliability_hosts", HOSTS_PATH)
    hosts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hosts)
else:
    hosts = None


ISOLATION_LIMITS = hosts._isolation_limits if hosts else None


class ContainmentTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('claude'),
                         'requires installed macOS Claude Code')
    def test_installed_claude_version_starts_inside_host_wrapper(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            fixture = root / 'fixture'
            state = root / 'state'
            fixture.mkdir()
            state.mkdir()
            executable = shutil.which('claude')
            profile = {'host': 'claude',
                       'isolation_evidence': {'mechanism': 'sandbox-exec'},
                       'auth_files': [], 'state_dir': str(state)}
            argv = hosts._contain([executable, '--version'], profile,
                                  executable, fixture, [])
            run = subprocess.run(argv, cwd=fixture,
                                 env=hosts._host_environment(profile),
                                 capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('Claude Code', run.stdout)

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('codex'),
                         'requires installed macOS Codex CLI')
    def test_installed_codex_version_starts_inside_host_wrapper(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            fixture = root / 'fixture'
            state = root / 'state'
            fixture.mkdir()
            state.mkdir()
            executable = shutil.which('codex')
            profile = {'host': 'codex',
                       'isolation_evidence': {'mechanism': 'sandbox-exec'},
                       'auth_files': [], 'state_dir': str(state)}
            argv = hosts._contain([executable, '--version'], profile,
                                  executable, fixture, [])
            run = subprocess.run(argv, cwd=fixture,
                                 env=hosts._host_environment(profile),
                                 capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('codex-cli', run.stdout)

    @unittest.skipUnless(sys.platform == 'darwin', 'requires macOS sandbox-exec')
    def test_mac_host_launch_uses_sandbox_exec(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / 'fixture'
            state = root / 'state'
            fixture.mkdir()
            state.mkdir()
            profile = {'isolation_evidence': {'mechanism': 'sandbox-exec'},
                       'auth_files': [], 'state_dir': str(state)}
            argv = hosts._contain(['/usr/bin/python3', '--version'], profile,
                                  '/usr/bin/python3', fixture, [])
            self.assertEqual(argv[:2], ['/usr/bin/sandbox-exec', '-p'])
            self.assertIn('(subpath ' + json.dumps(str(state.resolve())) + ')', argv[2])

    def test_unknown_isolation_mechanism_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, 'Unknown host isolation mechanism'):
                hosts._contain(['/bin/true'], {'isolation_evidence': {}},
                               '/bin/true', Path(temp), [])


class HostTests(unittest.TestCase):
    def test_startup_certification_is_bound_to_current_auth_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            auth = root / 'auth.json'
            auth.write_text('credential A')
            evidence = root / 'startup.json'
            auth_path = str(auth.resolve())
            digest_a = hashlib.sha256(auth.read_bytes()).hexdigest()
            executable_sha256 = 'a' * 64
            isolation_evidence = {'probe_sha256': 'b' * 64,
                                  'host_identity': {'system': 'Darwin', 'mechanism': 'sandbox-exec'}}
            proof = {'schema_version': 2, 'host': 'claude', 'model': 'claude-test',
                     'startup_ok': True, 'auth_only': True,
                     'global_inputs_denied': True, 'selected_plugin_visible': True,
                     'hook_status': 'executed',
                     'auth_file_sha256': {auth_path: digest_a},
                     'executable_sha256': executable_sha256,
                     'isolation_probe_sha256': isolation_evidence['probe_sha256'],
                     'host_identity': isolation_evidence['host_identity']}
            evidence.write_text(json.dumps(proof))
            with mock.patch.dict(os.environ, {'RELIABILITY_CLAUDE_STARTUP_EVIDENCE': str(evidence)}):
                accepted, _, error = hosts._configured_startup_evidence(
                    'claude', 'claude-test', {auth_path: digest_a},
                    executable_sha256, isolation_evidence)
                self.assertIsNone(error)
                self.assertEqual(accepted, proof)
                auth.write_text('credential B')
                digest_b = hashlib.sha256(auth.read_bytes()).hexdigest()
                rejected, _, error = hosts._configured_startup_evidence(
                    'claude', 'claude-test', {auth_path: digest_b},
                    executable_sha256, isolation_evidence)
                self.assertIsNone(rejected)
                self.assertIn('auth file hash', error)
                rejected, _, error = hosts._configured_startup_evidence(
                    'claude', 'claude-test', {auth_path: digest_a},
                    'c' * 64, isolation_evidence)
                self.assertIsNone(rejected)
                self.assertIn('executable hash', error)
                rejected, _, error = hosts._configured_startup_evidence(
                    'claude', 'claude-test', {auth_path: digest_a},
                    executable_sha256,
                    {**isolation_evidence, 'probe_sha256': 'd' * 64})
                self.assertIsNone(rejected)
                self.assertIn('isolation host identity', error)
                evidence.write_text(json.dumps({**proof, 'schema_version': 1}))
                rejected, _, error = hosts._configured_startup_evidence(
                    'claude', 'claude-test', {auth_path: digest_a},
                    executable_sha256, isolation_evidence)
                self.assertIsNone(rejected)
                self.assertIn('certification contract', error)

    def test_legacy_startup_proof_cannot_certify_host_profile(self):
        self.fake("raise SystemExit('task must not run')\n")
        auth = self.root / 'auth.json'
        auth.write_text('credential')
        evidence = self.root / 'startup.json'
        evidence.write_text(json.dumps({
            'schema_version': 1, 'host': 'claude', 'model': 'claude-fixture-1',
            'startup_ok': True, 'auth_only': True,
            'global_inputs_denied': True, 'selected_plugin_visible': True,
            'hook_status': 'executed'}))
        with mock.patch.object(hosts, '_isolation_limits', side_effect=ISOLATION_LIMITS), \
             mock.patch.object(hosts, '_isolation_evidence', return_value={
                 'mechanism': 'bubblewrap', 'filesystem_enforced': True,
                 'probe_sha256': 'a' * 64, 'host_identity': {'system': 'Linux'},
                 'error': None}), \
             mock.patch.dict(os.environ, {
                 'RELIABILITY_CLAUDE_AUTH_FILES': str(auth),
                 'RELIABILITY_CLAUDE_STARTUP_EVIDENCE': str(evidence)}):
            profile = hosts._profile('claude', str(self.executable),
                '--setting-sources --settings --model --effort --permission-mode '
                '--strict-mcp-config --plugin-dir')
        self.assertFalse(profile['isolation_supported'])
        self.assertTrue(any('certification contract' in reason
                            for reason in profile['unsupported_channels']))

    def test_certified_profile_requires_declared_auth_file(self):
        self.fake("raise SystemExit('task must not run')\n")
        with mock.patch.object(hosts, '_configured_startup_evidence',
                               return_value=({'startup_ok': True}, 'digest', None)):
            profile = hosts._profile('claude', str(self.executable),
                '--setting-sources --settings --model --effort --permission-mode '
                '--strict-mcp-config --plugin-dir')
        self.assertFalse(profile['isolation_supported'])
        self.assertTrue(any('auth-file allowlist' in reason
                            for reason in profile['unsupported_channels']))

    def test_certified_profile_requires_protected_trace_channel(self):
        self.fake("raise SystemExit('task must not run')\n")
        auth = self.root / 'auth.json'
        auth.write_text('credential')
        for scope, blocked in ((0, True), (None, True), (1, False)):
            with self.subTest(scope=scope), \
                 mock.patch.object(hosts, '_configured_startup_evidence',
                                   return_value=({'startup_ok': True}, 'digest', None)), \
                 mock.patch.object(hosts, '_isolation_evidence', return_value={
                     'mechanism': 'bubblewrap', 'filesystem_enforced': True,
                     'probe_sha256': 'a' * 64, 'host_identity': {'system': 'Linux'},
                     'error': None}), \
                 mock.patch.object(hosts._isolation(), 'yama_ptrace_scope', return_value=scope), \
                 mock.patch.dict(os.environ, {'RELIABILITY_CLAUDE_AUTH_FILES': str(auth)}):
                profile = hosts._profile('claude', str(self.executable),
                    '--setting-sources --settings --model --effort --permission-mode '
                    '--strict-mcp-config --plugin-dir')
            self.assertEqual(any('protected trace channel' in reason
                                 for reason in profile['unsupported_channels']), blocked)
            self.assertEqual(profile['isolation_supported'], not blocked)

    def test_mac_profile_requires_writable_state_directory(self):
        with mock.patch.object(hosts, '_isolation_evidence', return_value={
                'mechanism': 'sandbox-exec', 'filesystem_enforced': True,
                'host_certified': False, 'error': None}), \
             mock.patch.dict(os.environ, {'RELIABILITY_CODEX_STATE_DIR': ''}):
            profile = hosts._profile('codex', sys.executable,
                '--ignore-user-config --ignore-rules --model --sandbox --config --ephemeral')
        self.assertFalse(profile['isolation_supported'])
        self.assertTrue(any('writable state directory' in limit
                            for limit in profile['unsupported_channels']))

    def test_mac_profile_rejects_auth_on_state_filesystem(self):
        state = self.root / 'state'
        state.mkdir()
        auth = self.root / 'auth.json'
        auth.write_text('synthetic')
        with mock.patch.object(hosts, '_isolation_evidence', return_value={
                'mechanism': 'sandbox-exec', 'filesystem_enforced': True,
                'host_certified': False, 'error': None}), \
             mock.patch.dict(os.environ, {
                 'RELIABILITY_CODEX_STATE_DIR': str(state),
                 'RELIABILITY_CODEX_AUTH_FILES': str(auth)}):
            profile = hosts._profile('codex', sys.executable,
                '--ignore-user-config --ignore-rules --model --sandbox --config --ephemeral')
        self.assertFalse(profile['isolation_supported'])
        self.assertTrue(any('separate filesystem' in limit
                            for limit in profile['unsupported_channels']))
        self.assertTrue(any('cannot be pinned' in limit
                            for limit in profile['unsupported_channels']))

    def test_file_path_import_resolves_sibling_tool_events(self):
        root = Path(__file__).resolve().parents[2]
        script = ("import importlib.util, pathlib, sys; "
                  "sys.path.insert(0, sys.argv[1]); "
                  "spec = importlib.util.spec_from_file_location('reliability_hosts', sys.argv[2]); "
                  "module = importlib.util.module_from_spec(spec); "
                  "spec.loader.exec_module(module); "
                  "assert callable(module.extract_tool_events)")
        result = subprocess.run([sys.executable, '-I', '-c', script,
                                 str(root), str(HOSTS_PATH.resolve())],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_deeply_nested_trace_does_not_abort_host_metadata(self):
        trace = self.root / 'deep-trace.jsonl'
        trace.write_text('[' * 1_000_000 + '0' + ']' * 1_000_000)
        metadata = hosts._trace_metadata(trace, host='codex')
        self.assertEqual(metadata['tool_events'], [])
        self.assertTrue(metadata['tool_event_issues'])

    def test_malformed_metadata_cannot_supply_model_identity(self):
        trace = self.root / 'conflicting-trace.jsonl'
        trace.write_text('{"type":"system","model":"wrong","model":"claimed"}\n')
        metadata = hosts._trace_metadata(trace, host='claude')
        self.assertIsNone(metadata['observed_model'])
        self.assertTrue(metadata['tool_event_issues'])

    def setUp(self):
        self.assertIsNotNone(hosts, "host execution adapter has not been implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixture = self.root / "fixture"
        self.fixture.mkdir()
        self.traces = self.root / "private-traces"
        self.plugin = self.root / "plugin source"
        self.plugin.mkdir()
        self.executable = self.root / "fake-cli"
        # Exercise process handling with a simulated certified host. Real hosts
        # remain fail-closed; the production adapter has no bypass switch.
        patcher = mock.patch.object(hosts, "_isolation_limits", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        canary = mock.patch.object(hosts, "_isolation_evidence", return_value={
            "filesystem_enforced": True, "host_certified": False, "error": None})
        canary.start()
        self.addCleanup(canary.stop)
        uncontained_test_double = mock.patch.object(
            hosts, '_contain', side_effect=lambda argv, *_: argv)
        uncontained_test_double.start()
        self.addCleanup(uncontained_test_double.stop)
        env = mock.patch.dict(os.environ, {"RELIABILITY_CLAUDE_MODEL": "claude-fixture-1",
                                          "RELIABILITY_CODEX_MODEL": "codex-fixture-1"})
        env.start()
        self.addCleanup(env.stop)

    def fake(self, body, *, mcp=None):
        self.executable.write_text(
            "#!" + sys.executable + "\nimport json, os, sys, time, subprocess, signal\n"
            "if '--version' in sys.argv:\n print('test-cli 1.0'); sys.exit(0)\n"
            "if '--help' in sys.argv:\n print('--setting-sources --settings --model --effort --permission-mode --strict-mcp-config --plugin-dir --ignore-user-config --ignore-rules --sandbox --config --ephemeral'); sys.exit(0)\n"
            "if sys.argv[1:4] == ['mcp', 'list', '--json']:\n"
            " print(" + repr(json.dumps(mcp or [])) + "); sys.exit(0)\n" + body,
            encoding="utf-8",
        )
        self.executable.chmod(0o700)
        patcher = mock.patch.object(hosts.shutil, "which", return_value=str(self.executable))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_fake(self, host="codex", timeout_seconds=3):
        return hosts.run_host(host, self.fixture, "Do the task", [self.plugin], self.traces,
                              timeout_seconds=timeout_seconds)

    def test_inspect_host_reports_executable_and_version_without_running_task(self):
        self.fake("raise SystemExit('task must not run')\n")
        result = hosts.inspect_host("claude")
        self.assertTrue(result["available"])
        self.assertEqual(result["executable"], str(self.executable))
        self.assertEqual(result["version"], "test-cli 1.0")

    def test_unsupported_host_and_missing_fixture_are_rejected(self):
        with self.assertRaises(ValueError):
            hosts.inspect_host("unknown")
        with self.assertRaises(ValueError):
            hosts.build_command("unknown", self.fixture, "prompt", [], self.traces)
        with self.assertRaises(FileNotFoundError):
            hosts.run_host("codex", self.root / "missing", "prompt", [], self.traces)

    def test_claude_loads_only_session_plugins_and_uses_structured_output(self):
        self.fake("pass\n")
        argv = hosts.build_command("claude", self.fixture, "--literal prompt", [self.plugin], self.traces)
        self.assertEqual(argv[argv.index("--plugin-dir") + 1], str(self.plugin))
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
        self.assertIn("--verbose", argv)
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(json.loads(argv[argv.index("--mcp-config") + 1]), {"mcpServers": {}})
        self.assertEqual(argv[-2:], ["--", "--literal prompt"])
        self.assertFalse(any("bypass" in arg or "skip-permissions" in arg for arg in argv))
        self.assertEqual(argv[argv.index("--model") + 1], "claude-fixture-1")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project,local")

    def test_codex_ignores_user_config_and_pins_model_and_permissions(self):
        self.fake("pass\n", mcp=[{"name": "unrelated-service", "enabled": True}])
        argv = hosts.build_command("codex", self.fixture, "Do the task", [self.plugin], self.traces)
        self.assertIn("--json", argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write")
        self.assertEqual(argv[argv.index("--cd") + 1], str(self.fixture))
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("--ignore-rules", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "codex-fixture-1")
        self.assertIn('approval_policy="never"', argv)
        self.assertIn(str(self.plugin), argv[-1])
        self.assertIn("Do the task", argv[-1])
        for forbidden in ("danger-full-access",
                          "--dangerously-bypass-approvals-and-sandbox"):
            self.assertNotIn(forbidden, argv)

    def test_codex_state_writes_are_redirected_into_bound_state(self):
        state = self.root / "codex-state"
        state.mkdir()
        environment = hosts._host_environment({"host": "codex", "state_dir": str(state)})
        self.assertEqual(environment["HOME"], str(state))
        self.assertEqual(environment["CODEX_HOME"], str(state))
        self.assertEqual(environment["TMPDIR"], str(state / "tmp"))

    def test_claude_keeps_home_when_config_root_is_explicit(self):
        state = self.root / "claude-state"
        state.mkdir()
        environment = hosts._host_environment({"host": "claude", "state_dir": str(state)})
        self.assertNotIn("CODEX_HOME", environment)
        self.assertNotEqual(environment.get("HOME"), str(state))

    def test_success_captures_private_raw_traces_and_observed_metadata(self):
        self.fake("print(json.dumps({'type':'system','subtype':'init','model':'fixture-model'}))\n"
                  "print(json.dumps({'type':'result','is_error':False,'usage':{'input_tokens':3}}))\n"
                  "print('routine warning', file=sys.stderr)\n")
        result = self.run_fake("claude")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["observed_model"], "fixture-model")
        self.assertEqual(result["usage"], {"input_tokens": 3})
        for key in ("raw_stdout_path", "raw_stderr_path"):
            path = Path(result[key])
            self.assertTrue(path.is_file())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.traces.stat().st_mode), 0o700)
        self.assertIn("routine warning", Path(result["raw_stderr_path"]).read_text())

    def test_usage_without_model_does_not_invent_identity(self):
        self.fake("print(json.dumps({'type':'turn.completed','usage':{'input_tokens':2,'output_tokens':4}}))\n")
        result = self.run_fake()
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(result["observed_model"])
        self.assertEqual(result["usage"], {"input_tokens": 2, "output_tokens": 4})

    def test_codex_thread_start_binds_identity_to_frozen_launch_model(self):
        self.fake("print(json.dumps({'type':'thread.started','thread_id':'t'}))\n"
                  "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':2}}))\n")
        result = self.run_fake("codex")
        self.assertEqual(result["observed_model"], "codex-fixture-1")

    def test_host_result_retains_native_tool_attempts_without_tool_output(self):
        self.fake("print(json.dumps({'type':'thread.started','thread_id':'t'}))\n"
                  "print(json.dumps({'type':'item.started','item':{'id':'c1',"
                  "'type':'command_execution','status':'in_progress',"
                  "'command':'private command'}}))\n"
                  "print(json.dumps({'type':'item.completed','item':{'id':'c1',"
                  "'type':'command_execution','command':'private command',"
                  "'exit_code':0,'status':'completed','aggregated_output':'private output'}}))\n")
        result = self.run_fake("codex")
        self.assertEqual(result["tool_event_issues"], [])
        self.assertEqual(len(result["tool_events"]), 1)
        self.assertEqual(result["tool_events"][0]["status"], "responded")
        self.assertNotIn("private command", str(result["tool_events"]))
        self.assertNotIn("private output", str(result["tool_events"]))

    def test_malformed_trace_lines_do_not_hide_later_metadata(self):
        self.fake("print('not-json')\nprint('[]')\n"
                  "print(json.dumps({'type':'assistant','message':{'model':'fixture-model'}}))\n")
        result = self.run_fake("claude")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["observed_model"], "fixture-model")
        self.assertIsNone(result["usage"])

    def test_placeholder_diagnostic_model_does_not_overwrite_real_identity(self):
        self.fake("print(json.dumps({'type':'assistant','message':{'model':'fixture-model'}}))\n"
                  "print(json.dumps({'type':'assistant','message':{'model':'<synthetic>'}}))\n")
        result = self.run_fake("claude")
        self.assertEqual(result["observed_model"], "fixture-model")

    def test_provider_usage_limit_is_infrastructure_failure(self):
        self.fake("print(json.dumps({'type':'rate_limit_event','rate_limit_info':{'status':'rejected'}}))\n"
                  "print(json.dumps({'type':'error','message':'You have hit your usage limit'}))\n")
        result = self.run_fake("claude")
        self.assertEqual(result["status"], "infrastructure_failed")

    def test_provider_authentication_rejection_is_infrastructure_failure(self):
        self.fake("print(json.dumps({'type':'result','is_error':True,"
                  "'api_error_status':401,'result':'Failed to authenticate. HTTP 401'}))\n")
        result = self.run_fake("claude")
        self.assertEqual(result["status"], "infrastructure_failed")

    def test_only_explicit_command_receipts_are_exposed_as_evidence_inputs(self):
        valid = {"type": "agentic.command.completed", "evidence_id": "e1",
                 "run_id": "r", "source_revision": 2, "command": "pytest",
                 "cwd": ".", "source_hash": "sha256:abc", "exit_status": 0,
                 "host_record": {"record_id": "host-e1"}}
        self.fake("print(json.dumps(" + repr(valid) + "))\n"
                  "print(json.dumps({'type':'agentic.command.completed','run_id':'r'}))\n")
        result = self.run_fake("claude")
        self.assertEqual(result["command_receipts"][0]["evidence_id"], "e1")
        self.assertEqual(result["invalid_command_receipts"], 1)

    def test_retained_trace_can_be_adapted_to_signed_receipts(self):
        event = {"type": "agentic.command.completed", "evidence_id": "e1", "run_id": "r",
                 "source_revision": 1, "command": "pytest", "cwd": ".",
                 "source_hash": "sha256:abc", "exit_status": 0}
        self.fake("print(json.dumps(" + repr(event) + "))\n")
        result = self.run_fake("claude")
        receipts = hosts.adapt_trace_receipts(result["raw_stdout_path"], b"key",
                                              identity="claude", issued_at=1, expires_at=2)
        self.assertEqual(receipts[0]["host_record"]["identity"], "claude")

    def test_run_host_can_adapt_receipts_at_the_host_boundary(self):
        event = {"type": "agentic.command.completed", "evidence_id": "e1", "run_id": "r",
                 "source_revision": 1, "command": "pytest", "cwd": ".",
                 "source_hash": "sha256:abc", "exit_status": 0}
        self.fake("print(json.dumps(" + repr(event) + "))\n")
        # The normal path is deliberately opt-in: the caller supplies the
        # assignment-scoped key and identity after recording the dispatch.
        result = hosts.run_host("claude", self.fixture, "Do the task", [self.plugin], self.traces,
                                evidence_key=b"key", evidence_identity="claude-assignment",
                                evidence_issued_at=1, evidence_expires_at=2000000000)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["adapted_receipts"][0]["host_record"]["identity"],
                         "claude-assignment")
        self.assertNotIn("evidence_adapter_error", result)

    def test_adapted_receipts_can_be_ingested_with_coordinator_fencing(self):
        event = {"type": "agentic.command.completed", "evidence_id": "e1", "run_id": "r",
                 "source_revision": 2, "command": "pytest", "cwd": ".",
                 "source_hash": "sha256:abc", "exit_status": 0}
        self.fake("print(json.dumps(" + repr(event) + "))\n")
        result = hosts.run_host("claude", self.fixture, "Do the task", [self.plugin], self.traces,
                                evidence_key=b"key", evidence_identity="claude-assignment",
                                evidence_issued_at=1, evidence_expires_at=2000000000)
        store = RuntimeStore(self.root, host_key=b"key")
        store.create_run("r")
        run = store.acquire_lease("r", "coord")
        run = store.transition("r", "running", expected_revision=run["revision"],
                               lease_epoch=run["lease_epoch"], coordinator_id="coord")
        accepted = hosts.ingest_adapted_receipts(
            store, result["adapted_receipts"], expected_revision=run["revision"],
            lease_epoch=run["lease_epoch"], coordinator_id="coord")
        self.assertEqual(accepted["accepted"], ["e1"])
        self.assertEqual(store.get_run("r")["revision"], accepted["revision"])

    def test_partial_host_evidence_context_fails_before_launch(self):
        marker = self.root / "task-started"
        self.fake("open(" + repr(str(marker)) + ",'w').close()\n")
        with self.assertRaises(ValueError):
            hosts.run_host("codex", self.fixture, "task", [], self.traces,
                           evidence_key=b"key", evidence_identity="assignment")
        self.assertFalse(marker.exists())

    def test_missing_required_flag_fails_closed_before_task_launch(self):
        marker = self.root / "task-started"
        self.fake("open(" + repr(str(marker)) + ",'w').close()\n")
        content = self.executable.read_text().replace("--ignore-rules", "--unsupported-rules")
        self.executable.write_text(content)
        result = self.run_fake()
        self.assertEqual(result["status"], "infrastructure_failed")
        self.assertFalse(marker.exists())

    def test_launch_auth_preflight_failure_returns_infrastructure_result(self):
        self.fake("raise SystemExit('task must not run')\n")
        with mock.patch.object(hosts, '_contain',
                               side_effect=ValueError('Allowed auth file is hard-linked')):
            result = self.run_fake()
        self.assertEqual(result['status'], 'infrastructure_failed')
        self.assertIn('Allowed auth file is hard-linked', result['error'])
        self.assertIsNone(result['exit_code'])
        self.assertTrue(Path(result['raw_stdout_path']).is_file())
        self.assertTrue(Path(result['raw_stderr_path']).is_file())

    def test_real_isolation_limits_block_launch_with_named_channels(self):
        marker = self.root / "task-started"
        self.fake("open(" + repr(str(marker)) + ",'w').close()\n")
        with mock.patch.object(hosts, "_isolation_limits", side_effect=ISOLATION_LIMITS):
            for host in ("claude", "codex"):
                result = self.run_fake(host)
                self.assertEqual(result["status"], "infrastructure_failed")
                self.assertIn("Host isolation unavailable", result["error"])
                self.assertIn("policy", result["error"])
        self.assertFalse(marker.exists())

    def test_failed_filesystem_canary_blocks_even_simulated_host_certification(self):
        marker = self.root / "task-started"
        self.fake("open(" + repr(str(marker)) + ",'w').close()\n")
        with mock.patch.object(hosts, "_isolation_evidence", return_value={
                "filesystem_enforced": False, "host_certified": False,
                "error": "Filesystem containment canary failed"}):
            result = self.run_fake()
        self.assertEqual(result["status"], "infrastructure_failed")
        self.assertIn("canary failed", result["error"])
        self.assertFalse(marker.exists())

    def test_missing_and_alias_models_fail_closed(self):
        self.fake("raise SystemExit('task must not run')\n")
        for model in ("", "opus", "opus[1m]"):
            with mock.patch.dict(os.environ, {"RELIABILITY_CLAUDE_MODEL": model}):
                self.assertEqual(self.run_fake("claude")["status"], "infrastructure_failed")

    def test_frozen_profile_drift_rejected_before_launch(self):
        marker = self.root / "task-started"
        self.fake("open(" + repr(str(marker)) + ",'w').close()\n")
        profile = hosts.inspect_host("codex")["profile"]
        with mock.patch.dict(os.environ, {"RELIABILITY_CODEX_MODEL": "changed-model"}):
            result = hosts.run_host("codex", self.fixture, "task", [], self.traces,
                                    expected_profile=profile)
        self.assertEqual(result["status"], "infrastructure_failed")
        self.assertIn("drifted", result["error"])
        self.assertFalse(marker.exists())

    def test_auth_failure_inside_structured_event_is_infrastructure_failure(self):
        self.fake("print(json.dumps({'type':'turn.failed','error':{'message':'Authentication failed'}}))\n")
        self.assertEqual(self.run_fake()["status"], "infrastructure_failed")

    def test_nonzero_task_failure_is_not_infrastructure_failure(self):
        self.fake("print('assertion failed in task', file=sys.stderr)\nsys.exit(2)\n")
        result = self.run_fake()
        self.assertEqual(result["status"], "product_failed")
        self.assertEqual(result["exit_code"], 2)

    def test_structured_task_failure_is_detected_even_with_zero_exit(self):
        for event in ({"type": "result", "is_error": True},
                      {"type": "turn.failed", "error": {"message": "task failed"}}):
            with self.subTest(event=event):
                self.fake("print(" + repr(json.dumps(event)) + ")\n")
                self.assertEqual(self.run_fake()["status"], "product_failed")

    def test_auth_and_invalid_configuration_are_infrastructure_failures(self):
        for error in ("Not logged in. Please run login", "Error loading config.toml: invalid TOML"):
            with self.subTest(error=error):
                self.fake("print(" + repr(error) + ", file=sys.stderr)\nsys.exit(1)\n")
                self.assertEqual(self.run_fake()["status"], "infrastructure_failed")

    def test_missing_executable_returns_infrastructure_failure(self):
        with mock.patch.object(hosts.shutil, "which", return_value=None):
            self.assertFalse(hosts.inspect_host("codex")["available"])
            result = self.run_fake()
        self.assertEqual(result["status"], "infrastructure_failed")
        self.assertIsNone(result["exit_code"])

    def test_invalid_timeout_is_rejected(self):
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.run_fake(timeout_seconds=timeout)

    def test_checkpoint_interrupts_process_and_records_disk_observation(self):
        checkpoint = self.fixture / "checkpoint.json"
        self.fake("open(" + repr(str(checkpoint)) + ",'w').write('{}')\ntime.sleep(20)\n")
        result = hosts.run_host("claude", self.fixture, "Do the task", [self.plugin],
                                self.traces, timeout_seconds=3, checkpoint_path=checkpoint)
        self.assertEqual(result["status"], "interrupted")
        self.assertTrue(result["checkpoint_observed"])
        self.assertLess(result["elapsed_seconds"], 2)

    def test_checkpoint_text_in_stdout_does_not_trigger_interruption(self):
        checkpoint = self.fixture / "checkpoint.json"
        self.fake("print(" + repr(str(checkpoint)) + ")\n")
        result = hosts.run_host("claude", self.fixture, "Do the task", [self.plugin],
                                self.traces, timeout_seconds=3, checkpoint_path=checkpoint)
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["checkpoint_observed"])

    def test_setup_probe_obeys_total_timeout_budget(self):
        self.fake("pass\n")
        content = self.executable.read_text().replace("print('test-cli 1.0');", "time.sleep(20); print('test-cli 1.0');")
        self.executable.write_text(content)
        result = self.run_fake(timeout_seconds=0.3)
        self.assertEqual(result["status"], "timed_out")
        self.assertLess(result["elapsed_seconds"], 2)

    @unittest.skipUnless(os.name == "posix", "process groups require POSIX")
    def test_timeout_kills_descendant_even_when_it_ignores_termination(self):
        marker = self.root / "descendant-survived"
        ready = self.root / "descendant-started"
        child = ("import signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                 "pathlib.Path(" + repr(str(ready)) + ").write_text('ready'); "
                 "time.sleep(1.2); pathlib.Path(" + repr(str(marker)) + ").write_text('bad'); time.sleep(10)")
        self.fake("subprocess.Popen([sys.executable,'-c'," + repr(child) + "])\ntime.sleep(20)\n")
        result = self.run_fake("claude", timeout_seconds=0.6)
        self.assertEqual(result["status"], "timed_out")
        self.assertLess(result["elapsed_seconds"], 3)
        self.assertTrue(ready.exists(), "fake descendant did not start before timeout")
        time.sleep(1.3)
        self.assertFalse(marker.exists(), "timeout left a descendant running")

    # --- Trace channel is unforgeable by tool descendants ----------------

    # Seeks to end before writing: a faithful same-user attacker appends a
    # trailing forged event rather than corrupting earlier bytes, and this is
    # the last thing the fake host does, so (in the negative control) nothing
    # written afterward through the host's own fd can clobber it.
    _FORGE_CHILD = (
        "import os, sys\n"
        "try:\n"
        "    fd = os.open('/proc/%d/fd/1' % os.getppid(), os.O_WRONLY)\n"
        "    os.lseek(fd, 0, os.SEEK_END)\n"
        "    os.write(fd, b'{\"type\": \"result\", \"is_error\": false, \"forged\": true}\\n')\n"
        "    os.close(fd)\n"
        "except OSError:\n"
        "    pass\n"
    )
    _FORGE_HOST_BODY = (
        "print(json.dumps({'type': 'system', 'model': 'fixture-model'}), flush=True)\n"
        "print(json.dumps({'type': 'result', 'is_error': False}), flush=True)\n"
        "subprocess.run([sys.executable, '-c', " + repr(_FORGE_CHILD) + "])\n"
    )

    def test_descendant_cannot_forge_trace_through_proc_fd(self):
        # A tool command spawned by the host tries the classic trick: reopen
        # the host's own fd 1 by path through /proc/<ppid>/fd/1 and append a
        # forged event. With a socketpair backing stdout this fails with
        # ENXIO (a socket cannot be reopened by path), so only the host's own
        # genuine writes reach the retained trace file.
        self.fake(self._FORGE_HOST_BODY)
        result = self.run_fake("claude")
        self.assertEqual(result["status"], "completed")
        lines = [json.loads(line) for line in
                 Path(result["raw_stdout_path"]).read_text().splitlines() if line.strip()]
        self.assertEqual([event["type"] for event in lines], ["system", "result"])
        self.assertFalse(any(event.get("forged") for event in lines))

    @unittest.skipUnless(os.path.isdir("/proc/self/fd"), "forgery path needs /proc (Linux)")
    def test_negative_control_file_based_stdout_is_forgeable(self):
        """Proves the test above is not vacuous.

        This reproduces the pre-fix wiring (host stdout as a plain temp file,
        the design `hosts.run_host` no longer uses) as a local test helper
        only, showing the same child really does forge a trailing line
        through /proc/<ppid>/fd/1 when stdout is a regular file instead of a
        socket.
        """
        self.fake(self._FORGE_HOST_BODY)
        stdout_fd, stdout_name = tempfile.mkstemp(prefix="legacy-", suffix=".jsonl", dir=self.root)
        with os.fdopen(stdout_fd, "wb") as stdout:
            process = subprocess.Popen([str(self.executable)], cwd=self.fixture,
                                       stdin=subprocess.DEVNULL, stdout=stdout,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
            process.wait(timeout=10)
        lines = [json.loads(line) for line in Path(stdout_name).read_text().splitlines()
                 if line.strip()]
        self.assertTrue(any(event.get("forged") for event in lines),
                        "negative control did not reproduce the pre-fix forgery")

    def test_drain_socket_caps_written_bytes_but_keeps_draining(self):
        host_end, child_end = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        dest_path = self.root / "capped.bin"
        with dest_path.open("wb") as dest:
            thread = threading.Thread(target=hosts._drain_socket, args=(host_end, dest, 10))
            thread.start()
            child_end.sendall(b"0123456789ABCDEFGHIJ")  # 20 bytes into a 10-byte cap
            child_end.close()
            thread.join(timeout=5)
        self.assertEqual(dest_path.read_bytes(), b"0123456789")

    def test_run_host_enforces_trace_size_limit_through_the_socket_drain(self):
        payload = json.dumps({"type": "result", "is_error": False, "pad": "x" * 500})
        self.fake("print(" + repr(payload) + ")\n")
        with mock.patch.object(hosts, "MAX_TRACE_BYTES", 50):
            result = self.run_fake("claude")
        # The drain wrote one byte past the (patched) cap; the truncated
        # prefix is never read for identity, usage or receipts.
        self.assertEqual(Path(result["raw_stdout_path"]).stat().st_size, 51)
        self.assertEqual(result["status"], "infrastructure_failed")
        self.assertEqual(result["error"], "host trace exceeds size limit")
        self.assertIsNone(result["observed_model"])
        self.assertEqual(result["command_receipts"], [])
        self.assertEqual(result["tool_events"], [])
        self.assertIn("exceeds tool event limit", result["tool_event_issues"][0])

    def test_run_host_fails_on_oversized_stderr(self):
        self.fake("import sys\nsys.stderr.write('e' * 200)\n")
        with mock.patch.object(hosts, "MAX_TRACE_BYTES", 50):
            result = self.run_fake("claude")
        self.assertEqual(result["status"], "infrastructure_failed")

    def test_profile_records_trace_channel_evidence_without_gating_launch(self):
        self.fake("pass\n")
        profile = hosts.inspect_host("claude")["profile"]
        self.assertEqual(profile["trace_channel"]["channel"], "socketpair")
        self.assertIn("trace_channel_protected", profile["trace_channel"])
        # Purely informational: the mocked canary in setUp carries no
        # 'mechanism', so it cannot certify the trace channel either, yet the
        # simulated host above is still allowed to launch (existing gating
        # is untouched by this new evidence).
        self.assertFalse(profile["trace_channel"]["trace_channel_protected"])
        self.assertTrue(profile["isolation_supported"])


def _bwrap_usable() -> bool:
    if hosts is None:
        return False
    isolation = hosts._isolation()
    bwrap = isolation.linux_executable()
    if bwrap is None:
        return False
    return subprocess.run(isolation.linux_argv(bwrap, Path("/tmp"), command=["/bin/true"]),
                          capture_output=True).returncode == 0


class LinuxContainedLaunchTests(unittest.TestCase):
    """A fake host launched through the production Linux wrapper, not a model."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixture = self.root / "fixture"
        self.fixture.mkdir()
        (self.root / "plugin" / "hooks").mkdir(parents=True)
        (self.root / "plugin" / "SKILL.md").write_text("selected")
        (self.root / "secret").write_text("global instruction")
        (self.root / "auth.json").write_text("token")
        (self.root / "bin").mkdir()
        self.cli = self.root / "bin" / "fake-cli"
        self.repo = self.root / "repo"
        self.repo.mkdir()
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}
        (self.repo / "f").write_text("x")
        for args in (["init", "-q"], ["add", "."], ["commit", "-qm", "i"]):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True, env=env)
        for patch in (mock.patch.object(hosts, "_isolation_limits", return_value=[]),
                      mock.patch.dict(os.environ, {"RELIABILITY_CODEX_MODEL": "codex-fixture-1",
                                                   "AGENTIC_HOST_KEY": "launch-key"}),
                      mock.patch.object(hosts.shutil, "which", return_value=str(self.cli))):
            patch.start()
            self.addCleanup(patch.stop)

    def evidence(self, mechanism):
        return mock.patch.object(hosts, "_isolation_evidence", return_value={
            "mechanism": mechanism, "filesystem_enforced": True, "host_certified": False,
            "error": None, "probe_sha256": "p", "host_identity": {"system": "Linux"}})

    def write_cli(self, body):
        self.cli.write_text(
            "#!" + sys.executable + "\nimport json, os, pathlib, sys\n"
            "if '--version' in sys.argv:\n print('test-cli 1.0'); sys.exit(0)\n"
            "if '--help' in sys.argv:\n print('--ignore-user-config --ignore-rules --model "
            "--sandbox --config --ephemeral'); sys.exit(0)\n" + body)
        self.cli.chmod(0o700)

    @unittest.skipUnless(_bwrap_usable(), "requires bubblewrap with user namespaces")
    def test_wrapped_host_is_confined_to_fixture_and_selected_inputs(self):
        root = repr(str(self.root))
        self.write_cli(
            "r = pathlib.Path(" + root + "); out = {}\n"
            "def denied(f):\n try: f(); return False\n except OSError: return True\n"
            "(pathlib.Path.cwd() / 'work').write_text('done')\n"
            "out['plugin'] = (r / 'plugin' / 'SKILL.md').read_text() == 'selected'\n"
            "out['secret'] = denied(lambda: (r / 'secret').read_text())\n"
            "out['auth'] = denied(lambda: (r / 'auth.json').read_text())\n"
            "out['outside'] = denied(lambda: (r / 'escape').write_text('x'))\n"
            "out['key'] = 'AGENTIC_HOST_KEY' not in os.environ\n"
            "print(json.dumps({'type': 'probe', **out}))\n")
        with self.evidence("bubblewrap"):
            result = hosts.run_host("codex", self.fixture, "task", [self.root / "plugin"],
                                    self.root / "traces", timeout_seconds=20,
                                    receipt_repository=self.repo)
        self.assertEqual(result["status"], "completed", result)
        self.assertIn("--unshare-pid", result["argv"])
        probe = json.loads(Path(result["raw_stdout_path"]).read_text())
        self.assertEqual(probe, {"type": "probe", "plugin": True, "secret": True, "auth": True,
                                 "outside": True, "key": True})
        self.assertEqual((self.fixture / "work").read_text(), "done")
        self.assertFalse((self.root / "escape").exists())
        isolation = hosts._isolation()
        receipt = isolation.verify_command_receipt(
            result["isolation_receipt"], b"launch-key",
            repository_revision=isolation.repository_revision(self.repo)["revision"],
            fixture_sha256=isolation.fixture_binding(self.fixture)["tree_sha256"],
            host="codex", model="codex-fixture-1")
        self.assertEqual(receipt["isolation_mechanism"], "bubblewrap")
        self.assertEqual(receipt["exit_status"], 0)

    @unittest.skipUnless(_bwrap_usable(), "requires bubblewrap with user namespaces")
    def test_tool_descendant_inside_real_bwrap_cannot_forge_the_trace(self):
        # Under --unshare-pid the host shares its PID namespace with tool
        # commands it runs, so a same-user descendant can see the host's pid
        # in /proc. This exercises
        # that exact scenario end to end through the production bubblewrap
        # wrapper and confirms the socketpair still denies the reopen.
        forge = (
            "import os, sys\n"
            "try:\n"
            "    fd = os.open('/proc/%d/fd/1' % os.getppid(), os.O_WRONLY)\n"
            "    os.lseek(fd, 0, os.SEEK_END)\n"
            "    os.write(fd, b'{\"type\": \"result\", \"forged\": true}\\n')\n"
            "    os.close(fd)\n"
            "except OSError:\n"
            "    pass\n"
        )
        self.write_cli(
            "import subprocess\n"
            "print(json.dumps({'type': 'system', 'model': 'codex-fixture-1'}), flush=True)\n"
            "print(json.dumps({'type': 'result', 'is_error': False}), flush=True)\n"
            "subprocess.run([sys.executable, '-c', " + repr(forge) + "])\n")
        with self.evidence("bubblewrap"):
            result = hosts.run_host("codex", self.fixture, "task", [], self.root / "traces",
                                    timeout_seconds=20)
        self.assertEqual(result["status"], "completed", result)
        lines = [json.loads(line) for line in
                 Path(result["raw_stdout_path"]).read_text().splitlines() if line.strip()]
        self.assertEqual([event["type"] for event in lines], ["system", "result"])
        self.assertFalse(any(event.get("forged") for event in lines))

    @unittest.skipUnless(_bwrap_usable(), "requires bubblewrap with user namespaces")
    def test_declared_auth_file_is_the_only_home_input_bound(self):
        self.write_cli("")
        original = hosts._profile
        declared = lambda *a, **k: dict(original(*a, **k), auth_files=[str(self.root / "auth.json")])
        with self.evidence("bubblewrap"), mock.patch.object(hosts, "_profile", side_effect=declared):
            argv = hosts.build_command("codex", self.fixture, "task", [], self.root)
        bound = [argv[i + 1] for i, a in enumerate(argv) if a in ("--bind", "--ro-bind")]
        self.assertIn(str(self.root / "auth.json"), bound)
        self.assertNotIn(str(self.root), bound)
        self.assertEqual([argv[i + 1] for i, a in enumerate(argv) if a == "--bind"],
                         [str(self.fixture)])

    def test_host_never_receives_signing_key_and_missing_key_blocks_receipt(self):
        marker = self.fixture / "env"
        self.write_cli("pathlib.Path(" + repr(str(marker)) + ").write_text("
                       "str('AGENTIC_HOST_KEY' in os.environ))\n")
        with self.evidence(None), mock.patch.object(
                hosts, '_contain', side_effect=lambda argv, *_: argv):
            result = hosts.run_host("codex", self.fixture, "task", [], self.root / "traces",
                                    timeout_seconds=10, receipt_repository=self.repo)
        self.assertEqual(marker.read_text(), "False")
        self.assertEqual(result["isolation_receipt"]["model"], "codex-fixture-1")
        del os.environ["AGENTIC_HOST_KEY"]
        with self.evidence(None), mock.patch.object(
                hosts, '_contain', side_effect=lambda argv, *_: argv):
            result = hosts.run_host("codex", self.fixture, "task", [], self.root / "traces",
                                    timeout_seconds=10, receipt_repository=self.repo)
        self.assertNotIn("isolation_receipt", result)
        self.assertIn("AGENTIC_HOST_KEY", result["isolation_receipt_error"])

    def test_unavailable_bubblewrap_at_launch_fails_closed(self):
        marker = self.fixture / "started"
        self.write_cli("pathlib.Path(" + repr(str(marker)) + ").write_text('bad')\n")
        with self.evidence("bubblewrap"), \
             mock.patch.object(hosts._isolation(), "linux_executable", return_value=None):
            result = hosts.run_host("codex", self.fixture, "task", [], self.root / "traces",
                                    timeout_seconds=10, receipt_repository=self.repo)
        self.assertEqual(result["status"], "infrastructure_failed")
        self.assertFalse(marker.exists())
        self.assertEqual(result["isolation_receipt_error"], "host was not launched")


if __name__ == "__main__":
    unittest.main()
