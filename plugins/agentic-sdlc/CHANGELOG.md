# Changelog

Notable changes to the `agentic-sdlc` plugin, as distributed here. Format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this plugin
uses Semantic Versioning and its own release tag (`agentic-sdlc-v<X.Y.Z>`).

## [Unreleased]

### Runtime and installer reliability

- When uninstall keeps a file, its journal entry now records the bytes and
  identity actually on disk (a kept generated file keeps its recorded hash, so
  the user's edit stays detectable).

- Preserve pre-existing settings and identical user files during setup and
  uninstall, including after a detected user edit. Validate versions and the
  settings journal before writing; reject unsafe journal entries and anchor
  file mutations to directory handles against symlink path swaps. Recheck the
  planned file hash and inode before replacement or deletion; journal each file
  before advancing, and detect journal edits at the recheck before replacement.
  Same-byte file replacements with a new inode become user-owned; legacy
  journal entries without file identity are preserved conservatively.
  Detected directory replacement during an operation is rejected, and conditional
  rollback preserves the original inode so a retry can still recognize a
  managed file.
  Record nanosecond modification time as well as device and inode, preventing
  an immediately reused inode from claiming a recreated user file.
  Generic uninstall now preserves generated files for an individual decision,
  matching the role-removal contract instead of deleting them automatically.

- Add installer operations for operator decisions so setup, upgrade and
  uninstall can stop editing files and the journal directly: compare-and-swap
  confirmations on apply (`expect_sha256`) and remove (`confirm`) that act only
  while the reviewed bytes are present and never raise a file's ownership;
  files that existed before agentic-os are never deleted, even when confirmed.
  Journal entries for managed files already deleted are dropped, unknown
  file-spec fields are rejected, and `install.record` records answers and
  progress. A journal containing NaN or Infinity is refused. New files follow
  the umask, replacements keep their mode without setuid/setgid, and the
  journal is rewritten owner-only.

- Check all modern stored evidence claims before filtering required checks, so
  a damaged database row cannot hide a signed failed check by changing its
  required flag. Worker isolation from coordinator state remains a separate
  host boundary.

- Retain signed failed required checks and require the latest result of every
  required command stream in the completion gate; signed receipts now bind
  command identity and required status so a failed check cannot be hidden by
  citing an unrelated passing check. Completion revalidates persisted signed
  claims, so older receipts without those fields require a fresh check.

- Validate `run.start` input, coordinator identity, and the exact Git worktree
  root before the CLI creates SQLite state, so rejected starts do not leave a
  pending run or a new `.agentic` directory.

- Treat the shared lifecycle and messaging runtime as experimental; host identity,
  trusted completion gates, installer integration, and live certification remain
  incomplete. Unsupported completion and mailbox access fail closed during the
  bounded remediation of the lifecycle and communication stages.
- Define SQLite-backed resume and assignment recovery, preserve user-owned
  checkpoint inputs, keep legacy repair procedures out of managed runs, align
  resume handoff fields with the runtime contract, and update the resume evals
  to distinguish SQLite authority from legacy snapshot behavior. Legacy-only
  resumes now fail closed, and uncertain external actions reconcile only after
  the recovery coordinator acquires its fenced lease. New runs persist their
  normalized task input in authoritative metadata for later resume. Planned
  host interruptions now transition the run to `interrupted`; an unexpected
  coordinator death while still `running` remains blocked because lease-expiry
  takeover is not implemented. Worker launch instructions now start a bounded
  dispatch lease before execution and reconcile expired dispatches explicitly.

### Added

- Added the coordinator-backed `scripts/external-action.py` boundary. Managed
  ticket synchronization records external intent before adapter execution and
  reconciles success, failure, timeout, or launch uncertainty through the
  authoritative SQLite runtime; missing fencing context still fails closed.

- Added a structured host control matrix to preflight output, identifying which
  controls are enforced by the runtime, checked before integration, delegated
  to an adapter, or unsupported at the host boundary.

- Added the versioned `install.merge-settings` operation for atomic,
  journaled recursive settings merges that preserve user scalar values.

- Added revision-bound command evidence receipts; failed required checks cannot
  be recorded as successful verification.

- Added durable assignment ownership and typed peer-message envelopes with
  correlation, stale-revision, duplicate, sender, and payload-limit checks.

- Added the shared SQLite lifecycle runtime with fenced revisions, durable dispatch reservations,
  external-action reconciliation, and revision-labelled exports.

- Bundle the canonical versioned runtime contracts for independent installation, with deterministic drift checks and strict policy/input validation.

- **`usage.sampled` is now a real event, not just a reserved shape.**
  `references/model-routing.md` documented this event ("Usage sampling (spec
  only)") but nothing ever produced one. A new `usage-sampler` SubagentStop
  hook now samples each subagent's own isolated token usage (confirmed
  empirically to be a genuinely separate transcript from the parent
  session's, not an approximation) and appends a normalized `usage.sampled`
  line to the run's `events.jsonl`, with `role`/`tier` resolved via the new
  `references/role-tier-map.json`. `report-builder` (aggregating these into a
  cost report) remains a separate, unimplemented roadmap item — this only
  covers the collector.

- **Observability adapters, with Axiom as the first shipped profile.** Every
  run already produces a complete governance record — `events.jsonl` (phase
  transitions, side effects) and `decisions.jsonl` (every gate verdict, its
  source, confidence, and risk flags) — but it lived and died in a gitignored
  run directory with no way to see it in aggregate. `references/
  observability-adapters.md` is a new vendor-neutral contract, mirroring
  `work-item-adapters.md`'s adapter-declaration shape, that lets a host
  project export that record to an external backend without this plugin ever
  naming one or handling a credential.

  New: `scripts/export-run-telemetry.py` (stdlib-only projector; deny-by-
  default field allowlist — free-form text like `summary`,
  `verdict.rationale`, and `prior_context` is dropped, never forwarded),
  `skills/telemetry-export/` (the operator-invoked skill; not a registered
  hook, so nothing exports by default), `references/schemas/telemetry-
  record.schema.json`, and `references/profiles/{axiom,otlp-logs}.md` (Axiom
  ingest specifics plus starter APL queries; a vendor-neutral OTLP-logs
  alternative). `tests/lib/check-telemetry-allowlist.py` keeps the doc's
  allowlist tables and the projector's code from drifting apart.

  This plugin still ships zero network calls and zero secrets by default —
  export only happens when a host declares
  `.agentic/guides/integration/telemetry-flow.md` and invokes the skill.

### Fixed

- **`ticket-sync` silently wrote zero receipts on Linux**, even though it
  always exited 0 and looked healthy. Its `file_mtime()` helper picked "the
  newest pipeline run" by shelling out to `stat -f %m FILE`, falling back to
  `stat -c %Y FILE` on failure. On BSD (macOS) `-f` means "format", so
  `stat -f %m` cleanly prints the mtime and the fallback never runs. On GNU
  (Linux) `-f` means "filesystem status" — a different flag that happens to
  accept `%m` too — so it printed a multi-line filesystem-info block to stdout
  (only stderr was redirected) and exited nonzero. Because both `stat` calls
  shared one command substitution, the `||` fallback's real epoch got appended
  to that garbage rather than replacing it, so the mtime comparison silently
  evaluated false for every run. No error ever surfaced — the hook just
  concluded no run existed and took its normal no-op exit path.

  Wiring `hooks/test-ticket-sync` into CI (below) caught this immediately:
  20/20 locally on macOS, 10/20 on the actual Ubuntu runner. Reproduced and
  root-caused against real GNU coreutils in a container before fixing.
  `file_mtime()` now validates the captured value is a clean non-negative
  integer before accepting it, rather than trusting either `stat` flavor's
  exit status. Verified 20/20 on both BSD and GNU `stat`.

- **`sdlc-stage-guard`'s advisory nudges disagreed with the stage/phase numbers
  each flow's own `SKILL.md` documents, in three different ways.** The test
  suite (`hooks/test-sdlc-stage-guard`) was added alongside the hook and never
  actually run against it, so 30 of its 44 assertions had been failing since
  the file was introduced.

  `sdlc-brief`'s task flow collapsed the Stage 6 (implementation) / Stage 7
  (`qa-scoping --review-tests`) boundary into one "Stage 6" label regardless of
  which side of it the run was on, so every later stage in that flow
  (code review, `gate-runner`, health-update/handoff) was announced one number
  behind its documented position. `sdlc-direct` did the same at its Stage 2
  (clarity check) / Stage 3 (plan) boundary, under-numbering everything from
  Stage 4 onward. `sdlc-engine`'s phase-based nudges said "Stage N" throughout
  despite the skill's own Phase 0–12 map — the word never matched the
  vocabulary a user reading `sdlc.html` or the SKILL.md would recognize.

  Fixed by renumbering `sdlc-brief` from the Stage 6/7 split onward, `sdlc-direct`
  from Stage 4 onward (labeling the merged clarity+plan step "Stage 2-3" and the
  merged health-update+handoff step accordingly), and switching every
  `sdlc-engine` nudge from "Stage" to "Phase". Both task flows now also name
  themselves in the nudge ("sdlc-brief Stage 3", "sdlc-direct Stage 5") the way
  `sdlc-direct` already did for some of its own messages — `sdlc-brief`
  previously left its flow unnamed, which is why the model reading the nudge
  had no cheap way to tell which of the two task-level flows produced it.

  The remaining 9 failures were pure test-authoring drift — needles like
  `"spec.approved not recorded"` that never matched the hook's actual (and
  fine) phrasing `"the spec.approved gate has not recorded approval"` — fixed
  by aligning the test to what the hook correctly says. Verified stable across
  3 consecutive runs: 44/44.

