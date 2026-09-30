#!/usr/bin/env python3
"""Reference executor of agentic-init Phase 4 (deterministic scaffold only).

This is the acceptance harness's stand-in for a human/agent following
plugins/agentic-os/skills/agentic-init/SKILL.md by hand: it renders + places
every template in the *developer* preset union with the `--defaults` answers for
the nextjs-supabase profile, deep-merges the settings fragment, installs the
git-hook chain, and seeds the instruction scorecard. It deliberately SKIPS
Phase 5 (generation) and Phase 3 side effects outside the target.

If a step here is impossible to derive from the SKILL.md spec, that is a harness
finding — this file is the executable proof that the spec is followable.

Usage: refinstall.py <PLUGIN_ROOT> <TARGET_REPO> [--presets ba-po,developer]
                         [--mcp-state without-mcp|configured|unavailable]
                         [--reinstall]
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# The escaping rule and the adversarial answers live in one place so a mutation to
# either fails every check that depends on it, not just the copy that was edited.
from render_rule import ANSWERS as ADVERSARIAL_ANSWERS
from render_rule import LIST_ANSWERS as ADVERSARIAL_LISTS
from render_rule import esc

PLUGIN = Path(sys.argv[1]).resolve()
TARGET = Path(sys.argv[2]).resolve()


def option(name: str, default: str | None = None) -> str | None:
    for i, arg in enumerate(sys.argv[3:], start=3):
        if arg == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return default


PRESET_NAMES = [p for p in (option("--presets", "developer") or "").split(",") if p]
if not PRESET_NAMES:
    raise SystemExit("refinstall: --presets requires at least one role")
available_presets = {
    p.stem: json.loads(p.read_text())
    for p in (PLUGIN / "presets/roles").glob("*.json")
}
unknown_presets = sorted(set(PRESET_NAMES) - set(available_presets))
if unknown_presets:
    raise SystemExit("refinstall: unknown preset(s): " + ", ".join(unknown_presets))
# SKILL.md Screen 1 union rule: `default_hitl` resolves strictest-wins
# (strict > gated-autonomous > autonomous) across the selected presets, and
# `--defaults` accepts that pre-fill on Screen 3 — so a qa-only or
# security-only scaffold renders a `strict` policy of record.
HITL_ORDER = ["strict", "gated-autonomous", "autonomous"]
HITL_MODE = min((available_presets[name]["default_hitl"] for name in PRESET_NAMES),
                key=HITL_ORDER.index)
MCP_STATE = option("--mcp-state", "without-mcp")
if MCP_STATE not in {"without-mcp", "configured", "unavailable"}:
    raise SystemExit("refinstall: --mcp-state must be without-mcp, configured, or unavailable")
REINSTALL = "--reinstall" in sys.argv[3:]
TPL = PLUGIN / "templates"

VERSION = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["version"]

# The selected role union is the only install source of truth. The mapping below
# only maps an already-selected ID to its destination; it never selects assets.
PRESET_TEMPLATE_IDS = {
    tid for name in PRESET_NAMES for tid in available_presets[name]["templates"]
}
PRESET_GENERATED_IDS = {
    gid for name in PRESET_NAMES for gid in available_presets[name]["generated"]
}
PRESET_SDLC_SKILLS = {
    s for name in PRESET_NAMES
    for s in available_presets[name].get("sdlc_skills", [])
}
PRESET_QE_BLUEPRINTS = {
    b for name in PRESET_NAMES
    for b in available_presets[name].get("qe_blueprints", [])
}

# SKILL.md Phase 4 step 1, first installer-side conditional: these two are
# scaffolded whenever `hooks/settings-fragment` is in the union EVEN IF no preset
# lists them. The fragment unconditionally wires them as PreToolUse hooks, and a
# wired-but-missing PreToolUse script exits 2 and blocks every tool call. With
# empty lists they are safe no-ops. The union filter must not skip them.
ALWAYS_WITH_SETTINGS = {"hooks/human-gated-commands", "hooks/guarded-write-paths"}

# --- --defaults answers for the nextjs-supabase profile, developer preset ------
NEWLINE_VARS = {"GATE_COMMANDS", "HUMAN_GATED_COMMANDS", "GUARDED_WRITE_PATHS",
                "ENV_CHECK_COMMANDS", "SECRET_DENY_PATTERNS"}
LISTS = {
    "GATE_COMMANDS": ["npx tsc --noEmit", "npm run lint -- --max-warnings 0", "npm test"],
    "HUMAN_GATED_COMMANDS": ["git push origin main", "supabase db push --linked"],
    "GUARDED_WRITE_PATHS": [],
    "ENV_CHECK_COMMANDS": ["node --version"],
    "SECRET_DENY_PATTERNS": [],  # extras beyond the baked-in three
    "ESCALATE_ON": ["security", "breaking-change", "migration", "spend"],
}
SCALARS = {
    "AGENTIC_OS_VERSION": VERSION,
    "AGENTS_CANONICAL_DIR": ".agentic/agents/",
    "APP_START_COMMAND": "npm run dev",
    "BASE_URL": "http://localhost:3000",
    "DEFAULT_BRANCH": "main",
    "HITL_MODE": HITL_MODE,
    "LINT_FIX_COMMAND": "npx eslint --fix",
    "LINT_CHECK_COMMAND": "npx eslint",
    "MAX_FILES": "10",
    "MAX_LOC": "250",
    "MIGRATIONS_DIR": "supabase/migrations/",
    "MIGRATION_DIFF_COMMAND": "npx supabase db diff",
    "MR_ADAPTER": "gh",
    # Mirrors the installer's derivation: `configured` iff MR_ADAPTER is not
    # `none`. This fixture always detects `gh`, so the `not configured` branch is
    # exercised on the ticket adapter below rather than here.
    "MR_ADAPTER_STATUS": "configured",
    "OUTPUT_CONTRACT_SECTIONS": "Summary,Why,Blocking,Non-blocking,Escalate to human",
    "PROJECT_NAME": TARGET.name,
    "ROLE_PRESETS_ACTIVE": ",".join(PRESET_NAMES),
    "SCORECARD_PATH": "docs/audits/instruction-scorecard.json",
    "SCORE_THRESHOLD": "95",
    "STACK_SUMMARY": "Next.js + Supabase web app.",
    "STAGING_ENV_NAME": "staging",
    "TEST_FRAMEWORK": "playwright",
    "TICKET_ADAPTER": "none" if "ba-po" in PRESET_NAMES else "GitHub",
    "TICKET_ADAPTER_STATUS": "not configured" if "ba-po" in PRESET_NAMES else "configured",
    # A bare JSON literal, not prose: this lands unquoted in sdlc/config.json, where
    # the machine copy of the flag must agree with the adapter the guides declare.
    # Mirrors the installer's derivation in agentic-init/SKILL.md.
    "TICKET_INTEGRATION_ENABLED": "false" if "ba-po" in PRESET_NAMES else "true",
    "TICKET_PREFIX": "" if "ba-po" in PRESET_NAMES else "GH",
}

# None of the scalar answers above contains a quote, backslash, or newline, so for
# them `render()` emits the same bytes escaped or not. The newline-list answers are
# different: `"\n".join(...)` *introduces* a newline before `esc` sees it, so those
# constants do change — `X = """a\nb"""` on one source line, where they used to span
# two. Same value, same `.splitlines()`; less readable scaffold, uniform rule, and
# no dependence on "this only ever lands inside triple quotes", which is the
# reasoning that produced the bug. `/agentic-doctor` Check 3 reads these constants
# by importing the hook rather than scraping its text, for exactly this reason.
#
# What that leaves untestable is the *scalar* path: drop `esc` and every check above
# still passes. `REFINSTALL_ADVERSARIAL=1` swaps in the quote-bearing answers a real
# interview would produce, so T8b's round-trip fails when the rule is dropped, made
# lossy, or applied twice. Off by default: T1's golden manifest pins the defaults.
if os.environ.get("REFINSTALL_ADVERSARIAL"):
    unknown = set(ADVERSARIAL_ANSWERS) - set(SCALARS)
    if unknown:  # a silent skip here would quietly narrow T8b's coverage
        sys.exit("refinstall: adversarial answers not in SCALARS: %s" % sorted(unknown))
    SCALARS.update(ADVERSARIAL_ANSWERS)
    LISTS.update(ADVERSARIAL_LISTS)


def render_path(src: Path) -> str:
    """Render a template, deriving both flags from its name.

    The single place the file-type rule is applied. Passing `escape` by hand at each
    call site meant `CLAUDE.section.md.tmpl` could be — and was — rendered under a
    different rule than every other `.md.tmpl`, with nothing to catch it.
    """
    is_json = src.name.endswith(".json.tmpl")
    # Only these two file types embed variables in string literals; `.md.tmpl` prose
    # must stay unescaped or a path's backslash renders as `\\` and a newline-joined
    # fenced block collapses to one `\n`-separated line.
    escape = is_json or src.name.endswith(".py.tmpl")
    return render(src.read_text(encoding="utf-8"), is_json, escape)


def gate_entries() -> str:
    """Expand GATE_COMMANDS into one gate block each (SKILL.md Phase 4, step 5).

    Markdown, so no escaping — this only ever lands in `quality-gates.md.tmpl`. The
    command is both the gate name and the `Run` line; Pass/Fail/Skip are conservative
    defaults the human refines. Empty list ⇒ an instruction to add gates, never a
    blank registry (the guide forbids relying on an empty one)."""
    cmds = [c.strip() for c in LISTS["GATE_COMMANDS"] if c.strip()]
    if not cmds:
        return ("_No gate commands were detected. Add at least one — a project with "
                "no gate cannot enforce one._")
    return "\n\n".join(
        "### %s\n**Run**: `%s`\n**Pass**: exits 0.\n"
        "**Fail**: non-zero exit — fix the cause, never the symptom.\n"
        "**Skip if**: never." % (c, c) for c in cmds)


# The QA-only guide rows in the PATTERNS index. Emitted iff the guides are actually
# installed (the qa preset), so the developer scaffold does not index files that
# aren't there. Trailing newline per row so the following table row stays on its own
# line; empty string when absent, which collapses cleanly (a blank line would end the
# GFM table). Keyed off the preset union, the same signal that installs the guides.
QA_GUIDE_ROWS_TEXT = (
    "| Test design (deterministic, isolated, framework conventions) | "
    "[`.agentic/guides/standards/test-design-pattern.md`]"
    "(.agentic/guides/standards/test-design-pattern.md) |\n"
    "| Flaky-test protocol (classify → ledger → root-cause → burn-in) | "
    "[`.agentic/guides/standards/flaky-protocol.md`]"
    "(.agentic/guides/standards/flaky-protocol.md) |\n"
)
QA_GUIDE_ROWS = QA_GUIDE_ROWS_TEXT if {
    "guides/test-design-pattern", "guides/flaky-protocol"} <= PRESET_TEMPLATE_IDS else ""

# The devops-only incident-triage row, same emitted-iff-installed contract as
# the QA rows above.
OPS_GUIDE_ROWS_TEXT = (
    "| Incident triage (read-only diagnosis, three-hypothesis rule, runtime bounds) | "
    "[`.agentic/guides/standards/incident-triage.md`]"
    "(.agentic/guides/standards/incident-triage.md) |\n"
)
OPS_GUIDE_ROWS = OPS_GUIDE_ROWS_TEXT if "guides/incident-triage" in PRESET_TEMPLATE_IDS else ""

# The security-only threat-modeling row, same contract.
SEC_GUIDE_ROWS_TEXT = (
    "| Threat modeling (DFD-first STRIDE, risk distribution, proposed-only severities) | "
    "[`.agentic/guides/standards/threat-modeling.md`]"
    "(.agentic/guides/standards/threat-modeling.md) |\n"
)
SEC_GUIDE_ROWS = SEC_GUIDE_ROWS_TEXT if "guides/threat-modeling" in PRESET_TEMPLATE_IDS else ""

# The data-only pipeline-design row, same contract.
DATA_GUIDE_ROWS_TEXT = (
    "| Data pipeline design (layered row math, force-tested DQ checks, dataset lineage) | "
    "[`.agentic/guides/standards/data-pipeline-design.md`]"
    "(.agentic/guides/standards/data-pipeline-design.md) |\n"
)
DATA_GUIDE_ROWS = DATA_GUIDE_ROWS_TEXT if "guides/data-pipeline-design" in PRESET_TEMPLATE_IDS else ""

# The design-only experience row, same contract.
DESIGN_GUIDE_ROWS_TEXT = (
    "| Experience design (emotion-annotated journeys, decision-closing workshops, negative ACs) | "
    "[`.agentic/guides/standards/experience-design.md`]"
    "(.agentic/guides/standards/experience-design.md) |\n"
)
DESIGN_GUIDE_ROWS = DESIGN_GUIDE_ROWS_TEXT if "guides/experience-design" in PRESET_TEMPLATE_IDS else ""
# The five core guide rows, one per installed guide, fixed order — the index must
# never link a guide the union did not install (SKILL.md Phase 4 step 4).
CORE_GUIDE_ROW_TEXTS = [
    ("guides/git-workflow",
     "| Git workflow (branch flow, commit format, sync-before-work) | "
     "[`.agentic/guides/standards/git-workflow.md`](.agentic/guides/standards/git-workflow.md) |\n"),
    ("guides/code-quality",
     "| Code quality (tests & gates, blind review, comments, dead code) | "
     "[`.agentic/guides/standards/code-quality.md`](.agentic/guides/standards/code-quality.md) |\n"),
    ("guides/quality-gates",
     "| Quality gate commands (run/pass/fail/skip per gate) | "
     "[`.agentic/guides/standards/quality-gates.md`](.agentic/guides/standards/quality-gates.md) |\n"),
    ("guides/instruction-quality-rubric",
     "| Instruction quality grading (evidence-accuracy rubric) | "
     "[`.agentic/guides/standards/instruction-quality-rubric.md`]"
     "(.agentic/guides/standards/instruction-quality-rubric.md) |\n"),
    ("guides/qa-strategy-stub",
     "| QA / test strategy | "
     "[`.agentic/guides/standards/qa-strategy-stub.md`](.agentic/guides/standards/qa-strategy-stub.md) "
     "*(replaced by `.agentic/guides/testing/qa-strategy.md` after `/sdlc:qa-init`)* |\n"),
]
CORE_GUIDE_ROWS = "".join(
    row for tid, row in CORE_GUIDE_ROW_TEXTS if tid in PRESET_TEMPLATE_IDS)

# CLAUDE.md governance block: promise only what this union installs. The
# write-scope rule always renders; the hook citation only when the hook does.
WRITE_SCOPE_RULE = (
    "**Respect your `write_scope` absolutely.** Writing outside it is blocked by\n"
    "   `.claude/hooks/write_scope_guard.py` and treated as an orchestration error."
    if "hooks/write-scope-guard" in PRESET_TEMPLATE_IDS else
    "**Respect your `write_scope` absolutely.** Writing outside it is an\n"
    "   orchestration error — stop and escalate.")

# The blind-review section installs only with the git review layer; the spawn
# step names blind-code-reviewer only when that agent installs (devops has the
# gate but not the reviewer). Ends in a blank line; empty collapses cleanly.
_REVIEW_STEP_AGENT = (
    "spawn\n`blind-code-reviewer` on the staged diff (pass a one-paragraph "
    "functional brief only,\nnever your reasoning)")
_REVIEW_STEP_HUMAN = (
    "obtain an\nindependent review of the staged diff (this install carries no "
    "`blind-code-reviewer`\nagent — a human or external reviewer approves)")
REVIEW_GATE_SECTION = "" if not (
    {"hooks/precommit-review-gate", "githooks/pre-commit"} <= PRESET_TEMPLATE_IDS
) else (
    "### Blind code review before every commit (MANDATORY)\n"
    "\n"
    "Every `git commit` must be preceded by a review pass over the exact\n"
    "staged diff. Enforced by two independent layers:\n"
    "\n"
    "1. **PreToolUse(Bash) hook** — `python3 .claude/hooks/precommit_review_gate.py`\n"
    "   blocks the commit (exit 2) unless the staged diff is approved.\n"
    "2. **Native git `pre-commit` hook** — `.githooks/pre-commit` (installed via\n"
    "   `bash scripts/install-git-hooks.sh`) blocks at the git level even outside the harness.\n"
    "\n"
    "Workflow: run the quality gates → stage exactly what you intend to commit → "
    + ("%s" % (_REVIEW_STEP_AGENT
               if "agents/blind-code-reviewer" in PRESET_TEMPLATE_IDS
               else _REVIEW_STEP_HUMAN))
    + " → address every Blocker/Major → record approval\n"
    "(`python3 .claude/hooks/precommit_review_gate.py approve`) → commit. Any further\n"
    "`git add` invalidates the stamp. Escape hatch for merge/mechanical commits only:\n"
    "`[skip-review]` in the message or `SKIP_REVIEW=1 git commit …`.\n"
    "\n")

# The quality-gates section cites the gate catalogue guide, so it installs only
# when that guide does. Contains {{GATE_COMMANDS}} — substituted before the
# scalar/list pass in render(), so the nested placeholder still renders.
QUALITY_GATES_SECTION = "" if "guides/quality-gates" not in PRESET_TEMPLATE_IDS else (
    "### Quality gates\n"
    "\n"
    "Run before staging (commands catalogued in\n"
    "`.agentic/guides/standards/quality-gates.md`):\n"
    "\n"
    "```\n"
    "{{GATE_COMMANDS}}\n"
    "```\n"
    "\n")

# Agent-registry "Multi-step work" bullet: name only installed commands.
_HAS_PIPE = "commands/pipeline-orchestrator" in PRESET_TEMPLATE_IDS
_HAS_DISPATCH = "commands/dispatch" in PRESET_TEMPLATE_IDS
if _HAS_PIPE and _HAS_DISPATCH:
    ORCHESTRATION_STYLE_RULE = (
        "**Multi-step work** goes through the orchestration style your HITL mode "
        "prescribes: `strict` installs default to `dispatch`; "
        "`gated-autonomous`/`autonomous` default to `pipeline-orchestrator`.")
elif _HAS_DISPATCH:
    ORCHESTRATION_STYLE_RULE = (
        "**Multi-step work** goes through `dispatch` — the only orchestration "
        "command in this install; each step is user-invoked.")
elif _HAS_PIPE:
    ORCHESTRATION_STYLE_RULE = (
        "**Multi-step work** goes through `pipeline-orchestrator` — the only "
        "orchestration command in this install.")
else:
    ORCHESTRATION_STYLE_RULE = (
        "**Multi-step work** is orchestrated by the human — this install has no "
        "orchestration command.")
# The ba-po guide rows, same emitted-iff-installed contract; per-guide because the
# two guides are independent entries in the preset's template list.
BA_PO_GUIDE_ROWS_PER_GUIDE = (
    ("guides/ba-po-operating-model",
     "| BA/PO operating model (input paths, evidence rules, story handoffs) | "
     "[`.agentic/guides/standards/ba-po-operating-model.md`]"
     "(.agentic/guides/standards/ba-po-operating-model.md) |\n"),
    ("guides/mcp-onboarding",
     "| MCP onboarding (optional read-only data access for business work) | "
     "[`.agentic/guides/standards/mcp-onboarding.md`]"
     "(.agentic/guides/standards/mcp-onboarding.md) |\n"),
)
BA_PO_GUIDE_ROWS = "".join(
    row for tid, row in BA_PO_GUIDE_ROWS_PER_GUIDE if tid in PRESET_TEMPLATE_IDS)

# ai-policy "Enforcement layers": the hard hook-backed rows list only what this
# union installs — same promise-only-what-is-installed contract as the guide
# rows. Each row ends in a newline so absent rows collapse without breaking the
# GFM table; the two soft/settings rows stay in the template, so the table is
# never empty. The instruction-gate row nests {{SCORECARD_PATH}} — substituted
# before the scalar pass in render(), so it still resolves.
_ENFORCEMENT_ROW_TEXTS = [
    ({"hooks/precommit-review-gate", "githooks/pre-commit"},
     "| Pre-commit review stamp | `.claude/hooks/precommit_review_gate.py` + "
     "`.githooks/pre-commit` | hard (exit 2) |\n"),
    ({"hooks/subagent-gate"},
     "| Output-contract gate | `.claude/hooks/subagent_gate.py` (fail-closed) "
     "| hard (exit 2) |\n"),
    ({"hooks/write-scope-guard"},
     "| Write-scope guard | `.claude/hooks/write_scope_guard.py` per agent "
     "contract | hard (exit 2) |\n"),
    ({"hooks/instruction-gate"},
     "| Instruction-quality gate | `.claude/hooks/instruction_gate.py` vs "
     "{{SCORECARD_PATH}} | hard (exit 2) |\n"),
]
ENFORCEMENT_LAYER_ROWS = "".join(
    row for ids, row in _ENFORCEMENT_ROW_TEXTS if ids <= PRESET_TEMPLATE_IDS)

# AGENTS.md "Fleet invariants": derived as one numbered list so a union that
# skips an enforcement layer neither cites its hook nor leaves a numbering gap.
# Invariants 1 and 5 have no-hook variants; 5 and 6 drop entirely when their
# layer is absent; the rest hold in every install (every preset ships
# hooks/subagent-gate, so its citation stays unconditional).
_FLEET_WRITE_SCOPE = (
    "**Write scope is absolute.** An agent that writes outside the `write_scope` in its\n"
    "   contract frontmatter is a bug; treat it as you would a security breach. Enforced at\n"
    "   PreToolUse by `.claude/hooks/write_scope_guard.py` when an orchestrator has set the\n"
    "   active-agent lock (`.agentic/state/active-agent.json`)."
    if "hooks/write-scope-guard" in PRESET_TEMPLATE_IDS else
    "**Write scope is absolute.** An agent that writes outside the `write_scope` in its\n"
    "   contract frontmatter is a bug; treat it as you would a security breach — stop and\n"
    "   escalate. This install carries no write-scope guard hook; the humans in the loop\n"
    "   are the enforcement layer.")
_FLEET_INSTRUCTION_GATE = None if "hooks/instruction-gate" not in PRESET_TEMPLATE_IDS else (
    "**Instruction-quality gate.** Spawning an agent whose contract (or a guide it\n"
    "   cites, or the core index files) is stale/ungraded/below threshold is blocked at\n"
    "   SubagentStart by `.claude/hooks/instruction_gate.py`. The repair path is the\n"
    "   `instruction-auditor` (itself exempt — gating the auditor would deadlock)."
    if "agents/instruction-auditor" in PRESET_TEMPLATE_IDS else
    "**Instruction-quality gate.** Spawning an agent whose contract (or a guide it\n"
    "   cites, or the core index files) is stale/ungraded/below threshold is blocked at\n"
    "   SubagentStart by `.claude/hooks/instruction_gate.py`. The repair path is a human\n"
    "   re-grade of the instruction set (this install carries no `instruction-auditor`).")
_FLEET_BLIND_REVIEW = None if not (
    {"hooks/precommit-review-gate", "githooks/pre-commit"} <= PRESET_TEMPLATE_IDS
) else (
    "**Blind review before commit.** No commit ships unreviewed — see the managed\n"
    "   governance block in `CLAUDE.md`.")
FLEET_INVARIANTS = "\n".join(
    "%d. %s" % (i, item) for i, item in enumerate(
        [item for item in [
            _FLEET_WRITE_SCOPE,
            "**Orchestrator-only spawning.** Peer agents never spawn each other; only\n"
            "   orchestrating commands (and the human) spawn subagents. This keeps every spawn\n"
            "   auditable and every write attributable.",
            "**Gate agents are read-only** and must emit a literal `PASS` token for the\n"
            "   pipeline to advance. No PASS, no progress — a gate that \"mostly passed\" failed.",
            "**Output contract.** Every agent ends its final message with\n"
            "   `## Summary / ## Why / ## Blocking / ## Non-blocking / ## Escalate to human`.\n"
            "   `.claude/hooks/subagent_gate.py` parses it fail-closed: a missing contract is\n"
            "   treated as Blocking; a non-empty `## Escalate to human` requires the parent to ask\n"
            "   the human before proceeding.",
            _FLEET_INSTRUCTION_GATE,
            _FLEET_BLIND_REVIEW,
            "**Escalation over improvisation.** Anything listed in\n"
            "   `.agentic/guides/policy/escalation-policy.md` (human-gated commands, guarded write\n"
            "   paths, `escalate_on` risk flags) stops the pipeline and goes to the human with\n"
            "   concrete options.",
        ] if item is not None], 1))

# Screen 3's per-capability autonomy answers. `--defaults` accepts every mode
# default, so nothing is tightened — the block is the "no overrides" note. A real
# interview emits one bullet per capability the user set stricter than its mode row.
AUTONOMY_OVERRIDES = (
    "_No per-repository overrides — every capability follows the active mode's row "
    "above._")


def render(text: str, is_json: bool, escape: bool) -> str:
    q = esc if escape else (lambda v: v)
    # Derived, not raw variables: built by the installer from interview answers or
    # what it installs. Only in markdown templates, so never escaped.
    text = text.replace("{{GATE_ENTRIES}}", gate_entries())
    text = text.replace("{{QA_GUIDE_ROWS}}", QA_GUIDE_ROWS)
    text = text.replace("{{OPS_GUIDE_ROWS}}", OPS_GUIDE_ROWS)
    text = text.replace("{{SEC_GUIDE_ROWS}}", SEC_GUIDE_ROWS)
    text = text.replace("{{DATA_GUIDE_ROWS}}", DATA_GUIDE_ROWS)
    text = text.replace("{{DESIGN_GUIDE_ROWS}}", DESIGN_GUIDE_ROWS)
    text = text.replace("{{CORE_GUIDE_ROWS}}", CORE_GUIDE_ROWS)
    text = text.replace("{{WRITE_SCOPE_RULE}}", WRITE_SCOPE_RULE)
    # Before the scalar/list pass: the quality-gates section nests {{GATE_COMMANDS}}.
    text = text.replace("{{REVIEW_GATE_SECTION}}", REVIEW_GATE_SECTION)
    text = text.replace("{{QUALITY_GATES_SECTION}}", QUALITY_GATES_SECTION)
    text = text.replace("{{ORCHESTRATION_STYLE_RULE}}", ORCHESTRATION_STYLE_RULE)
    text = text.replace("{{BA_PO_GUIDE_ROWS}}", BA_PO_GUIDE_ROWS)
    # Before the scalar/list pass: the instruction-gate row nests {{SCORECARD_PATH}}.
    text = text.replace("{{ENFORCEMENT_LAYER_ROWS}}", ENFORCEMENT_LAYER_ROWS)
    text = text.replace("{{FLEET_INVARIANTS}}", FLEET_INVARIANTS)
    # --defaults accepts each capability's mode default, so no autonomy tightening.
    text = text.replace("{{AUTONOMY_OVERRIDES}}", AUTONOMY_OVERRIDES)
    for var in NEWLINE_VARS:
        text = text.replace("{{%s}}" % var, q("\n".join(LISTS[var])))
    # Not a scalar: JSON array elements carry their own quotes; the comma-joined
    # prose form (`.md.tmpl`) sits outside any literal. Neither takes `esc`.
    escalate = LISTS["ESCALATE_ON"]
    text = text.replace("{{ESCALATE_ON}}",
                        ",".join(json.dumps(x) for x in escalate) if is_json
                        else ",".join(escalate))
    for k, v in SCALARS.items():
        text = text.replace("{{%s}}" % k, q(v))
    return text


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


JOURNAL = {"agentic_os_version": VERSION, "answers": {"presets": PRESET_NAMES,
           "mcp_state": MCP_STATE, "defaults": True},
           "phase": "scaffold", "files": {}, "follow_ups": []}


# Files whose collision handling is bespoke (append/merge) — never blanket-skipped here.
MANAGED_APPEND = {"CLAUDE.md", ".claude/settings.json"}


# Every scaffold file is staged here and applied at the end through the shipped
# runtime's `install.apply` (SKILL.md Phase 4), which owns collision handling:
# a pre-existing or user-modified file is preserved and journaled user-owned.
# Later steps read staged content back through `current()`.
PENDING: dict[str, dict] = {}


def current(rel: str) -> str | None:
    if rel in PENDING:
        return PENDING[rel]["content"]
    path = TARGET / rel
    return path.read_text() if path.is_file() else None


def exists_after(rel: str) -> bool:
    return rel in PENDING or (TARGET / rel).exists()


def write(dest_rel: str, content: str, template: str, owner: str = "managed"):
    PENDING[dest_rel] = {"content": content, "template": template, "owner": owner}


def merge_into_existing(dest_rel: str, content: str, template: str):
    """Stage content that merges into a file the user may already own.

    A pre-existing file (or one the journal does not record as ours) is
    replaced only under a compare-and-swap confirmation of its current bytes;
    it stays user-owned. A managed file is replaced normally.
    """
    spec = {"content": content, "template": template}
    path = TARGET / dest_rel
    previous = JOURNAL_PREV.get("files", {}).get(dest_rel, {})
    if path.is_file() and (previous.get("owner") != "managed" or previous.get("sha256") != sha(path)):
        # Pre-existing, user-owned, or a managed file the user edited: merge
        # under a confirmation of the current bytes; it lands user-owned.
        spec["expect_sha256"] = sha(path)
    else:
        spec["owner"] = "managed"
    PENDING[dest_rel] = spec


def runtime(operation: str, **fields) -> dict:
    """Call the plugin's own versioned runtime, exactly as the skill does."""
    request = {"api_version": "1.0.0", "operation": operation, **fields}
    result = subprocess.run([sys.executable, str(PLUGIN / "runtime/run.py")],
                            input=json.dumps(request), text=True, capture_output=True)
    response = json.loads(result.stdout or "{}")
    if result.returncode != 0 or not response.get("ok"):
        raise SystemExit("refinstall: %s failed: %s" % (operation, response.get("error") or result.stderr))
    return response["result"]


