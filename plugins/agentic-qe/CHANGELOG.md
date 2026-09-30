# Changelog

Notable changes to the `agentic-qe` plugin. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this plugin uses
Semantic Versioning and its own release tag (`agentic-qe-v<X.Y.Z>`).

## [Unreleased]

### Fixed

- **`eval-harness/references/python.md` had 7 dead cross-references.** It
  pointed at `spec-format.md` and `references/providers.md`, neither of which
  exists — the real files are `eval-spec.md` and `judge-providers.md`
  (siblings in the same `references/` directory as `python.md` itself, so the
  correct form drops the `references/` prefix). Found by measurement while
  auditing the repo's overall link integrity, the same rot class as the
  `qa-sdlc-blueprint` fix below, just missed by that pass because it's a bare
  backticked reference rather than markdown link syntax.

- **The skill-authoring stub pointed at a skill that does not exist.** Its
  "Related material" section named a `qa-sdlc-blueprint` skill as the document
  that invokes the template; the skill is `qe-blueprints`, and
  `qa-sdlc-blueprint` appeared nowhere else in the repository. Anyone following
  the stub went looking for a file that was never there. Found by the new
  `tests/lib/check-skill-refs.py` on its first run.

### Added

- **`qe-blueprints` records which blueprint it used, locally.** A 28-document
  catalog accumulates documents nobody reaches for, and the only honest test of
  whether one earns its place is whether it is ever actually used — comparing
  two files and judging them similar is not that test. After a successful
  scaffold in a governed repo, one line lands in
  `.agentic/state/qe-blueprint-usage.jsonl`: blueprint id, stage, platform,
  date.

  This is the evidence two deferred decisions are waiting on — whether
  `threat-model` is retired now that the `threat-modeler` agent owns its method,
  and whether `risk-based-selection` and `change-impact-scoping` should merge.
  Both were left open deliberately rather than settled from a file comparison.

  Constraints, because this is telemetry in someone else's repo: local only,
  never transmitted, and `.agentic/state/` is already gitignored by every
  install so it is never committed. One line per scaffold — no repo identifier,
  no free text, no content from the run. Ungoverned repos are skipped entirely:
  they have no `.agentic/`, and the skill does not create one just to leave a
  log in.

### Fixed

- **`threat-model` contradicted the enforced standard.** The blueprint told the
  threat generator to "enumerate scenarios across all six categories" per
  boundary. `guides/standards/threat-modeling.md` — which the `security`
  preset's `threat-modeler` agent is graded against — says the opposite: threats
  are enumerated per DFD element and *each element type admits only its own
  categories* (external entity → spoofing/repudiation only; data flow and data
  store → tampering/disclosure/DoS only; only a process admits all six), with a
  counted self-check of `per-element-type constraint violations = 0`.

  Two authorities gave conflicting rules for one job, and the looser one sat
  outside the enforced path where nothing could catch it — worse than a name
  collision, which at least gets resolved. The blueprint now states the
  element-type constraint, and carries an explicit precedence note: in a repo
  running `agentic-os` the standard wins, the agent owns execution, and the
  blueprint covers what the contract does not — standing up the practice across
  a team (role tiering, connector wiring, adoption signals).

### Changed

- **Owner links point at `kinnister`.** The GitHub account was renamed from
  `Jarroslav` to `kinnister`; author, homepage and repository URLs follow it.

- **Seam sentences on seven blueprints whose descriptions competed.** Selection
  quality degrades as descriptions overlap, so each contested pair now says
  plainly which one to reach for: `risk-based-selection` (budget-constrained,
  per-test, defect history) vs `change-impact-scoping` (diff-triggered,
  suite/area, dependency graph); `product-risk` (planning-time, no diff);
  `pr-performance-review` (performance lens only, advisory, does not replace the
  review gate); `project-context` (tracker/wiki-sourced — **not** the
  `.agentic/guides/` tree, whose fixed output paths a parallel doc tree would
  break); and `api-schema-validation` vs `test-scripts` (contract-driven vs
  case-driven).

  No blueprint was merged or retired. Both decisions were deliberately deferred
  until blueprint access is measured — the retirement test worth applying is
  whether an asset is ever actually read, not whether two files look similar.

### Added