- **BREAKING: skills are named for their role in the pipeline.** Two naming
  defects drove this. `sdlc-task` and `sdlc-light` are both lightweight
  human-in-the-loop flows, and each had to explicitly disclaim the other in its
  own `description:` — the frontmatter was working around the names. And six
  skills marked `discoverable: false` carried names that read like public entry
  points, so the internal/public boundary existed only in frontmatter.

  The five entry points now form a ceremony ladder over one shared engine, and
  the rest group into families that pair with the agents already named that way:

  | Was | Is | |
  |---|---|---|
  | `sdlc-light` | `sdlc-direct` | straight to plan, no spec |
  | `sdlc-task` | `sdlc-brief` | writes a brief spec |
  | `sdlc-start` | `sdlc-guided` | full pipeline, human-guided gates |
  | `sdlc-autonomous` | `sdlc-auto` | full pipeline, autonomous gates |
  | `sdlc-pipeline` | `sdlc-engine` | the engine the four delegate to |
  | `sdlc-status` | `sdlc-runs` | inspects and resumes runs |
  | `sdlc-doctor` | `sdlc-preflight` | prerequisite check before a run |
  | `requirements-intake` | `story-intake` | pairs with the `story-proxy` agent |
  | `product-owner` | `story-author` | pairs with `story-intake` |
  | `mr-creator` | `mr-submit` | pairs with `mr-watch` |
  | `decision-router` | `gate-arbiter` | pairs with `gate-runner` |
  | `qa-gates` | `gate-runner` | pairs with `gate-arbiter` |
  | `complexity-scoring` | `effort-sizing` | pairs with the `sizing-analyst` agent |
  | `feature-verification` | `acceptance-check` | checks against acceptance criteria |
  | `qa-planner` | `qa-scoping` | pairs with `qa-baseline` |
  | `qa-foundation` | `qa-baseline` | pairs with `qa-scoping` |

  Literals derived from a skill name moved with it: the `sdlc-stage-guard`
  runtime globs, the `.state.json` `flow` values **and the flow default**, the
  `gate-runner.retry` / `acceptance-check.retry` loop ids, ledger `actor`
  values, and `feature-verification-plan.json` → `acceptance-check-plan.json`.

  Literals that name a *concept* rather than a skill are deliberately unchanged:
  gate ids (`spec.approved`, `feature.verification`, …), the `mode` enum whose
  `task` member is a mode and not `sdlc-task`, `verification-evidence.json`,
  and every `.agentic/` path that lands in a user's repository.

