# Changelog

All notable changes to `agentic-os-mcp`. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases are tagged `agentic-os-mcp-v<X.Y.Z>`.

## [Unreleased]

## [0.3.1]

### Changed
- **Served content refreshed** for `agentic-sdlc` 0.7.0: the vendor-neutral
  observability-adapters contract (Axiom and OTLP-logs export profiles, the
  `telemetry-export` skill) and the `usage.sampled` telemetry collector (the
  `usage-sampler` hook, `role-tier-map.json`).

## [0.3.0]

### Changed
- **BREAKING: two published prompt names changed.** `sdlc-start` is now
  `sdlc-guided` and `sdlc-task` is now `sdlc-brief`, following the skill renames
  in `agentic-sdlc`. A client calling either old name gets an unknown-prompt
  error; the prompt bodies and arguments are otherwise identical. The prompt set
  is asserted in `tests/contract.test.ts`, so this break is tested rather than
  incidental.

  The `agentic-os://skills/agentic-sdlc/sdlc-pipeline` resource URI is likewise
  now `.../sdlc-engine`, and `agentic-os://skills/agentic-sdlc/qa-gates` is
  `.../gate-runner`. Resource URIs are derived from paths under `plugins/`, so
  every renamed skill's URI moved with it.

- **Served content refreshed** for the `agentic-sdlc` skill renames and the
  adapter-contract reconciliation.

## [0.2.11]

### Changed
- **Served content refreshed** for `agentic-os` 0.13.0 and `agentic-sdlc` 0.4.1:
  the agent-contract CI check and its required blocks, stop-and-ask blocks on
  the QA and sdlc agents, the counted-rule ba-po operating model, and the
  architect preset's dispatcher routing. Agent frontmatter is now valid YAML in
  every served contract — 16 descriptions were unparseable before this release.

## [0.2.10]

### Changed
- **Served content refreshed** for `agentic-os` 0.12.0: skill-owned registry
  rows, eval fixtures for all ten presets, and ten-role docs parity.

## [0.2.9]

### Changed
- **Served content refreshed** for `agentic-sdlc` 0.4.0 (literal `Not for:`
  routing clauses on all 26 skill descriptions) and `agentic-os` 0.11.1
  (counted dispatcher PASS signal).

## [0.2.8]

### Changed
- **Served content refreshed** for `agentic-os` 0.11.0: the `design` preset
  (experience-designer + experience-design guide + evals) and its parity
  surfaces.

## [0.2.7]

### Changed
- **Served content refreshed** for `agentic-os` 0.10.0: the `data` preset
  (pipeline-designer + data-pipeline-design guide + evals) and its parity
  surfaces.

## [0.2.6]

### Changed
- **Served content refreshed** for `agentic-os` 0.8.0 + 0.9.0 together: the
  required-contract-blocks retrofit on all 10 pre-0.5.0 agent templates, and
  the union-conditional enforcement promises in `ai-policy.md.tmpl` /
  `AGENTS.md.tmpl` (new derived `{{ENFORCEMENT_LAYER_ROWS}}` +
  `{{FLEET_INVARIANTS}}` in the variable registry and the agentic-init
  skill), with both changelog entries.

## [0.2.5]

### Changed
- **Served content refreshed** for `agentic-os` 0.6.0 + 0.7.0 together: the
  preset-conditional governance rendering (0.6.0) and the `security` preset
  (threat-modeler pair, security evals) with its parity surfaces (0.7.0).

## [0.2.4]

### Changed
- **Served content refreshed** for `agentic-os` 0.5.0: the devops incident-triage
  pair (`agents/incident-triage` + `guides/incident-triage`), the devops preset
  eval fixture, and the `guides/evidence-integrity` registration fix.

## [0.2.3]

### Changed
- **Served content refreshed** to match the plugins as released together:
  `agentic-os` 0.4.0 (evidence-integrity guide, required contract blocks in
  the rubric, rule-provenance markers), `agentic-sdlc` 0.3.0 (guide-sync
  inlined-rule drift check), `agentic-qe` 0.1.1 (`Not for:` routing clauses).

