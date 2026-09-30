"""Deterministic, journal-aware file installation primitives.

The installer owns mechanical file application only. Interviews, rendering
decisions, and stack-specific generation remain in skills; they pass the
resulting relative-path/content manifest to these operations.
"""

from __future__ import annotations

import hashlib
import errno
import json
import os
from pathlib import Path
import re
import secrets
import stat
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
from typing import Any, Mapping


JOURNAL_RELATIVE = Path(".agentic/agentic-os/install.json")
_VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
_BOUND_ROOT: ContextVar[dict[str, Any] | None] = ContextVar("installer_bound_root", default=None)


def _bind_root(operation):
    """Keep a stable directory identity through one mutating operation."""
    @wraps(operation)
    def bound(target, *args, **kwargs):
        root = _target(target)
        if _BOUND_ROOT.get() is not None:
            raise RuntimeError("nested installer mutations are unsupported")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(root, flags)
        token = _BOUND_ROOT.set({"root": root, "fd": fd,
                                 "identity": (os.fstat(fd).st_dev, os.fstat(fd).st_ino),
                                 "parents": {}})
        try:
            return operation(root, *args, **kwargs)
        finally:
            _BOUND_ROOT.reset(token)
            os.close(fd)
    return bound


_SPEC_KEYS = {"content", "owner", "template", "origin", "expect_sha256"}
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _valid_version(value: Any) -> bool:
    if not isinstance(value, str) or _VERSION.fullmatch(value) is None:
        return False
    prerelease = value.split("+", 1)[0].partition("-")[2]
    return all(not (part.isdigit() and len(part) > 1 and part[0] == "0")
               for part in prerelease.split(".") if part)


