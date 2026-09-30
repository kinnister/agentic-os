# SDLC Start (HITL)

Opens an agentic-sdlc run that keeps you in the decision seat. Wherever the
pipeline reaches a judgment it cannot make on evidence alone — is this spec
right, is this plan right, does this review pass, has QA drifted — it stops and
asks you before going on.

The skill itself is only a doorway. It reads what you asked for, normalizes it,
and hands it to `sdlc-engine`; the run directory, the ledgers and every phase
document belong to the pipeline from that point on. If the host cannot invoke
`sdlc-engine`, this skill reports that and stops — it will not improvise the
pipeline by hand.

## Use It For

- Work you want to steer: you review the spec and the plan before code appears.
- Turning a tracker item, a story file, or a paragraph of prose into a real run.
- Changes where a wrong assumption is expensive and worth catching at a gate.
- Standing up something new from scratch, checkpoint by checkpoint.

## How To Ask

Examples:

- "Take PROJ-812 through SDLC."
- "Run this through SDLC with me approving the plan."
- "Start an SDLC run for the session-expiry bug."
- "Use sdlc-guided with --greenfield 'small Go service that signs webhooks'."

## What It Produces

Nothing directly — that is the point. The pipeline it delegates to produces the
run directory and its artifacts, beginning at Phase 0.

## What It Needs

- A repo-guides baseline under `.agentic/guides/` — at minimum `project.md`,
  `git-workflow.md` and `quality-gates.md`. Run `repo-guides` first if it is
  missing; the pipeline will halt and tell you so anyway.
- The superpowers plugin, 6.1.0 or newer.
- Either a feature branch to work on, or a base branch to cut one from.