- **The blueprint index is now CI-checked against the catalog.**
  `qe-blueprints/SKILL.md` carries a hand-maintained 28-row index table while
  Step 1 tells the model to enumerate `references/catalog/**/*.md` — two sources
  for one fact, drifting quietly in both directions: a row for a deleted file
  sends the model after a blueprint that is not there, and a file missing from
  the table is invisible to anyone reading the skill.
  `tests/lib/check-qe-catalog.py` fails when they disagree on membership, stage
  or duplication. Same posture as `mcp/content-index.json` — the derived view
  may exist, but it may not drift.

  No generated manifest file was added. `list_qe_blueprints` already derives
  `{id, stage, title, summary, uri}` at build time and `check-presets.py`
  resolves preset entries by globbing the catalog; a third on-disk copy would be
  one more thing to drift. The check makes the copy that already exists
  trustworthy instead.

### Fixed

- **`qe-blueprints` no longer collides with a governed repo.** It wrote full
  agent contracts to `.claude/agents/<name>.md` — a path `agentic-os` owns as
  journaled *thin pointers* to canonical contracts — and wrote repo-root
  `CLAUDE.md`, which `agentic-os` manages as a marker-delimited block replaced
  wholesale on upgrade. Both were silent corruption of an install this plugin
  did not know was there.

  Step 2 now detects `.agentic/agentic-os/install.json` and routes accordingly:
  contracts to the canonical agents dir (resolved from `journal.adoption` when
  the repo adopted an existing fleet, never hardcoded), `.claude/agents/` left
  to the installer's pointer synthesis, and the context file appended strictly
  outside the managed markers. Ungoverned repos are unaffected — the standalone
  path is unchanged, and `/agentic-init` is still never required.

- **A refused write is now reported, not routed around.** `guarded_write_paths.py`
  is fail-closed (exit 2), so a governed repo guarding `.claude/agents` or
  `CLAUDE.md` could stop the scaffolder mid-run with no documented behaviour.
  Step 5 now names the refused path and the rule that produced it, and forbids
  retrying, relocating to evade the guard, or summarizing files that were never
  written.

### Added

- **`write_scope` in generated contracts, in governed repos only.** The
  frontmatter allowlist banned every key beyond `name/description/tools/model`
  on the grounds that the runtime ignores them — correct in general, and wrong
  for this one key in a governed repo, where `write_scope_guard.py` parses it
  and enforces it at the tool call. The value comes from the blueprint role
  table's existing **Writes** column, so this is a rename rather than a new
  decision. Without it a write-capable QE agent was the one unbounded agent in
  an otherwise scope-enforced repo. Still omitted when ungoverned, where
  nothing reads it.

- A note in `eval-harness` distinguishing the `eval/` specs it generates into
  *your* repo from the `evals/` contract dir this marketplace's own CI requires
  of the skills it *ships*. Different scope and different owner; they only meet
  if you point the skill at the marketplace repo itself.

## [0.1.1]

### Changed

- Both skill descriptions (`qe-blueprints`, `eval-harness`) now carry an
  explicit `Not for:` routing clause per the agentic-os 0.4.0 contract
  standard (CI-enforced for new skills).

## [0.1.0] — initial public release

### Added

- Initial release of the `agentic-qe` plugin: a tool-agnostic catalog of
  Quality Engineering AI blueprints plus the skills to act on them, written
  in the agentic-os design language (blast-radius role tags R0–R3, human
  review gates before any R2/R3 step, model tiers economy/standard/premium,
  explicit grounding rules).
- **`qe-blueprints`** skill — 28 QE blueprints organized by STLC stage
  (`catalog/{analyze,design,build,execute,operate,report}/`), supported by
  `method/` (untrusted-content defense, agent topologies, context economy,
  tool access, design checklists), `platforms/` (Claude Code / Cursor /
  GitHub Copilot guides, connector catalog, unattended automation, model
  tiers), and `templates/` (scaffold building blocks). The skill interviews
  the user, matches intent to a blueprint, and scaffolds a ready-to-fill
  agent framework via `scripts/scaffold.{sh,ps1}`.
- **`eval-harness`** skill — generates a two-layer evaluation framework
  (deterministic contract checks + LLM-judge behavioral cases) for a repo of
  skills and agents, in TypeScript or Python, with a provider abstraction.
