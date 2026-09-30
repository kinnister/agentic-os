import hashlib
import json
import sqlite3
import subprocess
import unittest

from runtime.agentic_runtime.store import RuntimeStore
from runtime.agentic_runtime.host import sign_dispatch


MESSAGE_KEY = b'message-test-key'


def message_record(run_id, assignment_id, assignment_revision, identity, record_id):
  return sign_dispatch({
    'record_id': record_id, 'purpose': 'message.send', 'run_id': run_id,
    'assignment_id': assignment_id, 'assignment_revision': assignment_revision,
    'identity': identity, 'issued_at': 0, 'expires_at': 9999999999,
  }, MESSAGE_KEY)


class RuntimeStoreTests(unittest.TestCase):
  def worktree(self, root, name, branch):
    path = root / name
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "checkout", "-q", "-b", branch], check=True)
    return str(path)

  def test_store_uses_authoritative_database_and_records_lifecycle(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    root = __import__('pathlib').Path(tmp_path.name)
    now = [100.0]
    store = RuntimeStore(root, clock=lambda: now[0])
    run = store.create_run("run-1", branch="feature/run-1", worktree=self.worktree(root, "run-1", "feature/run-1"), precondition={"ownership": "verified"})
    self.assertEqual(run["state"], "pending")
    self.assertTrue((root / ".agentic/state/runtime.sqlite3").exists())

    run = store.acquire_lease("run-1", "coordinator-a")
    assert run["lease_epoch"] == 1
    run = store.transition("run-1", "running", expected_revision=run["revision"], lease_epoch=1, coordinator_id="coordinator-a")
    now[0] = 110.0
    run = store.transition("run-1", "waiting_for_user", expected_revision=run["revision"], lease_epoch=1, coordinator_id="coordinator-a")
    now[0] = 1000.0
    run = store.transition("run-1", "running", expected_revision=run["revision"], lease_epoch=1, coordinator_id="coordinator-a")
    now[0] = 1010.0
    run = store.transition("run-1", "cancelled", expected_revision=run["revision"], lease_epoch=1, coordinator_id="coordinator-a")
    self.assertAlmostEqual(run["active_seconds"], 20.0)


  def test_revision_and_lease_fence_mutations(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    store = RuntimeStore(tmp_path.name, host_key=MESSAGE_KEY)
    run = store.create_run("r")
    run = store.acquire_lease("r", "a")
    with self.assertRaises(RuntimeError):
        store.transition("r", "running", expected_revision=0, lease_epoch=1, coordinator_id="a")
    with self.assertRaises(RuntimeError):
        store.transition("r", "running", expected_revision=run["revision"], lease_epoch=2, coordinator_id="a")


  def test_retry_reservation_is_persistent_and_not_refunded(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    store = RuntimeStore(tmp_path.name)
    store.create_run("r")
    first = store.reserve_dispatch("r", "dispatch-1", max_dispatches=1)
    self.assertTrue(first["reserved"])
    self.assertTrue(store.reserve_dispatch("r", "dispatch-1", max_dispatches=1)["reserved"])
    self.assertFalse(store.reserve_dispatch("r", "dispatch-2", max_dispatches=1)["reserved"])


  def test_external_intent_is_idempotent_and_reconciliation_is_durable(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    store = RuntimeStore(tmp_path.name)
    run = store.create_run("r")
    intent = store.record_external_intent("r", "charge-1", "charge", {"amount": 10})
    self.assertEqual(intent["status"], "pending")
    self.assertEqual(store.record_external_intent("r", "charge-1", "charge", {"amount": 10}), intent)
    result = store.reconcile_external("r", "charge-1", status="succeeded", result={"id": "ch_1"})
    self.assertEqual(result["status"], "succeeded")

  def test_idempotency_key_cannot_change_request(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    store = RuntimeStore(tmp_path.name)
    store.create_run("r")
    store.record_external_intent("r", "key", "charge", {"amount": 10})
    with self.assertRaises(ValueError):
        store.record_external_intent("r", "key", "charge", {"amount": 99})

  def test_uncertain_external_outcome_requires_reconciliation(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    now = [100.0]
    store = RuntimeStore(tmp_path.name, clock=lambda: now[0])
    store.create_run("r")
    run = store.acquire_lease("r", "coordinator")
    run = store.transition("r", "running", expected_revision=run["revision"], lease_epoch=run["lease_epoch"], coordinator_id="coordinator")
    store.record_external_intent("r", "key", "charge", {"amount": 10}, lease_epoch=run["lease_epoch"], expected_revision=run["revision"], coordinator_id="coordinator")
    now[0] = 150.0
    store.reconcile_external("r", "key", status="uncertain", lease_epoch=run["lease_epoch"], expected_revision=run["revision"] + 1, coordinator_id="coordinator")
    with store._connect() as db:
        self.assertEqual(db.execute("select state from runs where run_id='r'").fetchone()[0], "reconciliation_required")
        self.assertEqual(db.execute("select active_seconds from runs where run_id='r'").fetchone()[0], 50.0)


  def test_export_is_revision_labelled_and_import_legacy_records_hash(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    root = __import__('pathlib').Path(tmp_path.name)
    store = RuntimeStore(root)
    run = store.create_run("r", branch="feature/r", worktree=self.worktree(root, "r", "feature/r"), precondition={"ownership": "verified"})
    exported = store.export_run("r", fault=lambda stage: None)
    self.assertTrue(exported.is_dir())
    self.assertIn(f"revision-{run['revision']}", exported.name)
    self.assertEqual(store.export_run("r"), exported)
    exported_payload = json.loads((exported / "run.json").read_text())
    self.assertEqual(set(("assignments", "peer_messages", "evidence", "dispatch_leases", "events")) - set(exported_payload), set())
    payload = b"legacy bytes"
    source = root / "legacy.json"
    source.write_bytes(payload)
    receipt = store.import_legacy("r", source)
    self.assertEqual(receipt["sha256"], hashlib.sha256(payload).hexdigest())
    with sqlite3.connect(root / ".agentic/state/runtime.sqlite3") as db:
        self.assertEqual(db.execute("select count(*) from migration_receipts").fetchone()[0], 1)

  def test_export_requires_ownership_precondition(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    store = RuntimeStore(tmp_path.name)
    store.create_run("r")
    with self.assertRaises(RuntimeError):
        store.export_run("r")

  def test_legacy_export_is_a_regenerable_view_and_preserves_user_files(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    root = __import__('pathlib').Path(tmp_path.name)
    store = RuntimeStore(root)
    run = store.create_run("r", branch="feature/r", worktree=self.worktree(root, "r", "feature/r"),
                           metadata={"task_input": "view me"}, precondition={"ownership": "verified"})
    store.transition("r", "running")
    destination = root / "legacy-view"
    destination.mkdir()
    (destination / "requirements.md").write_text("owned", encoding="utf-8")
    exported = store.export_legacy("r", destination)
    self.assertEqual(exported, destination)
    self.assertEqual(__import__('json').loads((destination / "meta.json").read_text())["status"], "running")
    self.assertIn('"to":"running"', (destination / "events.jsonl").read_text())
    self.assertEqual((destination / "requirements.md").read_text(), "owned")
    (destination / "meta.json").write_text('{"status":"completed"}', encoding="utf-8")
    store.export_legacy("r", destination)
    self.assertEqual(__import__('json').loads((destination / "meta.json").read_text())["status"], "running")

  def test_coordinator_event_is_durable_and_projected_to_legacy_view(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    root = __import__('pathlib').Path(tmp_path.name)
    store = RuntimeStore(root)
    run = store.create_run("r", branch="feature/r", worktree=self.worktree(root, "r", "feature/r"),
                           precondition={"ownership": "verified"})
    run = store.acquire_lease("r", "coord")
    run = store.transition("r", "running", expected_revision=run["revision"], lease_epoch=1, coordinator_id="coord")
    run = store.record_event("r", "qa-event-1", "qa.phase.completed", {"phase": 1, "status": "complete"},
                             expected_revision=run["revision"], lease_epoch=1, coordinator_id="coord")
    self.assertEqual(run["revision"], 3)
    destination = root / "legacy-view"
    store.export_legacy("r", destination)
    events = [__import__('json').loads(line) for line in (destination / "events.jsonl").read_text().splitlines()]
    self.assertEqual(events[-1]["event_id"], "qa-event-1")
    with self.assertRaises(ValueError):
      store.record_event("r", "qa-event-1", "qa.phase.completed", {"phase": 2},
                         expected_revision=run["revision"], lease_epoch=1, coordinator_id="coord")

  def test_ownership_requires_real_git_worktree_and_matching_branch(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    root = __import__('pathlib').Path(tmp_path.name)
    store = RuntimeStore(root)
    with self.assertRaises(ValueError):
      store.create_run("r", branch="feature/r", worktree=str(root / "missing"), precondition={"ownership": "verified"})

  def test_migration_receipt_rejects_changed_source(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    root = __import__('pathlib').Path(tmp_path.name)
    store = RuntimeStore(root)
    store.create_run("r")
    source = root / "legacy.json"
    source.write_bytes(b"first")
    store.import_legacy("r", source)
    source.write_bytes(b"changed")
    with self.assertRaises(ValueError):
      store.import_legacy("r", source)

  def test_coordinator_identity_is_required_once_leased(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    store = RuntimeStore(tmp_path.name)
    run = store.create_run("r")
    run = store.acquire_lease("r", "owner")
    with self.assertRaises(RuntimeError):
      store.transition("r", "running", expected_revision=run["revision"], lease_epoch=run["lease_epoch"])

  def test_assignments_are_owned_and_dependency_cycles_are_rejected(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    store = RuntimeStore(tmp_path.name)
    store.create_run("r")
    run = store.acquire_lease("r", "coord")
    a = store.create_assignment("r", "a", "worker-a", owned_paths=["src/"], context_refs=["plan"], acceptance=["tests"], coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"])
    run = store.get_run("r")
    with self.assertRaises(ValueError):
      store.create_assignment("r", "b", "worker-b", owned_paths=[], context_refs=[], acceptance=[], depends_on=["missing"], coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"])
    b = store.create_assignment("r", "b", "worker-b", owned_paths=[], context_refs=[], acceptance=[], depends_on=["a"], coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"])
    run = store.get_run("r")
    a2 = store.create_assignment("r", "a2", "worker-a", owned_paths=[], context_refs=[], acceptance=[], depends_on=["b"], coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"])
    self.assertEqual(a["worker_id"], "worker-a")
    self.assertEqual(b["depends_on"], ["a"])
    self.assertEqual(a2["depends_on"], ["b"])

  def test_peer_messages_are_typed_correlated_and_stale_rejected(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    store = RuntimeStore(tmp_path.name, host_key=MESSAGE_KEY)
    store.create_run("r")
    run = store.acquire_lease("r", "coord")
    assignment = store.create_assignment("r", "a", "worker-a", owned_paths=[], context_refs=[], acceptance=[], coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"])
    run = store.get_run("r")
    message = store.send_peer_message("r", message_id="m1", assignment_id="a", assignment_revision=0, correlation_id="q1", sender="worker-a", recipient="coord", message_type="question.request", deadline=run["updated_at"] + 300, payload={"question": "ready?"}, coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"], host_record=message_record("r", "a", 0, "worker-a", "m1"))
    self.assertEqual(message["message_id"], "m1")
    run = store.get_run("r")
    self.assertEqual(store.send_peer_message("r", message_id="m1", assignment_id="a", assignment_revision=0, correlation_id="q1", sender="worker-a", recipient="coord", message_type="question.request", deadline=message["deadline"], payload={"question": "ready?"}, coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"], host_record=message_record("r", "a", 0, "worker-a", "m1"))["message_id"], "m1")
    with self.assertRaises(RuntimeError):
      store.send_peer_message("r", message_id="m2", assignment_id="a", assignment_revision=1, correlation_id="q2", sender="worker-a", recipient="coord", message_type="question.request", deadline=message["deadline"], payload={}, coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"])

  def test_expired_question_escalates(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    now = [100.0]
    store = RuntimeStore(tmp_path.name, clock=lambda: now[0], host_key=MESSAGE_KEY)
    store.create_run("r")
    run = store.acquire_lease("r", "coord")
    store.create_assignment("r", "a", "worker-a", owned_paths=[], context_refs=[], acceptance=[], coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"])
    run = store.get_run("r")
    with self.assertRaises(RuntimeError):
      store.send_peer_message("r", message_id="expired", assignment_id="a", assignment_revision=0, correlation_id="q", sender="worker-a", recipient="coord", message_type="question.request", deadline=99, payload={}, coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"], host_record=message_record("r", "a", 0, "worker-a", "expired"))
    self.assertEqual(store.assignment("r", "a")["state"], "escalation_required")

  def test_recovery_scan_escalates_silent_workers(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    now = [100.0]
    store = RuntimeStore(tmp_path.name, clock=lambda: now[0], host_key=MESSAGE_KEY)
    store.create_run("r")
    run = store.acquire_lease("r", "coord")
    store.create_assignment("r", "a", "worker-a", owned_paths=[], context_refs=[], acceptance=[], coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"])
    run = store.get_run("r")
    store.send_peer_message("r", message_id="q", assignment_id="a", assignment_revision=0, correlation_id="q", sender="worker-a", recipient="coord", message_type="question.request", deadline=101, payload={}, coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"], host_record=message_record("r", "a", 0, "worker-a", "q"))
    now[0] = 102
    run = store.get_run("r")
    result = store.recover_timeouts("r", coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"])
    self.assertEqual(result["escalated_assignments"], ["a"])
    self.assertEqual(store.assignment("r", "a")["state"], "escalation_required")

  def test_recipient_can_receive_bounded_peer_messages(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    store = RuntimeStore(tmp_path.name, host_key=MESSAGE_KEY)
    store.create_run("r")
    run = store.acquire_lease("r", "coord")
    store.create_assignment("r", "a", "worker-a", owned_paths=[], context_refs=[], acceptance=[], coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"])
    run = store.get_run("r")
    store.send_peer_message("r", message_id="m1", assignment_id="a", assignment_revision=0, correlation_id="c", sender="worker-a", recipient="coord", message_type="task.progress", deadline=run["updated_at"] + 10, payload={"step": 1}, coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"], host_record=message_record("r", "a", 0, "worker-a", "m1"))
    with self.assertRaises(RuntimeError):
      store.receive_peer_messages("r", "coord", reader_id="other")
    received = store._inspect_peer_messages("r", "coord")
    self.assertEqual(received[0]["message_id"], "m1")
    self.assertEqual(received[0]["payload"], {"step": 1})
    run = store.get_run("r")
    store.send_peer_message("r", message_id="a", assignment_id="a", assignment_revision=0, correlation_id="c2", sender="worker-a", recipient="coord", message_type="task.progress", deadline=run["updated_at"] + 10, payload={"step": 2}, coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"], host_record=message_record("r", "a", 0, "worker-a", "a"))
    page = store._inspect_peer_messages("r", "coord", limit=1)
    self.assertEqual(store._inspect_peer_messages("r", "coord", after_message_id=page[0]["message_id"])[0]["message_id"], "a")

  def test_evidence_is_revision_bound_and_failed_required_checks_are_rejected(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    store = RuntimeStore(tmp_path.name, host_key=MESSAGE_KEY)
    store.create_run("r")
    run = store.acquire_lease("r", "coord")
    with self.assertRaises(RuntimeError):
      store.record_evidence("r", "bad", kind="test", source_revision=run["revision"], command="pytest", cwd=".", source_hash="h", exit_status=1, coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"])
    receipt = store.record_evidence("r", "ok", kind="test", source_revision=run["revision"], command="pytest", cwd=".", source_hash="h", exit_status=0, coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"])
    self.assertEqual(receipt["exit_status"], 0)
    with self.assertRaises(RuntimeError):
      store.record_evidence("r", "stale", kind="test", source_revision=run["revision"], command="pytest", cwd=".", source_hash="h", exit_status=0, coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=receipt["source_revision"])

  def test_peer_reply_can_use_the_responder_assignment(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    store = RuntimeStore(tmp_path.name, host_key=MESSAGE_KEY)
    store.create_run("r")
    run = store.acquire_lease("r", "coord")
    store.create_assignment("r", "a", "worker-a", owned_paths=[], context_refs=[], acceptance=[], coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"])
    run = store.get_run("r")
    store.create_assignment("r", "b", "worker-b", owned_paths=[], context_refs=[], acceptance=[], coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"])
    run = store.get_run("r")
    request = store.send_peer_message("r", message_id="q", assignment_id="a", assignment_revision=0, correlation_id="corr", sender="worker-a", recipient="worker-b", message_type="question.request", deadline=run["updated_at"] + 300, payload={}, coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"], host_record=message_record("r", "a", 0, "worker-a", "q"))
    run = store.get_run("r")
    reply = store.send_peer_message("r", message_id="r", assignment_id="b", assignment_revision=0, correlation_id="corr", sender="worker-b", recipient="worker-a", message_type="question.response", deadline=request["deadline"], payload={"answer": "yes"}, coordinator_id="coord", lease_epoch=run["lease_epoch"], expected_revision=run["revision"], host_record=message_record("r", "b", 0, "worker-b", "r"))
    self.assertEqual(reply["message_id"], "r")

  def test_commit_fault_does_not_leave_partial_run(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    active = [False]
    def fail(stage):
      if active[0] and stage == "before_commit":
        raise OSError("injected commit fault")
    store = RuntimeStore(tmp_path.name, fault=fail)
    active[0] = True
    with self.assertRaises(OSError):
      store.create_run("r")
    with self.assertRaises(KeyError):
      store.get_run("r")

  def test_export_fault_leaves_authoritative_state_and_no_partial_view(self):
    tmp_path = __import__('tempfile').TemporaryDirectory()
    self.addCleanup(tmp_path.cleanup)
    root = __import__('pathlib').Path(tmp_path.name)
    store = RuntimeStore(root)
    run = store.create_run("r", branch="feature/r", worktree=self.worktree(root, "r-fault", "feature/r"), precondition={"ownership": "verified"})
    def fail(stage):
      if stage == "after_write":
        raise OSError("injected export fault")
    with self.assertRaises(OSError):
      store.export_run("r", fault=fail)
    self.assertEqual(store.get_run("r")["revision"], run["revision"])
    self.assertFalse(any((root / ".agentic/runs/r").iterdir()))
