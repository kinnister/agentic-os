import unittest

from runtime.agentic_runtime.trace import command_claims, command_receipt


class TraceTests(unittest.TestCase):
    def event(self):
        return {
            "type": "agentic.command.completed", "evidence_id": "e1", "run_id": "r",
            "source_revision": 4, "command": "pytest", "cwd": ".",
            "source_hash": "sha256:abc", "exit_status": 0,
            "host_record": {"record_id": "evidence-1"},
        }

    def test_only_explicit_command_events_are_accepted(self):
        self.assertEqual(command_receipt(self.event())["evidence_id"], "e1")
        with self.assertRaises(ValueError):
            command_receipt({"type": "assistant", "text": "pytest passed"})

    def test_malformed_receipts_fail_closed(self):
        for field in ("host_record", "source_hash", "exit_status", "source_revision"):
            event = self.event()
            event.pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                command_receipt(event)

    def test_claims_can_be_validated_before_host_signature_is_attached(self):
        event = self.event()
        event.pop("host_record")
        self.assertEqual(command_claims(event)["source_revision"], 4)


if __name__ == "__main__":
    unittest.main()
