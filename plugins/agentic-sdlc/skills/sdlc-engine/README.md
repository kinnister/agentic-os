Orchestrates the full development lifecycle for a ticket or feature — from requirements intake through implementation, review, QA, and handoff — in one governed run.

## Use It For

Taking a ticket or feature description through every SDLC phase in a single pass: branch setup, sizing, spec, plan, TDD implementation, code review, QA gates, feature verification, and handoff. Every judgment gate along the way is approved and logged before the run advances, and the same phase sequence runs whether you're steering it live or letting it go autonomous — only how gates get approved differs. A run that stops partway (crash, closed session, manual interrupt) resumes at the last completed phase instead of starting over.

> This skill does not take direct requests. It is the machinery behind `sdlc-guided` and `sdlc-auto` — invoke one of those instead.

## How To Ask

Ask for one of the two entry points, not this skill by name:

| You want | Ask for |
|---|---|
| Approve each phase gate yourself as the run proceeds | `sdlc-guided` |
| Let the run proceed end-to-end without stopping for approval | `sdlc-auto` |

Either one normalizes your request into a working ticket or feature description, then hands off to this skill automatically.

## What It Needs

Checked before a run starts:

| Requirement | Detail |
|---|---|
| Guide files | `.agentic/guides/project.md`, `.agentic/guides/git-workflow.md`, `.agentic/guides/quality-gates.md` |
| Guide source | produced by the `repo-guides` skill |
| superpowers plugin | version `6.1.0` or newer |
| Checkout | a feature branch checked out in the current directory — not a git worktree |

> Missing guide files: run `repo-guides` first. Outdated superpowers: update the plugin. Working from a worktree: switch to the real checkout — this skill will not start there.
