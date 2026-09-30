#!/usr/bin/env python3
"""Reference executor of agentic-uninstall (deterministic convergence only).

The acceptance harness's stand-in for a human/agent following
plugins/agentic-os/skills/agentic-uninstall/SKILL.md by hand. Like refinstall.py
for init, this is the executable proof that the spec is followable: if a step
here cannot be derived from the SKILL.md, that is a harness finding.

HOW DESIRED STATE IS COMPUTED. The spec defines uninstall as "recompute what an
install of the remaining presets would produce, then converge to it". This
executor takes that literally: it runs refinstall.py into a scratch directory
for the remaining union and uses the result as the desired state. That is a
harness shortcut, not a claim about a real implementation, and it is sound for
what T9 asserts -- rendering correctness is already covered by T1-T8, whereas
every failure mode unique to *removal* (files not deleted, journal entries left
behind, settings still wired to a deleted script, the repo's own git hook not
restored, a user-edited file destroyed) still shows up as a tree difference
against an independently built install of the remaining roles.

What this executor deliberately does NOT model:
  * Phase 5 generation (refinstall skips it too), so gen/* slots never appear.
  * The interactive triples. --assume-keep / --assume-delete stand in for the
    human, mirroring refinstall.py's COLLISION-skip convention.
  * The HITL re-ask. The journaled HITL_MODE answer is carried through
    unchanged, which is the "keep the journaled answer" branch of the spec.

Usage: refuninstall.py <PLUGIN_ROOT> <TARGET_REPO> --remove qa[,devops]
                       [--all] [--assume-keep|--assume-delete] [--dry-run]
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import subprocess as sp
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT: Path | None = None
# The governance block the installer merges into CLAUDE.md (any version stamp).
BLOCK = re.compile(r"\n*<!-- agentic-os:begin v[^>]*-->.*?<!-- agentic-os:end -->\n?", re.S)


def runtime(operation: str, **fields) -> dict:
    """Call the plugin's own versioned runtime, exactly as the skill does."""
    request = {"api_version": "1.0.0", "operation": operation, **fields}
    result = subprocess.run([sys.executable, str(PLUGIN_ROOT / "runtime/run.py")],
                            input=json.dumps(request), text=True, capture_output=True)
    response = json.loads(result.stdout or "{}")
    if result.returncode != 0 or not response.get("ok"):
        die("%s failed: %s" % (operation, response.get("error") or result.stderr.strip()))
    return response["result"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def die(msg: str) -> None:
    print("  FAIL refuninstall: %s" % msg)
    sys.exit(1)


def option(argv: list[str], name: str, default: str | None = None) -> str | None:
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
    return default


def main() -> None:
    argv = sys.argv[1:]
    if len(argv) < 2:
        die("usage: refuninstall.py <PLUGIN> <TARGET> --remove a[,b] | --all")
    global PLUGIN_ROOT
    plugin, target = Path(argv[0]).resolve(), Path(argv[1]).resolve()
    PLUGIN_ROOT = plugin
    rest = argv[2:]
    remove_all = "--all" in rest
    dry_run = "--dry-run" in rest
    # Default keep, matching the spec's B5/B6 default and refinstall's skip default.
    assume_delete = "--assume-delete" in rest
    removed = [r for r in (option(rest, "--remove", "") or "").split(",") if r]

    jpath = target / ".agentic/agentic-os/install.json"
    if not jpath.is_file():
        die("not installed — no %s" % jpath.relative_to(target))
    journal = json.loads(jpath.read_text())
    answers = journal.get("answers", {})
    p_old = list(answers.get("presets") or ([answers["preset"]] if answers.get("preset") else []))
    if not p_old:
        die("journal records no presets")

    unknown = [r for r in removed if r not in p_old]
    if unknown:
        die("not installed: %s (installed: %s)" % (",".join(unknown), ",".join(p_old)))

    p_new = [] if remove_all else [p for p in p_old if p not in removed]
    if not p_new and not remove_all:
        die("removing %s would empty the preset list — that is the whole-layer "
            "case, pass --all explicitly" % ",".join(removed))
    if journal.get("adoption", {}).get("mode") == "adopt-existing":
        print("  ok   refuninstall: adopt-existing mode — reporting only, nothing deleted")
        return

    # ---- desired state: what an install of the remaining union would produce ----
    desired_files: dict[str, Path] = {}
    scratch = Path(tempfile.mkdtemp(prefix="refuninstall-desired-"))
    try:
        if p_new:
            # The reference install must run in THIS repo, not an empty one: the
            # installer's stack discovery reads marker files, so a bare scratch
            # repo would render different stack-derived content and the diff
            # would be noise. Copy the target, strip everything agentic-os
            # wrote, and install the remaining union into that.
            # Same basename as the target: the installer derives the project
            # name from the directory, so a differently-named scratch dir would
            # render a different heading in every governance file.
            ref = scratch / target.name
            shutil.copytree(target, ref, symlinks=True)
            strip_agentic(ref, journal)
            cmd = [sys.executable, str(HERE / "refinstall.py"), str(plugin), str(ref),
                   "--presets", ",".join(p_new)]
            mcp_state = answers.get("mcp_state")
            if mcp_state:
                cmd += ["--mcp-state", mcp_state]
            r = sp.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                die("reference install for %s failed: %s" % (",".join(p_new), r.stderr.strip()))
            ref_journal = json.loads((ref / ".agentic/agentic-os/install.json").read_text())
            for rel in ref_journal["files"]:
                if (ref / rel).is_file():
                    desired_files[rel] = ref / rel

        plan = converge(target, journal, desired_files, p_new, assume_delete, dry_run)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    for line in plan:
        print("  " + line)


def strip_agentic(root: Path, journal: dict) -> None:
    """Return a copied tree to its pre-install state, as far as the journal knows.

    Everything agentic-os wrote goes, so the reference install starts from the
    repo's own content and rediscovers the same stack. Files it merely adopted
    (owner user / origin adopted-existing) stay — a fresh install would find
    them there too.
    """
    for rel, entry in journal.get("files", {}).items():
        if entry.get("owner") == "user" or entry.get("origin") == "adopted-existing":
            continue
        p = root / rel
        if p.is_file():
            p.unlink()
    shutil.rmtree(root / ".agentic", ignore_errors=True)
    sc = root / "docs/audits/instruction-scorecard.json"
    if sc.is_file():
        sc.unlink()
    # Put the git-hook chain back the way the repo had it, so the reference
    # install performs the same displacement the real one did.
    hooks = root / ".git" / "hooks"
    live, local = hooks / "pre-commit", hooks / "pre-commit.local"
    if live.is_file() and "agentic-os:" in live.read_text(errors="replace"):
        live.unlink()
    if local.is_file() and not live.is_file():
        local.rename(live)
        live.chmod(0o755)


def converge(target: Path, journal: dict, desired: dict[str, Path], p_new: list[str],
             assume_delete: bool, dry_run: bool) -> list[str]:
    """Classify every journaled file, then converge through the shared installer.

    Settings wiring is subtracted first, then retained files are re-rendered
    (`install.apply`), then removals run as one `install.remove` whose
    confirmations name the exact bytes the operator agreed to delete.
    """
    report: list[str] = []
    files = journal["files"]
    removed_rel: list[str] = []
    rerendered: list[str] = []
    kept_by_choice: list[str] = []
    never_touch: list[str] = []
    rerender: dict[str, dict] = {}
    keep_settings = False
    removals: list[str] = []
    confirm: dict[str, str] = {}

    # Which hook scripts will exist afterwards — drives the settings subtraction.
    scripts_after = {rel for rel in desired if rel.startswith(".claude/hooks/") and rel.endswith(".py")}

    for rel in sorted(files):
        entry = files[rel]
        live = target / rel
        current = sha(live) if live.is_file() else None
        # B7 hybrid: settings is subtracted below, never treated as B4/B5 —
        # except under --all, where the union is empty and the whole file goes
        # (leaving an un-wired husk behind would make a later install merge into
        # residue instead of starting clean).
        if rel == ".claude/settings.json" and entry.get("owner") != "user":
            if not desired:
                edited = current is not None and current != entry.get("sha256")
                if edited and not assume_delete:
                    # Edited settings are un-wired and kept (below), never
                    # deleted without an explicit decision.
                    kept_by_choice.append("%s (locally modified, un-wired and kept)" % rel)
                    keep_settings = True
                else:
                    removals.append(rel)
                    if edited:
                        confirm[rel] = current
                    removed_rel.append(rel)
            continue
        # CLAUDE.md merged into a user's own file: refresh or strip only our
        # block, under a confirmation of the current bytes; ownership is kept.
        if rel == "CLAUDE.md" and entry.get("owner") == "user" and current:
            body = live.read_text()
            if rel in desired:
                want = desired[rel].read_text()
            else:
                want = BLOCK.sub("", body).strip("\n")
                want = want + "\n" if want else ""
                if (not want and assume_delete
                        and entry.get("origin") not in (None, "adopted-existing")):
                    # Only our block was left in a file agentic-os created.
                    removals.append(rel)
                    confirm[rel] = current
                    removed_rel.append(rel)
                    continue
            if want != body:
                rerender[rel] = {"content": want, "template": entry.get("template", "derived"),
                                 "expect_sha256": current}
                rerendered.append(rel)
            continue
        # A file agentic-os wrote that was kept earlier (declined deletion, or a
        # copy/re-clone that changed its identity) is user-owned but not
        # adopted. With an explicit --assume-delete it is removed under an
        # exact-byte confirmation, so the layer can still be fully removed.
        if (assume_delete and entry.get("owner") == "user" and rel not in desired
                and entry.get("origin") not in (None, "adopted-existing")
                and rel != "CLAUDE.md" and current):
            removals.append(rel)
            confirm[rel] = current
            removed_rel.append(rel)
            continue
        # B0 — never touch. Files agentic-os wrote that an earlier run kept are
        # user-owned too; report them as kept rather than as the user's own.
        if entry.get("owner") == "user" or entry.get("origin") == "adopted-existing":
            if entry.get("origin") in (None, "adopted-existing"):
                never_touch.append(rel)
            else:
                kept_by_choice.append("%s (kept earlier, user-owned)" % rel)
            continue
        if rel in desired:
            # Retained. Re-render when the desired content differs.
            if current is None:
                continue
            want = desired[rel].read_bytes()
            if live.read_bytes() == want:
                continue
            spec = {"content": want.decode("utf-8"), "template": entry.get("template", "derived"),
                    "owner": entry.get("owner", "managed")}
            if current != entry.get("sha256"):
                # B3 — retained but locally modified. Without a decision the
                # installer preserves it and records it user-owned.
                if not assume_delete:
                    kept_by_choice.append("%s (retained, local edits kept)" % rel)
                    rerender[rel] = spec
                    continue
                spec["expect_sha256"] = current
            rerender[rel] = spec
            rerendered.append(rel)
        else:
            # Removed from the union.
            dirty = current is not None and current != entry.get("sha256")
            if entry.get("owner") == "generated" or dirty:
                # B5 / B6 — default keep; the installer records the decision.
                if not assume_delete:
                    kept_by_choice.append("%s (%s, kept)" %
                                          (rel, "generated" if entry.get("owner") == "generated"
                                           else "locally modified"))
                    removals.append(rel)
                    continue
                if current:
                    confirm[rel] = current
            removals.append(rel)
            removed_rel.append(rel)

    # Under --all the settings file is removed whole (confirmed above), so it is
    # not rewritten first; otherwise un-wire before any script is deleted.
    # Under --all a managed settings file is removed whole (confirmed above); a
    # user-owned one is un-wired against an empty script set instead.
    settings_entry = journal["files"].get(".claude/settings.json", {})
    settings_removed = ".claude/settings.json" in removals
    if not settings_removed and (desired or settings_entry.get("owner") == "user" or keep_settings):
        settings_dropped = subtract_settings(target, journal, scripts_after, dry_run,
                                             frozenset(removals))
    else:
        settings_dropped = 0
    if not dry_run:
        if rerender:
            applied = set(runtime("install.apply", target=str(target), files=rerender)["applied"])
            # Report what the installer wrote, not what was planned.
            rerendered = [rel for rel in rerendered if rel in applied]
        # The settings file goes first, so an interruption can never leave it
        # wired to scripts that were already deleted.
        first = [rel for rel in removals if rel == ".claude/settings.json"]
        rest = [rel for rel in removals if rel not in first]
        outcome = {"removed": [], "preserved": []}
        for batch in (first, rest):
            if batch:
                result = runtime("install.remove", target=str(target), paths=batch,
                                 confirm={rel: confirm[rel] for rel in batch if rel in confirm})
                outcome["removed"] += result["removed"] + result.get("missing", [])
                outcome["preserved"] += result["preserved"]
            if batch is first and first and ".claude/settings.json" not in outcome["removed"]:
                # The installer kept it (for example a same-bytes rewrite with a
                # new identity). Un-wire it against the journal as it is now,
                # before any script it wires is deleted.
                current_journal = json.loads((target / ".agentic/agentic-os/install.json").read_text())
                settings_dropped += subtract_settings(target, current_journal, set(), dry_run,
                                                      frozenset(rest))
        # Report what the installer actually did, not what was planned.
        not_removed = set(removed_rel) - set(outcome["removed"])
        removed_rel = [rel for rel in removed_rel if rel not in not_removed]
        kept_by_choice += ["%s (kept by the installer)" % rel for rel in sorted(not_removed)]
    hook_notes = converge_git_hooks(target, desired, dry_run)

    if not dry_run:
        if not p_new:
            # --all: the journal is deleted LAST, so a crash anywhere above
            # still leaves a readable record of what was installed. Nothing is
            # written back — a rewritten journal would resurrect the very
            # directory the run just emptied.
            remaining = json.loads((target / ".agentic/agentic-os/install.json").read_text())
            # Files agentic-os wrote (not adopted) that the installer kept,
            # whatever owner it now records for them.
            still_ours = sorted(
                rel for rel, entry in remaining.get("files", {}).items()
                if (target / rel).is_file() and entry.get("origin") != "adopted-existing"
                and not (rel == "CLAUDE.md" and not BLOCK.search((target / rel).read_text()))
                and (entry.get("origin") is not None or entry.get("owner") != "user"))
            if still_ours:
                # The installer kept files agentic-os still owns; deleting the
                # journal would leave them untracked. Keep it and say so.
                report.append("WARN journal kept: %d agentic-os file(s) were not removed "
                              "(kept by choice, edited, generated, or changed identity): %s"
                              % (len(still_ours), ", ".join(still_ours[:5])))
            else:
                sc = target / "docs/audits/instruction-scorecard.json"
                if sc.is_file():
                    sc.unlink()      # the whole manifest goes with the layer
                shutil.rmtree(target / ".agentic/agentic-os", ignore_errors=True)
            for d in (".agentic", ".claude", "docs/audits"):
                prune_empty_dirs(target / d)
        else:
            journal = json.loads((target / ".agentic/agentic-os/install.json").read_text())
            prune_scorecard(target, journal, removed_rel)
            answers = dict(journal.get("answers", {}))
            answers["presets"] = p_new
            answers["ROLE_PRESETS_ACTIVE"] = ",".join(p_new)
            runtime("install.record", target=str(target), fields={"answers": answers})

    report.append("ok   refuninstall: %d removed, %d re-rendered, %d kept by choice, "
                  "%d never-touch, %d settings entries un-wired"
                  % (len(removed_rel), len(rerendered), len(kept_by_choice),
                     len(never_touch), settings_dropped))
    for n in hook_notes:
        report.append("ok   " + n)
    if dry_run:
        report.append("ok   --dry-run: nothing written")
    return report


def prune_empty_dirs(root: Path) -> None:
    """Remove directories the removal emptied, deepest first.

    A fresh install creates these on demand, so leaving empty husks behind
    would diverge from a never-installed repo — visible in `git status` as
    stray untracked directories.
    """
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*"), key=lambda q: len(q.parts), reverse=True):
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    if not any(root.iterdir()):
        root.rmdir()


def subtract_settings(target: Path, journal: dict, scripts_after: set[str],
                      dry_run: bool, removing: frozenset[str] = frozenset()) -> int:
    """Drop hook wirings whose script will not exist afterwards.

    Ordered before script deletion by the caller's contract: a crash here leaves
    'wired nothing' (harmless), never 'wired but missing' (which doctor Check 5
    reports as exit 2 on every event, blocking all tool use).
    """
    sp_path = target / ".claude/settings.json"
    if not sp_path.is_file():
        return 0
    # Only wiring for scripts agentic-os installed is ours to remove; the
    # repo's own hooks stay wired.
    ours = {rel for rel, entry in journal["files"].items()
            if rel.startswith(".claude/hooks/") and entry.get("owner") in ("managed", "generated")
            and entry.get("origin") != "adopted-existing"}
    # Any hook script this run deletes is un-wired first, whatever its owner.
    ours |= {rel for rel in removing if rel.startswith(".claude/hooks/")}
    settings = json.loads(sp_path.read_text())
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    dropped = 0
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            entries = group.get("hooks", []) if isinstance(group, dict) else []
            kept = []
            for h in entries:
                cmd = h.get("command", "") if isinstance(h, dict) else ""
                script = None
                for token in cmd.split():
                    if token.startswith(".claude/hooks/") and token.endswith(".py"):
                        script = token
                        break
                if script and script in ours and script not in scripts_after:
                    dropped += 1
                    continue
                kept.append(h)
            # Empty groups and empty event keys are KEPT. A fresh install leaves
            # them: the installer's prune reaches each matcher group through its
            # "matcher" branch, which filters the group's hooks in place and
            # returns, so the group shape survives even when it ends up empty.
            # Collapsing them here would produce a settings file no install can
            # produce — which is exactly what the round-trip caught.
            group["hooks"] = kept
            kept_groups.append(group)
        hooks[event] = kept_groups
    if dropped and not dry_run:
        # Un-wiring is safety-relevant even for a user-owned settings file, so
        # it runs under a confirmation of the current bytes; ownership is kept.
        entry = journal["files"].get(".claude/settings.json", {})
        spec = {"content": json.dumps(settings, indent=2) + "\n",
                "template": entry.get("template", "hooks/settings-fragment")}
        current = sha(sp_path)
        if entry.get("owner") == "managed" and entry.get("sha256") == current:
            # Unedited: it stays ours. An edited file lands user-owned, so the
            # user's edits are never relabelled as managed content.
            spec["owner"] = "managed"
        spec["expect_sha256"] = current
        runtime("install.apply", target=str(target), files={".claude/settings.json": spec})
    return dropped


def converge_git_hooks(target: Path, desired: dict, dry_run: bool) -> list[str]:
    """Remove our hook and restore the repo's own, when the git layer leaves."""
    if ".githooks/pre-commit" in desired:
        return []
    try:
        hooks_dir = Path(subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--git-path", "hooks"],
            capture_output=True, text=True, check=True).stdout.strip())
    except subprocess.CalledProcessError:
        return []
    if not hooks_dir.is_absolute():
        hooks_dir = target / hooks_dir
    live, local = hooks_dir / "pre-commit", hooks_dir / "pre-commit.local"
    notes: list[str] = []
    if live.is_file():
        if "agentic-os:" in live.read_text(errors="replace"):
            if not dry_run:
                live.unlink()
            notes.append("git hook: removed our .git/hooks/pre-commit")
        else:
            return ["git hook: .git/hooks/pre-commit is not ours — left in place"]
    if local.is_file():
        if live.is_file():
            return notes + ["git hook: both pre-commit and pre-commit.local present — "
                            "stopped, restore by hand"]
        if not dry_run:
            local.rename(live)
            live.chmod(0o755)
        notes.append("git hook: restored the repo's own pre-commit from .local")
    return notes


def prune_scorecard(target: Path, journal: dict, removed_rel: list[str]) -> None:
    sc = target / "docs/audits/instruction-scorecard.json"
    if not sc.is_file():
        return
    doc = json.loads(sc.read_text())
    entries = doc.get("files", {})
    for rel in removed_rel:
        entries.pop(rel, None)
    for rel in list(entries):
        p = target / rel
        if not p.is_file():
            entries.pop(rel, None)
            continue
        if rel in journal["files"]:
            entries[rel]["content_sha256"] = sha(p)
    sc.write_text(json.dumps(doc, indent=2) + "\n")


if __name__ == "__main__":
    main()
