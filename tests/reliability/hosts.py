"""Bounded, session-local host execution for the opt-in reliability harness.

Profiles freeze an explicit model, settings, permissions, executable hash and CLI
capabilities. Authentication storage is left untouched. CLI isolation flags do
not prove isolation of global skills, instructions or managed policy; unsupported
channels fail closed before model execution. POSIX process groups contain
ordinary descendants, not independently daemonized processes.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time

from runtime.agentic_runtime.trace import command_receipt, ingest_command_event
from runtime.agentic_runtime.adapter import adapt_json_lines


_TOOL_EVENTS_SPEC = importlib.util.spec_from_file_location(
    "reliability_tool_events", Path(__file__).with_name("tool_events.py"))
_TOOL_EVENTS = importlib.util.module_from_spec(_TOOL_EVENTS_SPEC)
_TOOL_EVENTS_SPEC.loader.exec_module(_TOOL_EVENTS)
MAX_TRACE_BYTES = _TOOL_EVENTS.MAX_TRACE_BYTES
extract_tool_events = _TOOL_EVENTS.extract_tool_events
strict_json_line = _TOOL_EVENTS.strict_json_line


_ISOLATION = None


def _isolation():
    # Load the sibling explicitly: the harness is also imported by file path.
    global _ISOLATION
    if _ISOLATION is None:
        path = Path(__file__).with_name("isolation.py")
        spec = importlib.util.spec_from_file_location("reliability_host_isolation", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _ISOLATION = module
    return _ISOLATION


def _isolation_evidence(timeout_seconds: float = 10) -> dict:
    return _isolation().probe_host_boundary(timeout_seconds=timeout_seconds)


def _host_environment(profile: dict | None = None) -> dict:
    """Build host env without receipt secrets or unwritable temp paths."""
    environment = {k: v for k, v in os.environ.items() if k != "AGENTIC_HOST_KEY"}
    state_dir = (profile or {}).get("state_dir")
    if state_dir:
        temp_dir = Path(state_dir) / "tmp"
        temp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp_dir.chmod(0o700)
        environment["TMPDIR"] = str(temp_dir)
        # Codex creates first-run aliases and other CLI state below its home
        # even with --ephemeral.  Point both HOME and CODEX_HOME at the
        # explicitly bound, isolated state directory so those writes stay
        # inside the sandbox. Claude keeps its normal HOME because its
        # configuration root is controlled separately by CLAUDE_CONFIG_DIR.
        if (profile or {}).get("host") == "codex":
            environment["HOME"] = str(state_dir)
            environment["CODEX_HOME"] = str(state_dir)
    return environment


def _validate_host(host: str) -> None:
    if host not in ("claude", "codex"):
        raise ValueError(f"Unsupported host: {host!r}")


def _fixture_path(fixture: Path) -> Path:
    fixture = Path(fixture).resolve()
    if not fixture.is_dir():
        raise FileNotFoundError(f"Fixture directory does not exist: {fixture}")
    return fixture


def _cleanup(process: subprocess.Popen) -> None:
    """Kill the group even when its parent already exited after SIGTERM."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        time.sleep(0.1)
        # Reap a dead leader before signaling again: macOS can report EPERM
        # for a process group containing only its unreaped zombie leader.
        process.poll()
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def _drain_socket(sock: socket.socket, dest, cap: int) -> None:
    """Copy one host stdio stream from a socketpair end into its trace file.

    The peer end is the host's actual fd 0>1 or stderr, so ``dest`` receives
    exactly what a direct-file redirect would have, except a same-user tool
    descendant can no longer reopen it through /proc/<pid>/fd/N (a socket,
    unlike a pipe or regular file, cannot be reopened by path; the kernel
    returns ENXIO). Writes stop at ``cap`` bytes so a runaway or hostile host
    cannot grow the trace file without bound, but the socket keeps being
    drained past that point so the host is never blocked on a full send
    buffer; the file therefore lands one byte over ``cap`` on overflow, and
    ``run_host`` then fails the launch without reading the truncated trace.
    """
    written = 0
    try:
        while True:
            try:
                chunk = sock.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            if written < cap:
                take = chunk[:cap - written]
                dest.write(take)
                dest.flush()
                written += len(take)
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _trace_channel_evidence(isolation_evidence: dict) -> dict:
    """Record how this launch protects host stdio from descendant forgery.

    A socketpair defeats /proc/<host pid>/fd/N reopening unconditionally (the
    kernel returns ENXIO for a socket, regardless of permissions), but a
    same-user descendant can still duplicate the fd directly via
    pidfd_getfd(2) or attach with ptrace(2) unless the kernel's Yama LSM
    restricts those to a process's own descendants. A host with startup
    evidence is certified only when this is protected (Yama scope 0 or
    unreadable, or a non-Linux mechanism never verified here, is a limit).
    """
    scope = _isolation().yama_ptrace_scope()
    mechanism = isolation_evidence.get("mechanism")
    protected = mechanism == "bubblewrap" and isinstance(scope, int) and scope > 0
    if protected:
        reason = None
    elif mechanism == "bubblewrap":
        reason = "kernel.yama.ptrace_scope is 0 or unreadable"
    else:
        reason = "trace channel forgery protection is not verified for this platform/mechanism"
    return {"channel": "socketpair", "yama_ptrace_scope": scope,
            "trace_channel_protected": protected, "reason": reason}


