# agentic-sdlc — Bundle Inventory

`agentic-sdlc` packages a full delivery lifecycle — idea/ticket through spec, plan, TDD
implementation, code review, QA, and functional verification — as a set of skills for coding
agents. Every run mode stops at a review-ready branch; opening the pull/merge request is a
separate, explicit step performed by a human or an adapter skill, never automatic.

> At every judgment point, run the cheapest deterministic check first. Escalate to a subagent
> only when neither a structural check nor a fast-path approval can resolve the gate.

## Prerequisite

Install and version-check the shared skill-infrastructure plugin before this one loads. Required
version: **≥ 6.1.0**.

```
/plugin marketplace add <prerequisite-plugin-source>
/plugin install superpowers
/plugin marketplace add <this-project's-marketplace-source>
/plugin install agentic-sdlc@agentic-os
```

Verify the environment once installed:

```
Use the sdlc-preflight skill
```

The same commands and skill-use phrasing apply unmodified under Claude Code and Codex CLI —
nothing in this bundle forks by host.

## Entry points

Pick one run mode per unit of work; sizing and risk tolerance decide which.

| Skill id | Mode | When to reach for it |
|---|---|---|
| `sdlc-guided` | Full HITL | Production, brownfield, or regulated changes — every judgment gate stops for human approval. |
| `sdlc-auto` | Autonomous | Greenfield POCs, well-scoped tickets, batch runs — stand-in agents resolve gates, with an escalation safety net on low confidence/risk. |
| `sdlc-brief` | Lightweight | XS/S/M tasks — inline TDD, one review round, minimal artifacts. |
| `sdlc-direct` | Lightest | Research-first flow with no spec phase, for work too small to justify `sdlc-brief`'s round-trip. |
| `sdlc-runs` | Utility | List, inspect, or resume in-flight runs. |
| `sdlc-preflight` | Utility | Environment check — confirms the prerequisite plugin, toolchain, and guide bootstrap are in place. |

First-run sequence:

```
Use the repo-guides skill
Use the sdlc-guided skill for "add SAML SSO provider"
Use the sdlc-auto skill for PROJ-12345
Use the sdlc-brief skill for "add email validator to signup"
Use the mr-submit skill
```

## Orchestration core

Skills invoked by the entry points rather than called directly by a user.

| Skill id | Role |
|---|---|
| `sdlc-engine` | Heavy-flow orchestrator behind `sdlc-guided` and `sdlc-auto`; drives phases end to end and persists deterministic artifacts so a crashed run can resume. |
| `story-intake` | Normalizes whatever the user handed in — free text, ticket link, idea — into `requirements.md`. |
| `effort-sizing` | Scores task complexity and routes simple work past the spec-writing phase entirely. |
| `gate-arbiter` | Resolves judgment gates in order: deterministic check → fast-path approval → subagent stand-in. Hands any `code-review.*` gate to `code-review-orchestrator` instead of handling it generically. |
| `code-review-orchestrator` | Runs three review lenses as parallel subagents (blind, edge-case, acceptance — defined in its own `references/review-lenses.md`), adjudicates against standards and security, and persists the verdict to `code-review-final.json`, satisfying the `code-review.final` gate. |
| `code-review` | Standalone, user-facing review for ad hoc use outside a managed run. |
| `gate-runner` | Detects the project's package manager and runs lint/type/test/build in sequence. |
| `acceptance-check` | Functional proof for user-visible changes — screenshots, console errors, network failures — rather than assuming a UI change works. |
| `role-memory` | Persistent per-role memory carried across runs. |

## Auxiliary skills

Supporting and standalone skills, invoked on demand rather than embedded in a pipeline phase.

| Skill id | Role |
|---|---|
| `repo-guides` | Bootstraps project, standards, and quality-gate guides for a repo new to the plugin. |
| `repo-audit-guides` | Re-audits and refreshes those guides as the repo evolves. |
| `story-author` | Drafts a ticket-ready story from a raw idea. |
| `mr-submit` | Opens the MR/PR through a platform adapter — no source-control platform hardcoded. |
| `mr-watch` | Monitors an open MR/PR's status after creation. |
| `release-manager` | Cross-references commits against tickets across repos. |
| `qa-case-generator` | Ticket ID → manual/API test cases. Standalone; never auto-invoked by the pipeline. |
| `qa-e2e-generator` | Ticket ID → automated E2E scripts via an 11-phase pipeline. Standalone; never auto-invoked by the pipeline. |
| `telemetry-export` | Projects a run's governance ledgers (`events.jsonl`, `decisions.jsonl`) into redacted NDJSON and hands them to a host-declared observability backend. No-op absent a configured profile in `.agentic/guides/integration/telemetry-flow.md`; never wired as a hook by this bundle itself. |

