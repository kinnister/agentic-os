# Changelog

Notable changes to the `agentic-os` plugin, as distributed here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this distribution uses
Semantic Versioning. The plugin version lives in
[`.claude-plugin/plugin.json`](.claude-plugin/plugin.json).

## [Unreleased]

## [0.15.0] — 2026-09-30

### Highlights

- **Uninstall keeps files you had before agentic-os.** `agentic-uninstall
  --all` could delete a `CLAUDE.md` or `.claude/settings.json` that existed
  before install. Such files are now never deleted, even when a removal is
  confirmed.
- **Setup, upgrade and uninstall write through a journaled installer**
  (`runtime/run.py`). Your edits are never overwritten, and merges into your
  existing files apply only to the bytes you were shown. In Claude Code you
  approve installer commands rather than each file.
- **Requires Python 3.10 or newer.** The shared runtime declares
  `python >= 3.10`; the Python 3.9 bundled with macOS is not enough. Install a
  current Python from python.org or Homebrew.
- **Experimental shared runtime.** The SQLite lifecycle runtime for SDLC runs
  ships, but the workflow skills do not start managed runs yet.

### Runtime and installer reliability

- agentic-upgrade explains how to refresh an existing `.ao-new` merge file
  (a confirmation of its current bytes).

- agentic-init re-runs refresh only unmodified managed files; user-owned files
  are never refreshed silently.

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

- Setup, upgrade and uninstall now make journal and scaffold-file writes
  through the shared runtime (`install.apply`, `install.record`,
  `install.remove`, `install.merge-settings`) instead of editing `install.json`
  or scaffold files directly; `.gitignore` lines, the instruction scorecard and
  git hooks remain direct writes. Uninstall removes only wiring for hook
  scripts agentic-os installed, and un-wires (rather than deletes) an adopted
  settings file under `--all`; settings are always removed or un-wired before
  any hook script they wire. Merges into a user's existing `CLAUDE.md` or settings, and
  confirmed deletions, are compare-and-swap confirmations of the bytes shown.
  The reference install/uninstall executors run the same operations, so the
  acceptance matrix now exercises the shipped installer end to end.

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

### Added

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

- Hardened managed worker enforcement: quoted frontmatter globs are parsed, malformed assignment
  state fails closed, and read-only assignments cannot invoke shell mutation through the scoped
  host hook. The policy documents the host boundary and its sandbox limitation.

- Bundle the canonical versioned runtime contracts for independent installation, with deterministic drift checks and strict policy/input validation.

- **`devops` preset picks up the `agentic-sdlc` `telemetry-export` skill.**
  `agentic-sdlc` 0.7.0 adds an observability-adapter contract that exports a
  run's governance ledgers to a host-declared backend (Axiom or a generic
  OTLP-logs profile); see that plugin's changelog for the full contract. This
  entry only covers `agentic-os`'s side: the `devops` role preset now claims
  `telemetry-export` in its `sdlc_skills`, and `agent-registry.md.tmpl` gained
  the matching routing row so an installed agent can find its owner (per the
  0.14.0 fix above — an installed, unrouted skill is worse than an absent
  one). Role composition, write scopes, and gate ids for every other preset
  are unchanged.

### Changed

- **Owner links point at `kinnister`.** The GitHub account was renamed from
  `Jarroslav` to `kinnister`; author, homepage and repository URLs follow it.

- **Presets and the agent registry follow the `agentic-sdlc` skill renames.**
  Role presets claim skills by name and `agent-registry.md.tmpl` routes to them
  by name, so both moved in lockstep with the rename documented in the
  `agentic-sdlc` changelog. The `agentic-init` and `agentic-uninstall` prune
  rules parse those registry rows and were updated with them. Role composition,
  write scopes and gate ids are unchanged.

- **`project.md` renders the two adapter sections under neutral names.**
  `## MR Adapter` → `## Review Adapter`, `## Ticket Adapter` →
  `## Work Item Adapter`. The old headings named one vendor's term for an
  indirection whose entire purpose is to bind no vendor; see the `agentic-sdlc`
  entry for the full reasoning. Fields inside each section are unchanged, and
  `{{MR_ADAPTER}}` / `{{TICKET_ADAPTER}}` keep their variable names.

  Existing installs keep working until re-rendered: the sections are read by
  heading, so re-run `/agentic-init` or rename the two headings in
  `.agentic/guides/project.md` by hand.

## [0.14.0] — 2026-07-29

### Fixed

- **An installed skill an agent cannot route to is worse than an absent one.**
  17 of the 23 skills the presets install had no row in the agent registry, and
  none were marked `discoverable: false` — so every one was user-facing and
  unroutable. Since the ownership cue landed, that combination actively
  misfires: a compliant agent checks the registry, finds no owner, and
  escalates rather than using the correct installed skill.

  Blind D6 grading caught it behaviourally. Asked to "remember for next
  quarter", a `portfolio` agent ran the ownership check, found no row owning
  durable memory, and escalated — while `role-memory` sat installed and
  unreachable. It then diagnosed the cause itself, noting that
  `session_learnings_notice.py` advertises a memory store the install does not
  carry.

  Split by what each skill actually is: the 12 user-facing ones gain registry
  rows (`role-memory`, `code-review`, `sdlc-start`, `sdlc-autonomous`,
  `sdlc-task`, `sdlc-light`, `sdlc-doctor`, `release-manager`, `repo-guides`,
  `qa-foundation`, `qa-case-generator`, `qa-e2e-generator`), each pruned to the
  presets that declare it. The 5 the pipeline invokes rather than users —
  `decision-router`, `complexity-scoring`, `feature-verification`, `qa-gates`,
  `qa-planner` — are marked `discoverable: false`, which is what they were
  always meant to be.

  `check-presets.py` gains check (1c): every preset-declared skill must have a
  registry row or be `discoverable: false`. Check (1b) proves a shipped skill is
  claimed by a preset; nothing until now proved an installed agent could find
  its owner. (1c) uses the same predicate (1b) does — *allowed to be unclaimed,
  not forbidden from being claimed* — so a skill may be both preset-claimed and
  internal.

  One correction to the (1b) entry below: it cites `qa-planner` as a skill that
  "declares itself internal **and** is claimed by `qa`". It was claimed but did
  not carry the declaration; the same was true of the other four pipeline-only
  skills. That sentence describes the intended state, and is accurate as of this
  change rather than as of the one it appeared in.

