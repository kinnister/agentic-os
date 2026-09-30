# sdlc-brief

Fast lane for small, already-sized work: brainstorm, spec, plan, build, review, and gate a task in one inline pass, no scoring or dispatch overhead.

## Use It For
- Tasks you have already sized XS, S, or M — no complexity scoring, no per-task subagent dispatch, no evidence files.
- Small features, bug fixes, and follow-ups that don't justify the full pipeline's ceremony.
- Reconciling a task's `spec.md` and `plan.md` against code that already shipped, via `mode: sync`.

> Reach for the full pipeline (`sdlc-guided` for human-in-the-loop, `sdlc-auto` for hands-off) instead when a task needs complexity scoring or per-task subagent dispatch — this skill assumes that call is already made.

## How To Ask
- "Use sdlc-brief to add a cache-invalidation endpoint — this is an S."
- "sdlc-brief: fix the off-by-one in the export path, XS."
- "Run sdlc-brief in sync mode, I already merged the fix — reconcile spec and plan."

Default mode runs the fixed inline sequence: brainstorm-lite → spec → plan → inline TDD → one round of code review → quality gates. Pass `mode: sync` to skip the build sequence and instead reconcile existing artifacts against code changed after completion.

## What It Needs
| Requirement | Detail |
|---|---|
| Task size | XS / S / M, asserted by you — the skill does not compute it |
| Branch | Current feature branch; offers to cut one first if you're on the base branch |
| Companion plugin | `superpowers` plugin, version >= 6.1.0 |
| Optional guides | `.agentic/guides/` for commit conventions and quality-gate definitions — runs fine without it |
| Artifacts | `docs/superpowers/tasks/<slug>/spec.md` and `plan.md`, kept live through the run and reconciled in `mode: sync` |