def copy_tpl(src_rel: str, dest_rel: str, template: str):
    src = TPL / src_rel
    content = render_path(src) if src.name.endswith(".tmpl") else src.read_text()
    write(dest_rel, content, template)


JOURNAL_PREV = {}
jpath = TARGET / ".agentic/agentic-os/install.json"
if jpath.exists():
    JOURNAL_PREV = json.loads(jpath.read_text())

# --- Phase 4 step 1: hooks -----------------------------------------------------
HOOKS = [
    ("precommit_review_gate.py", "precommit_review_gate.py", "hooks/precommit-review-gate"),
    ("subagent_gate.py.tmpl", "subagent_gate.py", "hooks/subagent-gate"),
    ("instruction_gate.py.tmpl", "instruction_gate.py", "hooks/instruction-gate"),
    ("instruction_stale_notice.py", "instruction_stale_notice.py", "hooks/instruction-stale-notice"),
    ("write_scope_guard.py.tmpl", "write_scope_guard.py", "hooks/write-scope-guard"),
    ("session_start_bootstrap.py.tmpl", "session_start_bootstrap.py", "hooks/session-bootstrap"),
    ("precompact_checkpoint.py", "precompact_checkpoint.py", "hooks/precompact-checkpoint"),
    ("session_learnings_notice.py", "session_learnings_notice.py", "hooks/session-learnings-notice"),
    ("context_monitor.py", "context_monitor.py", "hooks/context-monitor"),
    ("prompt_scan_guard.py", "prompt_scan_guard.py", "hooks/prompt-scan-guard"),
    ("human_gated_commands.py.tmpl", "human_gated_commands.py", "hooks/human-gated-commands"),
    ("guarded_write_paths.py.tmpl", "guarded_write_paths.py", "hooks/guarded-write-paths"),
    ("migration_notice.py.tmpl", "migration_notice.py", "hooks/migration-notice"),
    ("lint_on_save.py.tmpl", "lint_on_save.py", "hooks/lint-on-save"),
]
AGENTIC_HOOK_NAMES = {dest for _, dest, _ in HOOKS}
settings_in_union = "hooks/settings-fragment" in PRESET_TEMPLATE_IDS
for src, dest, tid in HOOKS:
    forced = tid in ALWAYS_WITH_SETTINGS and settings_in_union
    if tid not in PRESET_TEMPLATE_IDS and not forced:
        continue  # not in this preset's union — Phase 4 scaffolds the union only
    # SKILL.md Phase 4: migration_notice is skipped when MIGRATIONS_DIR is empty.
    # Non-empty here (nextjs-supabase → supabase/migrations/), so it installs.
    if tid == "hooks/migration-notice" and not SCALARS["MIGRATIONS_DIR"]:
        continue
    # Same rule for lint-on-save when no check command was configured.
    if tid == "hooks/lint-on-save" and not SCALARS["LINT_CHECK_COMMAND"]:
        continue
    copy_tpl("hooks/claude/" + src, ".claude/hooks/" + dest, tid)

