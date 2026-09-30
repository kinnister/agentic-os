# agentic-os-mcp

<!-- mcp-name: io.github.kinnister/agentic-os -->

[![npm](https://img.shields.io/npm/v/agentic-os-mcp)](https://www.npmjs.com/package/agentic-os-mcp)
[![npm downloads](https://img.shields.io/npm/dw/agentic-os-mcp)](https://www.npmjs.com/package/agentic-os-mcp)
[![License: Apache-2.0](https://img.shields.io/npm/l/agentic-os-mcp)](../LICENSE)
[![Glama MCP server](https://glama.ai/mcp/servers/kinnister/agentic-os/badges/score.svg)](https://glama.ai/mcp/servers/kinnister/agentic-os)

Read-only MCP server for the agentic-os methodology: governance
(**agentic-os**), the SDLC pipeline (**agentic-sdlc**), and Quality
Engineering blueprints (**agentic-qe**).

## What this is, in plain words

**agentic-os** puts *guardrails* on AI coding agents — what files they may touch,
when they must stop and ask a human, and how their work gets independently
reviewed before anything is committed. On top of that, **agentic-sdlc** is an
optional pipeline that carries a ticket from idea → spec → plan → tested code →
review-ready pull request, and **agentic-qe** is a catalog of Quality-Engineering
blueprints. There are role setups for developers, QA, architects, DevOps,
business analysts, and project/portfolio managers.

This MCP server hands that whole methodology — the docs, a per-role install plan,
the QE catalog, and an install auditor — to **any** MCP-capable assistant, not
just the Claude Code / Cursor plugins. So you can explore agentic-os, plan an
install, or audit an existing one from wherever your assistant runs.

**It serves knowledge, not actions.** Every tool is read-only — the server never
writes to your repository. It gives your assistant the documents and the plan;
*your assistant* performs any file writes, so you review each one. To actually
run the governed pipeline or scaffold files into a repo, install the plugins
(see the [main README](../README.md#install)).

## Install

Claude Code:

    claude mcp add agentic-os -- npx -y agentic-os-mcp

Codex:

    codex mcp add agentic-os -- npx -y agentic-os-mcp

VS Code — one-click:

[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect?url=vscode%3Amcp%2Finstall%3F%257B%2522name%2522%253A%2522agentic-os%2522%252C%2522command%2522%253A%2522npx%2522%252C%2522args%2522%253A%255B%2522-y%2522%252C%2522agentic-os-mcp%2522%255D%257D)

<!--
  The badge above uses the https://insiders.vscode.dev/redirect?url=... form,
  not a bare `vscode:` href — GitHub's markdown sanitizer strips custom URI
  schemes from rendered links, which makes a `vscode:`/`cursor://` href
  inert on the rendered README even though it works when pasted into a
  browser address bar directly. The redirect form is what VS Code's own
  ecosystem (and other MCP servers' READMEs) uses for exactly this reason.
  It double-encodes: the inner `vscode:mcp/install?{json}` link is itself
  URL-encoded as the outer redirect's `url=` value. Decodes to:
  vscode:mcp/install?{"name":"agentic-os","command":"npx","args":["-y","agentic-os-mcp"]}
-->

or from the command line:

    code --add-mcp '{"name":"agentic-os","command":"npx","args":["-y","agentic-os-mcp"]}'

Cursor — one-click:

[![Add to Cursor](https://img.shields.io/badge/Cursor-Add_MCP-000000?style=flat-square)](https://cursor.com/en/install-mcp?name=agentic-os&config=eyJjb21tYW5kIjoibnB4IC15IGFnZW50aWMtb3MtbWNwIn0%3D)

<!--
  Same reasoning as the VS Code badge above: cursor.com/en/install-mcp is
  Cursor's own https redirect form, replacing the bare `cursor://` deeplink
  that GitHub's sanitizer would strip. `config` is base64 of a single JSON
  object with the whole command line in one "command" string (this is
  Cursor's own convention for this endpoint, not this server's cursor-deeplink
  format) -- decodes to: {"command":"npx -y agentic-os-mcp"}
-->


or add to `.cursor/mcp.json` directly, same as Claude Desktop's
`claude_desktop_config.json`:

    { "mcpServers": { "agentic-os": { "command": "npx", "args": ["-y", "agentic-os-mcp"] } } }

## How you use it

You don't call these tools yourself — **your assistant does, when you ask in
plain language.** A typical exchange:

> **You:** "Search the agentic-os methodology for how to run a code review."
>
> **Assistant:** calls `search_methodology` → gets ranked `agentic-os://` URIs →
> calls `get_document` on the top hit → summarizes the `code-review` skill for you.

Start with `search_methodology` (find the right document) and `get_document`
(read it). The other five tools list the presets, phases, and blueprints, turn a
role into an install plan, or audit an existing install — see the examples below.

## Examples by role

Real things to ask your assistant once the server is connected. Each role is a
preset; `list_presets` shows all ten with their human-in-the-loop mode.

| Role | Ask your assistant | Tools it triggers | What you get |
| --- | --- | --- | --- |
| **Developer** | "Walk me through the agentic-sdlc pipeline, then plan a developer install." | `list_sdlc_phases`, `plan_install` | the 13-phase spec → plan → TDD → review → PR map, plus an ordered file manifest (stack-aware generator agents, blind + security review, QA gates) |
| **QA** | "What QE blueprints do you have for the execution stage?" | `list_qe_blueprints` | the QE catalog (28 blueprints across 6 STLC stages) — e.g. `coverage-analysis`, `flaky-debugging` — to scaffold a test framework from |
| **Architect** | "How does the blind pre-commit review gate work?" | `search_methodology` → `get_document` | the governance doc itself — the instruction-quality rubric, review gates, and patterns |
| **DevOps** | "What does the devops role set up, and how does MR-watch fix CI?" | `list_presets`, `get_document` | the devops preset (git hooks, PR pipeline gate) and the `mr-watch` skill that monitors merge requests and auto-fixes CI until they merge |
| **BA / PO** | "How do I turn a ticket into requirements with agentic-sdlc?" | `search_methodology`, `get_document` | the `story-intake` / `story-author` method — a story with acceptance criteria and an early complexity read (no code) |
| **PM / delivery** | "What's the PR-gate and status workflow for a delivery manager?" | `list_presets`, `get_document` | the pm-delivery preset — ticket/MR adapters, a PR pipeline gate, `mr-watch`, and status conventions |
| **Portfolio** | "What cross-project oversight does the portfolio role give?" | `list_presets`, `get_document` | run status, repo/knowledge-health audits, and durable cross-session memory — read/report-only, no git footprint |
| **Security** | "What does the security preset enforce when I threat-model a feature?" | `list_presets`, `get_document` | the threat-modeler contract + threat-modeling guide — DFD-first STRIDE with per-element constraints, severities `proposed — owner confirmation pending`, writes only `docs/security/` |
| **Data** | "What are the standards for designing a pipeline with quality checks?" | `list_presets`, `get_document` | the pipeline-designer contract + data-pipeline-design guide — counted row-math equations, force-tested DQ checks, lineage, recommend-only queries |
| **Design** | "What must an agent-ready design handoff contain?" | `list_presets`, `get_document` | the experience-designer contract + experience-design guide — emotion-annotated journeys, decision-closing workshops, verbatim negative ACs, the context+spec pair |

`plan_install` turns any of these roles into an ordered file manifest; you (or
your assistant, with your review) apply it. To run the pipeline or scaffold the
files for real, install the plugins — see the [main README](../README.md#install).

## Tools

| Tool | Purpose |
| --- | --- |
| `search_methodology` | Find the right document. Start here. |
| `get_document` | Fetch one document by its `agentic-os://` URI. |
| `list_presets` | List the agentic-os role presets with HITL default, orchestration mode, and SDLC skills. |
| `list_qe_blueprints` | List the agentic-qe Quality Engineering blueprints, filterable by STLC stage. |
| `list_sdlc_phases` | List the agentic-sdlc pipeline phase map with its judgment gates. |
| `plan_install` | Compose one or more role presets into an ordered file manifest (a plan; you perform the writes). |
| `run_doctor` | Audit an agentic-os install in a target repo you name. |

The tool surface is deliberately capped at 8 tools. Agent tool-selection accuracy degrades sharply as the number of available tools grows — research shows the performance cliff occurs around 30–40 tools, and real deployments (e.g., GitHub's MCP server) report measurable gains (2–5 points on SWE-Lancer and SWEbench-Verified, plus ~400ms lower latency) after cutting from ~40 tools to 13. The current surface exposes seven tools, one short of the cap.

### `run_doctor`'s split verdict

`run_doctor` audits `.agentic/agentic-os/install.json` and the files it
journals in a target repo you name, through a reader (`mcp/src/target.ts`)
gated by root containment rather than the bundle's build-time index — see
[SECURITY.md](../SECURITY.md) for exactly how that gate works and the one
accepted risk it documents. It verdicts what it can inspect natively as
plain file reads, and returns everything else as `host_must_run`: exact
commands for three checks that require executing Python (hook
compile+import, canned-event dry-runs, HITL smoke) — the server never runs
them itself.

Because of that split, **`verdict: "incomplete"` is the expected,
correct result of a server-side-only run**, not a sign that something went
wrong. `verdict` is `"passed"` only when every native check passed *and*
`host_must_run` is empty (i.e., your host actually ran the returned
commands and folded their results back in); it is `"incomplete"` whenever
`host_must_run` still has entries, and `"failed"` only when a native check
itself found a real problem. A reader who sees `"incomplete"` on its own
should read it as "native checks passed; three checks are still owed to
the host," not as a failure. `host_must_run` is never empty on a single
server-side call, so this server alone never returns `"passed"`.

**A host that automatically runs `host_must_run`'s commands writes to the
target repo, even though the server itself never does.** Two of the three
command sets do: `dry_runs` creates `.agentic/agents/__agentic_doctor_probe__.md`
(a one-line dummy contract, to exercise `instruction_gate.py`'s
never-graded case) and deletes it in the next command, unconditionally;
`hitl_smoke` creates a temporary working directory outside the target repo
(via `mktemp -d`) holding synthetic transcript files, removed automatically
on exit by a shell `trap`. Both are the doctor's real, documented
procedure — nothing here is left behind — but it means the "read-only"
claim above is a property of this server's own code, not of what happens
if a host executes what `run_doctor` hands back. See each `host_must_run`
entry's `why` field for the exact commands.

## Resources

31 `agentic-os://skills/<plugin>/<skill>` resources, one per `SKILL.md`
across the three plugins, plus a resource template,
`agentic-os://file/{+path}`, that serves any other file shipped by a plugin
that is tracked in `content-index.json` — not just markdown, JSON, or text:
template sources (`.md.tmpl`/`.json.tmpl`/`.py.tmpl`), plain hook scripts
(`.py`/`.sh` and six extensionless git hooks), and a long tail of one-off
files (`sdlc.html`, `scaffold.ps1`, `run-hook.cmd`, `.ts`/`.mts` sources,
`.shellcheckrc`, `*.md.template` repo-guide templates) are all servable too
(e.g. `agentic-os://file/agentic-sdlc/agents/guide-sync.md`). Index
membership is the entire access-control model — see `mcp/src/content.ts`.
The template is the primary integration point for clients that want to reach
content beyond the curated skill list.

Two families of shorter canonical aliases resolve to the same content:
`agentic-os://presets/{role}` for a role preset and
`agentic-os://qe/blueprints/{stage}/{id}` for a QE blueprint. `list_presets`
and `list_qe_blueprints` return these aliases as each item's `uri`, and
`search_methodology` returns the blueprint alias for a blueprint hit — it
searches markdown documents only, so a preset (JSON) can never be a
`search_methodology` result in the first place. Both alias forms, and the
plain `file/` form, always resolve via `get_document` or a direct resource
read.

## Prompts

Ready-made entry points your assistant can offer by name:

| Prompt | What it does |
| --- | --- |
| `agentic-init` | Interview to set up the governance guardrails in your repo |
| `agentic-doctor` | Verify an existing agentic-os install is healthy |
| `agentic-upgrade` | Upgrade the installed templates to a newer version |
| `agentic-uninstall` | Remove a role preset — or the whole layer — by converging to what a narrower install would produce |
| `sdlc-guided` | Run the governed SDLC pipeline on a task, stopping at human gates |
| `sdlc-brief` | Lightweight SDLC flow for a small (XS/S/M) task |
| `qe-blueprint-scaffold` | Scaffold a fill-in-ready QE agent framework from a blueprint |

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Releasing

Maintainer-only. See [RELEASE.md](RELEASE.md) for the one-time setup and
per-release runbook.

## Requirements

Node **>= 20**.

## Build & test

```bash
npm install
npm run build   # build:content (indexes plugins/ + copies dist/content) + build:ts
npm test        # vitest — requires the build above, since the content layer reads dist/content
```

## Docker

`npx -y agentic-os-mcp` is the supported install path; the [Dockerfile](../Dockerfile)
at the repository root exists for MCP directories that introspect a server by
building and running it in a sandbox. It is equivalent, not an alternative to
recommend.

Build from the **repository root**, never from `mcp/` — the content build reads
`plugins/**`, the root `LICENSE`/`NOTICE`, and `git ls-files`:

```bash
docker build -t agentic-os-mcp .
```

The server speaks JSON-RPC over stdio, so `-i` is required and `-t` must not be
used (a TTY corrupts the stream):

```bash
docker run --rm -i agentic-os-mcp
```
