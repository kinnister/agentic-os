"""Strict host trace parsing for command evidence.

The parser accepts only an explicit adapter event. It never infers a command,
exit status, revision, or hash from assistant prose or arbitrary tool output.
"""

from __future__ import annotations

from typing import Any, Mapping


def command_claims(event: Mapping[str, Any]) -> dict[str, Any]:
    """Validate explicit command fields before any host claim is attached."""
    if not isinstance(event, Mapping) or event.get("type") != "agentic.command.completed":
        raise ValueError("explicit command completion event is required")
    required = ("evidence_id", "run_id", "source_revision", "command", "cwd",
                "source_hash", "exit_status")
    if any(field not in event for field in required):
        raise ValueError("command completion event is missing required fields")
    if not all(isinstance(event[field], str) and event[field] for field in
               ("evidence_id", "run_id", "command", "cwd", "source_hash")):
        raise ValueError("command completion identifiers are invalid")
    if type(event["source_revision"]) is not int or event["source_revision"] < 0:
        raise ValueError("command completion source_revision is invalid")
    if type(event["exit_status"]) is not int:
        raise ValueError("command completion exit_status is invalid")
    if type(event.get("required", True)) is not bool:
        raise ValueError("command completion required flag is invalid")
    return {
        "evidence_id": event["evidence_id"],
        "run_id": event["run_id"],
        "source_revision": event["source_revision"],
        "command": event["command"],
        "cwd": event["cwd"],
        "source_hash": event["source_hash"],
        "exit_status": event["exit_status"],
        "required": event.get("required", True),
    }


def command_receipt(event: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one explicit ``agentic.command.completed`` adapter event."""
    receipt = command_claims(event)
    if not isinstance(event.get("host_record"), Mapping):
        raise ValueError("command completion host_record is required")
    receipt["host_record"] = dict(event["host_record"])
    return receipt


def ingest_command_event(store: Any, event: Mapping[str, Any], *,
                         expected_revision: int | None = None,
                         lease_epoch: int | None = None,
                         coordinator_id: str | None = None) -> dict[str, Any]:
    """Validate an explicit host event and persist it as authoritative evidence."""
    receipt = command_receipt(event)
    return store.record_evidence(
        receipt["run_id"], receipt["evidence_id"], kind="host.command",
        source_revision=receipt["source_revision"], command=receipt["command"],
        cwd=receipt["cwd"], source_hash=receipt["source_hash"],
        exit_status=receipt["exit_status"], required=receipt["required"], expected_revision=expected_revision,
        lease_epoch=lease_epoch, coordinator_id=coordinator_id,
        host_record=receipt["host_record"],
    )
