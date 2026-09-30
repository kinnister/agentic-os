# Contributing

`main` is protected: **no direct pushes — by anyone, including the owner.** Every
change lands through a pull request whose `gate` and `mcp` CI checks pass. Pull
requests from contributors also require review from a code owner (@kinnister).

## Workflow

```bash
# 1. Branch off main
git switch -c feat/my-change        # or fix/…, docs/…, chore/…

# 2. Make the change, then run the gates locally (CI runs the same ones)
bash tests/t0/run.sh                 # 105 hook unit tests
bash tests/t0/run-output-contract.sh # 12 output-contract parser checks
bash tests/run-matrix.sh             # T1–T8 acceptance (re-runs the output-contract suite as T7)

# If you touched anything under plugins/**, also rebuild and commit the mcp
# content index (see "The mcp/ content index" below):
cd mcp && npm run build:content && cd ..
git add mcp/content-index.json

# 3. Push the branch and open a PR
git push -u origin feat/my-change
gh pr create --fill --base main
```

CI (`.github/workflows/ci.yml`) re-runs the hook unit tests and the T1–T8
acceptance matrix (the `gate` job) and, separately, builds and tests the `mcp/`
server on Node 20 and 22 (the `mcp` job, shown as `mcp (20)` / `mcp (22)`).
Both are required checks — a red run on either blocks merge. `@kinnister` is a
code owner, so the PR requests their review automatically.

> Branch protection must be configured to require both `gate` and every `mcp`
> matrix leg (`mcp (20)`, `mcp (22)`) as status checks. Until that's done in
> the repo's GitHub settings, the `mcp` job's drift and read-only gates are
> advisory only — this file cannot change that setting, only document it.

## The `mcp/` content index

`mcp/` serves `plugins/**` to MCP clients through a build-time index
(`mcp/content-index.json`) rather than reading the working tree live. If you
add, edit, or remove a file under `plugins/**`, you must also run
`cd mcp && npm run build:content` and commit the resulting
`mcp/content-index.json` — otherwise the `mcp` job's content-drift check
(`npm run check:drift`) fails CI.

## Rules that CI enforces

- **The acceptance matrix stays green.** New templates or skills must keep
  `tests/run-matrix.sh` fully passing (it prints its own `N passed, 0 failed`
  at the end) — add cases when you add behavior.
- **Manifests stay consistent** (`tests/lib/check-manifests.py`): every JSON
  manifest and preset parses, each plugin's `.claude-plugin` /
  `.cursor-plugin` / `.codex-plugin` manifests carry the same version, and the
  author/owner identity matches the canonical block everywhere.
- **Neutrality is mechanical** (`tests/lib/check-neutrality.py`): no PII,
  personal names, or organization names in tracked files — cleartext shape
  classes (emails, home paths, confidentiality markers, vendor model IDs)
  plus a hashed token denylist in `tests/lib/neutrality-policy.json`. The
  canonical plugin-author identity is the one sanctioned exception.
- **The `mcp/` content index stays in sync with `plugins/`** (`mcp` CI job,
  `npm run check:drift`): `mcp/content-index.json` is a build-time snapshot
  of every git-tracked file under `plugins/`, and it must match exactly — see
  "The `mcp/` content index" above.
- **Shipped HTML pages point at files that exist**
  (`tests/lib/check-html-refs.py`): `plugins/agentic-sdlc/sdlc.html` names a
  source file per inventory entry and fetches it on click, so a rename leaves a
  dead link that nothing else would notice. Every cited path is resolved here.
- **A plugin's shipped content carries a changelog entry**
  (`tests/lib/check-changelog.py`): the plugins are distributed — users install
  what is on `main`, and the CHANGELOG is the only place they learn what moved.
  A PR that changes anything under `plugins/<name>/` must also change that
  plugin's `CHANGELOG.md`. This runs on pull requests only, since it needs a
  base ref to diff against. For a change a user genuinely cannot observe, apply
  the **`no-changelog`** label; reach for it rarely, because a typo in shipped
  text is still text a user reads.
- **The originality attestation still holds**
  (`tests/lib/check-provenance.py --verify-attestation`): every tracked text
  file's hash must match `tests/lib/originality-attestation.json`, the recorded
  result of the maintainer's last corpus scan. CI has no corpus, so it enforces
  the record rather than repeating the scan — which means **a PR that edits
  tracked text goes red until a maintainer re-attests**. See
  [tests/README.md](tests/README.md) § Originality check; the re-attest step is
  under "Releasing" below.

## Releasing

Each plugin versions independently, so releases are cut and tagged per plugin:

1. Bump `version` in **all** of that plugin's host manifests
   (`.claude-plugin/plugin.json`, `.cursor-plugin/plugin.json`, and
   `.codex-plugin/plugin.json` where present) — CI fails on drift.
2. Move the plugin's `CHANGELOG.md` `[Unreleased]` entries under the new
   version heading.
3. Refresh the originality attestation from a maintainer machine that has the
   local fingerprint store, and commit it:

   ```bash
   python3 tests/lib/check-provenance.py --require-store   # full scan against the corpus
   python3 tests/lib/check-provenance.py --attest          # refuses unless the tree is clean
   git add tests/lib/originality-attestation.json
   ```

   `--attest` is the only way `--verify-attestation` can pass in CI, and it
   cannot be produced from a tree that has findings — so this step is where a
   release either confirms the tree is clean or stops.

   Run `--require-store` first and read its result: `--attest` on its own would
   still refuse a dirty tree, but the scan is what tells you the tree is
   *clean* rather than merely re-baselined. `--attest` also refuses a store that
   is not the one behind the current record (different salt, or a smaller
   corpus), and prints exactly which entries it added, changed, or removed —
   check that list matches the files you touched. From a worktree without the
   store, set `PROVENANCE_STORE` and `PROVENANCE_SALT` rather than copying
   either file (see [tests/README.md](tests/README.md)).
4. Merge via PR as usual, then tag the merge commit and push the tag:

   ```bash
   git tag -a agentic-os-v0.1.0 -m "agentic-os 0.1.0"   # agentic-sdlc-v<X.Y.Z> for the SDLC plugin
   git push origin --tags
   ```

Tags activate the clean template-only upgrade diff documented in
[`plugins/agentic-os/docs/UPGRADING.md`](plugins/agentic-os/docs/UPGRADING.md).

`mcp/` carries its own independent `version` in `mcp/package.json` and
releases as **`agentic-os-mcp-v<X.Y.Z>`**, matching its npm package name so a
tag, a GitHub release, and a published version line up. Its version is
asserted against the running server by a contract test. The package
(`agentic-os-mcp`) is published on npm and listed in the MCP Registry as
`io.github.kinnister/agentic-os`.

## Commit style

Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`). No AI
attribution footers.

## Reporting a bug or requesting a feature

Open a GitHub issue. Include the role preset(s) installed, the discovered
stack (matched curated profile, or a summary of the full-discovery result if
none matched), and (for bugs) the output of `/agentic-doctor`.

## License

By contributing, you agree your contribution is licensed under this repo's
[Apache-2.0 license](LICENSE).
