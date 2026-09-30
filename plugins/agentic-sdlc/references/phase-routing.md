# Phase-Set Routing (work-type classification)

A hotfix, a spike, and a story should not pay for the same 13-phase pipeline.
Classification picks the **phase set** a run executes; complexity scoring
(Phase 3) still routes *within* it. This bounds the Tasks factor of the cost
model (`references/tokenomics.md`) and is orthogonal to mode routing
(`references/mode-routing.md`, which picks who resolves gates) and to the V2
adaptive-mode roadmap item.

Identifiers, phase sets, and defaults are defined only in `runtime/agentic_runtime/registry.json`;
see generated `references/runtime-contracts.md`. This table is an explanatory mirror.
The bundled runtime offers contract inspection only; unavailable managed lifecycle operations block.

## Classification table

| Classification | Phase set (of 0–12) | Skipped | Parallel-worker ceiling |
|---|---|---|---|
| `story` (default) | all | — | 3 (subject to safety preconditions) |
| `bug` | 0,1,2,3,5,6,7,8,9,10,11,12 | 4 (spec) | 2 |
| `hotfix` | 0,1,2,3,5,7,9,10,12 | 4 (spec), 6 (qa-checklist), 8 (test review), 11 (qa health) | 1 |
| `spike` | 0,1,4,12 | everything that ships code | 1 |
| `epic` | 0,1 + decomposition | — | children run sequentially, one run at a time |

Rules the table encodes:

- **Nothing skips verification.** Any phase set that reaches implementation
  keeps Phase 9 (code review) and Phase 10 (gate-runner + acceptance-check).
  A hotfix trades design ceremony for speed, never proof.
- **Spike ships no code.** Phase 4 runs unconditionally (the spike *is* the
  brainstorm) and its `design.md` is the deliverable; Phase 12 handoff prints
  the findings and opens no MR. No feature branch, no complexity scoring.
- **Epic decomposes, never implements.** After Phase 1, invoke the
  `story-author` skill to break the epic into child stories (each becomes a
  local work item); the epic run's handoff lists the children. Each child is
  its own full run with its own run identity. Separate export directories do not provide checkout isolation;
  children run **sequentially** by default to bound cost and keep review load sane.
- **Complexity routes within the set.** For `story`, Phase 3 still skips
  Phase 4 below score 15, exactly as before. For `bug`/`hotfix`, Phase 4 is
  skipped by classification regardless of score — but a `split-required`
  verdict still halts the run.
- **The ceiling is a maximum, not a target.** `parallelism-safety.md` rules
  (disjoint ownership, independent verification) still decide whether any
  parallelism is used at all.

## Classification procedure (Phase 1, heuristics first)

Derive a candidate from `requirements.md` with cheap signals, cheapest-first —
the same pattern Phase 3 uses:

1. `spike` — the goal asks to investigate/research/evaluate/compare/prototype
   and defines no shippable behavior change.
2. `hotfix` — production-incident language (outage, regression in production,
   urgent/sev keywords) AND single-fault scope.
3. `bug` — defect language (fix, broken, regression, incorrect behavior)
   against existing behavior.
4. `epic` — multiple independently shippable deliverables (several distinct
   goals or acceptance-criteria clusters).
5. Otherwise `story`.

Then confirm through the `classification.confirm` gate (`gate-arbiter`):
HITL always puts the candidate + phase-set consequence in front of the user;
autonomous checks mandatory escalation policy before fast-pathing a high-confidence candidate and escalates a low-
confidence one. **The user's override always wins.** Record the verdict like
any other gate through the coordinator-owned runtime decision operation, when available.

## Run-state effects (intended lifecycle contract)

- The database `.agentic/state/runtime.sqlite3` is the intended authority once persistence is implemented.
  `.agentic/runs/<run-id>/` exports are regenerable views; human specifications and plans
  remain in `docs/superpowers/`.
- Persist the confirmed classification and phase set through runtime operations, including
  skipped phases. Never mutate `meta.json` to implement a transition.
- Run states are `pending`, `running`, `waiting_for_user`, `interrupted`,
  `reconciliation_required`, `completed`, `failed`, and `cancelled`; allowed transitions
  come from the registry.
- A changed classification requires a coordinator-recorded human decision and explicit
  reconciliation or a new run. Missing lifecycle operations block; The current bundle does not yet
  implement managed initialization, reclassification, or resume.