# --- Phase 4 step 2: settings deep-merge --------------------------------------
frag = json.loads(render_path(TPL / "hooks/settings-fragment.json.tmpl"))
settings_path = TARGET / ".claude/settings.json"
settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}


def deep_merge(base, frag):
    for k, v in frag.items():
        if isinstance(v, dict):
            deep_merge(base.setdefault(k, {}), v)
        elif isinstance(v, list):
            arr = base.setdefault(k, [])
            for item in v:
                if item not in arr:
                    arr.append(item)
        else:
            base.setdefault(k, v)


deep_merge(settings, frag)


def prune_missing_hook_commands(node):
    """Drop hook entries whose scripts were not selected by the role union."""
    if isinstance(node, dict):
        if "matcher" in node and isinstance(node.get("hooks"), list):
            node["hooks"] = [
                hook for hook in node["hooks"]
                if not (".claude/hooks/" in hook.get("command", "")
                        and hook["command"].split(".claude/hooks/", 1)[1].split()[0]
                        in AGENTIC_HOOK_NAMES
                        and not exists_after(".claude/" + hook["command"].split(
                            ".claude/", 1)[1].split()[0]))
            ]
            return
        for key in list(node):
            if key == "hooks" and isinstance(node[key], list):
                if node[key] and all(isinstance(entry, dict) and "matcher" in entry
                                     for entry in node[key]):
                    kept_groups = []
                    for group in node[key]:
                        commands = group.get("hooks", [])
                        group["hooks"] = [
                            hook for hook in commands
                            if not (".claude/hooks/" in hook.get("command", "")
                                    and hook["command"].split(".claude/hooks/", 1)[1].split()[0]
                                    in AGENTIC_HOOK_NAMES
                                    and not exists_after(".claude/" + hook["command"].split(
                                        ".claude/", 1)[1].split()[0]))
                        ]
                        if group["hooks"]:
                            kept_groups.append(group)
                    node[key] = kept_groups
                    for group in node[key]:
                        prune_missing_hook_commands(group)
                else:
                    for item in node[key]:
                        prune_missing_hook_commands(item)
            else:
                prune_missing_hook_commands(node[key])
    elif isinstance(node, list):
        for item in node:
            prune_missing_hook_commands(item)