def merge_settings(base: Mapping[str, Any], fragment: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-merge a settings fragment without discarding user values.

    Objects merge recursively, arrays append only missing values, and scalar
    values already present in the user's settings win. Inputs are copied and
    validated so a caller cannot observe a partially mutated settings object.
    """
    if not isinstance(base, Mapping) or not isinstance(fragment, Mapping):
        raise ValueError("settings base and fragment must be objects")
    result = deepcopy(dict(base))

    def merge_object(destination: dict[str, Any], source: Mapping[str, Any]) -> None:
        for key, value in source.items():
            if not isinstance(key, str) or not key:
                raise ValueError("settings keys must be non-empty strings")
            if isinstance(value, Mapping):
                if key not in destination:
                    existing = {}
                    destination[key] = existing
                else:
                    existing = destination[key]
                if not isinstance(existing, dict):
                    raise ValueError("cannot merge an object into a non-object setting: " + key)
                merge_object(existing, value)
            elif isinstance(value, list):
                if key not in destination:
                    existing = []
                    destination[key] = existing
                else:
                    existing = destination[key]
                if not isinstance(existing, list):
                    raise ValueError("cannot merge an array into a non-array setting: " + key)
                for item in value:
                    copied = deepcopy(item)
                    if copied not in existing:
                        existing.append(copied)
            elif key not in destination:
                destination[key] = deepcopy(value)

    merge_object(result, fragment)
    return result


def _target(target: str | os.PathLike[str]) -> Path:
    path = Path(target).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("installation target must be an existing directory")
    return path


def _relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("installation paths must be non-empty POSIX-relative strings")
    path = Path(value)
    if (not path.parts or path.is_absolute() or path.as_posix() != value
            or any(part in ("", ".", "..") for part in path.parts)):
        raise ValueError("installation path escapes the target")
    journal = JOURNAL_RELATIVE.as_posix()
    if value == journal or journal.startswith(value + "/") or value.startswith(journal + "/"):
        raise ValueError("the install journal path is owned by the installer")
    return path.as_posix()


def _reject_path_collisions(paths: Mapping[str, Any]) -> None:
    for relative in paths:
        parts = Path(relative).parts
        if any("/".join(parts[:index]) in paths for index in range(1, len(parts))):
            raise ValueError("installation paths contain ancestor collisions")


def _destination(root: Path, relative: str) -> Path:
    """Reject symlink traversal in an installation path, including the leaf."""
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("installation path traverses a symlink: " + relative)
        if path != root / relative and path.exists() and not path.is_dir():
            raise ValueError("installation path has a non-directory parent: " + relative)
    return path


@contextmanager
def _parent_fd(root: Path, relative: str, *, create: bool = False):
    """Hold directory handles and reject changed root/ancestor identities."""
    if (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
            or not hasattr(os, "O_NONBLOCK")
            or any(operation not in os.supports_dir_fd
                   for operation in (os.open, os.mkdir, os.stat, os.unlink, os.rename, os.link))
            or os.stat not in os.supports_follow_symlinks):
        raise RuntimeError("safe installer directory handles are unavailable")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if relative != JOURNAL_RELATIVE.as_posix():
        _relative_path(relative)
    binding = _BOUND_ROOT.get()
    if binding is not None:
        if binding["root"] != root:
            raise RuntimeError("installer target changed during operation")
        try:
            current_root = os.stat(root, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise RuntimeError("installer target changed during operation") from exc
        if (current_root.st_dev, current_root.st_ino) != binding["identity"]:
            raise RuntimeError("installer target changed during operation")
        fd = os.dup(binding["fd"])
    else:
        fd = os.open(root, flags)
    try:
        for index, component in enumerate(Path(relative).parts[:-1]):
            prefix = "/".join(Path(relative).parts[:index + 1])
            expected = binding["parents"].get(prefix, ...) if binding is not None else ...
            created = False
            try:
                child = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                if binding is not None and expected is ...:
                    binding["parents"][prefix] = None
                if not create:
                    raise
                os.mkdir(component, dir_fd=fd)
                os.fsync(fd)
                child = os.open(component, flags, dir_fd=fd)
                created = True
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise ValueError("installation path traverses a symlink or non-directory: " + relative) from exc
                raise
            identity = (os.fstat(child).st_dev, os.fstat(child).st_ino)
            if binding is not None:
                if (expected is None and not created) or (expected is not ... and expected is not None and expected != identity):
                    os.close(child)
                    raise RuntimeError("installation parent changed after validation: " + relative)
                binding["parents"][prefix] = identity
            os.close(fd)
            fd = child
        yield fd, Path(relative).name
    finally:
        os.close(fd)


def _manifest(files: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(files, Mapping) or not files:
        raise ValueError("installation files must be a non-empty object")
    result: dict[str, dict[str, Any]] = {}
    for raw_path, raw_spec in files.items():
        path = _relative_path(raw_path)
        if isinstance(raw_spec, str):
            spec = {"content": raw_spec}
        elif isinstance(raw_spec, Mapping):
            spec = dict(raw_spec)
        else:
            raise ValueError("installation file spec must be a string or object")
        unknown = set(spec) - _SPEC_KEYS
        if unknown:
            raise ValueError("unknown installation file field: " + ", ".join(sorted(map(str, unknown))))
        content = spec.get("content")
        if not isinstance(content, str):
            raise ValueError("installation file content must be text")
        expected = spec.get("expect_sha256")
        if expected is not None and not _is_sha256(expected):
            raise ValueError("expect_sha256 must be a lowercase SHA-256 digest")
        # A confirmation authorizes replacing reviewed bytes, not claiming the
        # file for later unattended removal; ownership must then be stated.
        owner = spec.get("owner", "user" if expected is not None else "managed")
        if owner not in {"managed", "user", "generated"}:
            raise ValueError("unknown installation owner")
        template = spec.get("template", "derived")
        origin = spec.get("origin", "plugin")
        if (not isinstance(template, str) or not template
                or not isinstance(origin, str) or not origin):
            raise ValueError("installation template and origin must be non-empty strings")
        result[path] = {
            "content": content,
            "owner": owner,
            "template": template,
            "origin": origin,
            "expect_sha256": expected,
        }
    _reject_path_collisions(result)
    return dict(sorted(result.items()))


def _read_file(root: Path, relative: str) -> bytes | None:
    try:
        with _parent_fd(root, relative) as (parent, leaf):
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=parent)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError("installation source is not a regular file: " + relative)
                with os.fdopen(fd, "rb") as stream:
                    fd = -1
                    return stream.read()
            finally:
                if fd >= 0:
                    os.close(fd)
    except FileNotFoundError:
        return None


def _entry_snapshot(parent: int, leaf: str) -> tuple[str, int, int, int] | None:
    try:
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=parent)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("installation source is not a regular file: " + leaf)
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest(), info.st_dev, info.st_ino, info.st_mtime_ns
    finally:
        if fd >= 0:
            os.close(fd)


def _snapshot(root: Path, relative: str) -> tuple[str, int, int, int] | None:
    try:
        with _parent_fd(root, relative) as (parent, leaf):
            return _entry_snapshot(parent, leaf)
    except FileNotFoundError:
        return None


def _sha(root: Path, relative: str) -> str | None:
    snapshot = _snapshot(root, relative)
    return snapshot[0] if snapshot is not None else None


def _identity_matches(entry: Mapping[str, Any], snapshot: tuple[str, int, int, int] | None) -> bool:
    return (snapshot is not None and entry.get("device") == snapshot[1]
            and entry.get("inode") == snapshot[2]
            and entry.get("mtime_ns") == snapshot[3])


def _record_identity(entry: dict[str, Any], snapshot: tuple[str, int, int, int]) -> None:
    entry["device"], entry["inode"], entry["mtime_ns"] = snapshot[1:]


def _finite_float(value: str) -> float:
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("install journal contains a non-finite number: " + value)
    return number


def _reject_constant(value: str) -> None:
    raise ValueError("install journal contains a non-standard JSON constant: " + value)


def _journal(target: Path) -> tuple[dict[str, Any], Path, tuple[str, int, int, int] | None]:
    path = _destination(target, JOURNAL_RELATIVE.as_posix())
    try:
        with _parent_fd(target, JOURNAL_RELATIVE.as_posix()) as (parent, leaf):
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=parent)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    raise RuntimeError("install journal is not a regular file")
                with os.fdopen(fd, "rb") as stream:
                    fd = -1
                    data = stream.read()
                    value = json.loads(data, parse_constant=_reject_constant,
                                       parse_float=_finite_float)
                    snapshot = hashlib.sha256(data).hexdigest(), info.st_dev, info.st_ino, info.st_mtime_ns
            finally:
                if fd >= 0:
                    os.close(fd)
    except FileNotFoundError:
        return {}, path, None
    except (OSError, ValueError, UnicodeError) as exc:
        raise RuntimeError("install journal is unreadable") from exc
    if not isinstance(value, dict):
        raise RuntimeError("install journal must be an object")
    if "files" in value and not isinstance(value["files"], dict):
        raise RuntimeError("install journal files must be an object")
    if "agentic_os_version" in value and not _valid_version(value["agentic_os_version"]):
        raise RuntimeError("install journal has an invalid agentic_os_version")
    if "phase" in value and value["phase"] not in {
            "preflight", "interview", "dependencies", "scaffold", "generate", "verify", "done"}:
        raise RuntimeError("install journal has an invalid phase")
    for relative, entry in value.get("files", {}).items():
        _relative_path(relative)
        if (not isinstance(entry, dict) or entry.get("owner") not in {"managed", "user", "generated"}
                or not isinstance(entry.get("sha256"), str)
                or len(entry["sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in entry["sha256"])):
            raise RuntimeError("install journal contains an invalid file entry")
        if (("device" in entry) != ("inode" in entry)
                or ("device" in entry and
                    (type(entry["device"]) is not int or entry["device"] < 0
                     or type(entry["inode"]) is not int or entry["inode"] < 0))):
            raise RuntimeError("install journal contains an invalid file identity")
        if ("mtime_ns" in entry and
                ("device" not in entry or type(entry["mtime_ns"]) is not int
                 or entry["mtime_ns"] < 0)):
            raise RuntimeError("install journal contains an invalid file modification time")
        if any(key in entry and (not isinstance(entry[key], str) or not entry[key])
               for key in ("template", "origin")):
            raise RuntimeError("install journal contains invalid file metadata")
    _reject_path_collisions(value.get("files", {}))
    return value, path, snapshot


def _journal_entry_state(root: Path, relative: str, old: Any, new: Any) -> str:
    """Classify a failed journal write without trusting its exception timing."""
    try:
        current, _, _ = _journal(root)
        entry = current.get("files", {}).get(relative)
    except Exception:
        return "unknown"
    if entry == new:
        return "new"
    if entry == old:
        return "old"
    return "unknown"


def _atomic_write(root: Path, relative: str, content: str, *, prefix: str,
                  expected: tuple[str, int, int, int] | None | object = ...) -> tuple[str, int, int, int]:
    with _parent_fd(root, relative, create=True) as (parent, leaf):
        temporary = prefix + secrets.token_hex(12)
        original_link = None
        # A replacement keeps the destination's permission bits, so an
        # executable script stays executable; a new file follows the caller's
        # umask instead of being forced to owner-only.
        try:
            existing = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            mode = (stat.S_IMODE(existing.st_mode) & ~(stat.S_ISUID | stat.S_ISGID)
                    if stat.S_ISREG(existing.st_mode) else None)
        except FileNotFoundError:
            mode = None
        if relative == JOURNAL_RELATIVE.as_posix():
            # The journal decides which files an unattended removal may delete,
            # so it is re-hardened on every write rather than inheriting a mode.
            mode = 0o600
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600 if mode is not None else 0o666, dir_fd=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                if mode is not None:
                    # Widened only after the bytes are written, never before.
                    os.fchmod(stream.fileno(), mode)
                os.fsync(stream.fileno())
                info = os.fstat(stream.fileno())
            current = _entry_snapshot(parent, leaf)
            if expected is not ... and current != expected:
                raise RuntimeError("installation destination changed after validation: " + relative)
            if current is not None:
                original_link = ".install-before." + secrets.token_hex(12)
                os.link(leaf, original_link, src_dir_fd=parent, dst_dir_fd=parent,
                        follow_symlinks=False)
                if _entry_snapshot(parent, original_link) != current:
                    raise RuntimeError("installation destination changed before rename: " + relative)
            os.rename(temporary, leaf, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
            try:
                with _parent_fd(root, relative) as (reachable, _):
                    if (os.fstat(reachable).st_dev, os.fstat(reachable).st_ino) != (
                            os.fstat(parent).st_dev, os.fstat(parent).st_ino):
                        raise RuntimeError("installation parent moved during write: " + relative)
            except Exception:
                written = _entry_snapshot(parent, leaf)
                if written is not None and written[1:3] == (info.st_dev, info.st_ino):
                    if original_link is None:
                        os.unlink(leaf, dir_fd=parent)
                    else:
                        os.rename(original_link, leaf, src_dir_fd=parent, dst_dir_fd=parent)
                        original_link = None
                    os.fsync(parent)
                raise
            return hashlib.sha256(content.encode("utf-8")).hexdigest(), info.st_dev, info.st_ino, info.st_mtime_ns
        finally:
            if original_link is not None:
                os.unlink(original_link, dir_fd=parent)
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


def _unlink(root: Path, relative: str, *, expected: tuple[str, int, int, int]) -> None:
    with _parent_fd(root, relative) as (parent, leaf):
        if _entry_snapshot(parent, leaf) != expected:
            raise RuntimeError("installation destination changed after validation: " + relative)
        original_link = ".install-before." + secrets.token_hex(12)
        os.link(leaf, original_link, src_dir_fd=parent, dst_dir_fd=parent,
                follow_symlinks=False)
        try:
            if _entry_snapshot(parent, original_link) != expected:
                raise RuntimeError("installation destination changed before deletion: " + relative)
            os.unlink(leaf, dir_fd=parent)
            os.fsync(parent)
            try:
                with _parent_fd(root, relative) as (reachable, _):
                    if (os.fstat(reachable).st_dev, os.fstat(reachable).st_ino) != (
                            os.fstat(parent).st_dev, os.fstat(parent).st_ino):
                        raise RuntimeError("installation parent moved during deletion: " + relative)
            except Exception:
                if _entry_snapshot(parent, leaf) is None:
                    os.rename(original_link, leaf, src_dir_fd=parent, dst_dir_fd=parent)
                    original_link = None
                    os.fsync(parent)
                raise
        finally:
            if original_link is not None:
                os.unlink(original_link, dir_fd=parent)


def _backup_file(root: Path, relative: str,
                 expected: tuple[str, int, int, int] | None) -> str | None:
    """Hold the original inode for conditional rollback across journal failure."""
    if expected is None:
        return None
    with _parent_fd(root, relative) as (parent, leaf):
        backup = ".install-backup." + secrets.token_hex(12)
        os.link(leaf, backup, src_dir_fd=parent, dst_dir_fd=parent,
                follow_symlinks=False)
        try:
            if _entry_snapshot(parent, backup) != expected:
                raise RuntimeError("installation source changed before backup: " + relative)
            return backup
        except Exception:
            os.unlink(backup, dir_fd=parent)
            raise


def _discard_backup(root: Path, relative: str, backup: str | None) -> None:
    if backup is None:
        return
    with _parent_fd(root, relative) as (parent, _):
        try:
            os.unlink(backup, dir_fd=parent)
        except FileNotFoundError:
            return
        os.fsync(parent)


def _restore_file(root: Path, relative: str, before: bytes | None,
                  after: tuple[str, int, int, int] | None,
                  backup: str | None = None) -> None:
    """Undo a file effect only while its exact post-write identity remains."""
    if before is None:
        if after is not None:
            _unlink(root, relative, expected=after)
    elif backup is not None:
        with _parent_fd(root, relative) as (parent, leaf):
            if _entry_snapshot(parent, leaf) != after:
                raise RuntimeError("installation destination changed before rollback: " + relative)
            os.rename(backup, leaf, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
    else:
        _atomic_write(root, relative, before.decode("utf-8"),
                      prefix=".install-rollback.", expected=after)


@_bind_root
def merge_settings_file(target: str | os.PathLike[str], relative_path: str,
                        fragment: Mapping[str, Any], *,
                        agentic_os_version: str | None = None) -> dict[str, Any]:
    """Merge a JSON settings fragment and journal the resulting managed file."""
    root = _target(target)
    relative = _relative_path(relative_path)
    destination = _destination(root, relative)
    journal, journal_path, journal_snapshot = _journal(root)
    if agentic_os_version is not None and not _valid_version(agentic_os_version):
        raise ValueError("agentic_os_version must be a semantic version")
    before_bytes = _read_file(root, relative)
    before_hash = hashlib.sha256(before_bytes).hexdigest() if before_bytes is not None else None
    before_snapshot = _snapshot(root, relative)
    if (before_snapshot[0] if before_snapshot else None) != before_hash:
        raise RuntimeError("settings changed during merge planning")
    if before_bytes is not None:
        try:
            current = json.loads(before_bytes.decode("utf-8"), parse_constant=_reject_constant)
        except (OSError, ValueError, UnicodeError) as exc:
            raise RuntimeError("settings file is unreadable or invalid JSON") from exc
        if not isinstance(current, dict):
            raise RuntimeError("settings file must contain a JSON object")
    else:
        current = {}
    merged = merge_settings(current, fragment)
    try:
        content = json.dumps(merged, ensure_ascii=False, sort_keys=True, indent=2,
                             allow_nan=False) + "\n"
    except ValueError as exc:
        raise ValueError("settings must be standard JSON") from exc
    desired_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    changed = before_hash != desired_hash
    written_snapshot = None
    backup = _backup_file(root, relative, before_snapshot) if changed else None
    if changed:
        try:
            written_snapshot = _atomic_write(root, relative, content, prefix=f".{destination.name}.",
                                             expected=before_snapshot)
        except Exception:
            try:
                current = _snapshot(root, relative)
                if current is not None and current[0] == desired_hash and current != before_snapshot:
                    _restore_file(root, relative, before_bytes, current, backup)
            finally:
                _discard_backup(root, relative, backup)
            raise

    files = dict(journal.get("files", {}))
    previous = files.get(relative)
    owned = (before_hash is None or
             (isinstance(previous, Mapping) and previous.get("owner") == "managed"
              and previous.get("sha256") == before_hash
              and _identity_matches(previous, before_snapshot)))
    files[relative] = {"sha256": desired_hash, "template": "settings-merge",
                       "owner": "managed" if owned else "user",
                       "origin": "installer" if owned else "adopted-existing"}
    final_snapshot = written_snapshot if changed else before_snapshot
    if final_snapshot is not None:
        _record_identity(files[relative], final_snapshot)
    updated = dict(journal)
    if agentic_os_version is not None:
        updated["agentic_os_version"] = agentic_os_version
    updated["phase"] = updated.get("phase", "scaffold")
    updated["files"] = dict(sorted(files.items()))
    try:
        _atomic_write(root, JOURNAL_RELATIVE.as_posix(), json.dumps(updated, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
                      prefix=".settings-journal.", expected=journal_snapshot)
    except Exception:
        if changed and _journal_entry_state(root, relative,
                journal.get("files", {}).get(relative), files[relative]) == "old":
            _restore_file(root, relative, before_bytes, written_snapshot, backup)
        raise
    finally:
        _discard_backup(root, relative, backup)
    return {"schema": 1, "target": str(root), "path": relative,
            "journal": str(journal_path), "changed": changed,
            "before_sha256": before_hash, "after_sha256": desired_hash}


def plan_install(target: str | os.PathLike[str], files: Mapping[str, Any]) -> dict[str, Any]:
    """Return deterministic create/replace/preserve actions without writing."""
    root = _target(target)
    manifest = _manifest(files)
    journal, journal_path, _ = _journal(root)
    journal_files = journal.get("files", {})
    actions = []
    for relative, spec in manifest.items():
        destination = _destination(root, relative)
        desired = hashlib.sha256(spec["content"].encode("utf-8")).hexdigest()
        current_snapshot = _snapshot(root, relative)
        current = current_snapshot[0] if current_snapshot else None
        previous = journal_files.get(relative, {})
        prior_owned = (isinstance(previous, Mapping) and
                       previous.get("owner") in {"managed", "generated"})
        identity_matches = prior_owned and _identity_matches(previous, current_snapshot)
        managed_unchanged = (current is not None and isinstance(previous, Mapping) and
                             previous.get("sha256") == current and
                             previous.get("owner") == "managed" and identity_matches)
        if spec["expect_sha256"] is not None:
            # An operator confirmed these exact bytes. The confirmation is a
            # compare-and-swap: it authorizes replacing that content only.
            if current != spec["expect_sha256"]:
                action = "stale_confirmation"
            elif current == desired:
                action = "unchanged"
            else:
                action = "replace_confirmed"
        elif current is None:
            action = "create"
        elif prior_owned and not identity_matches:
            action = "preserve_modified"
        elif current == desired:
            action = "unchanged"
        elif managed_unchanged:
            action = "replace"
        else:
            action = "preserve_modified"
        actions.append({"path": relative, "action": action,
                        "current_sha256": current, "desired_sha256": desired,
                        "owner": spec["owner"]})
    return {"schema": 1, "target": str(root), "journal": str(journal_path),
            "actions": actions}


@_bind_root
def apply_install(target: str | os.PathLike[str], files: Mapping[str, Any], *,
                  agentic_os_version: str | None = None) -> dict[str, Any]:
    """Apply safe actions atomically and update the install journal.

    The plan is recomputed immediately before writes, so a caller cannot apply
    a stale decision after a user changes a file.
    """
    root = _target(target)
    manifest = _manifest(files)
    if agentic_os_version is not None and not _valid_version(agentic_os_version):
        raise ValueError("agentic_os_version must be a semantic version")
    journal, journal_path, journal_snapshot = _journal(root)
    before = {relative: _snapshot(root, relative) for relative in manifest}
    plan = plan_install(root, manifest)
    _, _, current_journal_snapshot = _journal(root)
    if current_journal_snapshot != journal_snapshot:
        raise RuntimeError("install journal changed during planning")
    stale = [item["path"] for item in plan["actions"] if item["action"] == "stale_confirmation"]
    if stale:
        raise RuntimeError("confirmed file changed since it was reviewed: " + ", ".join(stale))
    for relative, spec in manifest.items():
        prior = journal.get("files", {}).get(relative)
        if spec["expect_sha256"] is not None and spec["owner"] in {"managed", "generated"}:
            # A confirmation cannot raise ownership; it may only keep the owner
            # the journal already records for this path.
            if not (isinstance(prior, Mapping) and prior.get("owner") == spec["owner"]):
                raise RuntimeError("a confirmation cannot claim managed or generated ownership: " + relative)
    journal_files = dict(journal.get("files", {}))
    applied = []
    preserved = []
    updated = dict(journal)
    if agentic_os_version is not None:
        updated["agentic_os_version"] = agentic_os_version
    updated["phase"] = updated.get("phase", "scaffold")
    for action in plan["actions"]:
        relative = action["path"]
        spec = manifest[relative]
        prior_entry = deepcopy(journal_files.get(relative))
        destination = _destination(root, relative)
        if _snapshot(root, relative) != before[relative]:
            raise RuntimeError("installation destination changed during planning: " + relative)
        before_bytes = None
        written_snapshot = None
        backup = None
        if action["action"] in {"create", "replace", "replace_confirmed"}:
            before_bytes = _read_file(root, relative)
            backup = _backup_file(root, relative, before[relative])
            try:
                written_snapshot = _atomic_write(root, relative, spec["content"], prefix=f".{destination.name}.",
                                                 expected=before[relative])
            except Exception:
                try:
                    current = _snapshot(root, relative)
                    if current is not None and current[0] == action["desired_sha256"] and current != before[relative]:
                        _restore_file(root, relative, before_bytes, current, backup)
                finally:
                    _discard_backup(root, relative, backup)
                raise
        elif action["action"] == "preserve_modified":
            preserved.append(relative)
        if action["action"] != "preserve_modified":
            previous = journal_files.get(relative)
            if action["action"] == "unchanged" and not isinstance(previous, Mapping):
                journal_files[relative] = {
                    "sha256": action["desired_sha256"], "template": "adopted",
                    "owner": "user", "origin": "adopted-existing",
                }
            elif action["action"] == "unchanged" and isinstance(previous, Mapping):
                journal_files[relative] = dict(previous)
            else:
                origin = spec["origin"]
                if action["action"] == "replace_confirmed" and spec["owner"] == "user":
                    # A reviewed replacement of a pre-existing file keeps its
                    # adopted origin, so it is never deletable by the installer.
                    origin = (previous.get("origin", "adopted-existing")
                              if isinstance(previous, Mapping) else "adopted-existing")
                journal_files[relative] = {
                    "sha256": action["desired_sha256"], "template": spec["template"],
                    "owner": spec["owner"], "origin": origin,
                }
                snapshot = written_snapshot or before[relative]
                if snapshot is not None:
                    _record_identity(journal_files[relative], snapshot)
        elif relative in journal_files:
            previous = dict(journal_files[relative])
            adopted = _adopted(previous)
            previous["sha256"] = action["current_sha256"]
            previous["owner"] = "user"
            # Only a file agentic-os wrote becomes "user-modified"; a file that
            # existed before agentic-os keeps its adopted origin.
            previous["origin"] = "adopted-existing" if adopted else "user-modified"
            snapshot = before[relative]
            if snapshot is not None:
                _record_identity(previous, snapshot)
            journal_files[relative] = previous
        else:
            journal_files[relative] = {
                "sha256": action["current_sha256"], "template": "adopted",
                "owner": "user", "origin": "adopted-existing",
            }
        updated["files"] = dict(sorted(journal_files.items()))
        try:
            journal_snapshot = _atomic_write(root, JOURNAL_RELATIVE.as_posix(),
                      json.dumps(updated, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
                      prefix=".install.", expected=journal_snapshot)
        except Exception:
            if written_snapshot is not None and _journal_entry_state(
                    root, relative, prior_entry, journal_files[relative]) == "old":
                _restore_file(root, relative, before_bytes, written_snapshot, backup)
            raise
        finally:
            _discard_backup(root, relative, backup)
        if written_snapshot is not None:
            applied.append(relative)
    return {"schema": 1, "target": str(root), "journal": str(journal_path),
            "applied": applied, "preserved": preserved,
            "actions": plan["actions"]}


def _adopted(entry: Mapping[str, Any]) -> bool:
    """A file that existed before agentic-os, which the installer never deletes."""
    origin = entry.get("origin")
    return origin == "adopted-existing" or (origin is None and entry.get("owner") == "user")


def _leaf_absent(root: Path, relative: str) -> bool:
    """True only when the parent directory is reachable and the leaf is absent."""
    try:
        with _parent_fd(root, relative) as (parent, leaf):
            try:
                os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return True
            return False
    except (FileNotFoundError, ValueError):
        return False


@_bind_root
def remove_install(target: str | os.PathLike[str], paths: list[str] | None = None, *,
                   confirm: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Remove unchanged managed files; retain generated and user-owned files.

    ``confirm`` maps a journaled path to the SHA-256 of the exact bytes an
    operator agreed to delete; the path is removed only while those bytes are
    present. Files that existed before agentic-os (``origin: adopted-existing``)
    never accept a confirmation. A managed or generated entry is dropped when
    its file is absent from a reachable directory.
    """
    root = _target(target)
    journal, journal_path, journal_snapshot = _journal(root)
    entries = journal.get("files", {})
    if not isinstance(entries, dict):
        raise RuntimeError("install journal files must be an object")
    if paths is not None and (not isinstance(paths, list) or
                              not all(isinstance(item, str) for item in paths)):
        raise ValueError("install.remove paths must be a list of strings")
    selected = sorted(entries) if paths is None else sorted({_relative_path(item) for item in paths})
    if confirm is None:
        confirm = {}
    if (not isinstance(confirm, Mapping)
            or not all(isinstance(key, str) and _is_sha256(value)
                       for key, value in confirm.items())):
        raise ValueError("install.remove confirm must map paths to SHA-256 digests")
    normalized = {_relative_path(key): value for key, value in confirm.items()}
    if len(normalized) != len(confirm):
        raise ValueError("install.remove confirmation names the same path twice")
    confirm = normalized
    if not set(confirm) <= set(selected):
        raise ValueError("install.remove confirmation names an unselected path")
    destinations = {relative: _destination(root, relative) for relative in selected}
    before_all = {relative: _snapshot(root, relative) for relative in selected}
    for relative, digest in confirm.items():
        entry = entries.get(relative)
        if not isinstance(entry, Mapping):
            raise ValueError("removal confirmation names a path that is not journaled: " + relative)
        if _adopted(entry):
            raise ValueError("files that existed before agentic-os do not accept a removal confirmation: " + relative)
        if before_all[relative] is not None and before_all[relative][0] != digest:
            raise RuntimeError("confirmed file changed since it was reviewed: " + relative)
    removed, preserved, missing = [], [], []
    updated_files = dict(entries)
    updated = dict(journal)
    for relative in selected:
        entry = entries.get(relative)
        if not isinstance(entry, Mapping):
            continue
        destination = destinations[relative]
        before = before_all[relative]
        current = before[0] if before is not None else None
        removed_bytes = None
        backup = None
        identity_matches = _identity_matches(entry, before)
        if before is None:
            if entry.get("owner") in {"managed", "generated"} and _leaf_absent(root, relative):
                missing.append(relative)
                updated_files.pop(relative, None)
            else:
                # User records, and any record whose directory is unreachable
                # (for example moved aside), keep their ownership history.
                preserved.append(relative)
        elif ((current == entry.get("sha256") and entry.get("owner") == "managed"
               and identity_matches)
              or confirm.get(relative) == current):
            if before is None or before[0] != current:
                raise RuntimeError("installation destination changed during uninstall: " + relative)
            removed_bytes = _read_file(root, relative)
            backup = _backup_file(root, relative, before)
            try:
                _unlink(root, relative, expected=before)
            except Exception:
                try:
                    if _snapshot(root, relative) is None:
                        _restore_file(root, relative, removed_bytes, None, backup)
                finally:
                    _discard_backup(root, relative, backup)
                raise
            removed.append(relative)
            updated_files.pop(relative, None)
        else:
            preserved.append(relative)
            retained = dict(entry)
            retained["owner"] = "generated" if entry.get("owner") == "generated" else "user"
            # A managed or generated entry was written by agentic-os even when
            # an older journal omitted its origin; only user entries default to
            # "adopted-existing".
            retained["origin"] = retained.get(
                "origin", "adopted-existing" if entry.get("owner") == "user" else "user-modified")
            if retained["owner"] == "user" and before is not None:
                # The journal describes disk: a kept user file records the bytes
                # and identity actually present. A kept generated file keeps its
                # recorded hash so the user's edit stays detectable.
                retained["sha256"] = before[0]
                _record_identity(retained, before)
            updated_files[relative] = retained
        updated["files"] = dict(sorted(updated_files.items()))
        try:
            journal_snapshot = _atomic_write(root, JOURNAL_RELATIVE.as_posix(),
                      json.dumps(updated, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
                      prefix=".uninstall.", expected=journal_snapshot)
        except Exception:
            if removed_bytes is not None and _journal_entry_state(
                    root, relative, entry, updated_files.get(relative)) == "old":
                _restore_file(root, relative, removed_bytes, None, backup)
            raise
        finally:
            _discard_backup(root, relative, backup)
    return {"schema": 1, "target": str(root), "journal": str(journal_path),
            "removed": removed, "preserved": preserved, "missing": missing,
            "unapplied_confirmations": sorted(set(confirm) - set(removed))}


_RECORD_OBJECTS = {"answers", "stack_discovery", "adoption"}
_RECORD_LISTS = {"follow_ups", "sdlc_skills", "qe_blueprints"}
_RECORD_PHASES = {"preflight", "interview", "dependencies", "scaffold", "generate", "verify", "done"}
_RECORD_LIMIT = 1_000_000


@_bind_root
def record_journal(target: str | os.PathLike[str], fields: Mapping[str, Any]) -> dict[str, Any]:
    """Replace named top-level install-journal fields.

    Skills record interview answers, discovery results and progress here rather
    than editing ``install.json``. The ``files`` map is never accepted: file
    entries change only through apply, merge and remove, which bind them to the
    bytes and identity actually on disk.
    """
    root = _target(target)
    if not isinstance(fields, Mapping) or not fields:
        raise ValueError("journal fields must be a non-empty object")
    for key, value in fields.items():
        if key in _RECORD_OBJECTS:
            valid = isinstance(value, Mapping)
        elif key in _RECORD_LISTS:
            valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
        elif key == "phase":
            valid = value in _RECORD_PHASES
        elif key == "agentic_os_version":
            valid = _valid_version(value)
        else:
            raise ValueError("journal field is not recordable: " + str(key))
        if not valid:
            raise ValueError("journal field has an invalid value: " + key)
    try:
        encoded = json.dumps(fields, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("journal fields must be standard JSON") from exc
    if len(encoded) > _RECORD_LIMIT:
        raise ValueError("journal fields exceed the size limit")
    journal, journal_path, journal_snapshot = _journal(root)
    updated = dict(journal)
    updated.update(deepcopy(dict(fields)))
    _atomic_write(root, JOURNAL_RELATIVE.as_posix(),
                  json.dumps(updated, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
                  prefix=".record.", expected=journal_snapshot)
    return {"schema": 1, "target": str(root), "journal": str(journal_path),
            "recorded": sorted(fields)}
