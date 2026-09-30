import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from runtime.agentic_runtime.store import RuntimeStore


ROOT = pathlib.Path(__file__).resolve().parents[2]
HELPER = ROOT / "plugins/agentic-sdlc/scripts/external-action.py"


class ExternalActionTests(unittest.TestCase):
    def _running_run(self, root):
        store = RuntimeStore(root)
        run = store.create_run("run-1")
        run = store.acquire_lease("run-1", "coordinator")
        run = store.transition("run-1", "running", expected_revision=run["revision"],
                               lease_epoch=run["lease_epoch"], coordinator_id="coordinator")
        return run

    def _request(self, root, run, adapter, timeout_seconds=5):
        return {
            "api_version": "1.0.0", "operation": "external.execute", "root": str(root),
            "run_id": "run-1", "idempotency_key": "ticket-1", "action": "ticket.update",
            "request": {"state": "DONE"}, "coordinator_id": "coordinator",
            "lease_epoch": run["lease_epoch"], "expected_revision": run["revision"],
            "adapter": adapter, "timeout_seconds": timeout_seconds,
        }

    def test_intent_precedes_adapter_and_reconciles_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            run = self._running_run(root)
            proc = subprocess.run([sys.executable, str(HELPER)], input=json.dumps(self._request(
                root, run, [sys.executable, "-c", "print('DONE')"])),
                text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "succeeded")
            store = RuntimeStore(root)
            self.assertEqual(store.get_run("run-1")["state"], "running")
            with store._connect() as db:
                row = db.execute("select status from external_actions where idempotency_key='ticket-1'").fetchone()
                self.assertEqual(row[0], "succeeded")

    def test_timeout_is_uncertain_and_requires_reconciliation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            run = self._running_run(root)
            proc = subprocess.run([sys.executable, str(HELPER)], input=json.dumps(self._request(
                root, run, [sys.executable, "-c", "import time; time.sleep(2)"], timeout_seconds=.05)),
                text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["status"], "uncertain")
            self.assertEqual(RuntimeStore(root).get_run("run-1")["state"], "reconciliation_required")

    def test_legacy_hook_environment_mode_uses_same_fencing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            run = self._running_run(root)
            env = {
                "AGENTIC_EXTERNAL_ROOT": str(root), "AGENTIC_EXTERNAL_RUN_ID": "run-1",
                "AGENTIC_EXTERNAL_KEY": "ticket-env", "AGENTIC_EXTERNAL_ACTION": "ticket.sync",
                "AGENTIC_EXTERNAL_REQUEST": json.dumps({"state": "DEV"}),
                "AGENTIC_COORDINATOR_ID": "coordinator", "AGENTIC_LEASE_EPOCH": str(run["lease_epoch"]),
                "AGENTIC_EXPECTED_REVISION": str(run["revision"]),
                "AGENTIC_EXTERNAL_ADAPTER": "exit 0",
            }
            proc = subprocess.run([sys.executable, str(HELPER), "--env"], env={**__import__('os').environ, **env},
                                  text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["status"], "succeeded")
            with RuntimeStore(root)._connect() as db:
                self.assertEqual(db.execute("select status from external_actions where idempotency_key='ticket-env'").fetchone()[0], "succeeded")


if __name__ == "__main__":
    unittest.main()