prune_missing_hook_commands(settings)
merge_into_existing(".claude/settings.json", json.dumps(settings, indent=2) + "\n",
                    "hooks/settings-fragment")

# --- Phase 4 step 3: git hooks (chaining installer) ---------------------------
if "githooks/pre-commit" in PRESET_TEMPLATE_IDS:
    copy_tpl("githooks/pre-commit", ".githooks/pre-commit", "githooks/pre-commit")
    copy_tpl("scripts/install-git-hooks.sh", "scripts/install-git-hooks.sh", "scripts/install-git-hooks")

# Local hook/session state must never be committed to the host repo: the review
# stamp would make a fresh clone believe a diff was already approved, and the
# prompt-scan audit log is per-machine noise. Append-if-absent, idempotent.
LOCAL_STATE_IGNORES = [".claude/.review-stamp", ".claude/checkpoints/", ".agentic/state/"]
gi = TARGET / ".gitignore"
existing = gi.read_text().splitlines() if gi.exists() else []
additions = [line for line in LOCAL_STATE_IGNORES if line not in existing]
if additions:
    text = "\n".join(existing) if existing else ""
    if text and not text.endswith("\n"):
        text += "\n"
    gi.write_text((text + "\n".join(additions) + "\n") if text else "\n".join(additions) + "\n")

