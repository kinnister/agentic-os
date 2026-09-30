import json
import unittest

from runtime.agentic_runtime.adapter import adapt_event, adapt_json_lines
from runtime.agentic_runtime.trace import command_receipt


class AdapterTests(unittest.TestCase):
    def event(self):
        return {"type": "agentic.command.completed", "evidence_id": "e1", "run_id": "r",
                "source_revision": 2, "command": "pytest", "cwd": ".",
                "source_hash": "sha256:abc", "exit_status": 0}

    def test_unrelated_stream_events_are_not_evidence(self):
        self.assertIsNone(adapt_event({"type": "assistant", "text": "passed"}, b"key",
                                      identity="claude", issued_at=1, expires_at=2))

    def test_jsonl_extracts_only_signed_explicit_receipts(self):
        lines = [json.dumps({"type": "system", "model": "fixture"}), json.dumps(self.event())]
        receipts = adapt_json_lines(lines, b"key", identity="codex", issued_at=1, expires_at=2)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(command_receipt(receipts[0])["host_record"]["identity"], "codex")

    def test_malformed_stream_fails_closed(self):
        with self.assertRaises(ValueError):
            adapt_json_lines(["not-json"], b"key", identity="codex", issued_at=1, expires_at=2)


if __name__ == "__main__":
    unittest.main()