> `qa-case-generator` and `qa-e2e-generator` sit outside the managed run by design — call them
> directly for their output, not as a side effect of `sdlc-guided` or `sdlc-auto`.

## Stand-in agents (autonomous mode only)

Autonomous mode resolves gates through these agents when `gate-arbiter`'s deterministic and
fast-path checks can't decide. Full HITL mode never calls them — a human resolves every gate
instead.

| Agent id | Resolves |
|---|---|
| `story-proxy` | Ambiguous requirements — feeds the `requirements.ambiguous` gate. |
| `lead-proxy` | Spec/plan approval, drift watch, and verification-evidence review — feeds `spec.approved`, `plan.approved`, and `qa.drift`. |
| `sizing-analyst` | Boundary-case scope decisions that `effort-sizing`'s heuristic can't settle on its own. |
| `guide-sync` | Post-merge — promotes lessons captured in `role-memory` into curated guides for future runs. |

> `role-memory` and `guide-sync` form a closed loop: memory captured mid-run is later distilled
> into guides that the next run's `repo-guides`-bootstrapped context consumes.

## Hooks

| Hook id | Event | Behavior |
|---|---|---|
| `ticket-sync` | Stop / SubagentStop (async) | Transitions the external ticket via the adapter configured in `.agentic/guides/integration/ticket-flow.md`. Managed SQLite runs require coordinator-fenced `scripts/external-action.py` intent/reconciliation; without that context the hook fails closed. No mapping file → no-op; `repo-guides` offers to create one when it's missing. |
| `sdlc-stage-guard` | PostToolUse(Skill) | Informational only. After a skill completes mid-run, injects current stage/phase and next-step guidance. Never blocks a tool call or forces a retry. |
| `usage-sampler` | SubagentStop (async) | Samples the completed subagent's own isolated token usage and appends a normalized `usage.sampled` event to the run's `events.jsonl`. Only fires while the newest run's `meta.json` reports status `running`; every failure path is swallowed and the hook always exits 0. |

## Gate resolution order

Applies at every judgment point across all three modes:

1. **Deterministic structural check** — e.g., does a failing-test-then-passing-test trail exist for this task?
2. **Fast-path approval** — if the cheap check above passes cleanly, approve without further work.
3. **Subagent invocation** — only if neither of the above resolves the gate, hand off to the relevant stand-in.

`code-review.*` gates are the one carve-out: `gate-arbiter` routes them straight to
`code-review-orchestrator`, which runs its own three-lens adjudication instead of the generic
three-step order above.

## Artifacts

| Path | Written by | Purpose |
|---|---|---|
| `requirements.md` | `story-intake` | Normalized input for the run. |
| `design.md` | pipeline phases | Design decisions for the run. |
| `plan.md` | pipeline phases | Task breakdown and sequencing. |
| `code-review-final.json` | `code-review-orchestrator` | Persisted three-lens verdict. |
| `references/review-lenses.md` | `code-review-orchestrator` | Canonical definitions of the blind/edge-case/acceptance lenses; owned and read by the orchestrator itself. |
| `.agentic/guides/integration/ticket-flow.md` | `repo-guides` (on request) | Ticket-flow mapping consulted by `ticket-sync`. |
| `scripts/external-action.py` | runtime boundary | Records and reconciles coordinator-fenced external adapter effects for managed runs. |

All phase artifacts persist under `.agentic/` and `docs/superpowers/`, alongside the
`decisions.jsonl` and `events.jsonl` audit ledgers, so a run can resume after a crash without
re-deriving prior gate outcomes.

## QA runner coverage

`gate-runner` detects the project's package manager without hardcoding a stack. Supported tokens:
**npm / pnpm / yarn / cargo / poetry / uv / go**.

## Blast-radius tags

Skills and hooks in this bundle tag their own operations so a reviewer can scan intent at a
glance: **R0** read-only, **R1** run-artifact writes, **R2** repo file writes, **R3** external
side-effects — always behind a gate.

## Model tiers

Subagent calls (stand-ins, review lenses) select from **economy / standard / premium** tiers
rather than pinning a specific model version.

## Non-goals

- No mode merges automatically. MR/PR creation is `mr-submit`'s job; merging is left to a human or an adapter skill.
- No source-control platform, ticket backend, or test-case-management tool is hardcoded — every such integration is adapter-driven, configured per repo under `.agentic/guides/`.
- `qa-case-generator` and `qa-e2e-generator` never run automatically as part of a pipeline phase.
- Full HITL mode never substitutes automation for human judgment — every gate requires explicit approval.