# --- Phase 4 step 4: governance -----------------------------------------------
BEGIN = "<!-- agentic-os:begin v%s -->" % VERSION
END = "<!-- agentic-os:end -->"
claude_block = render_path(TPL / "governance/CLAUDE.section.md.tmpl")
claude_path = TARGET / "CLAUDE.md"
if claude_path.exists():
    body = claude_path.read_text()
    body = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), "", body, flags=re.S).rstrip()
    # Idempotent: a block-only file (no surrounding content) re-renders identically.
    merge_into_existing("CLAUDE.md", (body + "\n\n" if body else "") + claude_block + "\n",
                        "governance/claude-section")
else:
    merge_into_existing("CLAUDE.md", claude_block + "\n", "governance/claude-section")

copy_tpl("governance/AGENTS.md.tmpl", "AGENTS.md", "governance/agents")
copy_tpl("governance/PATTERNS.md.tmpl", "PATTERNS.md", "governance/patterns")
copy_tpl("governance/agent-registry.md.tmpl", ".agentic/guides/agent-registry.md",
         "governance/agent-registry")

# The registry template is shared, but only selected role-owned rows may remain.
# This is reconciliation within the existing canonical matrix, not a second
# registry. Preserve the generated-agent marker and explanatory prose.
registry_rel = ".agentic/guides/agent-registry.md"
if registry_rel in PENDING:
    registry_lines = []
    for line in current(registry_rel).splitlines(True):
        # Only remove orchestration matrix rows. Prose may mention an
        # unselected asset while still describing the shared architecture.
        if not line.lstrip().startswith("|"):
            registry_lines.append(line)
            continue
        assets = re.findall(r"`([^`]+)`", line)
        missing_selected_asset = False
        for asset in assets:
            if asset.startswith(".agentic/agents/"):
                name = asset.rsplit("/", 1)[-1].removesuffix(".md")
                missing_selected_asset |= "agents/" + name not in PRESET_TEMPLATE_IDS
            elif asset.startswith(".claude/commands/"):
                name = asset.rsplit("/", 1)[-1].removesuffix(".md")
                missing_selected_asset |= "commands/" + name not in PRESET_TEMPLATE_IDS
        # Skill-owned rows (SKILL.md Phase 4 step 4): the fixed cell shape
        # ``the agentic-sdlc `<name>` skill`` prunes against the union's
        # sdlc_skills, not template IDs.
        for skill in re.findall(r"agentic-sdlc `([a-z0-9-]+)` skill", line):
            missing_selected_asset |= skill not in PRESET_SDLC_SKILLS
        # Blueprint-owned rows: same contract, different sibling plugin. The
        # cell shape ``the agentic-qe `<id>` blueprint`` prunes against the
        # union's qe_blueprints.
        for bp in re.findall(r"agentic-qe `([a-z0-9-]+)` blueprint", line):
            missing_selected_asset |= bp not in PRESET_QE_BLUEPRINTS
        if missing_selected_asset:
            continue
        registry_lines.append(line)
    PENDING[registry_rel]["content"] = "".join(registry_lines)

