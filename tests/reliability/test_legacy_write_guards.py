import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from runtime.agentic_runtime.store import RuntimeStore


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins/agentic-sdlc/skills/qa-e2e-generator/scripts/qa-append-event.sh"
ASSEMBLE = ROOT / "plugins/agentic-sdlc/skills/qa-e2e-generator/scripts/qa-assemble-meta.sh"


class LegacyWriteGuardTests(unittest.TestCase):
    def run_script(self, run_dir):
        return subprocess.run([str(SCRIPT), str(run_dir), "1", "preflight", "complete"],
                              text=True, capture_output=True, env=os.environ.copy())

    def test_unmanaged_legacy_fixture_remains_compatible(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_script(Path(temp) / "e2e")
            self.assertEqual(result.returncode, 0, result.stderr)
            event = json.loads((Path(temp) / "e2e/events.jsonl").read_text())
            self.assertEqual(event["status"], "complete")

    def test_managed_runtime_fails_closed_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "docs" / "run" / "e2e"
            run_dir.mkdir(parents=True)
            (root / ".agentic/state").mkdir(parents=True)
            (root / ".agentic/state/runtime.sqlite3").write_bytes(b"marker")
            result = self.run_script(run_dir)
            self.assertEqual(result.returncode, 2)
            self.assertIn("managed SQLite run", result.stderr)
            self.assertFalse((run_dir / "events.jsonl").exists())

    def test_managed_runtime_records_event_with_fenced_context(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "docs" / "run" / "e2e"
            run_dir.mkdir(parents=True)
            worktree = root / "worktree"
            subprocess.run(["git", "init", "-q", str(worktree)], check=True)
            subprocess.run(["git", "-C", str(worktree), "checkout", "-q", "-b", "feature/qa"], check=True)
            store = RuntimeStore(root)
            store.create_run("run-qa", branch="feature/qa", worktree=str(worktree),
                             precondition={"ownership": "verified"})
            run = store.acquire_lease("run-qa", "coord")
            run = store.transition("run-qa", "running", expected_revision=run["revision"],
                                   lease_epoch=run["lease_epoch"], coordinator_id="coord")
            env = os.environ.copy()
            env.update({"AGENTIC_RUNTIME_RUN_ID": "run-qa", "AGENTIC_COORDINATOR_ID": "coord",
                        "AGENTIC_LEASE_EPOCH": str(run["lease_epoch"]),
                        "AGENTIC_EXPECTED_REVISION": str(run["revision"])})
            result = subprocess.run([str(SCRIPT), str(run_dir), "1", "preflight", "complete"],
                                    text=True, capture_output=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            with store._connect() as db:
                event = db.execute("SELECT event_type,payload_json FROM runtime_events").fetchone()
            self.assertEqual(event["event_type"], "qa.phase")
            self.assertIn('"status":"complete"', event["payload_json"])
            self.assertFalse((run_dir / "events.jsonl").exists())

    def test_meta_assembler_has_the_same_managed_run_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "docs" / "run" / "e2e"
            run_dir.mkdir(parents=True)
            (root / ".agentic/state").mkdir(parents=True)
            (root / ".agentic/state/runtime.sqlite3").write_bytes(b"marker")
            result = subprocess.run([str(ASSEMBLE), str(run_dir)], text=True,
                                    capture_output=True, env=os.environ.copy())
            self.assertEqual(result.returncode, 2)
            self.assertIn("managed SQLite run", result.stderr)
            self.assertFalse((run_dir / "meta.json").exists())


if __name__ == "__main__":
    unittest.main()
