import tempfile
import unittest

from runtime.agentic_runtime.host import adapt_command_event, sign_dispatch
from runtime.agentic_runtime.store import RuntimeStore
from runtime.agentic_runtime.trace import ingest_command_event


class TraceIngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.key = b"adapter-key"
        self.store = RuntimeStore(self.tmp.name, host_key=self.key)
        self.store.create_run("r")
        self.store.transition("r", "running")

    def event(self, **changes):
        run = self.store.get_run("r")
        host = sign_dispatch({
            "record_id": "event-host", "purpose": "evidence.record",
            "run_id": "r", "identity": "claude", "evidence_id": "e1",
            "source_revision": run["revision"], "source_hash": "sha256:abc",
            "exit_status": 0, "kind": "host.command", "command": "pytest", "cwd": ".",
            "required": True, "issued_at": 0, "expires_at": 9999999999,
        }, self.key)
        result = {
            "type": "agentic.command.completed", "evidence_id": "e1",
            "run_id": "r", "source_revision": run["revision"],
            "command": "pytest", "cwd": ".", "source_hash": "sha256:abc",
            "exit_status": 0, "host_record": host,
        }
        result.update(changes)
        return result

    def test_ingest_persists_signed_receipt(self):
        evidence = ingest_command_event(self.store, self.event())
        self.assertEqual(evidence["evidence_id"], "e1")
        self.assertEqual(evidence["host_record_id"], "event-host")

    def test_ingest_retains_failed_signed_command(self):
        event = self.event(exit_status=1)
        event["host_record"] = sign_dispatch({
            **{key: value for key, value in event["host_record"].items() if key != "signature"},
            "exit_status": 1,
        }, self.key)
        evidence = ingest_command_event(self.store, event)
        self.assertEqual(evidence["exit_status"], 1)
        self.assertEqual(evidence["required"], 1)

    def test_host_marks_exploratory_failure_optional_before_signing(self):
        run = self.store.get_run("r")
        event = adapt_command_event({
            "type": "agentic.command.completed", "evidence_id": "optional-check",
            "run_id": "r", "source_revision": run["revision"],
            "command": "probe --expect-failure", "cwd": ".",
            "source_hash": "sha256:abc", "exit_status": 1, "required": False,
        }, self.key, identity="claude", issued_at=0, expires_at=9999999999)
        receipt = ingest_command_event(self.store, event)
        self.assertEqual(receipt["required"], 0)

    def test_malformed_event_has_no_store_side_effect(self):
        before = self.store.get_run("r")["revision"]
        with self.assertRaisesRegex(ValueError, "explicit"):
            ingest_command_event(self.store, {"type": "assistant", "text": "passed"})
        self.assertEqual(self.store.get_run("r")["revision"], before)

    def test_event_run_mismatch_is_rejected_by_store(self):
        event = self.event(run_id="other")
        with self.assertRaises((KeyError, RuntimeError)):
            ingest_command_event(self.store, event)


if __name__ == "__main__":
    unittest.main()