### Fixed

- **The adapter contract disagreed with its own implementation, in both
  directions.** The reference declared a `**Comment Template**` field and six
  template tokens (`{{SUMMARY}}`, `{{CHANGES}}`, `{{SEVERITY}}`,
  `{{DESCRIPTION}}`, `{{IMPACT}}`, `{{FIX}}`) that nothing in the repository
  read, while omitting `**Instructions**`, which `/agentic-init` writes into
  every `project.md` and `mr-creator` reads back. Configuring an adapter by
  following the spec meant writing a dead field and missing a live one. The dead
  surface is gone, `**Instructions**` is documented, and the field table now
  matches the one `repo-guides` enforces.

- **`diff` and `inline-comment` are marked as declared-but-unused.** No shipped
  skill invokes them. They stay in the contract — they complete the documented
  operation set and pin the `RIGHT` diff side — but the reference no longer
  implies something calls them.

- **One status value, spelled one way.** The work-item intake gate wrote
  `**Status**: not_configured` while the section it reads is written
  `not configured` by the installer and by every other consumer. The underscore
  spelling never matched what was on disk. (The unrelated `sync_status` enum in
  `qa-case-generator` keeps its `not_configured` member — that is a JSON value,
  not this field.)

### Changed

- **Owner links point at `kinnister`.** The GitHub account was renamed from
  `Jarroslav` to `kinnister`; author, homepage and repository URLs follow it.