# --- Phase 4 step 5: policies, guides, sdlc -----------------------------------
for name in ("ai-policy", "escalation-policy", "safety-policy"):
    copy_tpl("policy/%s.md.tmpl" % name, ".agentic/guides/policy/%s.md" % name, "policy/" + name)
GUIDE_IDS = {
    "git-workflow": "guides/git-workflow",
    "ba-po-operating-model": "guides/ba-po-operating-model",
    "code-quality": "guides/code-quality",
    "quality-gates": "guides/quality-gates",
    "instruction-quality-rubric": "guides/instruction-quality-rubric",
    "working-with-agents": "guides/working-with-agents",
    "evidence-integrity": "guides/evidence-integrity",
    "incident-triage": "guides/incident-triage",
    "threat-modeling": "guides/threat-modeling",
    "data-pipeline-design": "guides/data-pipeline-design",
    "experience-design": "guides/experience-design",
    "qa-strategy-stub": "guides/qa-strategy-stub",
    "test-design-pattern": "guides/test-design-pattern",
    "flaky-protocol": "guides/flaky-protocol",
    "mcp-onboarding": "guides/mcp-onboarding",
}
for g, tid in GUIDE_IDS.items():
    if tid not in PRESET_TEMPLATE_IDS:
        continue
    dest = ".agentic/guides/standards/%s.md" % g
    # Prefer a `.tmpl` source when one exists (quality-gates renders GATE_ENTRIES);
    # the rest are copied verbatim. Dest is always the bare `.md`.
    src = "guides/standards/%s.md" % g
    if not (TPL / src).exists():
        src += ".tmpl"
    # Existing-guide rule (skip + owner user) is the installer's preserve
    # decision for any pre-existing file; no special case is needed here.
    copy_tpl(src, dest, "guides/" + g)