## [0.2.2]

### Changed
- **Served content refreshed.** `dist/content/` now matches the plugins as they
  stand: `agentic-os` 0.3.0 — the `ba-po` role made first-class (its own
  operating-model and MCP-onboarding guides), the new MCP access screen in the
  `/agentic-init` interview, and the adapter statuses in the generated
  `sdlc/project.md` now derived rather than asserted. 330 files indexed.

  0.2.1 shipped before those landed, so `agentic-os://file/...` reads against it
  return the earlier text for the affected paths — and the `ba-po` guides do not
  exist there at all. Prefer 0.2.2.

  No server code changed; this release exists to publish the content.

## [0.2.1]

### Changed
- **Served content refreshed.** `dist/content/` now matches the plugins as they
  stand: `agentic-os` 0.2.0 (adoption of an existing `.agents` fleet, native
  Codex packaging), the `agentic-sdlc` project-orchestration boundary, and the
  `agentic-qe` eval-runner report field naming. 327 files indexed.

  0.2.0 shipped before those landed, so `agentic-os://file/...` reads against it
  return the earlier text for the affected paths. Prefer 0.2.1.

## [0.2.0]

### Changed
- **Served content refreshed for `agentic-sdlc` 0.2.0.** The bundled
  `dist/content/` now carries the rebuilt `sdlc.html`, the replaced complexity
  calibration examples, and the updated QA artifact formats — so
  `agentic-os://file/...` reads return different text than 0.1.1 for those paths.
  See `plugins/agentic-sdlc/CHANGELOG.md`. Content count is 325 files.
- The server's reported version is no longer hardcoded out of step with
  `package.json` — `mcp/tests/contract.test.ts` already asserted they agree, and
  it caught this on the bump.

### Added
- **Packaging for publication (Phase 3).** `LICENSE` and `NOTICE` now ship
  in the npm tarball (copied from the repo root at build time), and the
  orphaned `.map` files that used to leak in are gone — both pinned by
  `mcp/tests/package.test.ts`, which also asserts the tarball contains
  every `content-index.json` entry and only those.
- `server.json` (MCP Registry server descriptor) and `manifest.json` (`.mcpb`
  bundle manifest), plus `mcp/scripts/build-mcpb.mjs` and `.mcpbignore`,
  producing a production-only `.mcpb` bundle (no devDependencies, no
  `tests/`/`src/`/`scripts/`) that unpacks and serves all 7 tools from the
  unpacked layout. `package.json`, `server.json`, and `manifest.json` are
  asserted to agree on version, name, and identifier by the same test file
  — proven to fail on drift.
- `.github/workflows/release.yml` — a tag-triggered (`agentic-os-mcp-v*`)
  release workflow: reruns the full repo gate (now including the Inspector
  CLI smoke), asserts the tag matches `package.json`'s version, logs in to
  the MCP Registry and asserts the granted permission covers `server.json`'s
  `name` *before* publishing anything (`mcp/scripts/check-registry-permission.mjs`,
  closing a failure mode where a namespace-case mismatch would otherwise 403
  at the Registry only after npm publish already succeeded and burned the
  version), publishes to npm with provenance, polls `registry.npmjs.org` for
  the published version to propagate, and only then publishes `server.json`
  to the MCP Registry (via a freshly re-authenticated
  `mcp-publisher login github-oidc`, since its JWT is short-lived) and
  attaches the built `.mcpb` to a GitHub release. A `workflow_dispatch` input
  resumes just the post-npm steps if one of them fails, without skipping the
  gate or re-running `npm publish`. See `mcp/RELEASE.md` for the maintainer
  runbook this workflow implements, including how the Registry namespace
  case (`io.github.kinnister/agentic-os`, matching the real GitHub owner
  login exactly) was confirmed.
- `list_presets` — the seven agentic-os role presets with HITL default,
  orchestration mode, and SDLC skills.