- **The two adapter sections are named for what they govern.** `## MR Adapter`
  used GitLab's noun for a section the spec itself always describes as "MR/PR",
  and `## Ticket Adapter` used a tracker-flavoured noun while its own reference
  file is `work-item-adapters.md` and its ledger events are `work_item.*`. Both
  named a vendor's term for a deliberately vendor-neutral indirection. They are
  now `## Review Adapter` and `## Work Item Adapter`.

  This changes the section headers in `.agentic/guides/project.md`. Re-run
  `/agentic-init` to re-render the file, or rename the two headings by hand —
  the fields inside them are unchanged. The `{{MR_ADAPTER}}` and
  `{{TICKET_ADAPTER}}` installer variables keep their names; they are a separate
  registry with its own three-way test coupling, and renaming them buys nothing
  here.

## [0.5.0] — 2026-07-29

### Fixed

- **Five pipeline-only skills now declare `discoverable: false`.**
  `decision-router`, `complexity-scoring`, `feature-verification`, `qa-gates`
  and `qa-planner` are invoked by `sdlc-pipeline`, not by users — each says so
  in its own description — but none carried the declaration, so each read as a
  user-facing skill a preset had failed to route.

  This completes the pattern `sdlc-pipeline`, `code-review-orchestrator` and
  `test-heal` already followed. Unlike those three, these five *are* legitimately
  claimed by presets: the agentic-os check treats internal-ness as *allowed to be
  unclaimed*, not *forbidden from being claimed*, so a skill can be both
  preset-installed and pipeline-only.

### Fixed

- **`sdlc-pipeline` now declares `discoverable: false`.** It is the most
  emphatically pipeline-only skill here — "never in direct response to a bare
  user request", with `sdlc-start` and `sdlc-autonomous` as the only entry
  points — but it carried no `discoverable:` key, while `code-review-orchestrator`
  and `test-heal` both set it. All three internal skills now declare
  themselves the same way, so tooling can identify them from frontmatter
  instead of parsing the description prose (which is YAML-folded, wrapping
  `Not for: direct user invocation` mid-phrase).

