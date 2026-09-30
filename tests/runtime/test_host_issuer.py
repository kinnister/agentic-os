import unittest
import tempfile

from runtime.agentic_runtime.host import adapt_command_event, issue_evidence_record, verify_dispatch
from runtime.agentic_runtime.store import RuntimeStore
from runtime.agentic_runtime.trace import command_receipt


class HostIssuerTests(unittest.TestCase):
    def event(self):
        return {"type": "agentic.command.completed", "evidence_id": "e1", "run_id": "r",
                "source_revision": 2, "command": "pytest", "cwd": ".",
                "source_hash": "sha256:abc", "exit_status": 0}

    def test_issuer_signs_only_explicit_command_claims(self):
        record = issue_evidence_record(self.event(), b"key", identity="codex",
                                       issued_at=10, expires_at=20)
        verified = verify_dispatch(record, b"key", purpose="evidence.record", now=11)
        self.assertEqual(verified["evidence_id"], "e1")
        self.assertEqual(verified["source_revision"], 2)

    def test_prose_and_missing_fields_cannot_be_issued(self):
        with self.assertRaises(ValueError):
            issue_evidence_record({"type": "assistant", "text": "pytest passed"}, b"key",
                                  identity="codex", issued_at=10, expires_at=20)
        with self.assertRaises(ValueError):
            issue_evidence_record({**self.event(), "source_hash": ""}, b"key",
                                  identity="codex", issued_at=10, expires_at=20)

    def test_issued_claim_is_accepted_by_authoritative_store(self):
        with tempfile.TemporaryDirectory() as temp:
            store = RuntimeStore(temp, host_key=b"key", clock=lambda: 10)
            store.create_run("r")
            store.transition("r", "running")
            event = self.event()
            event["source_revision"] = store.get_run("r")["revision"]
            event["host_record"] = issue_evidence_record(event, b"key", identity="codex",
                                                          issued_at=10, expires_at=20)
            evidence = store.record_evidence(
                "r", "e1", kind="host.command", source_revision=event["source_revision"],
                command=event["command"], cwd=event["cwd"], source_hash=event["source_hash"],
                exit_status=event["exit_status"], host_record=event["host_record"])
            self.assertEqual(evidence["host_record_id"], "e1")

    def test_signed_command_cannot_be_relabelled_as_other_check_or_optional(self):
        with tempfile.TemporaryDirectory() as temp:
            store = RuntimeStore(temp, host_key=b"key", clock=lambda: 10)
            store.create_run("r")
            store.transition("r", "running")
            event = self.event()
            event["source_revision"] = store.get_run("r")["revision"]
            claim = issue_evidence_record(event, b"key", identity="codex",
                                          issued_at=10, expires_at=20)
            for command, required in (("ruff check", True), ("pytest", False)):
                with self.subTest(command=command, required=required):
                    with self.assertRaisesRegex(RuntimeError, "does not match"):
                        store.record_evidence(
                            "r", "e1", kind="host.command", source_revision=event["source_revision"],
                            command=command, cwd=".", source_hash="sha256:abc", exit_status=0,
                            required=required, host_record=claim)
            self.assertEqual(store.get_run("r")["revision"], event["source_revision"])

    def test_adapter_returns_ingestible_event(self):
        event = adapt_command_event(self.event(), b"key", identity="claude",
                                    issued_at=10, expires_at=20)
        self.assertEqual(command_receipt(event)["evidence_id"], "e1")
        self.assertEqual(event["host_record"]["purpose"], "evidence.record")
        self.assertEqual(event["host_record"]["identity"], "claude")


if __name__ == "__main__":
    unittest.main()
