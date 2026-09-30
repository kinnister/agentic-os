#!/usr/bin/env python3
"""Execute one declared external action through the runtime fencing boundary.

The caller supplies a coordinator-owned run revision and an argv-style adapter
command.  The intent is recorded before the adapter starts.  The result is
reconciled afterwards; timeout and process-launch failures are deliberately
``uncertain`` so a caller cannot repeat an effect without reconciliation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def _runtime(root: Path, operation: str, payload: dict) -> dict:
    # The authoritative state root may be a fixture/worktree. Resolve the
    # runtime implementation from this shipped helper, never from the state
    # directory supplied by a caller. The plugin bundle carries its own copy;
    # the source checkout fallback supports repository tests.
    candidates = [
        Path(os.environ["AGENTIC_RUNTIME_ROOT"]) if os.environ.get("AGENTIC_RUNTIME_ROOT") else None,
        Path(__file__).resolve().parents[1] / "runtime",
        Path(__file__).resolve().parents[3] / "runtime",
    ]
    runtime = next((candidate for candidate in candidates if candidate and (candidate / "run.py").is_file()), None)
    if runtime is None:
        raise RuntimeError("bundled runtime is unavailable")
    request = {"api_version": "1.0.0", "operation": operation, "root": str(root), **payload}
    env = os.environ.copy()
    env["PYTHONPATH"] = str(runtime) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, str(runtime / "run.py")],
        input=json.dumps(request), text=True, capture_output=True, env=env,
    )
    if proc.returncode:
        raise RuntimeError(proc.stdout.strip() or proc.stderr.strip() or f"runtime {operation} failed")
    result = json.loads(proc.stdout)
    if not result.get("ok"):
        raise RuntimeError(result.get("error", {}).get("message", f"runtime {operation} failed"))
    return result["result"]


def _environment_request() -> dict:
    """Build a request for compatibility hooks with a coordinator context."""
    required = {
        "AGENTIC_EXTERNAL_ROOT", "AGENTIC_EXTERNAL_RUN_ID", "AGENTIC_EXTERNAL_KEY",
        "AGENTIC_EXTERNAL_ACTION", "AGENTIC_EXTERNAL_REQUEST", "AGENTIC_COORDINATOR_ID",
        "AGENTIC_LEASE_EPOCH", "AGENTIC_EXPECTED_REVISION", "AGENTIC_EXTERNAL_ADAPTER",
    }
    missing = sorted(k for k in required if not os.environ.get(k))
    if missing:
        raise ValueError("missing managed external context: " + ", ".join(missing))
    return {
        "api_version": "1.0.0", "operation": "external.execute",
        "root": os.environ["AGENTIC_EXTERNAL_ROOT"],
        "run_id": os.environ["AGENTIC_EXTERNAL_RUN_ID"],
        "idempotency_key": os.environ["AGENTIC_EXTERNAL_KEY"],
        "action": os.environ["AGENTIC_EXTERNAL_ACTION"],
        "request": json.loads(os.environ["AGENTIC_EXTERNAL_REQUEST"]),
        "coordinator_id": os.environ["AGENTIC_COORDINATOR_ID"],
        "lease_epoch": int(os.environ["AGENTIC_LEASE_EPOCH"]),
        "expected_revision": int(os.environ["AGENTIC_EXPECTED_REVISION"]),
        "adapter": ["bash", "-c", os.environ["AGENTIC_EXTERNAL_ADAPTER"]],
        "timeout_seconds": float(os.environ.get("AGENTIC_EXTERNAL_TIMEOUT", "120")),
    }


def main() -> int:
    try:
        request = _environment_request() if sys.argv[1:] == ["--env"] else json.load(sys.stdin)
        required = {
            "api_version", "operation", "root", "run_id", "idempotency_key",
            "action", "request", "coordinator_id", "lease_epoch",
            "expected_revision", "adapter",
        }
        if request.get("api_version") != "1.0.0" or request.get("operation") != "external.execute":
            raise ValueError("unsupported external action request")
        if set(request) - required - {"timeout_seconds"} or not required <= set(request):
            raise ValueError("unknown or missing external action fields")
        adapter = request["adapter"]
        if not isinstance(adapter, list) or not adapter or not all(isinstance(v, str) for v in adapter):
            raise ValueError("adapter must be a non-empty argv list")
        timeout = float(request.get("timeout_seconds", 120))
        if timeout <= 0 or timeout > 120:
            raise ValueError("timeout_seconds must be between 0 and 120")

        root = Path(request["root"]).resolve()
        common = {k: request[k] for k in (
            "run_id", "idempotency_key", "coordinator_id", "lease_epoch", "expected_revision"
        )}
        intent = _runtime(root, "external.intent", {
            **common, "action": request["action"], "request": request["request"]
        })
        # The intent mutation advances the run revision.  Read it back instead
        # of guessing, so reconciliation remains fenced after retries.
        current = _runtime(root, "run.status", {"run_id": request["run_id"]})
        reconcile = {"run_id": request["run_id"], "idempotency_key": request["idempotency_key"],
                     "coordinator_id": request["coordinator_id"], "lease_epoch": request["lease_epoch"],
                     "expected_revision": current["revision"]}
        try:
            completed = subprocess.run(adapter, cwd=root, capture_output=True, text=True, timeout=timeout)
            status = "succeeded" if completed.returncode == 0 else "failed"
            result = {"returncode": completed.returncode, "stdout": completed.stdout[-4096:], "stderr": completed.stderr[-4096:]}
        except subprocess.TimeoutExpired as error:
            status = "uncertain"
            result = {"reason": "timeout", "timeout_seconds": timeout,
                      "stdout": (error.stdout or "")[-4096:] if isinstance(error.stdout, str) else "",
                      "stderr": (error.stderr or "")[-4096:] if isinstance(error.stderr, str) else ""}
        except OSError as error:
            status = "uncertain"
            result = {"reason": "launch_error", "error": str(error)}
        final = _runtime(root, "external.reconcile", {**reconcile, "status": status, "result": result})
        print(json.dumps({"api_version": "1.0.0", "ok": True, "intent": intent,
                          "status": status, "result": final}, sort_keys=True))
        return 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError, json.JSONDecodeError) as error:
        print(json.dumps({"api_version": "1.0.0", "ok": False,
                          "error": {"code": "invalid_request", "message": str(error)}}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