- **`code-review` was misclassified in the skill catalog** as a "Phase skill —
  single-round inline review used by the task flow". Its own frontmatter carries
  user trigger phrases ("review my changes", "review my branch", "run a code
  review") and describes it as the standalone front door that resolves scope and
  lenses before delegating to `code-review-orchestrator`. The table now matches
  the contract; it is both an entry point and available inline.

### Changed

- **The five QA skills now name their methodology owner.** `qa-foundation`,
  `qa-planner`, `qa-case-generator`, `qa-e2e-generator` and `test-heal` each
  restated method the `agentic-qe` blueprint catalog also defines —
  `qa-case-generator` against `design/test-cases.md`, `test-heal` against
  `execute/flaky-debugging.md`, and so on — with no cross-reference in either
  direction. Two sets of practices for one job is the divergence the no-forking
  rule exists to prevent, and it is how two agents end up following different
  guidance for the same task.

  Each skill now cites the blueprint that owns its method and states precedence
  plainly: the skill executes, the blueprint is the authority, and where they
  disagree the blueprint wins and the skill is what gets corrected.
  **No skill's runtime behaviour changes** — these are executable pipeline steps
  and they still run exactly as before. The catalog is the source of truth for
  *method*, not a replacement for the code that does the work.

## [0.4.1]

### Added

- **The required contract blocks on all five agents** — `codebase-scout`,
  `guide-sync`, `lead-proxy`, `sizing-analyst`, and `story-proxy` now each
  carry a `Not for:` routing clause, a `## Decision rules` DO/DON'T table, a
  `## Stop and ask when` block, and an escalate-never-decide list. The 0.4.0
  retrofit covered all 26 skills but no agent; `tests/lib/check-agent-contract.py`
  in agentic-os now enforces the same blocks here.
- **`## Escalate, never decide` as an accepted spelling of the escalation
  block** — `lead-proxy` and `story-proxy` are contractually forbidden from
  escalating (decision-router owns every human contact, triggered by their
  `confidence` field). Their stop-and-ask blocks emit an immediate
  low-confidence verdict rather than prompting a user, so the contract no
  longer has to contradict itself to satisfy the rubric.

### Fixed

- **`story-proxy.md` frontmatter was unparseable YAML.** Its bare unquoted
  `description` contained `<example>Context:`, which a strict YAML reader takes
  as a nested mapping — the agent would fail to load in any host that parses
  frontmatter properly. Now a folded block scalar.

### Changed

- **`lead-proxy.md` heading levels normalized** from `#` to `##` for top-level
  sections (gate subsections demoted to `###`), matching every other agent
  contract in both plugins.

## [0.4.0]

### Changed

- **Every skill description now carries a literal `Not for:` routing clause**
  — all 26 skills, each clause accurate to that skill's adjacent-but-wrong
  routing targets (e.g. requirements-intake vs planning; qa-case-generator vs
  qa-e2e-generator; sdlc-task vs sdlc-start/sdlc-autonomous/sdlc-light).
  Existing prose negatives were converted to the literal form without losing
  meaning. This pays down the recurring D2 "routing negative space" partial
  from the blind role-grading waves, and the CI grandfather list is gone:
  `check-skill-contract.py` now enforces the clause on every skill, hard.

## [0.3.0]

### Added

- **Inlined-rule drift check in `guide-sync`.** After applying approved guide
  edits, the agent now greps agent contracts and command pointers for
  `agentic-os:rules` provenance markers (spec: the agentic-os
  `working-with-agents.md` § Rule provenance markers), and reports — never
  edits — every marked digest whose source guide changed in the run, plus any
  dangling `source` path, under a new `Inlined-rule drift` list in its report.
  Fixing a drifted contract remains an `/agentic-upgrade` regeneration or a
  human edit.

## [0.2.0]

### Changed

- **`sdlc.html` rebuilt from `references/architecture.md`.** The page was stale
  in ways that were invisible until clicked: its inventory cited seven files that
  do not exist (five `commands/*.md`, `agents/knowledge-enrichment.md`, and
  `skills/repo-guides/references/knowledge-craft.md`), so the source viewer was
  broken for most nodes, and its version badge disagreed with the manifest. It is
  now generated from the architecture contract and the tree, covers the twelve
  phase skills that were previously missing, and every path it points at is
  checked by `tests/lib/check-html-refs.py`. The six diagrams are laid out from
  node and edge lists rather than hand-placed coordinates, and the two rival CSS
  token vocabularies are now one — together roughly 1,800 fewer lines.
- **Complexity calibration examples replaced.** The previous set contained a band
  mismatch (an example scoring 13/36 → `S` filed under the M band and claiming an
  M outcome). The new examples are drawn from this repo's own work, sum correctly,
  land in their own bands, and include two deliberate sizing misses with notes on
  why — a wrong prediction recorded honestly calibrates better than a tidy one.
- **The complexity red-flag and band tables have one home.** `sizing-analyst`
  restated both in different words from the guide; it now reads the guide's copy,
  which removes a drift risk rather than a duplication nuisance.
- **QA artifact formats tightened.** `qa-checklist.md` and `qa-test-review.md`
  have clearer section names and column sets (blocking versus deferred is now the
  section, not a redundant column), and `qa-planner` was updated with them.
- **Report formats clarified** across `qa-gates` (the gate-plan runner list is no
  longer a pipe-delimited string inside a JSON value; `SKIPPED` rows now require a
  reason), `codebase-scout`, `repo-audit-guides` and `repo-guides` (one audit
  report spine instead of the same one restated across six files).
- **Vocabulary made consistent.** Leftover "factory" phrasing is gone;
  `references/architecture.md` says "the package" and now everything else does too.
- `evals/plugin-eval-benchmark.json` no longer describes a runner this repo does
  not ship — it declares the check and leaves the harness to supply its own
  sandbox and workspace settings.

## [0.1.0] — initial public release

First public version.

### Added

- **Four SDLC entry points**: `sdlc-start` (human-in-the-loop), `sdlc-autonomous`
  (factory mode), `sdlc-task` (lightweight, user-classified XS/S/M work, with
  `mode: "sync"` post-completion reconciliation), and `sdlc-light` (simple,
  clear tasks — research grounds a plan directly, with a targeted clarity
  check standing in for complexity assessment and brainstorming).
- **`sdlc-pipeline`** — the 13-phase orchestrator behind the entry points:
  requirements intake → complexity scoring → brainstorming → spec → plan →
  QA checklist → TDD implementation with per-task evidence → QA test review →
  multi-lens code review → QA gates → feature verification → QA health update
  → handoff. Phase-set routing by work type (`story | bug | hotfix | spike |
  epic`), loop caps with `halt`/`escalate` semantics, and append-only
  event/decision ledgers per run.
- **`decision-router`** — the single helper behind every judgment gate. HITL
  mode always prompts the user; autonomous mode applies deterministic checks
  and fast-paths before falling back to stand-in subagents
  (story-proxy, lead-proxy), with an escalation rule and a
  full audit trail in `decisions.jsonl`. Synthesizes a canonical safe-fail
  verdict when the code-review orchestrator cannot produce one.
- **Multi-lens code review**: `code-review-orchestrator` (blind adversarial,
  edge-case tracer, and spec-acceptance lenses as parallel subagents, with the
  canonical lens definitions in its own `references/`, plus standards/security
  adjudication and triage), and `code-review` (standalone user-facing review
  outside a managed run).
- **QA suite**: `qa-foundation` (repo QA knowledge bootstrap), `qa-planner`
  (per-feature checklist / test review / health update), `qa-gates`
  (vendor-neutral lint → build → tests gate runner), `feature-verification`
  (functional verification with evidence files), `test-heal` (repairs
  test-fault failures only, never application code), `qa-case-generator` and
  `qa-e2e-generator` (ticket-driven manual/API case and E2E script
  generation).
- **Delivery skills**: `mr-creator` (adapter-driven commits/push/MR),
  `mr-watch` (autonomous MR watching: CI failures, review comments, merge
  conflicts), `release-manager` (release validation by cross-referencing
  commits against tracked tickets).
- **Knowledge skills**: `repo-guides` (project/ticket-adapter/guide
  setup, including the ticket-flow mapping), `guide-sync` (post-merge
  guide sync), `repo-audit-guides` (docs/assistant-setup audit),
  `product-owner` (story drafting with negative-acceptance-criteria rule),
  `requirements-intake`, `complexity-scoring`, `sdlc-status`, `sdlc-doctor`,
  and per-role persistent `role-memory`.
- **Hooks**: `ticket-sync` (Stop/SubagentStop, async — syncs the external
  work-item to run progress through the project's declared adapter; pure bash,
  fails safe, ships with its own stub-adapter test suite) and
  `sdlc-stage-guard` (PostToolUse(Skill), informational-only stage/next-step
  nudges for active runs, with a full transition test suite), both
  cross-platform via the `hooks/run-hook.cmd` polyglot wrapper.
- **Run-artifact JSON Schemas + zero-dependency validator**
  (`references/schemas/`, `scripts/validate-run-artifact.py`): validate after
  write, validate before gate — malformed artifacts become deterministic fix
  instructions.
- **Model-tier routing** (`economy | standard | premium`,
  `references/model-routing.md`): every dispatch resolves a tier mapped via
  host config; all shipped defaults are `"inherit"` and no concrete model ID
  ships in the plugin.
- **References**: gate catalog, lifecycle artifacts, phase routing,
  parallelism safety, mode routing, diff materialization, tokenomics (the
  agent-loop cost model), and the interactive pipeline map
  ([`sdlc.html`](sdlc.html)).

No upgrade path from a prior version — this is the first release.