- `list_qe_blueprints` — the 28 Quality Engineering blueprints, filterable by
  STLC stage.
- `list_sdlc_phases` — the SDLC pipeline phase map with its judgment gates.
- Resource URI aliases `agentic-os://presets/{role}` and
  `agentic-os://qe/blueprints/{stage}/{id}`.
- `plan_install` — composes one or more role presets into an ordered file
  manifest (template id, source `agentic-os://` uri, owner), applying
  strictest-HITL-wins and unioning every orchestration style across the
  selected roles. Returns a plan only; the caller performs the writes.
- `run_doctor` — audits an agentic-os install in a target repo the caller
  names. Adds the server's second filesystem reader, `mcp/src/target.ts`,
  gated by root containment (canonicalized, symlinks resolved) rather than
  the bundle reader's build-time index — see SECURITY.md for the full
  access-control writeup and its one accepted risk (a TOCTOU window between
  containment validation and read, scoped to an attacker who already has
  write access to the repo being audited). Six of the doctor's checks run
  natively as pure file inspection; the three that require executing Python
  (hook compile+import, canned-event dry-runs, HITL smoke) come back as
  exact commands in `host_must_run` for the host to run itself — the server
  never executes code from a target repository. `verdict: "incomplete"` is
  the expected result of a server-side-only run, not a failure signal.
- Tool surface now stands at 7 of the documented 8-tool cap.
- **Bundle surface widened**: `content.ts`'s loader dropped its `md|json|txt`
  extension filter so `plan_install`'s template lookups (and the resources
  they point at) stop silently failing for any template that wasn't a plain
  `.md` file. This makes ~70 additional `content-index.json` entries
  servable through `get_document` and the public
  `agentic-os://file/{+path}` resource template — hook scripts (`.py`/`.sh`
  and six extensionless git hooks), `.tmpl` template sources, and one-off
  files such as `scaffold.ps1`, `sdlc.html`, `run-hook.cmd`, and
  `.shellcheckrc`. Verified: 326 total index entries, 256 of which end in
  `.md`/`.json`/`.txt`, so exactly 70 previously-unservable entries are now
  reachable. Index membership remains the entire access-control model — no
  extension-based gate was reintroduced.
- `mcp/tests/readonly.test.ts` extended to prove no source file writes to
  the filesystem or spawns a process (banning both write APIs and the
  `child_process` module specifier in any quoting) across `mcp/src/**`, and
  that exercising every tool — including `run_doctor` against a live target
  — leaves `plugins/` byte-identical.

## [0.1.1]

### Fixed
- **Server never started when launched via its `bin` (the documented `npx -y
  agentic-os-mcp` usage).** The entrypoint guard compared `import.meta.url`
  against a raw `` `file://${process.argv[1]}` ``. npm installs the `bin` as a
  link under `node_modules/.bin`, so `npx`, a global install, and every MCP
  client launched the server through that link — where `process.argv[1]` is
  the link's path but `import.meta.url` is the resolved real path of
  `dist/index.js`. The two never matched, so `main()` was skipped and the
  process exited `0` without connecting (clients reported `-32000: Connection
  closed`). The guard now canonicalizes `process.argv[1]` with `realpathSync`
  and builds the URL with `pathToFileURL`, matching in both the direct-path
  and linked-`bin` launch modes. `mcp/tests/bin_entrypoint.test.ts` launches
  the server through a link exactly as npm's `.bin` does and asserts the full
  tool surface is reachable — the coverage gap that let this ship in 0.1.0,
  where the only launch test used the literal `dist/index.js` path.

## [0.1.0]

### Added
- Read-only stdio MCP server on `@modelcontextprotocol/sdk` v1.x, spec
  `2025-11-25`.
- `search_methodology` and `get_document`.
- 31 skill resources, an `agentic-os://file/{+path}` template, and six
  workflow prompts.
- Content pipeline with a committed sha256 drift index enumerated from
  `git ls-files`, gated in CI before the build.

Not published to npm.
