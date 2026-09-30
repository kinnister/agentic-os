"""Strict JSON event-stream adapters for host command evidence."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from .host import adapt_command_event


def adapt_event(event: Mapping[str, Any], key: bytes | str, *, identity: str,
                issued_at: float, expires_at: float) -> dict[str, Any] | None:
    """Sign one explicit command event; return ``None`` for unrelated output."""
    if not isinstance(event, Mapping) or event.get("type") != "agentic.command.completed":
        return None
    return adapt_command_event(event, key, identity=identity,
                               issued_at=issued_at, expires_at=expires_at)


def adapt_json_lines(lines: Iterable[str], key: bytes | str, *, identity: str,
                     issued_at: float, expires_at: float) -> list[dict[str, Any]]:
    """Extract signed receipts from a JSONL host stream, failing closed on bad JSON."""
    receipts = []
    for line in lines:
        try:
            event = json.loads(line)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("host trace contains malformed JSON") from exc
        receipt = adapt_event(event, key, identity=identity,
                              issued_at=issued_at, expires_at=expires_at)
        if receipt is not None:
            receipts.append(receipt)
    return receipts