### Added

- **Agents now check ownership before starting work, not only when asked to
  route.** Every routing sentence in the governance layer was reactive — "to
  find who handles X, consult the registry" — so an agent handed an
  in-domain-sounding request it did not own would simply start on it. Blind
  A/B grading of the `architect` preset caught this: asked to triage a flaky
  e2e test (owned by the QA preset's `test-failure-triage`), the installed
  agent planned the triage itself and never consulted the registry.

  The managed `CLAUDE.md` block gains a **Check ownership before starting
  work** section, applying to every agent, spawned or not, with the three
  branches spelled out: another asset owns it → hand it there naming the path;
  nothing owns it → say so and escalate; two rows match → that is a tie, and
  ties are escalated. It names the trap directly — being *able* to do the work
  is not the same as *owning* it.

  Re-running the same graded scenario against the fix: the agent enumerates all
  six registry rows, reports zero matches, and escalates rather than
  improvising. `run-matrix` asserts the cue renders across three preset unions
  so a conditional render cannot drop it for some roles.

### Fixed

- **The scaffolded ticket integration no longer claims a surface that isn't
  there.** `sdlc/config.json` hardcoded `integrations.ticket.enabled: true`
  regardless of the adapter, so every install that selected no ticket adapter
  got a machine copy asserting an enabled integration whose own `adapter` field
  read `documented in .agentic/guides/project.md (none)`. The guides said
  `not configured`; the config said enabled. Nothing reconciled the two, and a
  reader hitting the pair had no way to tell which one was lying.

  `enabled` is now the derived `{{TICKET_INTEGRATION_ENABLED}}` — `true` only
  when `{{TICKET_ADAPTER}}` is not `none`, the same condition that already
  drives `{{TICKET_ADAPTER_STATUS}}`, so the two cannot diverge again.

  Found by two independent role-grading candidates reading a `ba-po` solo
  install, which is the case that renders the `none` branch. `run-matrix` gains
  a check that reads the adapter back out of `project.md` — the single point of
  adapter configuration — and asserts the flag agrees with it, on both a
  `ba-po` scaffold (`none`) and a developer scaffold (a real adapter).

### Added

- **A shipped skill can no longer go unreachable unnoticed.** `check-presets.py`
  gains the reverse of its existing orphan check (1b): every skill under
  `agentic-sdlc` must be claimed by some preset, or declare `discoverable: false`.

  The two checks need different opt-outs, and the reason matters. (1b) reads its
  registry from `VARIABLES.md`, so an ID opts *out* by not being registered.
  Skills resolve from the filesystem, so every new skill is
  orphaned-by-default the moment it lands and there is no "just don't register
  it" escape — which is why the exemption has to be **declared** rather than
  listed. A hardcoded list in the checker would drift from the skills it
  describes, which is the exact failure (1b)'s own comment records for
  `hooks/migration-notice`.

  The predicate is *allowed to be unclaimed*, not *forbidden from being
  claimed*: `qa-planner` declares itself internal **and** is claimed by `qa`,
  which is correct. An exclusion rule would have failed it. And it keys on
  frontmatter rather than the "Not for: direct user invocation" prose because
  descriptions are YAML-folded — that clause line-wraps mid-phrase, so a naive
  match finds only one of the three internal skills.

  Proven in both directions: unclaiming `release-manager` fails on exactly that
  skill, and stripping `discoverable: false` from `test-heal` fails on exactly
  that one.

  The blueprint half is deliberately not here. Only `threat-model` is unclaimed
  and it is already deferred pending the access measurement; a marker column
  across all 28 index rows to exempt one deferred file is disproportionate, and
  it belongs with that measurement work.


- **Every user-facing skill and all but one blueprint are now reachable from a
  preset.** 8 of 26 SDLC skills and 13 of 28 QE blueprints were claimed by no
  preset, so they never surfaced at install — a user could not discover them
  without already knowing they existed. Worst of these: `qa-case-generator` and
  `qa-e2e-generator`, the two skills whose methodology was wired up one change
  earlier, were unreachable from the `qa` role.

  Assigned on the assets' own declarations rather than by name: `code-review`
  and `sdlc-light` → developer; `qa-case-generator`, `qa-e2e-generator` → qa;
  `release-manager` → pm-delivery. Blueprints follow catalog stage against role
  remit — eight to qa, two to devops, one each to developer and architect.

  What deliberately stays unclaimed: the three genuinely internal skills
  (`sdlc-pipeline`, `code-review-orchestrator`, `test-heal` — dispatched by the
  pipeline, never by a user), and `threat-model`, pending the access measurement
  that should decide whether it is retired or kept.

### Fixed

- **`sdlc-pipeline` did not declare itself internal.** It is the most
  emphatically pipeline-only skill in the repo — "never in direct response to a
  bare user request" — yet carried no `discoverable:` key, while the two other
  internal skills both set `discoverable: false`. The declaration is now
  consistent across all three, which lets a future exemption key on frontmatter
  rather than parsing prose: the descriptions are YAML-folded, so
  `Not for: direct user invocation` line-wraps mid-phrase and a naive match
  finds only one of the three.

- **`code-review` was misclassified in the agentic-sdlc README** as a "Phase
  skill … used by the task flow", contradicting its own frontmatter, which
  carries user trigger phrases ("review my changes", "review my branch") and
  calls itself the standalone front door. The README now matches the contract.

- **QE is discoverable from the QA role.** The composition work is worth nothing
  if a QA user never learns the catalog exists, which was the actual adoption
  blocker. The `qa` role on the setup guide now lists `qe-blueprints` among its
  skills and carries a phrase for invoking it, the `qa` preset description names
  the catalog as where its methodology comes from, and the README's plugin table
  no longer presents `agentic-qe` as a separate thing you would have to already
  know about — it works alone *and* composes.

- **`qe_blueprints` — a second cross-plugin composition field.** `agentic-qe`
  shipped as an island: no preset referenced it, it held no reference to the
  governance layer, and `agentic-sdlc` did not know it existed. A user
  installing `--presets qa` got the SDLC quality skills and never learned the
  28 QE blueprints were there.

  Presets now name blueprints the same way they name SDLC skills, and the field
  behaves identically: **nothing is copied into the target repo.** It is
  journaled, and it prunes agent-registry rows whose Owning asset names it —
  ``the agentic-qe `<id>` blueprint``, mirroring
  ``the agentic-sdlc `<name>` skill``. A blueprint id is the filename stem under
  `references/catalog/<stage>/`; `check-presets.py` now enforces that stems stay
  unique across stages, so an id can never be ambiguous, and resolves every
  entry against the catalog so a typo cannot ship silently.

  `agentic-qe` joins `manifest/dependencies.json` as **optional**. Blueprints
  are methodology references, so a repo without the plugin gets weaker guidance
  rather than a broken install — and `agentic-qe` stays installable on its own,
  which was always the point of it standing alone.

  The uninstall algebra gains `S_new` and `B_new` terms alongside `U_new`/`G_new`.
  Without them a removed role would leave its skill- and blueprint-owned rows
  behind, and the round-trip law `install(a,b) → uninstall(b) == install(a)`
  would fail — a fresh install of the remaining presets never writes those rows.
  `check-presets.py`'s two cross-plugin resolvers are now one table, so a third
  composition axis is a row rather than another hardcoded sibling path.

- **`/agentic-uninstall` — the installer's inverse.** Adding a role was
  additive and idempotent; removing one was not possible, which made "pick the
  roles you need" only half true and left `presets/README.md` promising a
  migration flow that did not exist. This is that flow.

  It is deliberately **not** a deleter. Presets are additive unions of shared
  template IDs, so deleting what a role lists would break the roles that stay —
  removing `qa` from a `developer,qa` repo frees only 9 of 45 IDs, and four
  presets (`architect`, `devops`, `pm-delivery`, `portfolio`) sole-own nothing
  at all. Instead the skill recomputes what an install of the *remaining*
  presets would produce and converges the repo to it, so:

      install(developer,qa) → uninstall(qa)  ==  install(developer)

  Everything else follows from that invariant. Journal entries for removed
  files are deleted rather than tombstoned (a tombstone would make the journal
  differ from a narrower fresh install's, and doctor Check 1 only verifies that
  journaled files exist). Files that are *kept* can still be re-rendered,
  because `ROLE_PRESETS_ACTIVE`, the per-role guide rows and the ai-policy
  enforcement rows all shrink with the union. `HITL_MODE` is asked rather than
  recomputed, since removing the only `strict` preset would otherwise relax a
  repo's governance silently.

  Two hazards get explicit handling. `.claude/settings.json` is un-merged
  subtractively — entries are dropped only when byte-equal to ours, emptied
  matcher groups and event keys collapse, and the write happens **before** the
  hook scripts it wires are deleted, so a crash can never leave a hook wired to
  a missing script (which doctor Check 5 describes as exiting 2 on every event
  and blocking all tool use). And a `pre-commit.local` displaced at install
  time is moved back, so a repo's own hook survives the removal — out-of-tree
  state `git status` would never have shown.

  `--dry-run` prints the whole plan and writes nothing. `--all` removes the
  layer entirely, leaving the repo installable with any role as if it had never
  been scaffolded. In `adopt-existing` mode nothing is deleted at all: adopted
  files are immutable by `agentic-upgrade`'s own rule, so the run reports what
  it would have done instead.

  Served over MCP as a seventh workflow prompt.

- **The invariant is machine-asserted, not just claimed.**
  `tests/lib/refuninstall.py` is the reference executor (the same role
  `refinstall.py` plays for init), `tests/lib/check-roundtrip.py` is the
  differential comparator, and `T9a`–`T9g` build both trees in the same run and
  diff them — tree, journal, scorecard and out-of-tree hooks. No golden to
  re-record: `tests/golden/fresh-developer-manifest.txt` is directory-level and
  cannot see a file deleted inside `.agentic/`.

  Writing the harness corrected the spec twice, which is the point of having
  one. The settings rule originally said to collapse matcher groups and event
  keys left empty; a fresh install *keeps* them, because the installer's prune
  reaches each group through its `"matcher"` branch and filters in place — so
  collapsing them produced a settings file no install can produce. And `--all`
  originally rewrote the journal after emptying the layer, resurrecting the
  directory it had just removed, and left an un-wired `settings.json` husk that
  a later install merged into instead of starting clean. `T9b` and `T9e` caught
  both.

- **Doctor Check 6 now detects the commit-blocking hazard.** `.githooks/pre-commit`
  runs `python3 .claude/hooks/precommit_review_gate.py precommit || exit $?` as
  its first action, and chains the repo's own `pre-commit.local` only
  afterwards. If the gate script is ever absent while the marked hook is still
  installed in `.git/hooks/`, `python3` exits non-zero and **every `git commit`
  in the repo is blocked** — out of the working tree, absent from the install
  journal, and with the team's own hook silenced too. Nothing detected this
  before. The check now fails, with the remedy, whenever a hook carrying the
  `agentic-os:` marker has no gate script behind it. Deliberately independent
  of the journal: the installed hook lives outside the tree and can outlive the
  layer that placed it.
- **`check-presets.py` asserts two composition invariants** the installer has
  always relied on implicitly. (2b) every preset carries
  `hooks/settings-fragment` plus the two hooks force-scaffolded with it — the
  fragment is preset-independent, which is what will let a role removal compute
  its settings subtraction from the pruning rule alone. (2c) the git layer
  (`githooks/pre-commit`, `hooks/precommit-review-gate`,
  `scripts/install-git-hooks`) is all-or-nothing per preset: splitting the trio
  across presets would make the commit-blocking state above reachable through
  an ordinary role removal. Both hold across all ten presets today; both fail
  loudly if a future preset breaks them.


- **Doctor Check 6 failed six of the ten presets.** Its git-hook clause was
  written unconditionally ("Missing installed hook ⇒ fail"), but `ba-po`,
  `data`, `design`, `pm-delivery`, `portfolio` and `security` carry no
  `githooks/pre-commit` — a repo installed with only those roles reported a
  failure for a hook it was never meant to have. The clause is now conditional
  on `.githooks/pre-commit` being present in `journal.files`; when it is not,
  `git_hook` reports `passed: true` and says why in its `detail`.

## [0.13.0] — Agent contracts get the gate skills already had

A grading pass against this plugin's own instruction-quality rubric found the
required contract blocks enforced on skills and on nothing else. Closing that
gap surfaced two defects the asymmetry had been hiding.

### Added

- **`tests/lib/check-agent-contract.py`** — deterministic CI check over all 21
  shipped agent contracts (14 scaffolded templates, 5 agentic-sdlc agents, 2
  generator exemplars). Asserts four of the rubric's required blocks: the
  `Not for:` routing clause, `## Decision rules` holding a DO/DON'T table, an
  escalate-never-decide list, and `## Stop and ask when`. Wired into `ci.yml`
  and `release.yml` beside the skill-contract check. Counted verification
  criteria stay model-graded — see the rubric's new "What is machine-enforced"
  section for why a regex cannot decide them.
- **`## Stop and ask when` on all five QA agent contracts** — pre-verdict halt
  triggers, distinct from the `## Escalate to human` section they already had:
  escalation resolves at the end of a run, stop-and-ask halts before an
  artifact exists. Each names the conditions that make its own gates
  unanswerable (an unreachable ticket adapter, a case with no parseable steps,
  a spec and tracker that disagree on which is newer).
- **Counted self-checks, `## Escalation`, and a change protocol in
  `ba-po-operating-model.md`** — seven `= 0` rules covering approval-before-write,
  read-back verification, invented acceptance criteria, conversation-only
  payloads, direct provider calls, discarded local stories, and MCP-blocked
  work. The guide now matches the shape of the other role-behavior guides, and
  its eval fixture grades against rules a run can recompute.

### Fixed

- **Agent frontmatter was unparseable YAML in 16 of 21 contracts.** The
  repo-wide `Not for:` retrofit put a `word:` pair inside bare unquoted
  `description` scalars, so a strict YAML reader rejected every core and QA
  agent template plus both exemplars (`mapping values are not allowed here`).
  All descriptions are now folded block scalars, and the new checker rejects
  bare ones. `story-proxy.md` in agentic-sdlc had the same break independently,
  via the `<example>Context:` text in its description.
- **The architect preset promised routing it did not install.** Its eval
  fixture expected "the dispatcher outputs the owning asset or escalates", but
  an architect-only scaffold contained neither `agents/dispatcher` nor
  `commands/dispatch`. The preset now installs both and defaults to
  `dispatcher` orchestration — matching ba-po, devops, pm-delivery and
  portfolio, which already pair `gated-autonomous` with `dispatcher`.
  `commands/pipeline-orchestrator` is retained: removing it would orphan the
  file in existing architect installs, and architect-only now exercises the
  both-commands `{{ORCHESTRATION_STYLE_RULE}}` variant that previously only
  appeared in multi-role unions.

### Changed

- **Exemplar headings normalized to sentence case.** `test-automation-author.md`
  used Title Case (`## When To Escalate To The Human`, `## Input Contract`)
  where every other contract uses sentence case. Generated contracts are
  modelled on the exemplars, so the divergence propagated into every generated
  fleet. The five machine-parsed output sections were already correctly cased
  and are untouched.
- **`check-ba-po-operating-model.py` matches its required literals with
  whitespace collapsed**, so a rule statement no longer fails because the
  paragraph around it was rewrapped.

## [0.12.0] — Every dot connected: skill routing, full-union proof, ten-role parity

The post-role-wave consolidation: the routing matrix now covers skill-owned
intents, every preset has a graded eval fixture, and the largest install shape
is finally tested.

### Added

- **Skill-owned rows in the agent-registry matrix** — six intents whose owner
  is an agentic-sdlc skill rather than an agent or command (story drafting →
  `product-owner`; requirements normalization → `requirements-intake`;
  commit/push/MR → `mr-creator`; MR watching → `mr-watch`; run inspection →
  `sdlc-status`; knowledge audits → `repo-audit-guides`), each with accurate
  preset parentheticals and human-gate notes. Installer spec and the reference
  executor prune them against the union's `sdlc_skills` — ba-po, pm-delivery,
  portfolio, and architect intents no longer dead-end in dispatcher
  escalation.
- **Preset eval fixtures for the five remaining roles** (developer, qa,
  architect, pm-delivery, portfolio) — eight counted scenarios each, plus the
  generic `tests/lib/check-preset-evals.py`, which requires a well-formed
  fixture for **every** preset (wired into the acceptance matrix).
- **T3j: the full ten-preset union install** — previously the largest union
  ever tested was two presets. T3j installs all ten and asserts governance
  promises resolve, active mode is strict (strictest-wins), PATTERNS/registry
  integrity, all six role-specific guides present, every agent and skill row
  in the matrix, zero unrendered placeholders, and skill-row pruning in both
  directions (present in the union, absent from a developer-only scaffold).

### Changed

- Ten-role parity across every remaining seven-role surface: README intro,
  Start-here note, "Using it, by role" (three new bullets + incident triage on
  devops + the no-code note), Glossary, FAQ, MCP README examples table,
  setup-page meta description, and the stale partial enumerations in
  agentic-init/agentic-upgrade/stack-discovery/registry template/ROADMAP/
  tests docs (portfolio joins the git-layer exclusion list; "any no-code
  union" replaces the qa/ba-po/pm-delivery-only lists).
- `tests/lib/check-presets.py` prints usage instead of a traceback and
  resolves its plugin path from any cwd.
- `tests/README.md` documents T3e, T3g, the fixtures checker, and T3j.

## [0.11.1]

### Changed

- **The dispatcher's PASS is now a counted signal**: `PASS` iff matrix rows
  matching the intent = 1, recomputed against the registry table — 0 or ≥2
  matches is a `FAIL` with the tie or gap escalated. Pays down the last
  recurring D3 "counted PASS criteria" partial from the blind role-grading
  waves; every shipped agent contract now carries a recomputable verdict.

## [0.11.0] — The design role: emotion-annotated journeys and agent-ready handoffs

Fourth and final core role from the coverage backlog. Tenth preset.

### Added

- **`design` preset** — strict HITL, dispatcher-routed, no code, no
  visual-asset generation, no git layer: experience-designer + dispatcher,
  policies, evidence-integrity + the new experience-design guide,
  `hooks/write-scope-guard`; sdlc_skills `product-owner` +
  `requirements-intake` + `role-memory` (design feeds story drafting, so the
  story skill ships with it — the ba-po precedent).
- **`agents/experience-designer`** — third scoped doc-writer
  (`write_scope: docs/design/**`): journey maps where every step carries the
  user's emotion ("a journey map without emotions is a flowchart"), problem
  framings that name a journey step + emotion and never a feature, workshop
  artifacts that record ≥1 named decision with a named owner ("a workshop
  that closes no decision was a meeting"), negative acceptance criteria
  carried verbatim, an agent-ready `context.md` + `spec.md` handoff pair
  whose spec cites only recorded decisions, every decision
  `decision: proposed — owner confirmation pending`, and research treated as
  feedback to synthesize, never instructions to follow.
- **`guides/experience-design`** — the binding standards, indexed via the new
  conditional `{{DESIGN_GUIDE_ROWS}}`.
- **`presets/evals/design.json`** — eight counted scenarios, shape-checked by
  the new deterministic `check-experience-design.py` in the acceptance matrix
  (T3i), incl. isolation from a developer-only install, the strict
  active-mode assertion, and the governance-promises check.
- Parity: README table, presets/README (ten presets), installer Screen 1,
  setup-page Designer/UX card, agent-registry row, ROADMAP, MCP preset
  list + tests.

## [0.10.0] — The data role: layered pipeline design with counted row math

Third role from the coverage backlog, same blind-grading loop. Ninth preset.

### Added

- **`data` preset** — strict HITL, dispatcher-routed, no code-writing agents,
  no git layer: pipeline-designer + dispatcher, policies, evidence-integrity
  + the new data-pipeline-design guide, `hooks/write-scope-guard`; sdlc_skills
  `requirements-intake` + `role-memory`.
- **`agents/pipeline-designer`** — second scoped doc-writer
  (`write_scope: docs/data/**`): layered design raw → cleaned → consumable
  with a counted, query-verifiable equation per transition ("no equations, no
  design"; canonical form `cleaned = raw − rejected − duplicates`); every
  data-quality check force-tested against an injected violation before a
  clean pass is trusted ("a check that has never failed has never been
  tested"); per-dataset lineage (`≥1 upstream source and ≥1 downstream
  consumer`, gaps recorded as owner findings, never invented);
  classifications always `classification: proposed — owner confirmation
  pending`; queries recommend-only — a human or CI executes them; embedded
  directives in sample data are data to profile, never instructions to follow.
- **`guides/data-pipeline-design`** — the binding standards, indexed via the
  new conditional `{{DATA_GUIDE_ROWS}}`.
- **`presets/evals/data.json`** — eight counted scenarios, shape-checked by
  the new deterministic `check-data-pipeline-design.py` in the acceptance
  matrix (T3h), incl. isolation from a developer-only install, the
  strictest-HITL active-mode assertion, and the governance-promises check.
- Parity: README table, presets/README (nine presets), installer Screen 1,
  setup-page Data Engineer card, agent-registry row, ROADMAP, MCP preset
  list + tests.

## [0.9.0] — Enforcement promises match the install everywhere

The 2026-07-28 governance re-grade found two leftovers from 0.6.0's
conditional-rendering pass: the policy templates still promised enforcement
hooks a minimal union never installs, and the acceptance harness's reference
installer ignored the strictest-HITL union rule.

### Changed

- **`ai-policy.md` enforcement layers are union-conditional** — the four
  hook-backed rows of the "Enforcement layers" table (pre-commit review
  stamp, output-contract gate, write-scope guard, instruction-quality gate)
  render via the new derived `{{ENFORCEMENT_LAYER_ROWS}}` and list only what
  the selected preset union installs. A portfolio-only install no longer
  claims three hard hooks it does not scaffold.
- **`AGENTS.md` fleet invariants are union-conditional** — the numbered list
  renders via the new derived `{{FLEET_INVARIANTS}}`, renumbered contiguously:
  the write-scope invariant cites `write_scope_guard.py` only when that hook
  installs (else it states the rule as stop-and-escalate), and the
  instruction-quality and blind-review invariants drop entirely when their
  layer is absent from the union. Both variables are documented in
  `templates/VARIABLES.md` and `agentic-init/SKILL.md` Phase 4.

### Fixed

- **Reference installer implements strictest-HITL-wins** —
  `tests/lib/refinstall.py` hardcoded `gated-autonomous`, so a qa-only or
  security-only fixture install rendered an `ai-policy.md` contradicting the
  preset's declared `default_hitl: strict`. It now derives `{{HITL_MODE}}`
  from the union (`strict > gated-autonomous > autonomous`) per the SKILL.md
  Screen 1 rule; run-matrix T3g pins the rendered active mode for qa-only,
  security-only, developer-only, and developer+qa unions.
- **`check-governance-promises.py` also audits `AGENTS.md` + `ai-policy.md`**
  for citations of uninstalled hooks, git hooks, and scripts — it previously
  passed while a portfolio scaffold cited three uninstalled enforcement hooks.

## [0.8.0] — Required contract blocks retrofitted onto every shipped agent template

Closes the 2026-07-27 role-grading baseline's cross-cutting D3 finding: the
0.4.0 contract-hardening wave added the rubric's § Required contract blocks to
the generator and exemplars, but none of the pre-0.5.0 shipped templates
carried them. All 10 now do; no behavior was added — every new block restates
rules its contract already stated in prose.

### Added

- **`## Decision rules` DO/DON'T table on all 10 pre-0.5.0 agent templates**
  (`blind-code-reviewer`, `dispatcher`, `instruction-auditor`,
  `pr-pipeline-gate`, `security-reviewer`, `test-automation-author`,
  `test-case-generator`, `test-case-syncer`, `test-failure-triage`,
  `work-item-creator`), 4–6 rows each, grounded in each contract's existing
  rules. The `test-automation-author` and `test-failure-triage` tables digest
  guide rules and are wrapped in `agentic-os:rules` provenance markers naming
  `test-design-pattern.md` and `flaky-protocol.md` respectively.
- **`## Stop and ask when`** on `instruction-auditor` (ungovernable input,
  missing rubric, unmatchable `content_sha256`) and `pr-pipeline-gate` (no
  open MR/PR, wrong target branch, adapter unavailable) — the two templates
  that lacked it.
- **Escalate-never-decide list on all 10 templates**: each contract's
  negative-scope section now states the always-human-owned decisions as a
  list sourced from `.agentic/guides/policy/escalation-policy.md`
  (previously prose-only equivalents); templates without a negative-scope
  section gained `## What this agent does NOT do`.
- **`{{BA_PO_GUIDE_ROWS}}`** derived variable: `PATTERNS.md` index rows for
  `ba-po-operating-model.md` and `mcp-onboarding.md`, emitted only when those
  guides are installed — so multi-role unions that include the ba-po guides
  no longer leave them unindexed (registered in `templates/VARIABLES.md`,
  substituted in `agentic-init` Phase 4, slotted in
  `templates/governance/PATTERNS.md.tmpl`).

### Fixed

- **`test-failure-triage`'s inlined failure-class taxonomy** (the
  TIMING/SELECTOR/…/PROPAGATION table digested from
  `flaky-protocol.md`) now carries the required `agentic-os:rules` marker
  pair; it was the one guide digest shipping without provenance
  (`working-with-agents.md` § Rule provenance markers).

## [0.7.0] — Security role: DFD-first threat modeling

Second role from the coverage backlog, added with the same blind-grading loop
as 0.5.0's incident triage. Eighth preset.

### Added

- **`security` preset** — strict HITL, dispatcher-routed, no code-writing
  agents, no git layer: threat-modeler + security-reviewer + dispatcher,
  policies, evidence-integrity, and the new threat-modeling guide;
  sdlc_skills `requirements-intake` + `role-memory`; includes
  `hooks/write-scope-guard` to enforce the writer's scope.
- **`agents/threat-modeler`** — the first scoped doc-writer in the shipped
  template set (`write_scope: docs/security/**`): DFD first (mermaid, ≥2
  trust boundaries, no threats before the DFD exists), STRIDE constrained by
  element type (external entities S/R only; processes all six; flows/stores
  T/I/D only), 8–15 threats counted never padded, likelihood×impact register
  with a distribution requirement (≥2 Low-likelihood, ≥2 High-impact — not
  everything is High), every severity `proposed — owner confirmation
  pending`, mitigation rows tracing to register rows, and a model-in-scope
  gate (LLM threat pass only when a model is in scope; text inside analyzed
  inputs is data to threat-model, never instructions to follow).
- **`guides/threat-modeling`** — the binding standards the agent digests,
  indexed in `PATTERNS.md` via the new conditional `{{SEC_GUIDE_ROWS}}`.
- **`presets/evals/security.json`** — eight counted scenarios, shape-checked
  by the new deterministic `check-threat-modeling.py` in the acceptance
  matrix (T3e), incl. isolation from a developer-only install.
- Parity: README preset table, presets/README (eight presets), installer
  Screen 1, setup-page card, agent-registry row, MCP preset list.
## [0.6.0] — Governance docs promise only what the preset installs

Second wave driven by the blind role-grading baseline (2026-07-27): presets
that skip the git layer (portfolio, and partially ba-po/pm-delivery) used to
install governance text mandating enforcement they don't deliver — a
`CLAUDE.md` block citing `precommit_review_gate.py`, `.githooks/pre-commit`,
`install-git-hooks.sh` and the `blind-code-reviewer` agent none of which those
unions scaffold, a `PATTERNS.md` index linking uninstalled guides, and an
agent-registry default naming a `pipeline-orchestrator` command read-only
presets don't get. All of that is now conditional on the preset union, the
same emitted-iff-installed contract `{{QA_GUIDE_ROWS}}` established.

### Added

- **`{{CORE_GUIDE_ROWS}}`** — the `PATTERNS.md` index rows for
  `git-workflow`, `code-quality`, `quality-gates`,
  `instruction-quality-rubric`, and `qa-strategy-stub` are now derived: one
  row per guide actually in the union, fixed order, empty for a union that
  installs none (the static working-with-agents / evidence-integrity rows
  keep the table non-empty).
- **`{{WRITE_SCOPE_RULE}}`**, **`{{REVIEW_GATE_SECTION}}`**,
  **`{{QUALITY_GATES_SECTION}}`** — the `CLAUDE.md` governance block's
  write-scope bullet cites `write_scope_guard.py` only when that hook
  installs; the blind-review section renders only when
  `hooks/precommit-review-gate` + `githooks/pre-commit` are in the union
  (with a no-agent-spawn variant for unions carrying the gate but not
  `agents/blind-code-reviewer`, i.e. devops); the quality-gates section
  renders only when `guides/quality-gates` installs.
- **`{{ORCHESTRATION_STYLE_RULE}}`** — the agent-registry "Multi-step work"
  bullet now names only orchestration commands the union installs, instead
  of unconditionally defaulting `gated-autonomous` installs to a
  `pipeline-orchestrator` command that read-only presets don't get.
- **`check-governance-promises.py`** + acceptance-matrix section T3e — for
  portfolio-only, ba-po, devops, and developer scaffolds: every enforcement
  artifact `CLAUDE.md` cites exists, every `PATTERNS.md` guide link
  resolves, the registry's orchestration rules name no absent command — and
  full installs verifiably keep the review-gate mandate.

### Changed

- `agentic-init` SKILL.md Phase 4 and `templates/VARIABLES.md` document the
  five new derived variables and their substitution rules (section values
  substitute before the scalar/list pass so the nested `{{GATE_COMMANDS}}`
  still renders).

## [0.5.0] — Read-only incident triage for the devops role

First role-capability wave driven by the blind role-grading baseline
(2026-07-27): the devops preset gains an incident-triage capability, and the
baseline's one hard checker failure is fixed.

### Added

- **`agents/incident-triage`** — read-only incident reporter for
  production/runtime incidents: exactly three ranked root-cause hypotheses,
  each with a confidence label, its evidence lines, and the cheapest
  read-only next diagnostic; shortfalls stated ("1 of 3 slots
  evidence-backed") with unsupported slots labeled `speculative — no direct
  evidence`; number+unit runtime bounds with the
  `AGENTIC_INCIDENT_TRIAGE_DISABLED=1` kill-switch; allowlist-only tooling.
  Never mutates cluster or infra state — fixes are human-executed. Carries
  the full required-contract-block set (Decision rules table, Stop and ask
  when, counted PASS criteria, provenance-marked guide digests).
- **`guides/incident-triage`** — the binding triage standards the agent
  digests: read-only principle, three-hypothesis rule (governed by
  evidence-integrity's no-padding rule), runtime bounds ("a bound without a
  unit is not a bound"), allowlist-not-denylist, human-owned escalation.
  Indexed in `PATTERNS.md` via the new conditional `{{OPS_GUIDE_ROWS}}`
  variable — only installs that carry the guide index it.
- **`presets/evals/devops.json`** — eight counted triage scenarios (second
  preset-level eval fixture after ba-po), shape-checked by the new
  deterministic `check-incident-triage.py` in the acceptance matrix (T3d),
  including isolation (a developer-only install must not receive the guide).
- devops preset installs the pair; its description, README row, and setup-page
  entry now say so.

### Fixed

- **`guides/evidence-integrity` registered in `templates/VARIABLES.md`** — it
  was claimed by every preset since 0.4.0 but never registered, so
  `validate-presets.sh` failed on all seven presets (unnoticed because that
  script is not wired into CI; `check-presets.py` only checks the reverse
  direction).

## [0.4.0] — Contract hardening, evidence integrity, rule provenance

Tightens the authoring standards every agent contract is built and graded
against, and gives inlined rule digests a declared source of truth.

### Added

- **`guides/evidence-integrity`** — new blocking standards guide
  (`.agentic/guides/standards/evidence-integrity.md`) against fabricated
  compliance: no self-citation, quotes verified verbatim before presenting,
  classification/approval tags only from durable owner-authored records, no
  padding lists to a required count (shortfalls stated, extras labeled
  `speculative — no direct evidence`), sourced/unverified tags preserved across
  documents, and a counted self-check. Installed by every role preset and
  indexed in `PATTERNS.md`.
- **Required contract blocks** section in the instruction-quality rubric — the
  normative structural list for agent contracts: a `Not for:` routing clause in
  the description, a `## Decision rules` DO/DON'T table, an
  escalate-never-decide list, `## Stop and ask when` triggers, and counted
  (recomputable) verification criteria. The agent-generator skeleton, both
  exemplars, and all ten shipped agent templates now carry these blocks;
  the instruction-auditor grades against the list.
- **Rule provenance markers** — inlined guide-rule digests in generated
  contracts are wrapped in `agentic-os:rules source="…" topic="…"` marker
  pairs (spec: `working-with-agents.md` § Rule provenance markers; index note
  in `PATTERNS.md`). The agent-generator emits them; a deterministic CI check
  validates marker syntax and that standards/policy sources map to shipped
  templates.

### Changed

- The three skill descriptions (`agentic-init`, `agentic-doctor`,
  `agentic-upgrade`) gained explicit `Not for:` routing clauses; new skills
  must include one (CI-enforced; pre-existing sdlc skills are grandfathered
  with a visible warning).
- Upgraders: expect `/agentic-upgrade` diff prompts on the rubric,
  `working-with-agents.md`, `PATTERNS.md`, and any locally modified agent
  templates; the new evidence-integrity guide arrives automatically as a new
  preset template.

## [0.3.0] — BA/PO onboarding and MCP access

Makes `ba-po` a first-class role rather than a preset that installed no guidance
of its own, and gives the business roles a supported path to data that does not
assume a working MCP connection.

### Added

- **Screen 2 — MCP access** in the `/agentic-init` interview: a required
  single-choice screen (`connect now` / `configure later` / `continue without
  MCP`) recorded as `answers.mcp_state` (`configured`, `deferred`,
  `without-mcp`). MCP stays optional — the no-MCP path is supported by pasted
  tables, CSV extracts, screenshots, and manually supplied findings — and an
  unavailable server is recorded as `unavailable` rather than blocking the
  install. Connecting now surfaces the easiest available route and host-specific
  verification commands in the generated MCP onboarding guide. This makes the
  installer seven screens: the HITL dial, autonomy matrix, gates, stack confirm
  and adapter screens shift from 2–6 to 3–7.
- **`guides/mcp-onboarding`** — the shared, host-specific MCP guidance for the
  business roles, generated to `.agentic/guides/standards/mcp-onboarding.md`.
  Installed only when a selected preset declares it, so a developer-only install
  is unaffected.
- **`guides/ba-po-operating-model`** — the role-specific BA/PO entrypoint. It
  delegates to the existing product-owner, requirements-intake and adapter
  contracts rather than defining a second orchestration system beside them.
- **`{{TICKET_ADAPTER_STATUS}}`**, derived from `{{TICKET_ADAPTER}}`, so a
  generated guide can state the adapter's real state instead of asserting one.
- An eval set for the `ba-po` preset (`presets/evals/ba-po.json`).

### Changed

- The `ba-po` preset installs the two new guides, so a `ba-po`-only install now
  scaffolds its own operating model instead of leaving the role undocumented.
- **Role selection is explicit.** The installer never silently selects
  `developer`, `ba-po`, or any other role: Screen 1 asks unless `--presets` was
  passed. `--defaults` accepts detected stack and autonomy defaults only — it
  does not invent a role selection, and is valid only alongside an explicit
  `--presets` or an existing journal.
- Role changes are documented as additive for this lifecycle. Removing a role is
  not automatic, because its files may have been edited by the user; removal
  needs an explicit future migration flow.

### Fixed

- The generated `sdlc/project.md` hard-coded **Status: configured** for the
  ticket adapter. An install that selected no adapter therefore claimed one was
  configured and hid the local-work-item fallback; it now renders the derived
  status and makes that fallback visible.
- The same template hard-coded **Status: configured** for the MR adapter, which
  is equally optional (`gh` / `glab` / MCP / **none**), so a repo with no review
  path was handed a guide asserting one existed. The generated value could never
  be `not configured`, even though that is half of the documented schema — which
  left the consumers' fallbacks unreachable: `qa-e2e-generator` would attempt
  MR-diff steps instead of dropping to commit search, and `mr-creator`'s
  infer-from-remote recovery never triggered. Added `{{MR_ADAPTER_STATUS}}`,
  derived from `{{MR_ADAPTER}}` exactly as the ticket adapter's status is.

## [0.2.0] — mature fleet adoption and native Codex packaging

### Added

- Native Codex plugin metadata, so the governance plugin installs on Codex the
  same way it does elsewhere.
- A deterministic, fail-closed adoption probe
  (`scripts/detect-adoption.py`) for repositories that already treat `.agents/`
  as their canonical agent, skill, hook and state layer. It reports a conflict
  rather than guessing, and a conflict stops the install.
- An `origin` field in the install journal, distinguishing assets adopted from
  a fleet the repo already had from the ones agentic-os wrote or generated —
  `owner` alone could not express that difference.
- `{{SKILLS_CANONICAL_DIR}}` and `{{ORCHESTRATION_STATE_DIR}}`, so templates can
  address an adopted layout instead of assuming `.agentic/`.
- Codex-aware dependency, adapter, hook, rule and doctor requirements.

### Changed

- `/agentic-init` adopts an existing neutral fleet rather than generating a
  competing `.agentic/agents/` tree beside it.
- `/agentic-upgrade` and `/agentic-doctor` resolve the canonical directories
  from the journal, and treat adopted assets as user-owned: verified and
  reported on, never rewritten.

### Fixed

- The git-workflow guide template now instantiates under `.agentic/guides/`,
  matching the directory every other guide template uses.

## [0.1.0] — initial public release

First public version.

### Added

- **Six-screen installer** (`/agentic-init`): role presets, HITL dial, autonomy
  matrix, gates, stack confirm, ticket/MR adapter. `--defaults` accepts every
  detected default. Local hook/session state (`.claude/.review-stamp`,
  `.claude/checkpoints/`, `.agentic/state/`) is gitignored at install.
- **Seven role presets** (developer, QA, BA/PO, architect, devops, PM/delivery,
  portfolio), additive — install several and their template sets union
  (strictest HITL wins).
- **The HITL enforcement pillar**: policy files (autonomy matrix + escalation
  ladder), the output-contract parser, and hard exit-2 PreToolUse gates
  (blind pre-commit review, write-scope guard, guarded write paths, human-gated
  commands, instruction-quality spawn gate). Block gates fail closed on input
  they cannot evaluate.
- **Evidence-grounded stack discovery**: six curated profiles (Next.js/Supabase,
  Django, Spring, Rails, Go, Playwright) recognized instantly; anything else gets
  a full from-scratch inspection, not a degraded stub.
- **Generated, audited agent contracts** and stack guides for the detected stack,
  each graded against the instruction-quality rubric before being armed.
- **Advisory + safety hooks**, installed per preset:
  - *Prompt-scan guard* (UserPromptSubmit) — catches secrets pasted into
    prompts before they are sent, using generic shape classes only (private-key
    blocks, JWTs, credential assignments, basic-auth URLs, Luhn-valid card
    numbers, high-entropy tokens near credential keywords) plus warn-only email
    PII; modes `warn`/`block`/`audit`, masked audit trail, fails open.
  - *Context-monitor* (PostToolUse, advisory-only) — announces context usage
    at 65%/75% thresholds ahead of the PreCompact checkpoint hook.
  - *Lint-on-save* (PostToolUse Write/Edit) — fix-then-recheck on each saved
    source file; remaining errors surface in the same turn. Fails open on
    missing, broken, or unconfigured linters.
  - *Session-learnings notice* (Stop, advisory-only) — detects correction
    signals in the transcript and nudges capturing the lesson into the durable
    memory store.
- **SDLC host config** (`sdlc/config.json.tmpl`): `context_boundaries`
  (plan→implementation fresh-session notice) and `model_tiers`
  (`economy`/`standard`/`premium`, all defaulting to `"inherit"` — concrete
  model IDs are user-supplied values only; the repo's neutrality scan enforces
  that none ships).
- **`/agentic-doctor`** verification pass (imports each managed hook, not just
  `py_compile`) and **`/agentic-upgrade`** three-way reconciliation
  (see [`docs/UPGRADING.md`](docs/UPGRADING.md)).

No upgrade path from a prior version — this is the first release.
