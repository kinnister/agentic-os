# agentic-os

[![CI](https://github.com/kinnister/agentic-os/actions/workflows/ci.yml/badge.svg)](https://github.com/kinnister/agentic-os/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Install: Claude Code plugin](https://img.shields.io/badge/install-Claude%20Code%20plugin-5A2EBB)](#install)
[![Install: Cursor plugin](https://img.shields.io/badge/install-Cursor%20plugin-000000)](#install)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

**Turn your repo into a governed multi-agent setup in one interview** — scoped
agent contracts, enforcement hooks (not just prompts), and optional SDLC
orchestration. Works in Claude Code and Cursor; the SDLC pipeline
(**agentic-sdlc**) also runs in Codex.

### In plain words

You install two plugins into your AI coding editor (Claude Code or Cursor).
The first, **agentic-os**, sets up guardrails for AI agents in your project:
what files they may touch, when they must stop and ask a human, and how their
work gets independently reviewed before anything is committed. The second,
**agentic-sdlc**, runs a software-delivery pipeline on top of those
guardrails: it takes an idea or a ticket and carries it through requirements,
a spec, a plan, tested code, and a review-ready pull request. You don't need
to be a programmer to benefit — there are role setups for developers, QA,
architects, DevOps, business analysts, project/portfolio managers, security
engineers, data engineers, and designers, and the non-coding roles work
entirely through plain chat phrases. Unfamiliar
terms (HITL, gate, preset…) are one-liners in the [Glossary](#glossary).

## Start here

> **Prefer a walk-through?** The **[role-based setup guides](https://kinnister.github.io/agentic-os/setup/)**
> cover the same install for every role preset — pick your role (developer, QA,
> BA/PO, architect, DevOps, PM, portfolio, security, data, design) and follow
> the checklist, quick or fully guided.

**New to this repo?** You do not need to read everything below. Pick a path:

| Your goal | Install from marketplace | First command in *your* project |
|-----------|--------------------------|----------------------------------|
| **Governed agents in my repo** — scoped writes, blind pre-commit review, role presets, stack agents | **agentic-os** + **agentic-sdlc** + [**superpowers**](https://github.com/anthropics/claude-plugins-official) (≥ **6.1.0** — enforced by `/agentic-init`; see `plugins/agentic-os/manifest/dependencies.json`) | Choose roles: `/agentic-init --presets ba-po` → `/agentic-doctor` |
| **SDLC pipeline on top** — spec → plan → TDD → QA (`/sdlc-guided`, `/sdlc-auto`, …) | Same three plugins (pipeline skills ship in **agentic-sdlc**) | After init: `/sdlc-guided <task>` or run **sdlc-preflight** |
| **QE AI blueprints** — 28 QE methodology blueprints, scaffold an agent framework from one, or set up evals for skills/agents | **agentic-qe** (works alone — no `/agentic-init` needed; composes with the other two when they are installed) | Ask e.g. *"scaffold the bug-reporting blueprint for Claude Code"* or *"set up evals for my skills"* |

**Five-minute flow (any editor):**

1. [Install the plugin(s)](#install) for your editor (Claude Code or Cursor).
2. Open the **git repo you want to improve** (not this marketplace repo).
3. Run `/agentic-init --presets <role[,role...]>` (or `/agentic-init` for the full role-selection interview).
4. Run `/agentic-doctor` — expect `passed: true` in `.agentic/agentic-os/doctor.json`.
5. `git status` — review scaffolded files; nothing is committed for you.
6. If you use the SDLC pipeline, run **sdlc-preflight** — expect `passed: true` in
   `.agentic/agentic-sdlc/doctor.json`.

**Safe first try:** use the [throwaway repo walkthrough](#try-it-in-two-minutes-throwaway-repo) before touching a real project.

### Full install checklist

Complete this **before** `/agentic-init` in the repo you want to equip:

| # | Requirement | How to check |
|---|-------------|--------------|
| 1 | **Claude Code** or **Cursor** | Editor running with plugin support |
| 2 | **`python3`** 3.10 or newer on PATH | `python3 --version` — enforcement hooks and the installer runtime are Python; the 3.9 bundled with macOS is too old |
| 3 | **`git`** | Target directory is a git repo (`git status`) |
| 4 | **`node`** on PATH | `node --version` — checked by **sdlc-preflight** when using **agentic-sdlc** |
| 5 | **`superpowers`** plugin ≥ **6.1.0** | [Install superpowers](#install-superpowers) |
| 6 | **`agentic-os`** custom marketplace added | [Install](#install) for your editor |
| 7 | **`agentic-os`** + **`agentic-sdlc`** plugins installed | Both cards/skills visible after reload |
| 8 | **`gh`** (optional) | Only for GitHub ticket/MR adapters |

**After equip — which doctor?**

| Check | When | Output |
|-------|------|--------|
| `/agentic-doctor` | After `/agentic-init` or `/agentic-upgrade` | `.agentic/agentic-os/doctor.json` — manifest, hooks, dependencies, scorecard |
| **sdlc-preflight** skill | Before `/sdlc-guided` or other SDLC skills | `.agentic/agentic-sdlc/doctor.json` — superpowers, `node`, `git` |

> **Cursor users:** this plugin is **not** in Browse Marketplace → All (curated
> public plugins only). You add a **custom marketplace** and install from the
> **User** tab — see [Cursor install](#cursor).

## Why this exists

Left alone, multi-agent coding fails in a few specific, recurring ways: an
agent's write scope silently creeps into files it wasn't asked to touch; an
agent reviewing its own work rationalizes away the gaps it should have
caught; "autonomous mode" is a blunt on/off switch instead of a resolution
strategy sized to each decision's actual risk; and stack facts get re-guessed
from scratch every session, with nothing stopping a Postgres-flavored rule
from leaking into a MongoDB agent's contract. `agentic-os` closes each of
those with a mechanism that's enforced, not just requested in a prompt — see
[`docs/PRINCIPLES.md`](docs/PRINCIPLES.md) for what each one does and why a
plain agent session doesn't already have it.

## What it is

`agentic-os` packages that governance layer as an installable system. One
command interviews you (role, autonomy level, stack) and scaffolds a coherent
system into your project: canonical agent contracts, enforcement hooks (blind
pre-commit review, write-scope guard, instruction-quality spawn gate), a
human-in-the-loop escalation ladder, and — where it fits your stack — generated
stack-specific agents. It is **stack-universal**: six curated profiles
(Next.js, Django, Spring, Rails, Go, Playwright) are recognized instantly,
and anything else — a NestJS backend, a schemaless Mongo service, or no code
stack at all — gets real, evidence-grounded persistence and API agents via
live repo discovery instead of a degraded stub (proven live against both a
migration-managed and a schemaless non-curated backend — see
`tests/universal/README.md`). Frontend/UI generation on a non-curated stack
uses the same discovery mechanism but is earlier in its own verification
cycle. It is also role-agnostic
(developer, QA, BA/PO, architect, delivery).

Today it's delivered as a Claude Code and Cursor plugin (the agentic-sdlc
pipeline additionally ships Codex packaging) — that's the install mechanism,
not the architectural boundary: the scaffolded contracts are harness-neutral
by design (thin per-host pointer files over a canonical, host-independent
body).

This repo is a **marketplace** (Claude Code and Cursor) hosting three plugins:

- **`agentic-os`** — the product: the `/agentic-init`, `/agentic-doctor`, and
  `/agentic-upgrade` skills plus the template library, generators, and role
  presets they scaffold from.
- **`agentic-sdlc`** — the SDLC pipeline and the **gate-arbiter** that
  resolves every judgment gate (ask the human in HITL mode; deterministic →
  fast-path → stand-in subagent → escalate in autonomous mode) with a full
  `decisions.jsonl` audit trail. For an interactive visual map of the whole
  pipeline, open
  [`plugins/agentic-sdlc/sdlc.html`](plugins/agentic-sdlc/sdlc.html) in a
  browser.
- **`agentic-qe`** — a tool-agnostic catalog of Quality Engineering AI
  blueprints (28, organized by STLC stage) plus two skills: `qe-blueprints`
  scaffolds a ready-to-fill agent framework from a chosen blueprint, and
  `eval-harness` generates a two-layer evaluation framework for skills and
  agents. `/agentic-init` is never required — but when the governance layer
  *is* present, `qe-blueprints` detects it and adapts, writing contracts where
  the write-scope guard and instruction gate can see them instead of alongside
  the installer's own files. Composes when governed, stands alone when not.

There's also **`mcp/`** — a read-only MCP server that serves this same
governance/SDLC/QE methodology to hosts that don't speak the Claude Code or
Cursor plugin format (any MCP-capable client). It's a separate package with its
own build, published on npm and the MCP Registry; see
[`mcp/README.md`](mcp/README.md).

### Use it from any MCP client

Don't use Claude Code or Cursor? The same methodology is a published MCP server —
your assistant can search the docs, list the role presets and QE blueprints, turn
a role into an install plan, and audit an existing install, all read-only:

    claude mcp add agentic-os -- npx -y agentic-os-mcp

Works in any MCP-capable assistant. See [`mcp/README.md`](mcp/README.md) for
per-role examples and the full tool list.

**Which plugin?** For the governed platform, install **agentic-os** +
**agentic-sdlc** plus **superpowers**: `agentic-os` is the installer/governance
layer, `agentic-sdlc` is the SDLC orchestrator, and `/agentic-init` wires them
together and registers missing dependencies in Phase 3 if any are absent.
**agentic-qe** is optional and installs with or without the other two: alone it
is the QE blueprint catalog and scaffolder, and inside a governed repo it
detects the install journal and writes into the governed paths instead.

**Why separate plugins, not one?** The governance layer and the pipeline have
different lifecycles and different audiences: agentic-os scaffolds *into your
repo* once and evolves with your codebase, while agentic-sdlc is a set of
runtime skills you invoke per task — and some teams want the guardrails
without the pipeline (or, on Codex, the pipeline alone). agentic-qe is separate
again: a knowledge-and-scaffolding add-on with no dependency on the other two.
Splitting them keeps each independently versioned, upgraded, and installable.

> `/agentic-init` Phase 3 treats **agentic-sdlc** and **superpowers** as
> **non-optional** (`plugins/agentic-os/manifest/dependencies.json`). Install
> all three up front to avoid a pending-restart loop.

## Prerequisites

- **Claude Code** or **Cursor** — see [Install](#install). This is a custom
  plugin marketplace; you add it once per editor, then equip projects with
  `/agentic-init`.
- **`python3`** on your PATH — enforcement hooks are Python scripts.
- **`git`** — the target repo must be a git repository (`/agentic-init` can
  `git init` if it is not).
- **`node`** on your PATH — required when using **agentic-sdlc**; **sdlc-preflight**
  runs `node --version` and `git --version` (`plugins/agentic-sdlc/skills/sdlc-preflight/SKILL.md`).
- **`superpowers`** ≥ **6.1.0** and **`agentic-sdlc`** ≥ **0.4.4** — required
  by `/agentic-init` (`plugins/agentic-os/manifest/dependencies.json`).
- Optional: **`gh`** (GitHub CLI) for GitHub ticket/MR adapters.

## Install

### Install superpowers

`/agentic-init` and **agentic-sdlc** require the **superpowers** plugin ≥
**6.1.0** (`plugins/agentic-os/manifest/dependencies.json`). Install it
**before** equipping a target repo.

**Claude Code:**

```
/plugin install superpowers@claude-plugins-official
```

If that marketplace is missing, add it first:

```
/plugin marketplace add anthropics/claude-plugins-official
/plugin install superpowers@claude-plugins-official
```

Fallback marketplace (same plugin family):

```
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

**Cursor:**

1. **Customize → Plugins → Browse Marketplace → All** → install **Superpowers**
   (curated public plugin), **or**
2. Install superpowers in Claude Code and enable **“Automatically import agent
   configs from other tools”**, then reload Cursor.

Confirm version ≥ 6.1.0 on the plugin card or via **sdlc-preflight** after equip.

### Claude Code

Install **superpowers** ([above](#install-superpowers)), then add this marketplace:

```
/plugin marketplace add kinnister/agentic-os
/plugin install agentic-os@agentic-os
/plugin install agentic-sdlc@agentic-os
```

Or try it straight from a local clone, no publish needed:

```
git clone https://github.com/kinnister/agentic-os
# in Claude Code:
/plugin marketplace add /absolute/path/to/agentic-os
/plugin install agentic-os@agentic-os
/plugin install agentic-sdlc@agentic-os
```

**Restart the session** so the plugins load (Claude Code activates plugins at
session start).

### Cursor

`agentic-os` is a **custom marketplace**, not a curated Cursor Store listing.
You will not find it by searching Browse Marketplace → **All**.

#### Install (recommended)

1. Open **Customize → Plugins** (or **Settings → Plugins**; use **Customize**
   if you see the “Plugins are moving to Customize” banner).
2. **Add marketplace** and paste the Git clone URL (must end in `.git`):

   ```
   https://github.com/kinnister/agentic-os.git
   ```

   Or, from a local clone:

   ```
   /absolute/path/to/agentic-os
   ```

3. Open the **User** tab (not **All**).
4. Install **both** plugins from the `agentic-os` marketplace:
   - **agentic-os** — `/agentic-init`, `/agentic-doctor`, `/agentic-upgrade`,
     `/agentic-uninstall`
   - **agentic-sdlc** — SDLC skills + subagents (display name **Agentic SDLC**)
5. Install **superpowers** ≥ 6.1.0 ([Install superpowers](#install-superpowers) —
   curated **Superpowers** from Browse Marketplace → **All** works in Cursor).
6. **Reload the window** (Command Palette → “Developer: Reload Window”).

You should see each plugin as its own card (often tagged **Imported**), with
bundled skills listed — similar to other third-party plugins. The page
**Rules, Skills, Subagents** is a flat list of *everything* on your machine;
that is not the plugin install view.

#### Alternative: import via Claude Code

If you already use Claude Code with **“Automatically import agent configs from
other tools”** enabled in Cursor:

```
/plugin marketplace add kinnister/agentic-os
/plugin install agentic-os@agentic-os
/plugin install agentic-sdlc@agentic-os
```

Reload Cursor. Plugins registered in Claude appear as **Imported** in Cursor.

#### Equip your project

Open the **target repo** (your app, not the `agentic-os` clone), then:

```
/agentic-init --presets ba-po            # explicit role selection + guided interview
/agentic-init --presets ba-po --defaults # explicit role, accept detected defaults
```

The interview **never commits** — it scaffolds files, shows a settings diff
before merging, and leaves the working tree for you to review.

Then:

```
/agentic-doctor          # verify governance install → .agentic/agentic-os/doctor.json
/agentic-upgrade         # reconcile after a plugin version bump
/agentic-uninstall qa    # drop a role (--all for the whole layer, --dry-run to preview)
```

If you use SDLC skills (`/sdlc-guided`, `/sdlc-auto`, …), also run
**sdlc-preflight** — it writes `.agentic/agentic-sdlc/doctor.json` and checks
superpowers, `node`, and `git`.

#### Cursor troubleshooting

| Symptom | Fix |
|---------|-----|
| Cannot find `agentic-os` in Browse Marketplace | Expected. Add custom marketplace (above) and use the **User** tab. |
| Marketplace added but no plugin card | You added the repo but did not **Install** each plugin. Install both, then reload. |
| Skills page shows hundreds of items, not `agentic-init` | Search for `agentic-init`, or open the plugin card under Customize → Plugins. |
| `/agentic-init` not recognized | Plugins not loaded — reload window; confirm both plugins show as installed. |
| Init or sdlc doctor fails on superpowers | Install superpowers ≥ **6.1.0** ([Install superpowers](#install-superpowers)), then reload. |
| sdlc-preflight fails on node | Install **Node.js** (`node --version` on PATH). |

### Portfolio and MCP (Cursor or Claude Code)

Role selection is explicit. Choose `ba-po` when your work is requirements,
customer, and delivery focused; it installs the dispatcher and requirements
workflow without developer/code-writing agents. Add another role later by
re-running `/agentic-init --presets ba-po,developer` (or the role combination
you need); the installer unions the existing architecture and preserves
user-owned files.

MCP is optional. During setup choose one of:

- **Connect now** — use an approved host directory/“Add to Cursor” connector
  or an organization-provided server.
- **Configure later** — finish setup and return when access is available.
- **Continue without MCP** — paste a table, attach a CSV, share a screenshot,
  or paste a Power BI finding. Portfolio workflows remain usable.

For Cursor, project MCP configuration is `.cursor/mcp.json` and global
configuration is `~/.cursor/mcp.json`. Verify with
`cursor-agent mcp list`, authenticate with `cursor-agent mcp login <name>`, and
inspect capabilities with `cursor-agent mcp list-tools <name>`.

For Claude Code, shared project configuration is `.mcp.json`. Use
`claude mcp add <name> --scope project ...` or `claude mcp add-json`, verify
with `claude mcp list` / `claude mcp get <name>`, and use `/mcp` for OAuth and
approval. Keep secrets in OAuth or environment variables, never in committed
JSON.

Glossary: a **repo** is the project folder Git tracks; a **plugin** adds
skills; a **marketplace** is where plugins are installed; **MCP** connects
approved external tools and data; **OAuth** is browser-based sign-in; and
**project scope** means configuration shared by that project.

First Portfolio prompts:

- “Turn this Power BI insight into a customer-ready requirement.”
- “Convert this Excel analysis into acceptance criteria.”
- “Prepare clarification questions for the customer and delivery team.”

Cursor reads `.cursor-plugin/marketplace.json` from the repo root. Use a Git
clone URL ending in `.git`, not the GitHub browser URL.

## Try it in two minutes (throwaway repo)

Nothing here touches a real project — build a disposable repo and watch the
whole install cycle end-to-end:

```bash
mkdir /tmp/try-agentic && cd /tmp/try-agentic && git init
printf '{"name":"try","dependencies":{"next":"15.0.0"}}' > package.json
```

Open **Claude Code** or **Cursor** in that directory (after the
[marketplace/plugin install](#install) steps and a session reload), then run:

```
/agentic-init --presets ba-po
```

What happens, in order:

1. **Preflight** — detects this is a git repo, then runs stack discovery: a
   cheap marker check spots the `next` dependency and matches the
   `nextjs-supabase` profile, then a subagent confirms that match against the
   real repo (a non-matching repo gets a full from-scratch inspection
   instead, not a dead-end fallback).
2. **Interview** — role selection is explicit. The flow then asks for MCP
   access (`connect now`, `configure later`, or `continue without MCP`) before
   role-relevant autonomy, gates, stack, and adapter questions. `--defaults`
   accepts detected defaults only after an explicit `--presets` selection (or
   an existing journal).
3. **Dependency check** — verifies every non-optional dependency
   (`agentic-sdlc`, `superpowers`) is registered; prints a pending-restart
   notice for any that aren't.
4. **Scaffold** — writes `.agentic/agents/`, `.agentic/guides/`,
   `.claude/hooks/`, `.githooks/pre-commit`; always writes `CLAUDE.md` as a
   marker-delimited block, and writes `AGENTS.md` whole on a fresh repo like
   this one (it only becomes a marker-delimited block when the file already
   exists). Nothing is committed — it's your working tree to review.
5. **Generate** — spawns per-slot subagents for the generated set (the union
   across every selected role preset): writer contracts, any applicable
   read-only gate like `migration-validator`, and stack guides — each
   independently audited against the instruction-quality rubric before
   being armed in the scorecard.

Then:

```
/agentic-doctor
```

runs all 8 checks (file manifest vs. install journal, hook compilation,
canned-event dry-runs of four enforcement hooks, a 3-part HITL smoke test,
settings registration, git hook + dependencies, scorecard coverage/thresholds,
and agent-registry table integrity) and writes the result to
`.agentic/agentic-os/doctor.json`.

**Cursor note:** same commands work in Cursor chat once **agentic-os** is
installed from the custom marketplace. If `/agentic-init` is missing, reload
the window and confirm the plugin card appears under Customize → Plugins.

```bash
git status         # inspect exactly what was scaffolded; nothing was committed
```

## Role presets

Presets are **additive** — install several and their template sets union
(strictest HITL wins).

| Preset | What it installs | Default HITL / orchestration |
|---|---|---|
| **developer** | generated stack writer agents (schema/api/component), read-only gates, blind pre-commit review, staged pipeline orchestrator | gated-autonomous / pipeline |
| **qa** | dispatcher routing; test-case generation / automation / sync agents with real-ID + existing-coverage gates; failure triage + flaky protocol; adapter-driven work-item creation (tests are recommend-only) | strict / dispatcher |
| **ba-po** | story & requirements intake via agentic-sdlc, ticket adapter — no code-writing agents | gated-autonomous / dispatcher |
| **architect** | full governance scaffolding (AGENTS/PATTERNS/registry), instruction-auditor + scorecard spawn gate, dispatcher routing, generated architecture guides | gated-autonomous / dispatcher |
| **pm-delivery** | ticket/MR adapters, PR pipeline gate, MR-monitoring glue, status conventions | gated-autonomous / dispatcher |
| **devops** | git hooks + quality gates, PR pipeline gate, MR-monitoring/CI-fixing glue, security reviewer, read-only incident triage (3 ranked hypotheses, human-executed fixes) — no code-writing agents | gated-autonomous / dispatcher |
| **security** | DFD-first STRIDE threat modeling (doc-writer scoped to `docs/security/`, proposed-only severities, mitigation→risk traceability), code-level security reviewer, dispatcher routing — no code-writing agents | strict / dispatcher |
| **data** | layered pipeline design raw → cleaned → consumable (doc-writer scoped to `docs/data/`, counted row-math equations, force-tested DQ checks, per-dataset lineage, proposed-only classifications), dispatcher routing — recommend-only queries, no code-writing agents | strict / dispatcher |
| **design** | emotion-annotated journey mapping → step+emotion problem framings → decision-closing workshops → negative-AC acceptance criteria → agent-ready context+spec handoff pair (doc-writer scoped to `docs/design/`, proposed-only decisions), dispatcher routing — no code, no visual-asset generation, no code-writing agents | strict / dispatcher |
| **portfolio** | run status, repo/knowledge health audits, durable cross-session memory, requirements intake — read/report-only, no git layer | gated-autonomous / dispatcher |

## The HITL dial

The install sets how much agents may do before a human must weigh in:

- **`strict`** — every step is user-invoked; agents recommend, they don't act
  (e.g. QA: agents author tests but never run them). Dispatcher orchestration.
- **`gated-autonomous`** — pipelines run, but judgment gates and the
  `escalate_on` risk flags (default: security, breaking-change, migration,
  spend) stop them for a human decision.
- **`autonomous`** — the agentic-sdlc gate-arbiter resolves gates with
  deterministic checks, fast-paths, and stand-in reviewers, escalating to you
  only on low confidence, a matching risk flag, or malformed agent output.

Underneath, three mechanisms make HITL real, not advisory:

1. **Policy files** (`.agentic/guides/policy/`) — the autonomy matrix, size
   ceiling, env write boundaries, secret deny-lists, and the escalation ladder.
2. **Resolver conventions** — every agent ends its output with
   `## Summary / ## Why / ## Blocking / ## Non-blocking / ## Escalate to human`,
   parsed fail-closed by a Stop/SubagentStop hook: a non-empty `Blocking` stops
   the parent (no silent retry); a non-empty `Escalate to human` forces an
   `AskUserQuestion`.
3. **Hard gates** — exit-2 hooks: blind pre-commit review (sha256 stamp of the
   staged diff), write-scope guard, instruction-quality spawn gate, human-gated
   command blocks.

## What gets scaffolded

Into your target repo (harness-neutral canonical contracts, thin Claude
pointers):

```
.agentic/agents/            canonical agent contracts (single source of truth)
.agentic/guides/            policy/, standards/, agent-registry.md, project.md
.agentic/agentic-sdlc/      config.json (gate-arbiter wiring)
.claude/hooks/             the enforcement hooks
.claude/agents/, commands/ thin pointers + orchestration commands
.githooks/pre-commit       the review gate's git-level twin
CLAUDE.md / AGENTS.md      a managed block (your content outside it is untouched)
docs/audits/               the instruction-quality scorecard
```

Mature repos are handled non-destructively: managed marker blocks, deep-merged
settings (shown as a diff first), skip-by-default name collisions, chained
(never replaced) git hooks.

## Using it, by role

After install, what you reach for depends on the preset(s) you chose:

- **developer** — describe a feature; the pipeline orchestrator runs the staged
  flow (generated schema/api/component agents → read-only gates → blind
  pre-commit review). Every `git commit` is blocked until the staged diff is
  reviewed. `/agentic-doctor` confirms the fleet is spawnable.
- **qa** — `/dispatch` routes each request to one owning agent (strict HITL, one
  step at a time). Generate test-case drafts from a story, automate approved
  work-item IDs (with real-ID + existing-coverage gates), triage a red test
  against the flaky protocol. Agents author tests but never run them — they hand
  you the exact command.
- **ba-po** — draft stories and requirements through the agentic-sdlc intake
  skills, wired to your ticket adapter.
- **architect** — the governance layer: `AGENTS.md`/`PATTERNS.md`/agent-registry,
  the instruction-auditor + scorecard spawn gate, dispatcher routing over that
  registry, generated architecture guides.
- **pm-delivery** — ticket/MR adapters, the PR pipeline gate, MR-monitoring.
- **devops** — the delivery-infrastructure layer: chained git hooks, the
  quality-gates registry, the PR pipeline gate, MR-monitoring that fixes
  red CI and reviewer comments until the MR merges, and read-only incident
  triage (exactly three ranked hypotheses with the cheapest read-only next
  diagnostic; fixes stay human-executed).
- **portfolio** — oversight without touching code: ask for run status, audit
  a repo's docs/agent-setup health, keep durable notes across sessions, and
  turn stakeholder asks into normalized requirements.
- **security** — say *"threat-model the checkout flow"*: the threat-modeler
  writes the DFD-first pack (diagram → per-element threats → risk register →
  mitigations) only under `docs/security/`, with every severity
  `proposed — owner confirmation pending` until you confirm it. Code-diff
  review stays with the security-reviewer.
- **data** — say *"design the orders pipeline"*: the pipeline-designer writes
  layered designs, force-tested DQ checks, and lineage maps only under
  `docs/data/`, with row math as counted equations and every verification
  query handed to you ready to run — never executed by the agent.
- **design** — say *"map the checkout journey"*: the experience-designer
  writes emotion-annotated journeys, step+emotion framings, decision-closing
  workshop logs, and the agent-ready `context.md` + `spec.md` handoff pair
  only under `docs/design/`; negative acceptance criteria are carried
  verbatim, and story drafting hands off to `story-author`.

> **If you don't write code** (pm-delivery, ba-po, portfolio, security, data,
> design): everything you
> need is a plain chat phrase, not a CLI command. Type things like *"draft a
> story for password reset"*, *"what's the status of the current run?"*,
> *"watch MR !123"*, or *"turn this stakeholder email into requirements"*
> directly into the editor's chat. The one honest prerequisite: someone
> installs Claude Code or Cursor with these plugins for you first — after
> that, no terminal is required.

Everything obeys the HITL dial you set: an agent that hits a `## Blocking` item
stops and surfaces it; an `## Escalate to human` item forces a question before
anything proceeds.

## Why not just prompt the agent yourself?

You can, and for a one-off change you should. The difference shows up when the
work is big enough to span several agents, several sessions, or a stack the
agent has to *learn* rather than be told about:

| | Plain agent session | With `agentic-os` |
|---|---|---|
| **Scope enforcement** | A session-wide allow/deny list (`permissions.deny`) plus a coarse per-agent `tools:` allowlist. Neither can say "the migration agent may write migrations, and *only* the migration agent may" — one is path-scoped but not per-agent, the other per-agent but not path-scoped. | A `write_scope`/`forbidden_paths` glob **per agent contract** — path-scoped *and* per-agent — checked by a `PreToolUse` hook that exits non-zero before the write lands. |
| **Review independence** | You can spawn a fresh-context reviewer, and should. But nothing *gates the commit* on it: a review is advisory, and the agent decides whether to honor it. | The reviewer reads the staged diff cold, and its approval is a sha256 stamp of that exact diff. No stamp, no commit — enforced by a `PreToolUse` hook *and* a native git hook. Re-staging invalidates the stamp. |
| **Autonomy granularity** | Permission rules are per *tool call* — may this session run `Bash(git push:*)`? They can't express "may this *decision* proceed without me?" | Resolution is per *gate*: deterministic check → fast-path → stand-in subagent → escalate, with `escalate_on` risk flags that force a human. Every resolution logged to `decisions.jsonl`. |
| **Stack-fact provenance** | Re-derived each session, uncited, with nothing stopping a Postgres idiom leaking into a MongoDB rule. | Every fact carries a `file:line` citation and a 0–100 confidence. A low-confidence fact is still recorded — but flagged `unresolved` and surfaced at the interview, never a *silent* guess. A rule may never cite the discovery record as its source, enforced by a rubric check. |
| **Instruction freshness** | Custom instructions are static text that silently rots as the code moves. | Contracts are graded artifacts: independently audited, hash-pinned in a scorecard. A stale hash blocks that agent's spawn (`exit 2`). |

The claim isn't that agents can't do this work, or that a plain session has no
guardrails — it has good ones. It's that those guardrails are **per session and
per tool**, and the failures above are **per agent and per decision**. Nothing
in a plain session stops a specific agent from quietly doing a specific thing
wrong. See [`docs/PRINCIPLES.md`](docs/PRINCIPLES.md) for the reasoning behind
each row.

**Why hooks, not prompts?** A prompt is a request the model may weigh against
everything else in context; a hook is a program the harness runs outside the
model, whose non-zero exit *physically blocks* the tool call. An agent under
context pressure can rationalize its way past "please don't commit unreviewed
code" — it cannot rationalize its way past a `PreToolUse` hook that exits 2.
That's why every load-bearing rule here (blind review before commit, write
scope, human-gated commands, instruction freshness) is enforced by a hook,
with prompts reserved for guidance ([`docs/PRINCIPLES.md`](docs/PRINCIPLES.md)).

## FAQ

**Does it ever commit or push on its own?**
Not unless you ask it to. `/agentic-init` scaffolds files and shows you a
settings diff before merging it — it never runs `git add` or `git commit`, so
the working tree is yours to review. The SDLC pipeline stops at a review-ready
branch and never opens a PR by itself. Two bundled skills *do* write to git,
and only when you invoke them by name: `mr-submit` (commits, pushes, opens the
PR) and `mr-watch` (pushes review fix-ups with `--force-with-lease`).

**What if my stack isn't one of the six curated profiles?**
Then discovery inspects the repo from scratch instead of matching a profile,
and you still get real, evidence-grounded agents — not a degraded stub. This
is verified against non-curated fixtures spanning both persistence paradigms
and both UI paradigms; see [`tests/universal/README.md`](tests/universal/README.md).

**What if I have no code stack at all?**
That's a first-class path by design, not a degradation: any no-code preset
(qa, ba-po, pm-delivery, portfolio, security, data, design) declares
`generated: []`; a `pm-delivery` or `ba-po` install wires ticket/MR adapters plus the
governance layer instead of code agents. Honest caveat — the preset
combinatorics are covered deterministically in CI, but this zero-capability
path hasn't yet been driven through a live end-to-end `/agentic-init` run
(tracked in [`ROADMAP.md`](ROADMAP.md)).

**Will it fight my existing CI, hooks, or `CLAUDE.md`?**
No. Mature repos are handled non-destructively: `CLAUDE.md`/`AGENTS.md` get a
marker-delimited managed block (your content outside it is never touched),
settings are deep-merged after showing you a diff, name collisions skip by
default, and a pre-existing git hook is *chained*, not replaced.

**Does this work outside Claude Code?**
The canonical agent contracts are harness-neutral by design — the
host-specific files are thin pointers over them. Install via Claude Code or
Cursor; on Codex, the **agentic-sdlc** pipeline installs and runs, but the
agentic-os governance installer has no Codex packaging yet (tracked in
[`ROADMAP.md`](ROADMAP.md); see [INSTALL.md](plugins/agentic-sdlc/INSTALL.md)).
Claude Code is the best-supported enforcement host today; Cursor packaging
reuses the same skills and scaffolds the same `.agentic/` layer.

**What does `/agentic-doctor` actually check?**
Eight things: file manifest vs. install journal, hook compilation, canned-event
dry-runs of four enforcement hooks, a 3-part HITL smoke test, settings
registration, git hook + dependencies, scorecard coverage/thresholds, and
agent-registry table integrity (that the routing matrix the orchestrator reads
is a real, contiguous table with a row per generated agent). It writes the
result to `.agentic/agentic-os/doctor.json`.

**Can I uninstall it?**
Yes — `/agentic-uninstall <role>` drops a role, `/agentic-uninstall --all` takes
the whole layer out, and `--dry-run` shows you either plan without writing
anything. It is not a delete: presets share most of their templates, so removing
`qa` from a `developer,qa` repo removes only what `developer` does not also
claim. What it actually does is recompute the state an install of the *remaining*
roles would produce and converge to it, which is why the result equals a fresh
narrower install and the repo stays installable with any role afterwards. Files
you edited are never removed without an explicit choice; files it adopted rather
than wrote are never touched. Nothing is committed for you either way, so
`git diff` remains your undo.

## Glossary

One-liners for the jargon used above, no forward references required:

- **Agent** — an AI worker with its own instructions and tool access, spawned
  to do one job (write a migration, review a diff, triage a test failure).
- **Subagent** — an agent spawned by another agent rather than by you.
- **Agent contract** — the written instructions an agent runs under: its job,
  the files it may write, and when it must escalate.
- **HITL (human-in-the-loop)** — the rule that certain decisions stop and wait
  for a person instead of proceeding automatically.
- **HITL dial** — the install-time setting choosing how much runs unattended:
  `strict` (agents only recommend), `gated-autonomous` (pipelines run, risky
  decisions stop for you), `autonomous` (only low-confidence or flagged-risk
  decisions reach you).
- **Gate** — a checkpoint that work cannot pass until a condition holds
  (tests green, review approved, human said yes).
- **Hook** — a small program the editor runs automatically around an agent's
  actions; a failing hook physically blocks the action, unlike a prompt.
- **Preset** — a role-shaped bundle (developer, qa, ba-po, architect,
  pm-delivery, devops, portfolio, security, data, design) choosing which
  agents, hooks, and skills get installed.
- **Scaffold** — the set of files `/agentic-init` writes into your repo
  (contracts, hooks, policies, guides); nothing is committed for you.
- **Doctor** — a read-only verifier (`/agentic-doctor`, sdlc-preflight) that
  checks an install actually works and writes a pass/fail report.
- **Adapter** — a small config declaring which ticket/MR tool you use (GitHub,
  GitLab, Jira, Azure DevOps…), so no vendor is hardcoded.
- **MR / PR** — merge request (GitLab) / pull request (GitHub): a proposed
  change someone reviews before it lands.
- **TDD (test-driven development)** — writing the failing test first, then the
  code that makes it pass.
- **Dispatcher vs pipeline** — the two orchestration styles: dispatcher routes
  each request to one owning agent, one step at a time; pipeline runs the
  staged multi-agent flow.
- **Skill** — a packaged, invocable capability of a plugin (e.g.
  `/agentic-init`, `sdlc-guided`, `mr-watch`).

## Testing & development

```bash
bash tests/t0/run.sh                 # 61 hook unit tests
bash tests/t0/run-output-contract.sh # 12 output-contract parser checks
bash tests/run-matrix.sh             # T1–T8 acceptance (38 checks; re-runs the output-contract suite as T7)
cd mcp && npm run build && npm test  # mcp/ server: contract, content, and read-only tests
```

**What CI proves, deterministically, on every PR:** 99 checks — 61 hook unit
tests (`tests/t0/run.sh`) plus the 38-check T1–T8 acceptance matrix — and JSON
manifest/preset validation. The matrix *executes the installer's deterministic
phases* against fresh and mature fixture repos; it is a skill-executability
proof, not a mock. It covers non-destructive mature-repo handling, idempotent
re-runs, upgrade classification, preset/ID resolution, dependency
registration, the output-contract parser, and template rendering under
quote-bearing answers. See
[`tests/README.md`](tests/README.md).

**What CI structurally cannot prove, and how it's proven instead:** the
generation loop is model-driven — you cannot spawn real subagents from a bash
script, and mocking them would prove nothing about the actual claim. So it is
verified by hand, repeatably, against fixtures on stacks the plugin has never
seen, and **every generation run below is recorded with its score**: discovery →
capability-driven generation → *independent audit by a separate
`instruction-auditor` subagent* that re-checks every claim in the generated
contract against the fixture's real code. Recorded results
([`tests/universal/README.md`](tests/universal/README.md)):

| Non-curated fixture | Generated contract | Audit score |
|---|---|---|
| SvelteKit | `component-generator` | **100/100** first audit (25/25 claims verified) |
| Express + EJS | `component-generator` | **100/100** first audit (22/22 verified) |
| FastAPI + Alembic | `schema-architect` | **95/100** first audit (19/20 verified) |
| Express + Mongoose | `schema-architect` | 90/100 → **95/100** after one regen |

The 95s are the interesting ones. On FastAPI + Alembic the contract carried
**zero** Postgres/Supabase RLS vocabulary from the exemplar it was shown; on
Mongoose, zero migration vocabulary — and the rubric's evidence check caught a
real generation mistake *live*, before it could reach a user's repo. The
unverified claims are named in the log rather than rounded away.

That split is deliberate: the deterministic half is gated in CI, and the
model-driven half is never quietly claimed as CI-covered.

## Contributing

`main` is protected — **no direct pushes; every change lands through a
CI-passing pull request**, and contributor PRs require a code-owner review. See
[`CONTRIBUTING.md`](CONTRIBUTING.md) for the branch → PR flow.

## Docs

- Engineering principles — the ideas behind the enforcement mechanisms, and why a plain agent session doesn't have them: [`docs/PRINCIPLES.md`](docs/PRINCIPLES.md)
- Upgrade flow: [`plugins/agentic-os/docs/UPGRADING.md`](plugins/agentic-os/docs/UPGRADING.md)
- Changelog: [`plugins/agentic-os/CHANGELOG.md`](plugins/agentic-os/CHANGELOG.md)
- Preset composition rules: [`plugins/agentic-os/presets/README.md`](plugins/agentic-os/presets/README.md)
- MCP server (non-plugin hosts): [`mcp/README.md`](mcp/README.md)
- MCP server changelog: [`mcp/CHANGELOG.md`](mcp/CHANGELOG.md)
- Roadmap: [`ROADMAP.md`](ROADMAP.md)
- Security policy: [`SECURITY.md`](SECURITY.md)
- Code of conduct: [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)

License: Apache-2.0.
