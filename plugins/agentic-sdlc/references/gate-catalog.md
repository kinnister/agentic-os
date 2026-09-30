# Gate Catalog

Gate IDs, phase IDs, loop IDs, retry budgets, and defaults come exclusively from
`runtime/agentic_runtime/registry.json` (the plugin-local bundle matches the repository runtime).
`references/runtime-contracts.md` is its generated reference; this catalog explains routing.
Tables below mirror the registry and do not independently define contracts.

The bundled runtime implements contract validation only. Managed lifecycle mutations
are not yet implemented. If an operation
is unavailable, block with that limitation; never simulate it with JSON/JSONL writes.
The intended authority is `.agentic/state/runtime.sqlite3`; `.agentic/runs/<run-id>/`
contains regenerable exports. Human specs and plans remain under `docs/superpowers/`.

Deterministic evidence checks run first. Mandatory escalation policy must be evaluated before
any approval fast path. Only the coordinator resolves gates; resolver and review workers advise.

## Resolver routing by mode

Mode sets the default routing for every gate:

- **HITL** — unresolved judgment goes to the user, directly. No fast path, no stand-in substitution.
- **Autonomous** — unresolved judgment routes through `gate-arbiter`, which applies deterministic
  checks, mandatory escalation policy, and eligible fast-path approvals, and only falls back to a named stand-in resolver when
  neither closes the case.

Two advisory-routing shapes appear in the table below and they are not interchangeable:

| Shown as | HITL | Autonomous |
|---|---|---|
| `human` or `lead-proxy` | user, asked directly | `gate-arbiter`, falling back to `lead-proxy` when it can't fast-path |
| `human` (HITL) or `gate-arbiter` (autonomous) | user, asked directly | `gate-arbiter` itself is terminal — no separate stand-in named |

> `classification.confirm` is the one gate where the *routing* is conditional, not just the resolver
> identity: HITL always asks the user regardless of confidence; autonomous only fast-paths through
> `gate-arbiter` when confidence is high and mandatory escalation does not apply. A user override on this gate wins in either mode — it
> is never fast-pathed shut against an explicit human answer.

All rows describe evidence routing; the coordinator retains resolution authority.

## Judgment gates

| Gate | Phase | Advisory route | Artifact Inputs | Blocking Conditions |
|---|---|---|---|---|
| `requirements.ambiguous` | 1 | `gate-arbiter` | `requirements.md` | Unanswered required scope or acceptance questions |
| `classification.confirm` | 1 | `gate-arbiter` (HITL always asks; autonomous fast-paths after escalation checks on high confidence) | `requirements.md`, classification candidate, phase-set consequence | Low-confidence candidate; user override always wins |
| `spec.clarification` | 4 | `gate-arbiter` | Brainstorming question context | Unclear product or technical decision |
| `spec.approved` | 4 | human or `lead-proxy` | `requirements.md`, `design.md` | Rejected design; missing required constraints |
| `plan.approved` | 5 | human or `lead-proxy` | `design.md`, `plan.md` | Missing test-first task lines; unsafe plan |
| `qa-checklist.approved` | 6 | human (HITL) or `gate-arbiter` (autonomous) | `qa-checklist.md` | Unresolved high-risk gaps with no test scenario |
| `qa-tests.approved` | 8 | human (HITL) or `gate-arbiter` (autonomous) | `qa-test-review.md` | Missing high-risk scenarios; high-severity quality findings |
| `code-review.final` | 9 | `code-review-orchestrator` (skill, inline) | Review bundle, diff, evidence summaries | Critical or major review findings |
| `code-review.check` | 9 | `code-review-orchestrator` (skill, inline) | Prior verdict, original findings, fix-up diff | Unresolved finding; new high-risk regression |
| `qa.drift` | 10 | human or `lead-proxy` | `qa-report.md`, `design.md`, diff summary | Implementation drift from approved artifacts |
| `feature.verification` | 10 | deterministic evidence check, then human or `lead-proxy` | Browser/tool evidence | Missing or blocking user-visible proof |

`code-review.final` and `code-review.check` use inline `code-review-orchestrator`
reports as advisory evidence. The coordinator resolves and records the gate through
`gate-arbiter`; HITL requires the user's answer and autonomous mode enforces escalation policy.

> `feature.verification` is two-stage: the deterministic evidence-shape check runs first (did the
> required browser/tool evidence get produced at all), and only a *present-but-questionable* result
> escalates to human or `lead-proxy` judgment. A missing artifact never reaches that second stage —
> see Cross-cutting rules below.

## Loop accounting

Retry counts belong to the intended runtime database, never authoritative export files.
Each cap is the maximum retries **after the initial attempt**. Evaluate success first;
exhaustion prevents a new attempt and never invalidates a successful final attempt.
User-requested reruns consume the same budget. Further attempts require an explicit,
recorded budget increase; resuming does not reset counters.

| Loop ID | Phase | What Loops | Maximum retries | On Cap |
|---|---|---|---|---|
| `spec.revision` | 4 | `spec.approved` request-changes → `superpowers:brainstorming` | 3 | `halt` |
| `plan.revision` | 5 | `plan.approved` request-changes → `superpowers:writing-plans` | 3 | `halt` |
| `evidence.retry:<task-id>` | 7 | Deterministic evidence failure → task retry | 2 | `escalate` |
| `qa-test-review.retry` | 8 | Test-review request-changes → fix-up task | 1 | `escalate` |
| `code-review.fixup` | 9 | Review findings → fix-up task | 2 | `halt` |
| `gate-runner.retry` | 10 | Failed gate → autonomous fix-up task | 2 | `escalate` |
| `acceptance-check.retry` | 10 | Blocking verification → fix-up task | 2 | `escalate` |
| `arbiter.malformed.retry` | any gate | Malformed resolver output → retry | 1 | `escalate` |

`evidence.retry:<task-id>` is a template — `<task-id>` is a placeholder segment, one counter per
task, not one counter for the whole phase.

### On-cap behavior

| Behavior | Effect |
|---|---|
| `halt` | Coordinator records `interrupted` in the runtime and prints the resume instruction when lifecycle operations exist. |
| `escalate` | HITL: put the full loop history in front of the user for a decision. Autonomous: hand off through the escalation ladder (a separate, named concept — not detailed in this catalog). |

When a failed attempt needs another retry but its budget is exhausted, record exhaustion
and apply `on_cap`. Never start an extra retry or reject success just because its retry
number equals the cap. Unavailable recording operations block progression.

## Cross-cutting rules

- **Evidence shape is deterministic, always.** Malformed or missing required evidence artifacts are
  blockers decided by a script, never routed to `gate-arbiter`, a human, or a stand-in — a
  shape failure is data, not judgment.
- **User-visible changes need proof.** A user-visible change cannot proceed to handoff without
  `feature.verification` evidence, unless the coordinator has recorded an authorized substitute for it.
- **MR/PR creation is not a gate.** It is a distinct, non-gated action. No gate in this catalog
  triggers it automatically, and it is never invoked as a side effect of gate resolution.

## Out of scope

- The internal decision logic of `gate-arbiter`, `code-review-orchestrator`, and `lead-proxy` —
  this catalog names what each is invoked for, not how it decides.
- The autonomous-mode escalation ladder referenced above — defined elsewhere.
- MR/PR creation mechanics.
- Phase numbering/ordering semantics beyond the phase number attached to each row.
- UI/prompt wording for human-facing approval requests.
