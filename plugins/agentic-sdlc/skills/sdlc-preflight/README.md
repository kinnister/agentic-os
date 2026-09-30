# SDLC Doctor

Force-check the local environment the agentic-sdlc plugin needs, and rewrite the cached report so every other tool reads current results, not stale ones.

## Use It For

- Verifying a freshly set-up machine before your first SDLC run.
- Diagnosing why an SDLC run failed to start.
- Re-checking prerequisites after upgrading the superpowers plugin or Node.js.

## How To Ask

Ask directly — no arguments needed:

- "run sdlc doctor"
- "check my agentic-sdlc prerequisites"
- "verify my environment for agentic-sdlc"
- "re-run doctor after the upgrade"

Every invocation force-runs all three checks and overwrites the cache. There is no incremental or read-only mode — if you only want to inspect the last result, read the cache file directly instead of invoking the skill.

## What It Needs

Nothing from you. It inspects the local environment directly:

| Check | Requirement |
|---|---|
| superpowers plugin | installed and resolvable, superpowers plugin >= 6.1.0 |
| Node.js | any recent LTS release |
| Git | installed |

> The superpowers plugin gate is the only hard version floor. Node.js and Git are presence checks — any recent LTS of Node.js passes, and Git just needs to be on your PATH.

Results land in `.agentic/agentic-sdlc/doctor.json`, replacing the previous contents. Treat that file as the current snapshot, not a history — this skill does not tell you how to fix a failing check, only what failed.
