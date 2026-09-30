"""Durable runtime lifecycle store backed by the authoritative SQLite database."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from .contracts import load_registry, validate_identifier, validate_transition
from .host import verify_dispatch


SCHEMA_VERSION = "1"


def validate_run_ownership(branch: str | None, worktree: str | None,
                           precondition: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Check branch/worktree ownership without creating runtime artifacts."""
    if (branch is None) != (worktree is None):
        raise ValueError("branch and worktree must be supplied together")
    condition = dict(precondition or {})
    if branch is not None:
        if condition.get("ownership") != "verified":
            raise ValueError("branch/worktree ownership must be verified before run creation")
        worktree_path = Path(worktree)
        if not worktree_path.is_dir():
            raise ValueError("worktree must be an existing directory")
        try:
            inside = subprocess.run(
                ["git", "-C", str(worktree_path), "rev-parse", "--is-inside-work-tree"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            current_branch = subprocess.run(
                ["git", "-C", str(worktree_path), "branch", "--show-current"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            actual_root = subprocess.run(
                ["git", "-C", str(worktree_path), "rev-parse", "--show-toplevel"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ValueError("worktree ownership could not be verified") from exc
        if Path(actual_root).resolve() != worktree_path.resolve():
            raise ValueError("worktree root does not match requested worktree")
        if inside != "true" or current_branch != branch:
            raise ValueError("worktree branch does not match requested branch")
        condition.update({"branch": branch, "worktree": worktree, "ownership": "verified"})
    return condition


class RuntimeStore:
    """Small transactional API for runtime state.

    Every mutating operation commits one SQLite transaction.  ``expected_revision``
    and ``lease_epoch`` are checked in the same transaction as the write, so a
    stale coordinator cannot append a lifecycle event after ownership changes.
    """

    def __init__(self, root: str | os.PathLike[str], clock: Callable[[], float] | None = None,
                 fault: Callable[[str], None] | None = None, host_key: bytes | str | None = None):
        self.root = Path(root)
        self.db_path = self.root / ".agentic" / "state" / "runtime.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or time.time
        self.fault = fault
        self.host_key = host_key
        self._initialize()

    def _commit(self, db):
        if self.fault:
            self.fault("before_commit")
        db.commit()
        if self.fault:
            self.fault("after_commit")

    @contextmanager
    def _connect(self, *, validate: bool = True):
        db = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if validate:
                self._validate_versions(db)
            yield db
        finally:
            db.close()

    def _validate_versions(self, db):
        """Reject unknown formats before DDL or mutations, including on reopened handles."""
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not tables:
            return
        if "metadata" not in tables:
            raise RuntimeError("runtime schema version metadata missing")
        metadata = dict(db.execute("SELECT key,value FROM metadata"))
        expected = {"schema_version": SCHEMA_VERSION,
                    "registry_contract_version": load_registry()["contract_version"]}
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise RuntimeError("unsupported runtime schema or registry contract version")

    def _initialize(self):
        # Initialization must be able to repair a process that died between
        # SQLite DDL statements. All normal/reopened handles validate first.
        with self._connect(validate=False) as db:
            db.execute("BEGIN IMMEDIATE")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "metadata" in tables:
                existing_metadata = dict(db.execute("SELECT key,value FROM metadata"))
                # An empty metadata table is a valid interrupted-initialization
                # checkpoint. Once a version is recorded, reject mismatches
                # before changing the schema.
                expected_metadata = {"schema_version": SCHEMA_VERSION,
                                     "registry_contract_version": load_registry()["contract_version"]}
                if set(existing_metadata) >= set(expected_metadata):
                    self._validate_versions(db)
                elif any(existing_metadata.get(key) != value for key, value in existing_metadata.items() if key in expected_metadata):
                    raise RuntimeError("unsupported runtime schema or registry contract version")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, state TEXT NOT NULL, revision INTEGER NOT NULL,
                    lease_epoch INTEGER NOT NULL DEFAULT 0, coordinator_id TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    active_seconds REAL NOT NULL DEFAULT 0, active_since REAL,
                    dispatch_count INTEGER NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL,
                    precondition_json TEXT
                );
                CREATE TABLE IF NOT EXISTS transitions (
                    run_id TEXT NOT NULL, sequence INTEGER NOT NULL, source TEXT,
                    target TEXT NOT NULL, revision INTEGER NOT NULL, at REAL NOT NULL,
                    reason TEXT, PRIMARY KEY(run_id, sequence), FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS runtime_events (
                    event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL, revision INTEGER NOT NULL, at REAL NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    run_id TEXT NOT NULL, sequence INTEGER NOT NULL, decision_key TEXT NOT NULL,
                    value_json TEXT NOT NULL, revision INTEGER NOT NULL, at REAL NOT NULL,
                    PRIMARY KEY(run_id, sequence), FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS counters (
                    run_id TEXT NOT NULL, name TEXT NOT NULL, value INTEGER NOT NULL,
                    PRIMARY KEY(run_id, name), FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS dispatch_reservations (
                    run_id TEXT NOT NULL, reservation_id TEXT NOT NULL, created_at REAL NOT NULL,
                    PRIMARY KEY(run_id, reservation_id), FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    run_id TEXT NOT NULL, sequence INTEGER NOT NULL, sender TEXT,
                    body TEXT NOT NULL, at REAL NOT NULL, revision INTEGER NOT NULL,
                    PRIMARY KEY(run_id, sequence), FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS external_actions (
                    run_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, action TEXT NOT NULL,
                    request_json TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY(run_id, idempotency_key), FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS migration_receipts (
                    run_id TEXT NOT NULL, source TEXT NOT NULL, sha256 TEXT NOT NULL,
                    imported_at REAL NOT NULL, receipt_json TEXT NOT NULL,
                    PRIMARY KEY(run_id, source), FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS assignments (
                    run_id TEXT NOT NULL, assignment_id TEXT NOT NULL, worker_id TEXT NOT NULL,
                    state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                    owned_paths_json TEXT NOT NULL, context_json TEXT NOT NULL,
                    acceptance_json TEXT NOT NULL, limits_json TEXT NOT NULL,
                    depends_on_json TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY(run_id, assignment_id), FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS peer_messages (
                    message_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, assignment_id TEXT NOT NULL,
                    assignment_revision INTEGER NOT NULL, correlation_id TEXT NOT NULL,
                    sender TEXT NOT NULL, recipient TEXT NOT NULL, message_type TEXT NOT NULL,
                    deadline REAL NOT NULL, payload_json TEXT NOT NULL, created_at REAL NOT NULL,
                    FOREIGN KEY(run_id, assignment_id) REFERENCES assignments(run_id, assignment_id)
                );
                CREATE TABLE IF NOT EXISTS evidence (
                    run_id TEXT NOT NULL, evidence_id TEXT NOT NULL, kind TEXT NOT NULL,
                    source_revision INTEGER NOT NULL, command TEXT NOT NULL, cwd TEXT NOT NULL,
                    source_hash TEXT NOT NULL, exit_status INTEGER NOT NULL, required INTEGER NOT NULL,
                    created_at REAL NOT NULL, host_record_id TEXT, PRIMARY KEY(run_id, evidence_id), FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS host_dispatches (
                    record_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, purpose TEXT NOT NULL,
                    identity TEXT NOT NULL, assignment_id TEXT, assignment_revision INTEGER,
                    claims_json TEXT NOT NULL, accepted_at REAL NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS dispatch_leases (
                    run_id TEXT NOT NULL, reservation_id TEXT NOT NULL, worker_id TEXT NOT NULL,
                    started_at REAL NOT NULL, deadline REAL NOT NULL, finished_at REAL,
                    outcome TEXT, PRIMARY KEY(run_id, reservation_id),
                    FOREIGN KEY(run_id, reservation_id) REFERENCES dispatch_reservations(run_id, reservation_id)
                );
                """
            )
            evidence_columns = {row[1] for row in db.execute("PRAGMA table_info(evidence)")}
            if "host_record_id" not in evidence_columns:
                db.execute("ALTER TABLE evidence ADD COLUMN host_record_id TEXT")
            db.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('schema_version',?)", (SCHEMA_VERSION,))
            db.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('registry_contract_version',?)", (load_registry()["contract_version"],))
            self._validate_versions(db)
            self._commit(db)

    def _host_claims(self, record: Mapping[str, Any], *, purpose: str, run_id: str,
                     assignment_id: str | None = None) -> dict[str, Any]:
        if self.host_key is None:
            raise RuntimeError("host-issued dispatch verification is not configured")
        claims = verify_dispatch(record, self.host_key, purpose=purpose, now=self.clock())
        if claims.get("run_id") != run_id:
            raise RuntimeError("host dispatch run mismatch")
        if assignment_id is not None and claims.get("assignment_id") != assignment_id:
            raise RuntimeError("host dispatch assignment mismatch")
        return claims

    def _accept_host_claim(self, db, claims: Mapping[str, Any]) -> None:
        record_id = claims["record_id"]
        existing = db.execute("SELECT claims_json FROM host_dispatches WHERE record_id=?", (record_id,)).fetchone()
        encoded = self._json(dict(claims))
        if existing:
            if existing[0] != encoded:
                raise RuntimeError("host dispatch record was reused with different claims")
            return
        db.execute(
            "INSERT INTO host_dispatches(record_id,run_id,purpose,identity,assignment_id,assignment_revision,claims_json,accepted_at) VALUES(?,?,?,?,?,?,?,?)",
            (record_id, claims["run_id"], claims["purpose"], claims["identity"], claims.get("assignment_id"), claims.get("assignment_revision"), encoded, self.clock()),
        )

    def _evidence_claim_is_bound(self, item: sqlite3.Row) -> bool:
        """Reject pre-binding receipts and damaged persisted host claims."""
        if item["claims_json"] is None or item["accepted_at"] is None or self.host_key is None:
            return False
        try:
            claims = verify_dispatch(json.loads(item["claims_json"]), self.host_key,
                                     purpose="evidence.record", now=item["accepted_at"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        expected = {"record_id": item["host_record_id"], "run_id": item["run_id"],
                    "evidence_id": item["evidence_id"], "kind": item["kind"],
                    "command": item["command"], "cwd": item["cwd"],
                    "source_revision": item["source_revision"],
                    "source_hash": item["source_hash"], "exit_status": item["exit_status"]}
        return (all(claims.get(field) == value for field, value in expected.items())
                and claims.get("required") is bool(item["required"])
                and item["accepted_at"] >= claims["issued_at"])

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def _run(self, db, run_id: str) -> dict[str, Any]:
        row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("unknown run: " + run_id)
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json"))
        raw = result.pop("precondition_json")
        result["precondition"] = json.loads(raw) if raw else None
        return result

    def _guard(self, db, run_id, expected_revision, lease_epoch, coordinator_id=None):
        row = db.execute("SELECT revision, lease_epoch, coordinator_id, state FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("unknown run: " + run_id)
        if expected_revision is not None and row["revision"] != expected_revision:
            raise RuntimeError("revision mismatch")
        if row["coordinator_id"] is not None:
            if lease_epoch != row["lease_epoch"]:
                raise RuntimeError("lease epoch mismatch")
            if not coordinator_id or coordinator_id != row["coordinator_id"]:
                raise RuntimeError("coordinator identity mismatch")
        if row["state"] in {"completed", "failed", "cancelled"}:
            raise RuntimeError("run is terminal")
        return row

    def create_run(self, run_id: str | None = None, *, branch: str | None = None,
                   worktree: str | None = None, metadata: Mapping[str, Any] | None = None,
                   precondition: Mapping[str, Any] | None = None) -> dict[str, Any]:
        run_id = run_id or uuid4().hex
        validate_identifier(run_id)
        condition = validate_run_ownership(branch, worktree, precondition)
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            try:
                db.execute("INSERT INTO runs(run_id,state,revision,created_at,updated_at,metadata_json,precondition_json) VALUES(?,?,?,?,?,?,?)",
                           (run_id, "pending", 0, now, now, self._json(dict(metadata or {})), self._json(condition) if condition else None))
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise ValueError("run already exists: " + run_id) from exc
            db.execute("INSERT INTO transitions VALUES(?,?,?,?,?,?,?)", (run_id, 1, None, "pending", 0, now, "created"))
            self._commit(db)
            return self._run(db, run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Read authoritative state without trusting an export."""
        with self._connect() as db:
            return self._run(db, run_id)

    def acquire_lease(self, run_id: str, coordinator_id: str, *, expected_revision: int | None = None) -> dict[str, Any]:
        try:
            validate_identifier(coordinator_id)
        except ValueError as exc:
            raise ValueError("invalid coordinator_id") from exc
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            row = db.execute("SELECT revision, lease_epoch, state FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError("unknown run: " + run_id)
            if row["state"] in {"completed", "failed", "cancelled"}:
                db.rollback()
                raise RuntimeError("cannot acquire a lease for a terminal run")
            if expected_revision is not None and row["revision"] != expected_revision:
                raise RuntimeError("revision mismatch")
            epoch = row["lease_epoch"] + 1
            revision = row["revision"] + 1
            db.execute("UPDATE runs SET coordinator_id=?,lease_epoch=?,revision=?,updated_at=? WHERE run_id=?", (coordinator_id, epoch, revision, now, run_id))
            self._commit(db)
            return self._run(db, run_id)

    def transition(self, run_id: str, target: str, *, expected_revision: int | None = None,
                   lease_epoch: int | None = None, coordinator_id: str | None = None,
                   reason: str | None = None) -> dict[str, Any]:
        if target == "completed":
            raise RuntimeError("completion unavailable: trusted completion gate and host certification are not implemented")
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            row = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            current = db.execute("SELECT state,active_seconds,active_since FROM runs WHERE run_id=?", (run_id,)).fetchone()
            validate_transition(current["state"], target)
            active = current["active_seconds"]
            if current["active_since"] is not None and target != "running":
                active += max(0, now - current["active_since"])
            since = now if target == "running" else None
            revision = row["revision"] + 1
            seq = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM transitions WHERE run_id=?", (run_id,)).fetchone()[0]
            db.execute("UPDATE runs SET state=?,revision=?,updated_at=?,active_seconds=?,active_since=? WHERE run_id=?", (target, revision, now, active, since, run_id))
            db.execute("INSERT INTO transitions VALUES(?,?,?,?,?,?,?)", (run_id, seq, current["state"], target, revision, now, reason))
            if target == "cancelled":
                db.execute("UPDATE assignments SET state='cancelled',revision=revision+1,updated_at=? WHERE run_id=? AND state NOT IN ('completed','failed','cancelled')", (now, run_id))
                db.execute("UPDATE dispatch_leases SET finished_at=?,outcome='cancelled' WHERE run_id=? AND finished_at IS NULL", (now, run_id))
            self._commit(db)
            return self._run(db, run_id)

    def complete_run(self, run_id: str, *, host_record: Mapping[str, Any],
                     expected_revision: int | None = None, lease_epoch: int | None = None,
                     coordinator_id: str | None = None) -> dict[str, Any]:
        """Complete only with a host-signed gate and successful required evidence."""
        claims = self._host_claims(host_record, purpose="run.complete", run_id=run_id)
        if claims.get("gate_decision") != "approved":
            raise RuntimeError("trusted completion gate approval is required")
        evidence_ids = claims.get("evidence_ids")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            raise RuntimeError("trusted completion evidence is required")
        artifact_hashes = claims.get("artifact_hashes")
        if not isinstance(artifact_hashes, Mapping):
            raise RuntimeError("trusted completion artifact hashes are required")
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            current = db.execute("SELECT state,active_seconds,active_since FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if current["state"] != "running":
                raise RuntimeError("run must be running before completion")
            self._accept_host_claim(db, claims)
            # Check modern persisted claims before filtering by the row's
            # required projection. A damaged projection must not hide a
            # signed required failure from the later stream scan. Legacy
            # claims without this field can be superseded by fresh receipts.
            for item in db.execute("SELECT e.*,h.claims_json,h.accepted_at FROM evidence e LEFT JOIN host_dispatches h ON h.record_id=e.host_record_id WHERE e.run_id=? AND e.host_record_id IS NOT NULL", (run_id,)):
                try:
                    persisted = json.loads(item["claims_json"])
                except (TypeError, ValueError):
                    raise RuntimeError("required completion evidence is missing or failed") from None
                if not isinstance(persisted, dict) or (
                        "required" in persisted and not self._evidence_claim_is_bound(item)):
                    raise RuntimeError("required completion evidence is missing or failed")
            placeholders = ",".join("?" for _ in evidence_ids)
            evidence = db.execute(f"SELECT e.*,h.claims_json,h.accepted_at FROM evidence e LEFT JOIN host_dispatches h ON h.record_id=e.host_record_id WHERE e.run_id=? AND e.evidence_id IN ({placeholders})", (run_id, *evidence_ids)).fetchall()
            if (len(evidence) != len(set(evidence_ids)) or
                    any(item["required"] and item["exit_status"] != 0 for item in evidence) or
                    not any(item["required"] and item["exit_status"] == 0 for item in evidence) or
                    any(not self._evidence_claim_is_bound(item) for item in evidence) or
                    any(artifact_hashes.get(item["evidence_id"]) != item["source_hash"] for item in evidence)):
                raise RuntimeError("required completion evidence is missing or failed")
            # A gate may not cherry-pick a passing check while a different
            # required check has failed. The latest signed result for each
            # command stream must pass and be named by the gate.
            latest_required = {}
            for item in db.execute("SELECT e.rowid,e.*,h.claims_json,h.accepted_at FROM evidence e LEFT JOIN host_dispatches h ON h.record_id=e.host_record_id WHERE e.run_id=? AND e.required=1 AND e.host_record_id IS NOT NULL ORDER BY e.rowid", (run_id,)):
                latest_required[(item["kind"], item["command"], item["cwd"])] = item
            selected = set(evidence_ids)
            if any(item["exit_status"] != 0 or item["evidence_id"] not in selected
                   or not self._evidence_claim_is_bound(item)
                   for item in latest_required.values()):
                raise RuntimeError("required completion evidence is missing or failed")
            unfinished = db.execute("SELECT 1 FROM assignments WHERE run_id=? AND state NOT IN ('completed','failed','cancelled')", (run_id,)).fetchone()
            if unfinished:
                raise RuntimeError("unfinished assignments block completion")
            active = current["active_seconds"]
            if current["active_since"] is not None:
                active += max(0, now - current["active_since"])
            revision = row["revision"] + 1
            seq = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM transitions WHERE run_id=?", (run_id,)).fetchone()[0]
            db.execute("UPDATE runs SET state='completed',revision=?,updated_at=?,active_seconds=?,active_since=NULL WHERE run_id=?", (revision, now, active, run_id))
            db.execute("INSERT INTO transitions VALUES(?,?,?,?,?,?,?)", (run_id, seq, "running", "completed", revision, now, "trusted host gate approved"))
            self._commit(db)
            return self._run(db, run_id)

    def reserve_dispatch(self, run_id: str, reservation_id: str, *, max_dispatches: int | None = None,
                         expected_revision: int | None = None, lease_epoch: int | None = None,
                         coordinator_id: str | None = None) -> dict[str, Any]:
        default_limit = int(load_registry()["policy_defaults"]["max_dispatches"])
        if max_dispatches is None:
            max_dispatches = default_limit
        if type(max_dispatches) is not int or max_dispatches < 1 or max_dispatches > default_limit:
            raise ValueError("max_dispatches must be within the registry ceiling")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            row = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            saved = db.execute("SELECT value FROM counters WHERE run_id=? AND name='dispatch_limit'", (run_id,)).fetchone()
            effective_limit = min(max_dispatches, saved[0] if saved else default_limit)
            tightened = saved is None or effective_limit < saved[0]
            db.execute("INSERT INTO counters VALUES(?,'dispatch_limit',?) ON CONFLICT(run_id,name) DO UPDATE SET value=excluded.value", (run_id, effective_limit))
            max_dispatches = effective_limit
            if db.execute("SELECT 1 FROM dispatch_reservations WHERE run_id=? AND reservation_id=?", (run_id, reservation_id)).fetchone():
                count = db.execute("SELECT COALESCE(value,0) FROM counters WHERE run_id=? AND name='dispatches'", (run_id,)).fetchone()[0]
                if tightened:
                    db.execute("UPDATE runs SET revision=revision+1,updated_at=? WHERE run_id=?", (self.clock(), run_id))
                self._commit(db)
                return {"reserved": True, "reservation_id": reservation_id, "count": count}
            existing = db.execute("SELECT value FROM counters WHERE run_id=? AND name=?", (run_id, "dispatches")).fetchone()
            count = existing[0] if existing else 0
            if max_dispatches is not None and count >= max_dispatches:
                if tightened:
                    db.execute("UPDATE runs SET revision=revision+1,updated_at=? WHERE run_id=?", (self.clock(), run_id))
                self._commit(db)
                return {"reserved": False, "reservation_id": reservation_id, "count": count}
            db.execute("INSERT INTO counters(run_id,name,value) VALUES(?,?,?) ON CONFLICT(run_id,name) DO UPDATE SET value=value+1", (run_id, "dispatches", 1))
            db.execute("INSERT INTO dispatch_reservations VALUES(?,?,?)", (run_id, reservation_id, self.clock()))
            db.execute("UPDATE runs SET dispatch_count=dispatch_count+1,revision=?,updated_at=? WHERE run_id=?", (row["revision"] + 1, self.clock(), run_id))
            self._commit(db)
            return {"reserved": True, "reservation_id": reservation_id, "count": count + 1}

    def start_dispatch(self, run_id: str, reservation_id: str, worker_id: str, *,
                       timeout_seconds: int | None = None, expected_revision: int | None = None,
                       lease_epoch: int | None = None, coordinator_id: str | None = None) -> dict[str, Any]:
        """Start a reserved worker dispatch under persistent concurrency limits."""
        policy = load_registry()["policy_defaults"]
        timeout = int(policy["worker_minutes"] * 60 if timeout_seconds is None else timeout_seconds)
        ceiling = int(policy["worker_minutes"] * 60)
        if not worker_id or type(timeout) is not int or timeout < 1 or timeout > ceiling:
            raise ValueError("timeout_seconds must be within the worker policy ceiling")
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            run = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            if db.execute("SELECT 1 FROM dispatch_reservations WHERE run_id=? AND reservation_id=?", (run_id, reservation_id)).fetchone() is None:
                raise KeyError("unknown dispatch reservation")
            existing = db.execute("SELECT * FROM dispatch_leases WHERE run_id=? AND reservation_id=?", (run_id, reservation_id)).fetchone()
            if existing:
                db.rollback()
                return dict(existing)
            active = db.execute("SELECT COUNT(*) FROM dispatch_leases WHERE run_id=? AND finished_at IS NULL", (run_id,)).fetchone()[0]
            if active >= int(policy["max_concurrent_workers"]):
                raise RuntimeError("concurrent worker limit exhausted")
            current = db.execute("SELECT active_seconds,active_since FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if current["active_since"] is not None and current["active_seconds"] + max(0, now - current["active_since"]) >= int(policy["active_run_minutes"] * 60):
                active_seconds = current["active_seconds"] + max(0, now - current["active_since"])
                revision = run["revision"] + 1
                sequence = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM transitions WHERE run_id=?", (run_id,)).fetchone()[0]
                db.execute("UPDATE runs SET state='waiting_for_user',revision=?,updated_at=?,active_seconds=?,active_since=NULL WHERE run_id=?", (revision, now, active_seconds, run_id))
                db.execute("INSERT INTO transitions VALUES(?,?,?,?,?,?,?)", (run_id, sequence, "running", "waiting_for_user", revision, now, "active execution budget exhausted"))
                self._commit(db)
                raise RuntimeError("active execution budget exhausted; escalation required")
            result = (run_id, reservation_id, worker_id, now, now + timeout)
            db.execute("INSERT INTO dispatch_leases(run_id,reservation_id,worker_id,started_at,deadline) VALUES(?,?,?,?,?)", result)
            db.execute("UPDATE runs SET revision=?,updated_at=? WHERE run_id=?", (run["revision"] + 1, now, run_id))
            self._commit(db)
            row = db.execute("SELECT * FROM dispatch_leases WHERE run_id=? AND reservation_id=?", (run_id, reservation_id)).fetchone()
            return dict(row)

    def finish_dispatch(self, run_id: str, reservation_id: str, *, outcome: str,
                        expected_revision: int | None = None, lease_epoch: int | None = None,
                        coordinator_id: str | None = None) -> dict[str, Any]:
        if outcome not in {"succeeded", "failed", "cancelled", "timed_out"}:
            raise ValueError("invalid dispatch outcome")
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            run = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            row = db.execute("SELECT * FROM dispatch_leases WHERE run_id=? AND reservation_id=?", (run_id, reservation_id)).fetchone()
            if row is None: raise KeyError("unknown dispatch lease")
            if row["finished_at"] is not None:
                db.rollback(); return dict(row)
            db.execute("UPDATE dispatch_leases SET finished_at=?,outcome=? WHERE run_id=? AND reservation_id=?", (now, outcome, run_id, reservation_id))
            db.execute("UPDATE runs SET revision=?,updated_at=? WHERE run_id=?", (run["revision"] + 1, now, run_id))
            self._commit(db)
            return dict(db.execute("SELECT * FROM dispatch_leases WHERE run_id=? AND reservation_id=?", (run_id, reservation_id)).fetchone())

    def recover_dispatches(self, run_id: str, *, expected_revision: int | None = None,
                           lease_epoch: int | None = None, coordinator_id: str | None = None) -> list[dict[str, Any]]:
        """Close expired in-flight dispatches without refunding reservations."""
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            run = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            rows = db.execute("SELECT * FROM dispatch_leases WHERE run_id=? AND finished_at IS NULL AND deadline<=?", (run_id, now)).fetchall()
            if not rows:
                db.rollback(); return []
            db.execute("UPDATE dispatch_leases SET finished_at=?,outcome='timed_out' WHERE run_id=? AND finished_at IS NULL AND deadline<=?", (now, run_id, now))
            db.execute("UPDATE runs SET revision=?,updated_at=? WHERE run_id=?", (run["revision"] + 1, now, run_id))
            self._commit(db)
            return [dict(row) | {"finished_at": now, "outcome": "timed_out"} for row in rows]

    def record_decision(self, run_id: str, decision_key: str, value: Any, *, expected_revision: int | None = None, lease_epoch: int | None = None, coordinator_id: str | None = None) -> dict[str, Any]:
        if not isinstance(decision_key, str) or decision_key not in load_registry()["gates"]:
            raise ValueError("unknown gate identifier")
        if not isinstance(value, Mapping) or value.get("decision") not in {"approve", "request-changes", "abort"}:
            raise ValueError("gate decision must contain an allowed decision")
        if value.get("source") not in {"hitl", "deterministic", "fast-path", "subagent"}:
            raise ValueError("gate decision source is required")
        if value.get("decision") == "approve" and value.get("risk_flags") and value.get("source") != "hitl":
            raise RuntimeError("risk-bearing approval requires human escalation")
        if value["decision"] == "approve":
            hashes = value.get("artifact_hashes")
            if not isinstance(hashes, Mapping) or not hashes or not all(
                    isinstance(key, str) and isinstance(item, str) and item for key, item in hashes.items()):
                raise ValueError("approved gate decision requires artifact hashes")
        return self._append(run_id, "decisions", (decision_key, self._json(value)), expected_revision, lease_epoch, coordinator_id)

    def record_message(self, run_id: str, body: str, *, sender: str | None = None, expected_revision: int | None = None, lease_epoch: int | None = None, coordinator_id: str | None = None, max_messages: int | None = None, max_bytes: int | None = None) -> dict[str, Any]:
        if not isinstance(body, str):
            raise ValueError("body must be a string")
        policy = load_registry()["policy_defaults"]
        max_messages = int(policy["max_messages_per_worker"] if max_messages is None else max_messages)
        max_bytes = int(policy["max_message_bytes"] if max_bytes is None else max_bytes)
        if len(body.encode("utf-8")) > max_bytes:
            raise ValueError("message exceeds byte limit")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            row = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            count = db.execute("SELECT COUNT(*) FROM messages WHERE run_id=?", (run_id,)).fetchone()[0]
            if count >= max_messages:
                raise RuntimeError("message budget exhausted")
            seq = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM messages WHERE run_id=?", (run_id,)).fetchone()[0]
            now = self.clock(); revision = row["revision"] + 1
            db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)", (run_id, seq, sender, body, now, revision))
            db.execute("UPDATE runs SET revision=?,updated_at=? WHERE run_id=?", (revision, now, run_id))
            self._commit(db)
            return self._run(db, run_id)

    def _append(self, run_id, kind, values, expected_revision, lease_epoch, coordinator_id=None):
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            row = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            seq = db.execute(f"SELECT COALESCE(MAX(sequence),0)+1 FROM {kind} WHERE run_id=?", (run_id,)).fetchone()[0]
            revision = row["revision"] + 1
            if kind == "decisions":
                db.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?)", (run_id, seq, values[0], values[1], revision, now))
            else:
                db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)", (run_id, seq, values[0], values[1], now, revision))
            db.execute("UPDATE runs SET revision=?,updated_at=? WHERE run_id=?", (revision, now, run_id))
            self._commit(db)
            return self._run(db, run_id)

    def record_external_intent(self, run_id: str, idempotency_key: str, action: str, request: Any, *, expected_revision: int | None = None, lease_epoch: int | None = None, coordinator_id: str | None = None) -> dict[str, Any]:
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            row = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            found = db.execute("SELECT * FROM external_actions WHERE run_id=? AND idempotency_key=?", (run_id, idempotency_key)).fetchone()
            if found:
                if found["action"] != action or found["request_json"] != self._json(request):
                    db.rollback()
                    raise ValueError("idempotency key reused with different action or request")
                db.rollback()
                return self._external(found)
            db.execute("INSERT INTO external_actions VALUES(?,?,?,?,?,?,?,?)", (run_id, idempotency_key, action, self._json(request), "pending", None, now, now))
            db.execute("UPDATE runs SET revision=?,updated_at=? WHERE run_id=?", (row["revision"] + 1, now, run_id))
            self._commit(db)
            return self._external(db.execute("SELECT * FROM external_actions WHERE run_id=? AND idempotency_key=?", (run_id, idempotency_key)).fetchone())

    def _external(self, row):
        result = dict(row)
        result["request"] = json.loads(result.pop("request_json"))
        raw_result = result.pop("result_json")
        result["result"] = json.loads(raw_result) if raw_result else None
        return result

    def reconcile_external(self, run_id: str, idempotency_key: str, *, status: str, result: Any = None, expected_revision: int | None = None, lease_epoch: int | None = None, coordinator_id: str | None = None) -> dict[str, Any]:
        if status not in {"pending", "succeeded", "failed", "uncertain"}:
            raise ValueError("invalid external status")
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            row = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            if db.execute("SELECT 1 FROM external_actions WHERE run_id=? AND idempotency_key=?", (run_id, idempotency_key)).fetchone() is None:
                raise KeyError("unknown external intent")
            db.execute("UPDATE external_actions SET status=?,result_json=?,updated_at=? WHERE run_id=? AND idempotency_key=?", (status, self._json(result) if result is not None else None, now, run_id, idempotency_key))
            revision = row["revision"] + 1
            current = db.execute("SELECT state,active_seconds,active_since FROM runs WHERE run_id=?", (run_id,)).fetchone()
            current_state = current["state"]
            if status == "uncertain" and current_state in {"running", "interrupted"}:
                seq = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM transitions WHERE run_id=?", (run_id,)).fetchone()[0]
                db.execute("INSERT INTO transitions VALUES(?,?,?,?,?,?,?)", (run_id, seq, current_state, "reconciliation_required", revision, now, "external outcome uncertain"))
                active = current["active_seconds"]
                if current["active_since"] is not None:
                    active += max(0, now - current["active_since"])
                db.execute("UPDATE runs SET state='reconciliation_required',revision=?,updated_at=?,active_seconds=?,active_since=NULL WHERE run_id=?", (revision, now, active, run_id))
            else:
                db.execute("UPDATE runs SET revision=?,updated_at=? WHERE run_id=?", (revision, now, run_id))
            self._commit(db)
            return self._external(db.execute("SELECT * FROM external_actions WHERE run_id=? AND idempotency_key=?", (run_id, idempotency_key)).fetchone())

    def export_run(self, run_id: str, *, fault: Callable[[str], None] | None = None) -> Path:
        with self._connect() as db:
            run = self._run(db, run_id)
            precondition = run.get("precondition") or {}
            if precondition.get("ownership") != "verified" or not precondition.get("branch") or not precondition.get("worktree"):
                raise RuntimeError("branch/worktree ownership precondition is required before export")
            transitions = [dict(r) for r in db.execute("SELECT * FROM transitions WHERE run_id=? ORDER BY sequence", (run_id,))]
            events = [dict(r) for r in db.execute("SELECT * FROM runtime_events WHERE run_id=? ORDER BY revision,event_id", (run_id,))]
            decisions = [dict(r) for r in db.execute("SELECT * FROM decisions WHERE run_id=? ORDER BY sequence", (run_id,))]
            messages = [dict(r) for r in db.execute("SELECT * FROM messages WHERE run_id=? ORDER BY sequence", (run_id,))]
            assignments = []
            for row in db.execute("SELECT * FROM assignments WHERE run_id=? ORDER BY assignment_id", (run_id,)):
                item = dict(row)
                for field in ("owned_paths_json", "context_json", "acceptance_json", "limits_json", "depends_on_json"):
                    item[field[:-5]] = json.loads(item.pop(field))
                assignments.append(item)
            peer_messages = []
            for row in db.execute("SELECT * FROM peer_messages WHERE run_id=? ORDER BY created_at,message_id", (run_id,)):
                item = dict(row); item["payload"] = json.loads(item.pop("payload_json")); peer_messages.append(item)
            evidence = [dict(r) for r in db.execute("SELECT * FROM evidence WHERE run_id=? ORDER BY created_at,evidence_id", (run_id,))]
            dispatch_leases = [dict(r) for r in db.execute("SELECT * FROM dispatch_leases WHERE run_id=? ORDER BY started_at,reservation_id", (run_id,))]
            external = [self._external(r) for r in db.execute("SELECT * FROM external_actions WHERE run_id=? ORDER BY created_at", (run_id,))]
        destination = self.root / ".agentic" / "runs" / run_id / f"revision-{run['revision']}"
        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if (destination / "run.json").is_file():
                return destination
            raise RuntimeError("incomplete export requires reconciliation: " + destination.as_posix())
        temp = Path(tempfile.mkdtemp(prefix=".export-", dir=parent))
        try:
            if fault: fault("before_write")
            (temp / "run.json").write_text(self._json({"run": run, "transitions": transitions, "events": events, "decisions": decisions, "messages": messages, "assignments": assignments, "peer_messages": peer_messages, "evidence": evidence, "dispatch_leases": dispatch_leases, "external_actions": external}), encoding="utf-8")
            if fault: fault("after_write")
            try:
                temp.rename(destination)
            except OSError:
                if (destination / "run.json").is_file():
                    shutil.rmtree(temp, ignore_errors=True)
                    return destination
                raise
            if fault: fault("after_rename")
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise
        return destination

    def record_event(self, run_id: str, event_id: str, event_type: str, payload: Mapping[str, Any], *,
                     expected_revision: int | None = None, lease_epoch: int | None = None,
                     coordinator_id: str | None = None) -> dict[str, Any]:
        """Record a bounded coordinator-owned event for compatibility projections."""
        validate_identifier(event_id)
        validate_identifier(event_type)
        if not isinstance(payload, Mapping):
            raise ValueError("event payload must be an object")
        encoded = self._json(dict(payload))
        if len(encoded.encode("utf-8")) > int(load_registry()["policy_defaults"]["max_message_bytes"]):
            raise ValueError("event payload exceeds byte limit")
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            existing = db.execute("SELECT * FROM runtime_events WHERE event_id=?", (event_id,)).fetchone()
            if existing:
                if existing["run_id"] != run_id or existing["event_type"] != event_type or existing["payload_json"] != encoded:
                    db.rollback()
                    raise ValueError("event id reused with different content")
                db.rollback()
                return self._run(db, run_id)
            revision = row["revision"] + 1
            db.execute("INSERT INTO runtime_events VALUES(?,?,?,?,?,?)", (event_id, run_id, event_type, encoded, revision, now))
            db.execute("UPDATE runs SET revision=?,updated_at=? WHERE run_id=?", (revision, now, run_id))
            self._commit(db)
            return self._run(db, run_id)

    def export_legacy(self, run_id: str, destination: str | os.PathLike[str]) -> Path:
        """Regenerate legacy JSON/JSONL files as views of authoritative state.

        Existing user files in ``destination`` are preserved; only the three
        compatibility view files are atomically replaced.  Nothing in these
        files is read back for lifecycle decisions.
        """
        destination = Path(destination)
        with self._connect() as db:
            run = self._run(db, run_id)
            precondition = run.get("precondition") or {}
            if precondition.get("ownership") != "verified":
                raise RuntimeError("branch/worktree ownership precondition is required before export")
            transitions = [dict(row) for row in db.execute(
                "SELECT * FROM transitions WHERE run_id=? ORDER BY sequence", (run_id,))]
            decisions = [dict(row) for row in db.execute(
                "SELECT * FROM decisions WHERE run_id=? ORDER BY sequence", (run_id,))]
            events = [dict(row) for row in db.execute(
                "SELECT * FROM runtime_events WHERE run_id=? ORDER BY revision,event_id", (run_id,))]
        meta = {
            "run_id": run["run_id"], "status": run["state"],
            "revision": run["revision"], "started_at": run["created_at"],
            "updated_at": run["updated_at"], "task_input": run["metadata"].get("task_input"),
            "precondition": run["precondition"],
        }
        event_lines = []
        for row in transitions:
            event_lines.append(self._json({
                "type": "runtime.transition", "run_id": run_id,
                "sequence": row["sequence"], "from": row["source"],
                "to": row["target"], "revision": row["revision"],
                "at": row["at"], "reason": row["reason"],
            }))
        for row in events:
            event_lines.append(self._json({
                "type": row["event_type"], "event_id": row["event_id"],
                "run_id": run_id, "revision": row["revision"],
                "at": row["at"], "data": json.loads(row["payload_json"]),
            }))
        decision_lines = []
        for row in decisions:
            decision_lines.append(self._json({
                "run_id": run_id, "sequence": row["sequence"],
                "decision_key": row["decision_key"],
                "value": json.loads(row["value_json"]),
                "revision": row["revision"], "at": row["at"],
            }))
        destination.mkdir(parents=True, exist_ok=True)
        files = {
            "meta.json": self._json(meta) + "\n",
            "events.jsonl": "\n".join(event_lines) + ("\n" if event_lines else ""),
            "decisions.jsonl": "\n".join(decision_lines) + ("\n" if decision_lines else ""),
        }
        for name, content in files.items():
            temp = destination / ("." + name + ".tmp")
            temp.write_text(content, encoding="utf-8")
            os.replace(temp, destination / name)
        return destination

    def import_legacy(self, run_id: str, source: str | os.PathLike[str] | bytes) -> dict[str, Any]:
        if isinstance(source, (str, os.PathLike)):
            path = Path(source)
            payload = path.read_bytes()
            name = str(path)
        else:
            payload = bytes(source)
            name = "<bytes>"
        receipt = {"run_id": run_id, "source": name, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload), "imported_at": self.clock()}
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            if db.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone() is None:
                raise KeyError("unknown run: " + run_id)
            existing = db.execute("SELECT sha256,receipt_json FROM migration_receipts WHERE run_id=? AND source=?", (run_id, name)).fetchone()
            if existing:
                if existing["sha256"] != receipt["sha256"]:
                    raise ValueError("legacy source changed after migration receipt")
                return json.loads(existing["receipt_json"])
            db.execute("INSERT INTO migration_receipts VALUES(?,?,?,?,?)", (run_id, name, receipt["sha256"], receipt["imported_at"], self._json(receipt)))
            self._commit(db)
        return receipt

    def create_assignment(self, run_id: str, assignment_id: str, worker_id: str, *,
                          owned_paths: list[str], context_refs: list[str], acceptance: list[str],
                          limits: Mapping[str, Any] | None = None, depends_on: list[str] | None = None,
                          expected_revision: int | None = None, lease_epoch: int | None = None,
                          coordinator_id: str | None = None) -> dict[str, Any]:
        validate_identifier(assignment_id)
        if not worker_id or not isinstance(owned_paths, list) or not isinstance(context_refs, list) or not isinstance(acceptance, list):
            raise ValueError("assignment fields are invalid")
        deps = list(depends_on or [])
        if any(not isinstance(item, str) for item in deps):
            raise ValueError("depends_on must contain assignment identifiers")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            run = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            if db.execute("SELECT 1 FROM assignments WHERE run_id=? AND assignment_id=?", (run_id, assignment_id)).fetchone():
                db.rollback(); raise ValueError("assignment already exists: " + assignment_id)
            known = {r[0]: json.loads(r[1]) for r in db.execute("SELECT assignment_id,depends_on_json FROM assignments WHERE run_id=?", (run_id,))}
            if any(dep not in known for dep in deps):
                db.rollback(); raise ValueError("unknown assignment dependency")
            known[assignment_id] = deps
            visiting, visited = set(), set()
            def visit(node):
                if node in visiting: return True
                if node in visited: return False
                visiting.add(node)
                if any(visit(dep) for dep in known[node]): return True
                visiting.remove(node); visited.add(node); return False
            if visit(assignment_id):
                db.rollback(); raise ValueError("assignment dependency cycle")
            now = self.clock()
            db.execute("INSERT INTO assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (run_id, assignment_id, worker_id, "pending", 0, self._json(owned_paths), self._json(context_refs), self._json(acceptance), self._json(dict(limits or {})), self._json(deps), now, now))
            revision = run["revision"] + 1
            db.execute("UPDATE runs SET revision=?,updated_at=? WHERE run_id=?", (revision, now, run_id))
            self._commit(db)
            return self.assignment(run_id, assignment_id)

    def assignment(self, run_id: str, assignment_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM assignments WHERE run_id=? AND assignment_id=?", (run_id, assignment_id)).fetchone()
            if row is None: raise KeyError("unknown assignment: " + assignment_id)
            result = dict(row)
            for field in ("owned_paths_json", "context_json", "acceptance_json", "limits_json", "depends_on_json"):
                result[field[:-5]] = json.loads(result.pop(field))
            return result

    def assignment_transition(self, run_id: str, assignment_id: str, target: str, *, expected_assignment_revision: int,
                              worker_id: str | None = None, expected_revision: int | None = None,
                              lease_epoch: int | None = None, coordinator_id: str | None = None) -> dict[str, Any]:
        allowed = {"pending": {"running", "cancelled"}, "running": {"waiting", "completed", "failed", "cancelled", "escalation_required"}, "waiting": {"running", "cancelled", "escalation_required"}, "escalation_required": {"running", "failed", "cancelled"}}
        if target not in {"running", "completed", "failed", "cancelled", "waiting", "escalation_required"}:
            raise ValueError("invalid assignment state")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            run = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            row = db.execute("SELECT * FROM assignments WHERE run_id=? AND assignment_id=?", (run_id, assignment_id)).fetchone()
            if row is None: raise KeyError("unknown assignment: " + assignment_id)
            if row["revision"] != expected_assignment_revision: raise RuntimeError("assignment revision mismatch")
            if worker_id is not None and row["worker_id"] != worker_id: raise RuntimeError("assignment owner mismatch")
            if row["state"] in {"completed", "failed", "cancelled"}: raise RuntimeError("assignment is terminal")
            if target not in allowed.get(row["state"], set()): raise ValueError("forbidden assignment transition")
            if target in {"running", "completed"}:
                dependencies = json.loads(row["depends_on_json"])
                if dependencies:
                    placeholders = ",".join("?" for _ in dependencies)
                    states = [r[0] for r in db.execute(f"SELECT state FROM assignments WHERE run_id=? AND assignment_id IN ({placeholders})", (run_id, *dependencies)).fetchall()]
                    if len(states) != len(dependencies) or any(state != "completed" for state in states): raise RuntimeError("assignment dependencies are incomplete")
            now = self.clock(); assignment_revision = row["revision"] + 1
            db.execute("UPDATE assignments SET state=?,revision=?,updated_at=? WHERE run_id=? AND assignment_id=?", (target, assignment_revision, now, run_id, assignment_id))
            if target == "cancelled":
                cancelled = {assignment_id}
                while True:
                    changed = False
                    dependents = db.execute("SELECT assignment_id,depends_on_json,state FROM assignments WHERE run_id=?", (run_id,)).fetchall()
                    for dependent in dependents:
                        if dependent["state"] not in {"completed", "failed", "cancelled"} and any(dep in cancelled for dep in json.loads(dependent["depends_on_json"])):
                            db.execute("UPDATE assignments SET state='cancelled',revision=revision+1,updated_at=? WHERE run_id=? AND assignment_id=?", (now, run_id, dependent["assignment_id"]))
                            cancelled.add(dependent["assignment_id"]); changed = True
                    if not changed: break
            db.execute("UPDATE runs SET revision=?,updated_at=? WHERE run_id=?", (run["revision"] + 1, now, run_id))
            self._commit(db)
            return self.assignment(run_id, assignment_id)

    def send_peer_message(self, run_id: str, *, message_id: str, assignment_id: str,
                          assignment_revision: int, correlation_id: str, sender: str, recipient: str,
                          message_type: str, deadline: float, payload: Any,
                          expected_revision: int | None = None, lease_epoch: int | None = None,
                          coordinator_id: str | None = None,
                          host_record: Mapping[str, Any] | None = None) -> dict[str, Any]:
        registry = load_registry()
        if message_type not in registry["message_types"]: raise ValueError("unknown message type")
        if not all(isinstance(value, str) and value for value in (message_id, assignment_id, correlation_id, sender, recipient)):
            raise ValueError("message identifiers are required")
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError("message deadline must be finite")
        reply_seconds = int(registry["policy_defaults"]["question_reply_seconds"])
        if message_type == "question.request" and deadline > self.clock() + reply_seconds:
            raise ValueError(f"question deadline exceeds {reply_seconds} seconds")
        encoded = self._json(payload)
        if len(encoded.encode("utf-8")) > int(registry["policy_defaults"]["max_message_bytes"]): raise ValueError("message exceeds byte limit")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            run = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            assignment = db.execute("SELECT * FROM assignments WHERE run_id=? AND assignment_id=?", (run_id, assignment_id)).fetchone()
            if assignment is None: raise KeyError("unknown assignment: " + assignment_id)
            if host_record is not None:
                claims = self._host_claims(host_record, purpose="message.send", run_id=run_id, assignment_id=assignment_id)
                if claims.get("assignment_revision") != assignment_revision or claims.get("identity") != sender:
                    raise RuntimeError("host dispatch does not authorize this message")
                self._accept_host_claim(db, claims)
            existing = db.execute("SELECT * FROM peer_messages WHERE message_id=?", (message_id,)).fetchone()
            if existing:
                if any(existing[field] != value for field, value in (("run_id", run_id), ("assignment_id", assignment_id), ("assignment_revision", assignment_revision), ("correlation_id", correlation_id), ("sender", sender), ("recipient", recipient), ("message_type", message_type), ("deadline", float(deadline)), ("payload_json", encoded))):
                    raise ValueError("message id reused with different content")
                db.rollback(); return dict(existing)
            if assignment["state"] in {"completed", "failed", "cancelled"}:
                raise RuntimeError("assignment is terminal")
            if assignment["revision"] != assignment_revision: raise RuntimeError("stale assignment message")
            if sender != coordinator_id:
                if host_record is None:
                    raise RuntimeError("host-issued sender identity is required")
                if sender != assignment["worker_id"]:
                    raise RuntimeError("sender is not assignment owner")
            now = self.clock()
            if float(deadline) < now:
                db.execute("UPDATE assignments SET state='escalation_required',revision=revision+1,updated_at=? WHERE run_id=? AND assignment_id=?", (now, run_id, assignment_id))
                db.execute("UPDATE runs SET revision=?,updated_at=? WHERE run_id=?", (run["revision"] + 1, now, run_id))
                self._commit(db)
                raise RuntimeError("message deadline expired; escalation required")
            count = db.execute("SELECT COUNT(*) FROM peer_messages WHERE run_id=? AND assignment_id=?", (run_id, assignment_id)).fetchone()[0]
            if count >= int(registry["policy_defaults"]["max_messages_per_worker"]): raise RuntimeError("assignment message budget exhausted")
            if message_type == "question.request":
                prior = db.execute("SELECT rowid AS _rowid,* FROM peer_messages WHERE run_id=? AND correlation_id=? ORDER BY rowid", (run_id, correlation_id)).fetchall()
                requests = [item for item in prior if item["message_type"] == "question.request"]
                if requests and prior[-1]["message_type"] != "question.response":
                    raise ValueError("question correlation already has an outstanding request")
                outstanding = db.execute("SELECT COUNT(*) FROM peer_messages q WHERE q.run_id=? AND q.assignment_id=? AND q.message_type='question.request' AND NOT EXISTS (SELECT 1 FROM peer_messages r WHERE r.message_type='question.response' AND r.run_id=q.run_id AND r.correlation_id=q.correlation_id)", (run_id, assignment_id)).fetchone()[0]
                if outstanding >= int(registry["policy_defaults"]["max_outstanding_questions"]): raise RuntimeError("question budget exhausted")
                if requests:
                    if prior[-1]["message_type"] != "question.response" or prior[-1]["sender"] != recipient or prior[-1]["recipient"] != sender:
                        raise RuntimeError("question round participants do not match")
                    if len(requests) >= int(registry["policy_defaults"]["max_question_rounds"]):
                        raise RuntimeError("question round budget exhausted")
            if message_type == "question.response":
                prior = db.execute("SELECT rowid AS _rowid,* FROM peer_messages WHERE run_id=? AND correlation_id=? ORDER BY rowid", (run_id, correlation_id)).fetchall()
                request = next((item for item in reversed(prior) if item["message_type"] == "question.request" and not any(reply["message_type"] == "question.response" and reply["_rowid"] > item["_rowid"] for reply in prior)), None)
                if request is None:
                    raise ValueError("question response has no request")
                if request["sender"] != recipient or request["recipient"] != sender: raise RuntimeError("question participants do not match")
                if now > request["deadline"]: raise RuntimeError("question reply deadline expired")
            db.execute("INSERT INTO peer_messages VALUES(?,?,?,?,?,?,?,?,?,?,?)", (message_id, run_id, assignment_id, assignment_revision, correlation_id, sender, recipient, message_type, float(deadline), encoded, now))
            db.execute("UPDATE runs SET revision=?,updated_at=? WHERE run_id=?", (run["revision"] + 1, now, run_id))
            self._commit(db)
            return dict(db.execute("SELECT * FROM peer_messages WHERE message_id=?", (message_id,)).fetchone())

    def recover_timeouts(self, run_id: str, *, expected_revision: int | None = None,
                         lease_epoch: int | None = None, coordinator_id: str | None = None) -> dict[str, Any]:
        """Escalate expired unanswered questions and peer wait cycles."""
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            run = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            requests = db.execute("SELECT rowid AS _rowid,* FROM peer_messages WHERE run_id=? AND message_type='question.request'", (run_id,)).fetchall()
            all_messages = db.execute("SELECT rowid AS _rowid,* FROM peer_messages WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
            unanswered = [request for request in requests if request["deadline"] <= now and not any(reply["message_type"] == "question.response" and reply["correlation_id"] == request["correlation_id"] and reply["_rowid"] > request["_rowid"] for reply in all_messages)]
            active_requests = [request for request in requests if not any(reply["message_type"] == "question.response" and reply["correlation_id"] == request["correlation_id"] and reply["_rowid"] > request["_rowid"] for reply in all_messages)]
            escalated = {r["assignment_id"] for r in unanswered}
            edges = [(r["sender"], r["recipient"], r["assignment_id"]) for r in active_requests]
            graph = {}
            for sender, recipient, assignment_id in edges:
                graph.setdefault(sender, []).append((recipient, assignment_id))
            visiting, visited = set(), set()
            def visit(node, path):
                if node in visiting:
                    cycle_nodes = set(path[path.index(node):])
                    escalated.update(a for s, t, a in edges if s in cycle_nodes and t in cycle_nodes)
                    return
                if node in visited: return
                visiting.add(node)
                for target, _ in graph.get(node, []): visit(target, path + [target])
                visiting.remove(node); visited.add(node)
            for node in graph: visit(node, [node])
            eligible = {r[0] for r in db.execute("SELECT assignment_id FROM assignments WHERE run_id=? AND state NOT IN ('completed','failed','cancelled','escalation_required')", (run_id,))}
            escalated &= eligible
            if escalated:
                placeholders = ",".join("?" for _ in escalated)
                db.execute(f"UPDATE assignments SET state='escalation_required',revision=revision+1,updated_at=? WHERE run_id=? AND assignment_id IN ({placeholders}) AND state NOT IN ('completed','failed','cancelled')", (now, run_id, *sorted(escalated)))
                db.execute("UPDATE runs SET revision=?,updated_at=? WHERE run_id=?", (run["revision"] + 1, now, run_id))
                self._commit(db)
            else:
                db.rollback()
            return {"escalated_assignments": sorted(escalated), "checked_at": now}

    def receive_peer_messages(self, run_id: str, recipient: str, *, reader_id: str | None = None,
                              host_record: Mapping[str, Any] | None = None, limit: int = 8,
                              after_message_id: str | None = None) -> list[dict[str, Any]]:
        if host_record is None:
            raise RuntimeError("mailbox delivery unavailable: host-issued identity is not implemented")
        claims = self._host_claims(host_record, purpose="message.receive", run_id=run_id)
        if claims.get("identity") != recipient or (reader_id is not None and reader_id != recipient):
            raise RuntimeError("host dispatch does not authorize mailbox recipient")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._accept_host_claim(db, claims)
            rows = self._inspect_peer_messages_db(db, run_id, recipient, limit, after_message_id)
            self._commit(db)
            return rows

    def _inspect_peer_messages_db(self, db, run_id: str, recipient: str, limit: int,
                                  after_message_id: str | None) -> list[dict[str, Any]]:
        if not recipient or type(limit) is not int or limit < 1 or limit > 8:
            raise ValueError("recipient required and limit must be bounded")
        if db.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone() is None:
            raise KeyError("unknown run: " + run_id)
        if after_message_id:
            cursor = db.execute("SELECT created_at FROM peer_messages WHERE run_id=? AND message_id=?", (run_id, after_message_id)).fetchone()
            if cursor is None: raise ValueError("unknown message cursor")
            rows = db.execute("SELECT * FROM peer_messages WHERE run_id=? AND recipient=? AND (created_at>? OR (created_at=? AND message_id>?)) ORDER BY created_at,message_id LIMIT ?", (run_id, recipient, cursor[0], cursor[0], after_message_id, limit)).fetchall()
        else:
            rows = db.execute("SELECT * FROM peer_messages WHERE run_id=? AND recipient=? ORDER BY created_at,message_id LIMIT ?", (run_id, recipient, limit)).fetchall()
        result = []
        for row in rows:
            item = dict(row); item["payload"] = json.loads(item.pop("payload_json")); result.append(item)
        return result

    def _inspect_peer_messages(self, run_id: str, recipient: str, *, limit: int = 8,
                               after_message_id: str | None = None) -> list[dict[str, Any]]:
        """Internal persistence inspection, NOT authenticated delivery or a public API."""
        if not recipient or type(limit) is not int or limit < 1 or limit > 8:
            raise ValueError("recipient required and limit must be bounded")
        with self._connect() as db:
            if db.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone() is None:
                raise KeyError("unknown run: " + run_id)
            if after_message_id:
                cursor = db.execute("SELECT created_at FROM peer_messages WHERE run_id=? AND message_id=?", (run_id, after_message_id)).fetchone()
                if cursor is None: raise ValueError("unknown message cursor")
                rows = db.execute("SELECT * FROM peer_messages WHERE run_id=? AND recipient=? AND (created_at>? OR (created_at=? AND message_id>?)) ORDER BY created_at,message_id LIMIT ?", (run_id, recipient, cursor[0], cursor[0], after_message_id, limit)).fetchall()
            else:
                rows = db.execute("SELECT * FROM peer_messages WHERE run_id=? AND recipient=? ORDER BY created_at,message_id LIMIT ?", (run_id, recipient, limit)).fetchall()
            result = []
            for row in rows:
                item = dict(row); item["payload"] = json.loads(item.pop("payload_json")); result.append(item)
            return result

    def record_evidence(self, run_id: str, evidence_id: str, *, kind: str, source_revision: int,
                        command: str, cwd: str, source_hash: str, exit_status: int,
                        required: bool = True, expected_revision: int | None = None,
                        lease_epoch: int | None = None, coordinator_id: str | None = None,
                        host_record: Mapping[str, Any] | None = None) -> dict[str, Any]:
        validate_identifier(evidence_id)
        if not kind or not command or not cwd or not source_hash or type(exit_status) is not int:
            raise ValueError("evidence receipt fields are invalid")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_versions(db)
            run = self._guard(db, run_id, expected_revision, lease_epoch, coordinator_id)
            if source_revision != run["revision"]: raise RuntimeError("evidence is stale for current revision")
            if exit_status != 0 and required and host_record is None:
                raise RuntimeError("required verification failed")
            host_record_id = None
            if host_record is not None:
                claims = self._host_claims(host_record, purpose="evidence.record", run_id=run_id)
                if (claims.get("evidence_id") != evidence_id or claims.get("source_revision") != source_revision
                        or claims.get("source_hash") != source_hash or claims.get("exit_status") != exit_status
                        or claims.get("kind") != kind or claims.get("command") != command
                        or claims.get("cwd") != cwd or claims.get("required") is not required):
                    raise RuntimeError("host evidence record does not match receipt")
                self._accept_host_claim(db, claims)
                host_record_id = claims["record_id"]
            now = self.clock()
            db.execute("INSERT INTO evidence(run_id,evidence_id,kind,source_revision,command,cwd,source_hash,exit_status,required,created_at,host_record_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (run_id, evidence_id, kind, source_revision, command, cwd, source_hash, exit_status, int(bool(required)), now, host_record_id))
            db.execute("UPDATE runs SET revision=?,updated_at=? WHERE run_id=?", (run["revision"] + 1, now, run_id))
            self._commit(db)
            return dict(db.execute("SELECT * FROM evidence WHERE run_id=? AND evidence_id=?", (run_id, evidence_id)).fetchone())