def _probe(argv: list[str], cwd: Path | None = None,
           timeout_seconds: float = 10) -> subprocess.CompletedProcess:
    """Read-only CLI probe; inherited auth/config is never modified."""
    with subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, start_new_session=os.name == "posix") as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
        finally:
            _cleanup(process)


def _isolation_limits(host: str) -> list[str]:
    """Name the remaining evidence needed; no environment waiver is accepted."""
    common = ("Offline filesystem controls do not certify actual host startup: require "
              "a no-inference startup probe proving existing authentication, denied global "
              "instructions/skills/plugins and managed policy inputs, plus retained project "
              "and selected-plugin hook execution under the same outer sandbox (sandbox-exec "
              "on macOS, bubblewrap on Linux) with the host's declared auth files")
    if host == "claude":
        return [common + "; installed --bare changes auth and skips hooks, while "
                "--safe-mode disables the hooks/plugins under evaluation"]
    return [common + "; installed exec --help/--version do not exercise authentication "
            "or hook discovery; --ignore-user-config retains CODEX_HOME auth but does "
            "not itself establish exclusion of other CODEX_HOME inputs"]


def _configured_auth_files(host: str) -> tuple[list[str], dict[str, str]]:
    """Resolve an explicit, operator-provided read-only auth allowlist.

    The evaluator never guesses credential paths and never prints their
    contents. A missing allowlist keeps the host uncertified; when supplied,
    only existing regular files are passed to the outer sandbox.
    """
    raw = os.environ.get(f"RELIABILITY_{host.upper()}_AUTH_FILES", "")
    paths: list[str] = []
    hashes: dict[str, str] = {}
    for item in raw.split(os.pathsep) if raw else []:
        candidate = Path(item).expanduser()
        if not candidate.is_absolute():
            raise ValueError(f"{host} auth file must be an absolute path")
        resolved = candidate.resolve()
        if not resolved.is_file() or resolved.is_symlink():
            raise ValueError(f"{host} auth file is not a regular file: {resolved}")
        paths.append(str(resolved))
        hashes[str(resolved)] = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return sorted(set(paths)), hashes