copy_tpl("sdlc/config.json.tmpl", ".agentic/agentic-sdlc/config.json", "sdlc/config")
copy_tpl("sdlc/project.md.tmpl", ".agentic/guides/project.md", "sdlc/project")

# MCP setup is a guide in the same canonical standards directory, not a second
# onboarding layer. Keep its state visible in the generated project context so
# the readiness summary can distinguish connected, deferred, and unavailable.
project_rel = ".agentic/guides/project.md"
if project_rel in PENDING:
    project_body = current(project_rel)
    project_body += "\n\n## MCP readiness\n\n"
    project_body += {
        "without-mcp": "MCP status: without MCP. Continue with pasted tables, CSV extracts, screenshots, or Power BI findings.",
        "configured": "MCP status: configured. Verify with `cursor-agent mcp list` or `claude mcp list` before using connected business data.",
        "unavailable": "MCP status: unavailable. Continue without MCP and retry setup later; do not block requirements work.",
    }[MCP_STATE]
    # SKILL.md Phase 7 asks for "three first-task prompts appropriate to the role
    # set", and names the Excel/Power BI examples for `ba-po` specifically. Emitting
    # them for every preset put business-analysis prompts into developer, qa, devops
    # and architect scaffolds, where blind-graded candidates repeatedly and correctly
    # flagged them as wrong-preset content. Scope them to the roles the spec names;
    # the harness does not invent prompts for the others.
    if {"ba-po", "portfolio"} & set(PRESET_NAMES):
        project_body += ("\n\nFirst tasks:\n\n"
                         "- Turn this Power BI insight into a customer-ready requirement.\n"
                         "- Convert this Excel analysis into acceptance criteria.\n"
                         "- Prepare clarification questions for the customer and delivery team.\n")
    PENDING[project_rel]["content"] = project_body + "\n"

