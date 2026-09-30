"""Deterministic host capability discovery used by setup and run preflight."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Mapping
from pathlib import Path


def _version(command: str) -> str | None:
    executable = shutil.which(command)
    if not executable:
        return None
    try:
        result = subprocess.run([executable, "--version"], check=True, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or result.stderr.strip() or "present"


def preflight(root: str | Path) -> dict:
    """Report observed capabilities; never claims unsupported sandbox guarantees."""
    root = Path(root)
    host_identity = "configured" if os.environ.get("AGENTIC_HOST_KEY") else "unsupported"
    control_matrix = {
        "state_protocol": {
            "status": "enforced", "boundary": "runtime",
            "evidence": "SQLite transactions, revisions, and coordinator leases",
        },
        "coordinator_identity": {
            "status": host_identity, "boundary": "before_execution",
            "evidence": "host-signed dispatch records" if host_identity == "configured"
                        else "AGENTIC_HOST_KEY is unavailable",
        },
        "worker_tool_scope": {
            "status": "unsupported", "boundary": "before_execution",
            "evidence": "host adapter must provide tool restriction and identity binding",
        },
        "artifact_integrity": {
            "status": "enforced", "boundary": "before_integration",
            "evidence": "signed evidence and current-revision hash checks",
        },
        "os_sandbox": {
            "status": "unsupported", "boundary": "before_execution",
            "evidence": "native host sandbox certification is not available",
        },
        "external_effects": {
            "status": "adapter_required", "boundary": "before_execution",
            "evidence": "record intent and reconcile outcome through a host adapter",
        },
    }
    return {
        "python": {"available": sys.version_info >= (3, 10), "version": sys.version.split()[0]},
        "sqlite": {"available": sqlite3.sqlite_version_info >= (3, 24, 0), "version": sqlite3.sqlite_version},
        "git": {"available": _version("git") is not None, "version": _version("git")},
        "hosts": {name: {"available": _version(name) is not None, "version": _version(name)} for name in ("claude", "codex", "cursor")},
        "repository": {"root": str(root.resolve()), "git_worktree": (root / ".git").exists()},
        "enforcement": {
            "sqlite_protocol": "enforced",
            "host_identity": host_identity,
            "completion_gate": host_identity,
            "dispatch_leases": "enforced",
            "os_sandbox": "unsupported",
            "external_effects": "adapter_required",
        },
        "control_matrix": control_matrix,
    }


def require_capabilities(report: Mapping[str, Any], required: list[str]) -> dict:
    """Fail closed when a workflow declares controls that preflight cannot prove."""
    if not isinstance(required, list) or any(not isinstance(item, str) or not item for item in required):
        raise ValueError("required capabilities must be a list of names")
    enforcement = report.get("enforcement", {})
    unsupported = [item for item in required if enforcement.get(item) != "enforced" and enforcement.get(item) != "configured"]
    if unsupported:
        raise RuntimeError("required host capabilities unavailable: " + ", ".join(sorted(unsupported)))
    result = dict(report)
    result["required_capabilities"] = list(required)
    result["ready"] = True
    return result


def _canonical(record: Mapping[str, Any]) -> bytes:
    payload = {key: value for key, value in record.items() if key != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_dispatch(record: Mapping[str, Any], key: bytes | str) -> dict[str, Any]:
    """Create a deterministic host-issued record using an adapter-held key."""
    secret = key.encode("utf-8") if isinstance(key, str) else bytes(key)
    if not secret:
        raise ValueError("host signing key is required")
    result = dict(record)
    result["signature"] = base64.urlsafe_b64encode(hmac.new(secret, _canonical(result), hashlib.sha256).digest()).decode("ascii")
    return result


def issue_evidence_record(event: Mapping[str, Any], key: bytes | str, *,
                          identity: str, issued_at: float, expires_at: float) -> dict[str, Any]:
    """Attach a short-lived host signature to an explicit command event.

    The host signs only fields parsed from the explicit adapter event. It never
    derives a command, result, revision, or source hash from model text.
    """
    from .trace import command_claims
    claims = command_claims(event)
    if not isinstance(identity, str) or not identity:
        raise ValueError("host identity is required")
    if not isinstance(issued_at, (int, float)) or not isinstance(expires_at, (int, float)) or expires_at <= issued_at:
        raise ValueError("host evidence lifetime is invalid")
    record = {
        "record_id": claims["evidence_id"], "purpose": "evidence.record",
        "run_id": claims["run_id"], "identity": identity,
        "evidence_id": claims["evidence_id"],
        "source_revision": claims["source_revision"],
        "source_hash": claims["source_hash"], "exit_status": claims["exit_status"],
        "kind": "host.command", "command": claims["command"], "cwd": claims["cwd"],
        "required": claims["required"],
        "issued_at": issued_at, "expires_at": expires_at,
    }
    return sign_dispatch(record, key)


def adapt_command_event(event: Mapping[str, Any], key: bytes | str, *,
                        identity: str, issued_at: float, expires_at: float) -> dict[str, Any]:
    """Return an explicit command event with a signed evidence claim attached."""
    record = issue_evidence_record(event, key, identity=identity,
                                   issued_at=issued_at, expires_at=expires_at)
    result = dict(event)
    result["host_record"] = record
    return result


def verify_dispatch(record: Mapping[str, Any], key: bytes | str, *, purpose: str,
                    now: float | None = None) -> dict[str, Any]:
    """Verify a short-lived host dispatch record and return its claims."""
    if not isinstance(record, Mapping) or record.get("purpose") != purpose:
        raise ValueError("host dispatch purpose mismatch")
    signature = record.get("signature")
    secret = key.encode("utf-8") if isinstance(key, str) else bytes(key)
    if not secret or not isinstance(signature, str):
        raise ValueError("host dispatch signature is missing")
    try:
        supplied = base64.urlsafe_b64decode(signature.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("host dispatch signature is malformed") from exc
    expected = hmac.new(secret, _canonical(record), hashlib.sha256).digest()
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("host dispatch signature is invalid")
    issued = record.get("issued_at")
    expires = record.get("expires_at")
    if not isinstance(issued, (int, float)) or not isinstance(expires, (int, float)) or expires <= issued:
        raise ValueError("host dispatch lifetime is invalid")
    current = time.time() if now is None else now
    if current > expires:
        raise ValueError("host dispatch record expired")
    if not isinstance(record.get("record_id"), str) or not record["record_id"]:
        raise ValueError("host dispatch record_id is required")
    if not isinstance(record.get("identity"), str) or not record["identity"]:
        raise ValueError("host dispatch identity is required")
    return dict(record)