def _configured_state_dir(host: str) -> str | None:
    value = os.environ.get(f"RELIABILITY_{host.upper()}_STATE_DIR", "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise ValueError(f"{host} writable state directory must be an existing absolute directory")
    return str(path.resolve())


def _configured_startup_evidence(host: str, model: str,
                                 auth_file_sha256: dict[str, str],
                                 executable_sha256: str,
                                 isolation_evidence: dict
                                 ) -> tuple[dict | None, str | None, str | None]:
    """Load operator-retained startup proof; never treat an env flag as proof."""
    raw = os.environ.get(f"RELIABILITY_{host.upper()}_STARTUP_EVIDENCE", "").strip()
    if not raw:
        return None, None, "startup evidence file is not configured"
    path = Path(raw).expanduser()
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        return None, None, "startup evidence file is not a regular absolute file"
    try:
        evidence = strict_json_line(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        return None, None, f"startup evidence is invalid: {type(exc).__name__}"
    required = ("schema_version", "host", "model", "startup_ok", "auth_only",
                "global_inputs_denied", "selected_plugin_visible", "hook_status",
                "auth_file_sha256", "executable_sha256", "isolation_probe_sha256",
                "host_identity")
    if (not isinstance(evidence, dict) or evidence.get("schema_version") != 2
            or evidence.get("host") != host or evidence.get("model") != model
            or not all(key in evidence for key in required)
            or not all(evidence.get(key) is True for key in
                       ("startup_ok", "auth_only", "global_inputs_denied", "selected_plugin_visible"))
            or evidence.get("hook_status") not in ("executed", "not_applicable")):
        return None, None, "startup evidence does not satisfy the certification contract"
    if host == "claude" and evidence.get("hook_status") != "executed":
        return None, None, "Claude certification requires selected hook execution"
    if evidence.get("auth_file_sha256") != auth_file_sha256:
        return None, None, "startup evidence auth file hash differs from current credentials"
    if evidence.get("executable_sha256") != executable_sha256:
        return None, None, "startup evidence executable hash differs from current host"
    if (evidence.get("isolation_probe_sha256") != isolation_evidence.get("probe_sha256")
            or evidence.get("host_identity") != isolation_evidence.get("host_identity")):
        return None, None, "startup evidence isolation host identity differs from current host"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return evidence, digest, None


def _profile(host: str, executable: str, help_text: str,
             timeout_seconds: float = 10) -> dict:
    model = os.environ.get(f"RELIABILITY_{host.upper()}_MODEL", "")
    required = (["--setting-sources", "--settings", "--model", "--effort",
                 "--permission-mode", "--strict-mcp-config", "--plugin-dir"]
                if host == "claude" else
                ["--ignore-user-config", "--ignore-rules", "--model", "--sandbox",
                 "--config", "--ephemeral"])
    auth_files, auth_file_hashes = _configured_auth_files(host)
    state_dir = _configured_state_dir(host)
    executable_sha256 = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
    isolation_evidence = _isolation_evidence(timeout_seconds)
    # A certified host also needs a trace channel its tool descendants cannot
    # forge; test doubles without startup evidence are unaffected.
    trace_channel = _trace_channel_evidence(isolation_evidence)
    isolation_evidence = {**isolation_evidence, "trace_channel": trace_channel}
    startup_evidence, startup_evidence_sha256, certification_error = _configured_startup_evidence(
        host, model, auth_file_hashes, executable_sha256, isolation_evidence)
    base_limits = _isolation_limits(host)
    limits = [] if startup_evidence is not None else base_limits
    if startup_evidence is not None and not auth_files:
        limits.append("Certified host requires a declared auth-file allowlist")
    if startup_evidence is not None and not trace_channel["trace_channel_protected"]:
        limits.append("Certified host requires a protected trace channel: "
                      + trace_channel["reason"])
    # An empty policy result is reserved for deterministic test doubles and
    # explicitly certified adapters; do not add a synthetic environment error
    # in that mode.
    if certification_error and base_limits:
        limits.append(certification_error)
    if not isolation_evidence["filesystem_enforced"]:
        limits.append(isolation_evidence["error"] or "Filesystem containment canary failed")
    if isolation_evidence.get("mechanism") == "sandbox-exec" and state_dir is None:
        limits.append("macOS host launch requires an explicit writable state directory")
    if isolation_evidence.get("mechanism") == "sandbox-exec" and auth_files:
        limits.append("macOS auth-file identity cannot be pinned across validation and launch")
    if (isolation_evidence.get("mechanism") == "sandbox-exec" and state_dir
            and any(Path(path).stat().st_dev == Path(state_dir).stat().st_dev
                    for path in auth_files)):
        limits.append("macOS auth files require a separate filesystem from writable state")
    if not model or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", model):
        limits.append(f"RELIABILITY_{host.upper()}_MODEL must name an explicit model ID")
    elif model in {"opus", "sonnet", "haiku", "fable", "default", "latest"}:
        limits.append("Model aliases are not frozen model identities")
    missing = [flag for flag in required if flag not in help_text]
    if missing:
        limits.append("Missing required CLI flags: " + ", ".join(missing))
    return {
        "schema_version": 1, "model": model or None,
        "executable_sha256": executable_sha256,
        "help_sha256": hashlib.sha256(help_text.encode()).hexdigest(),
        "effort": "medium" if host == "claude" else "high",
        "permissions": "dontAsk" if host == "claude" else "workspace-write",
        "settings": ({"setting_sources": "project,local", "settings": {
            "permissions": {"allow": ["Read", "Edit", "Write", "Bash"]}}}
            if host == "claude" else {"ignore_user_config": True, "ignore_rules": True,
                                     "approval_policy": "never"}),
        "isolation_supported": not limits, "unsupported_channels": limits,
        "isolation_evidence": isolation_evidence, "trace_channel": trace_channel,
        "auth_files": auth_files,
        "auth_file_sha256": auth_file_hashes,
        "state_dir": state_dir,
        "host": host,
        "startup_evidence": startup_evidence,
        "startup_evidence_sha256": startup_evidence_sha256,
    }


def inspect_host(host: str, timeout_seconds: float = 10) -> dict:
    """Read-only capability/profile probe; never authenticates or runs a task."""
    _validate_host(host)
    executable = shutil.which(host)
    result = {"host": host, "executable": executable, "version": None,
              "available": False, "error": None, "profile": None, "timed_out": False}
    if executable is None:
        result["error"] = f"{host} executable is unavailable"
        return result
    started = time.monotonic()
    try:
        probe = _probe([executable, "--version"], timeout_seconds=timeout_seconds)
        if probe.returncode:
            raise RuntimeError(f"{host} version probe exited {probe.returncode}")
        remaining = timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise subprocess.TimeoutExpired([executable, "--help"], timeout_seconds)
        help_probe = _probe([executable] + (["exec"] if host == "codex" else []) +
                            ["--help"], timeout_seconds=remaining)
        if help_probe.returncode:
            raise RuntimeError(f"{host} help probe exited {help_probe.returncode}")
        remaining = timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise subprocess.TimeoutExpired([executable, "isolation-canary"], timeout_seconds)
        result.update(available=True, version=probe.stdout.strip() or None,
                      profile=_profile(host, executable, help_probe.stdout, min(10, remaining)))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        result["error"] = f"{host} profile probe failed ({type(exc).__name__})"
        result["timed_out"] = isinstance(exc, subprocess.TimeoutExpired)
    return result


def build_command(host: str, fixture: Path, prompt: str,
                  plugin_roots: list[Path], trace_dir: Path) -> list[str]:
    """Build only commands whose explicit host profile passes isolation checks."""
    return _build_command(host, fixture, prompt, plugin_roots, probe_timeout=10)


def _build_command(host: str, fixture: Path, prompt: str,
                   plugin_roots: list[Path], probe_timeout: float,
                   expected_profile: dict | None = None) -> list[str]:
    return _launch(host, fixture, prompt, plugin_roots, probe_timeout, expected_profile)[0]


def _contain(argv: list[str], profile: dict, executable: str, fixture: Path,
             roots: list[Path]) -> list[str]:
    """Wrap a launch in the same kernel boundary the platform canary proved."""
    mechanism = (profile.get("isolation_evidence") or {}).get("mechanism")
    if mechanism not in ("bubblewrap", "sandbox-exec"):
        raise RuntimeError("Unknown host isolation mechanism")
    isolation = _isolation()
    resolved_executable = Path(executable).resolve()
    runtime_root = next((parent for parent in resolved_executable.parents
                         if str(parent) != "/"
                         and all((parent / name).is_dir() for name in ("bin", "lib"))),
                        resolved_executable.parent)
    auth_files = [Path(p) for p in profile.get("auth_files", [])]
    writable_dirs = ([Path(profile["state_dir"])]
                     if profile.get("state_dir") else [])
    if mechanism == "bubblewrap":
        bwrap = isolation.linux_executable()
        if bwrap is None:
            raise RuntimeError("Linux bubblewrap is unavailable at launch")
        return isolation.linux_argv(bwrap, fixture, [runtime_root], auth_files,
                                    roots, argv, writable_dirs=writable_dirs)
    sandbox = isolation.executable()
    if sandbox is None:
        raise RuntimeError("macOS sandbox-exec is unavailable at launch")
    return isolation.mac_argv(sandbox, fixture, [runtime_root], auth_files,
                              roots, argv, writable_dirs=writable_dirs)


def _launch(host: str, fixture: Path, prompt: str, plugin_roots: list[Path],
            probe_timeout: float, expected_profile: dict | None = None
            , allow_uncertified_probe: bool = False) -> tuple[list[str], dict]:
    _validate_host(host)
    fixture = _fixture_path(fixture)
    inspection = inspect_host(host, timeout_seconds=probe_timeout)
    if inspection["timed_out"]:
        raise subprocess.TimeoutExpired([host, "--help"], probe_timeout)
    if not inspection["available"]:
        raise RuntimeError(inspection["error"])
    profile = inspection["profile"]
    if expected_profile is not None and profile != expected_profile:
        raise RuntimeError("Frozen host profile drifted before launch")
    if not profile["isolation_supported"] and not allow_uncertified_probe:
        raise RuntimeError("Host isolation unavailable: " + "; ".join(profile["unsupported_channels"]))
    executable = inspection["executable"]
    roots = [Path(root).resolve() for root in plugin_roots]
    for root in roots:
        if not root.is_dir():
            raise FileNotFoundError(f"Plugin directory does not exist: {root}")
    if host == "claude":
        argv = [executable, "--print", "--verbose", "--output-format", "stream-json",
                "--no-session-persistence", "--strict-mcp-config", "--mcp-config",
                '{"mcpServers":{}}', "--setting-sources", profile["settings"]["setting_sources"],
                "--settings", json.dumps(profile["settings"]["settings"], sort_keys=True),
                "--model", profile["model"], "--effort", profile["effort"],
                "--permission-mode", profile["permissions"]]
        for root in roots:
            argv.extend(["--plugin-dir", str(root)])
        return _contain(argv + ["--", prompt], profile, executable, fixture, roots), profile
    argv = [executable, "exec", "--json", "--ephemeral", "--color", "never",
            "--ignore-user-config", "--ignore-rules", "--model", profile["model"],
            "--config", 'model_reasoning_effort="high"',
            "--config", 'approval_policy="never"',
            "--sandbox", profile["permissions"], "--cd", str(fixture)]
    if roots:
        prompt += ("\n\nUse the local plugin source directories below for this task. "
                   "Read the relevant SKILL.md and referenced files directly.\n" +
                   "\n".join(f"- {root}" for root in roots))
    return _contain(argv + ["--", prompt], profile, executable, fixture, roots), profile


_INFRA_ERROR = re.compile(
    r"not logged in|not authenticated|authentication (?:failed|required|error)|"
    r"invalid (?:api[ _-]?key|authentication|credentials)|"
    r"(?:api[ _-]?key|auth(?:entication)? token|access token).*(?:missing|expired|invalid)|"
    r"(?:missing|expired|invalid).*(?:api[ _-]?key|auth(?:entication)? token|access token)|"
    r"unauthorized|error (?:loading|parsing) (?:config|settings)|"
    r"(?:invalid|failed to (?:load|parse)) (?:configuration|config\.toml)|"
    r"unexpected argument|unrecognized (?:option|argument)|unknown option|"
    r"usage limit|rate limit|out of credits|resetsat",
    re.IGNORECASE,
)

_PLACEHOLDER_MODELS = frozenset({"<synthetic>", "synthetic", "unknown", "none"})


def _trace_metadata(stdout_path: Path, *, host: str | None = None,
                    launch_model: str | None = None) -> dict:
    metadata = {"observed_model": None, "usage": None, "failed": False,
                "infrastructure_failed": False, "command_receipts": [],
                "invalid_command_receipts": 0, "thread_started": False,
                "model_identity_source": None}
    with stdout_path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                event = strict_json_line(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "thread.started":
                metadata["thread_started"] = True
            if kind == "agentic.command.completed":
                try:
                    metadata["command_receipts"].append(command_receipt(event))
                except (TypeError, ValueError):
                    # A host trace is evidence input, not evidence itself. Keep
                    # malformed adapter output visible without trusting it.
                    metadata["invalid_command_receipts"] += 1
            # Read host metadata, never model-looking strings inside tool output.
            if kind in ("system", "session.started", "thread.started", "result", "turn.completed"):
                if (isinstance(event.get("model"), str)
                        and event["model"].strip().lower() not in _PLACEHOLDER_MODELS):
                    metadata["observed_model"] = event["model"]
            if kind in ("result", "turn.completed") and isinstance(event.get("usage"), dict):
                metadata["usage"] = event["usage"]
            if kind == "assistant" and isinstance(event.get("message"), dict):
                model = event["message"].get("model")
                if (isinstance(model, str)
                        and model.strip().lower() not in _PLACEHOLDER_MODELS):
                    metadata["observed_model"] = model
            failed = (kind in ("turn.failed", "error") or
                      (kind == "result" and event.get("is_error") is True)
                      or (kind == "rate_limit_event" and
                          str((event.get("rate_limit_info") or {}).get("status", "")).lower()
                          in {"rejected", "blocked"}))
            if failed:
                metadata["failed"] = True
                error = event.get("error", event.get("errors", event.get("result",
                                  event.get("message", event.get("rate_limit_info", "")))))
                if (kind == "rate_limit_event"
                        or event.get("api_error_status", event.get("error_status")) in (401, 403, 407)
                        or _INFRA_ERROR.search(json.dumps(error))):
                    metadata["infrastructure_failed"] = True
    # Codex CLI 0.155.1 does not include the selected model in JSON events.
    # Accept the frozen launch identity only when the host emitted a genuine
    # thread-start event and the adapter's explicit --model matches it. A
    # usage-only or fabricated trace remains without an identity.
    if (metadata["observed_model"] is None and host == "codex"
            and launch_model and metadata["thread_started"]):
        metadata["observed_model"] = launch_model
        metadata["model_identity_source"] = "frozen_launch_argument"
    try:
        if stdout_path.stat().st_size > MAX_TRACE_BYTES:
            raise ValueError("host trace exceeds tool event limit")
        native = extract_tool_events(stdout_path.read_text(encoding="utf-8", errors="replace"), host)
        metadata["tool_events"] = native["events"]
        metadata["tool_event_issues"] = native["issues"]
    except (OSError, ValueError, RecursionError) as exc:
        # An unusable stream never becomes positive tool evidence.
        metadata["tool_events"] = []
        metadata["tool_event_issues"] = [str(exc)]
    return metadata


def adapt_trace_receipts(stdout_path: Path, key: bytes | str, *, identity: str,
                         issued_at: float, expires_at: float) -> list[dict]:
    """Convert retained explicit host events into signed evidence receipts."""
    try:
        lines = Path(stdout_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise RuntimeError("host trace cannot be read") from exc
    return adapt_json_lines(lines, key, identity=identity,
                            issued_at=issued_at, expires_at=expires_at)


def ingest_adapted_receipts(store, receipts: list[dict], *, expected_revision: int,
                            lease_epoch: int, coordinator_id: str) -> dict:
    """Persist signed host receipts through the same fenced evidence path.

    The host runner retains raw output and adapts it separately so malformed or
    incomplete traces stay visible. Callers must explicitly choose to ingest
    the adapted receipts with the coordinator's current revision and lease.
    """
    if not isinstance(receipts, list):
        raise ValueError("adapted receipts must be a list")
    revision = expected_revision
    accepted = []
    for receipt in receipts:
        ingest_command_event(store, receipt, expected_revision=revision,
                             lease_epoch=lease_epoch,
                             coordinator_id=coordinator_id)
        revision = store.get_run(receipt["run_id"])["revision"]
        accepted.append(receipt["evidence_id"])
    return {"accepted": accepted, "revision": revision}


def _sign_launch(result: dict, host: str, profile: dict | None, fixture: Path,
                 repository: Path) -> None:
    """Sign only adapter-observed launch facts; unlaunched hosts get no receipt."""
    if profile is None or result["exit_code"] is None:
        result["isolation_receipt_error"] = "host was not launched"
        return
    isolation = _isolation()
    try:
        result["isolation_receipt"] = isolation.sign_command_receipt(
            key=isolation.host_key(), host=host, model=profile["model"], argv=result["argv"],
            exit_status=result["exit_code"], repository=isolation.repository_revision(repository),
            fixture=isolation.fixture_binding(fixture),
            isolation=profile.get("isolation_evidence") or {})
    except (OSError, RuntimeError, ValueError) as exc:
        result["isolation_receipt_error"] = str(exc)


def run_host(host: str, fixture: Path, prompt: str, plugin_roots: list[Path],
             trace_dir: Path, timeout_seconds: float = 900,
             checkpoint_path: Path | None = None,
             expected_profile: dict | None = None,
             evidence_key: bytes | str | None = None,
             evidence_identity: str | None = None,
             evidence_issued_at: float | None = None,
             evidence_expires_at: float | None = None,
             receipt_repository: Path | None = None,
             allow_uncertified_probe: bool = False) -> dict:
    """Run one host, retaining traces and optionally adapting signed evidence.

    Evidence adaptation is opt-in because the caller owns the host key and the
    assignment identity. Supplying only part of the evidence context is a
    configuration error and fails closed before the host process starts.
    With ``receipt_repository``, the adapter signs an isolation command receipt
    using AGENTIC_HOST_KEY, bound to that repository's revision and the fixture.
    """
    _validate_host(host)
    fixture = _fixture_path(fixture)
    evidence_context = (evidence_key is not None or evidence_identity is not None or
                        evidence_issued_at is not None or evidence_expires_at is not None)
    if evidence_context:
        if (evidence_key is None or not isinstance(evidence_identity, str) or
                not evidence_identity or not isinstance(evidence_issued_at, (int, float)) or
                not isinstance(evidence_expires_at, (int, float)) or
                not math.isfinite(float(evidence_issued_at)) or
                not math.isfinite(float(evidence_expires_at)) or
                float(evidence_expires_at) <= float(evidence_issued_at)):
            raise ValueError("complete, ordered evidence context is required")
    if checkpoint_path is not None:
        checkpoint_path = Path(checkpoint_path)
        if not checkpoint_path.is_absolute():
            checkpoint_path = fixture / checkpoint_path
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive and finite")
    if os.name != "posix":
        raise RuntimeError("Host runs require POSIX process-group cleanup")
    trace_dir = Path(trace_dir).resolve()
    trace_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    trace_dir.chmod(0o700)
    stdout_fd, stdout_name = tempfile.mkstemp(prefix=f"{host}-", suffix=".jsonl", dir=trace_dir)
    stderr_fd, stderr_name = tempfile.mkstemp(prefix=f"{host}-", suffix=".stderr", dir=trace_dir)
    result = {"host": host, "status": "infrastructure_failed", "exit_code": None,
              "elapsed_seconds": 0.0, "argv": [], "raw_stdout_path": stdout_name,
              "raw_stderr_path": stderr_name, "observed_model": None, "usage": None,
              "error": None, "checkpoint_observed": False}
    started = time.monotonic()
    process = None
    profile = None
    drain_threads: list[threading.Thread] = []
    host_ends: list[socket.socket] = []
    with os.fdopen(stdout_fd, "wb") as stdout, os.fdopen(stderr_fd, "wb") as stderr:
        try:
            result["argv"], profile = _launch(host, fixture, prompt, plugin_roots,
                                              probe_timeout=min(10, timeout_seconds),
                                              expected_profile=expected_profile,
                                              allow_uncertified_probe=allow_uncertified_probe)
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                result["status"] = "timed_out"
            else:
                # The host's stdout/stderr are one end of an AF_UNIX
                # socketpair, not a regular file: a same-user tool descendant
                # that tries to reopen the host's fd via /proc/<pid>/fd/N gets
                # ENXIO (a socket cannot be reopened by path). The parent
                # drains its end concurrently into the same retained trace
                # files a direct redirect would have produced.
                host_out, child_out = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
                host_ends = [host_out]
                try:
                    host_err, child_err = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
                except OSError:
                    child_out.close()
                    raise
                host_ends.append(host_err)
                try:
                    process = subprocess.Popen(result["argv"], cwd=fixture,
                                               stdin=subprocess.DEVNULL, stdout=child_out,
                                               stderr=child_err, start_new_session=True,
                                               env=_host_environment(profile))
                finally:
                    # This process's own copies keep the connection open even
                    # after the host exits; drop them so EOF reaches the
                    # drain threads once every holder of the fd is gone.
                    child_out.close()
                    child_err.close()
                cap = MAX_TRACE_BYTES + 1
                drain_threads = [
                    threading.Thread(target=_drain_socket, args=(host_out, stdout, cap), daemon=True),
                    threading.Thread(target=_drain_socket, args=(host_err, stderr, cap), daemon=True),
                ]
                for thread in drain_threads:
                    thread.start()
                while True:
                    if checkpoint_path is not None and checkpoint_path.is_file():
                        result.update(status="interrupted", checkpoint_observed=True)
                        break
                    if process.poll() is not None:
                        result["exit_code"] = process.returncode
                        result["status"] = "completed" if process.returncode == 0 else "product_failed"
                        break
                    remaining = timeout_seconds - (time.monotonic() - started)
                    if remaining <= 0:
                        result["status"] = "timed_out"
                        break
                    time.sleep(min(0.05, remaining))
        except subprocess.TimeoutExpired:
            result["status"] = ("timed_out" if time.monotonic() - started >= timeout_seconds
                                else "infrastructure_failed")
            result["error"] = "Host configuration probe timed out"
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            result["error"] = f"Host setup or execution failed: {exc}"
            # Only reachable before any drain thread exists (a pre-launch
            # configuration/probe failure): no concurrent writer to race.
            if not drain_threads:
                stderr.write((result["error"] + "\n").encode("utf-8", errors="replace"))
        finally:
            if process is not None:
                _cleanup(process)
                result["exit_code"] = process.returncode
            for thread in drain_threads:
                thread.join(timeout=5)
            for end in host_ends:
                try:
                    end.close()
                except OSError:
                    pass
    oversized = any(Path(name).stat().st_size > MAX_TRACE_BYTES
                    for name in (stdout_name, stderr_name))
    if oversized:
        # The drain stopped writing at the cap, so the retained trace is a
        # truncated prefix: never read it for identity, usage or receipts.
        result.update(status="infrastructure_failed", error="host trace exceeds size limit")
        metadata = {"observed_model": None, "usage": None, "failed": False,
                    "infrastructure_failed": True, "command_receipts": [],
                    "invalid_command_receipts": 0, "tool_events": [],
                    "tool_event_issues": ["host trace exceeds tool event limit"]}
    else:
        metadata = _trace_metadata(Path(stdout_name), host=host,
                                   launch_model=(profile or {}).get("model"))
    result.update(observed_model=metadata["observed_model"], usage=metadata["usage"],
                  command_receipts=metadata["command_receipts"],
                  invalid_command_receipts=metadata["invalid_command_receipts"],
                  tool_events=metadata["tool_events"],
                  tool_event_issues=metadata["tool_event_issues"])
    if evidence_context and oversized:
        result["adapted_receipts"] = []
        result["evidence_adapter_error"] = "host trace exceeds size limit"
    elif evidence_context:
        try:
            result["adapted_receipts"] = adapt_trace_receipts(
                Path(stdout_name), evidence_key, identity=evidence_identity,
                issued_at=float(evidence_issued_at), expires_at=float(evidence_expires_at))
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            result["adapted_receipts"] = []
            result["evidence_adapter_error"] = str(exc)
    if receipt_repository is not None:
        _sign_launch(result, host, profile, fixture, Path(receipt_repository))
    if result["status"] in ("completed", "product_failed"):
        if metadata["failed"]:
            result["status"] = "product_failed"
        with Path(stderr_name).open(encoding="utf-8", errors="replace") as stream:
            infra_stderr = any(_INFRA_ERROR.search(line) for line in stream)
        if metadata["infrastructure_failed"] or (result["exit_code"] != 0 and infra_stderr):
            result["status"] = "infrastructure_failed"
    result["elapsed_seconds"] = round(time.monotonic() - started, 6)
    return result