# --- Phase 4 step 7: core agents + pointers -----------------------------------
CORE_AGENTS = [("dispatcher", True), ("blind-code-reviewer", False),
               ("security-reviewer", True), ("instruction-auditor", True),
               ("pr-pipeline-gate", True), ("incident-triage", True),
               ("threat-modeler", False),
               ("pipeline-designer", False),
               ("experience-designer", False),
               ("test-case-generator", False),
               ("test-automation-author", False), ("test-case-syncer", False),
               ("test-failure-triage", True), ("work-item-creator", False)]
for name, ro in CORE_AGENTS:
    if "agents/" + name not in PRESET_TEMPLATE_IDS:
        continue
    subdir = "qa" if name in {"test-automation-author", "test-case-generator",
                              "test-case-syncer", "test-failure-triage", "work-item-creator"} else "core"
    copy_tpl("agents/%s/%s.md.tmpl" % (subdir, name), ".agentic/agents/%s.md" % name, "agents/" + name)
    tools = "Read, Grep, Glob" if ro else "Read, Grep, Glob, Edit, Write, Bash"
    ptr = ("---\nname: %s\ndescription: Pointer to the canonical %s contract.\n"
           "tools: %s\nmodel: inherit\n---\n\nRead `.agentic/agents/%s.md` — the canonical "
           "contract — and follow it exactly.\n" % (name, name, tools, name))
    write(".claude/agents/%s.md" % name, ptr, "derived")
    cmd = ("---\nname: %s\ndescription: Run the %s agent.\n---\n\n"
           "Read `.agentic/agents/%s.md` and execute its contract on the current context.\n"
           % (name, name, name))
    write(".claude/commands/%s.md" % name, cmd, "derived")

# commands (canonical in .claude/commands)
for command in ("pipeline-orchestrator", "dispatch"):
    tid = "commands/" + command
    if tid in PRESET_TEMPLATE_IDS:
        copy_tpl("commands/core/%s.md.tmpl" % command, ".claude/commands/%s.md" % command, tid)

# --- Phase 4 step 4 (apply): one journaled, compare-and-swap installer pass ----
# Answers first, so an interrupted run still leaves an uninstallable journal.
runtime("install.record", target=str(TARGET),
        fields={"answers": JOURNAL["answers"], "phase": "scaffold",
                "follow_ups": JOURNAL_PREV.get("follow_ups", [])})
runtime("install.apply", target=str(TARGET), agentic_os_version=VERSION,
        files=dict(sorted(PENDING.items())))
JOURNAL = json.loads(jpath.read_text())

# --- Phase 4 step 8: seed instruction scorecard -------------------------------
scorecard = {"schema": 1, "threshold": 95, "files": {}}
for rel in list(JOURNAL["files"]):
    p = TARGET / rel
    if rel.endswith(".md") and (
        rel.startswith(".agentic/agents/") or rel.startswith(".claude/agents/")
        or rel in ("CLAUDE.md", "AGENTS.md", "PATTERNS.md")
        or rel == ".agentic/guides/agent-registry.md"
        or rel.startswith(".agentic/guides/")):
        scorecard["files"][rel] = {"content_sha256": sha(p), "composite_score": 100,
                                   "source": "template-inherited"}
sc_path = TARGET / "docs/audits/instruction-scorecard.json"
sc_path.parent.mkdir(parents=True, exist_ok=True)
sc_path.write_text(json.dumps(scorecard, indent=2) + "\n")

# --- flaky ledger only for qa preset (not developer) --------------------------

print("refinstall: journaled %d files in %s" % (len(JOURNAL["files"]), TARGET))
