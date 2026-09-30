# Release runbook

This is the maintainer's checklist for cutting a release of `agentic-os-mcp`.
It is a human-run procedure — `.github/workflows/release.yml` automates the
publish itself once you push the tag, but every step before that (bumping
versions, updating the changelog, merging) is done by hand through the normal
PR flow.

**The most important sentence in this document: npm publishes are
permanent.** npm refuses to republish a version number once it has been
published — even if you unpublish it first, that exact version can never be
reused. Unpublishing itself is also heavily restricted (npm only allows it
within 72 hours of publish, and only if no other package depends on it).
Treat every push of an `agentic-os-mcp-v*` tag as a one-way door: if the
package is broken, the fix is a **new** version, not a redo of the old one.

## One-time setup (before the first release)

1. **Configure npm trusted publishing for the package.**
   - Log in to npmjs.com as the account that owns `agentic-os-mcp`.
   - Package page → Settings → **Publishing access / Trusted publisher** →
     GitHub Actions, with:
     - organization or user: `kinnister`
     - repository: `agentic-os`
     - workflow filename: `release.yml`
     - environment: leave empty (the workflow declares none)
   - That is the whole credential: the workflow's own GitHub OIDC token is
     exchanged for a short-lived publish credential at run time. There is no
     npm token to create, store, or rotate, and no `NPM_TOKEN` repository
     secret — if one still exists it is unused and can be deleted.
   - History, so nobody reintroduces a token: the original setup used a
     classic **Automation** token as `NPM_TOKEN` (granular/publish tokens
     fail headless CI with `EOTP`). That worked through 0.2.1 and then npm
     began refusing it outright — the 0.2.2 release failed with
     `403 … Two-factor authentication is required to publish this package
     but an automation token was specified` on 2026-07-27, with no change on
     our side. npm is retiring token-based publishing; trusted publishing is
     the supported replacement, and the version was not burned because the
     workflow fails closed.
   - The publish job upgrades npm to `>= 11.5.1` before publishing — the
     OIDC exchange does not exist in the npm 10.x that Node 22 bundles. Keep
     that step.
3. **The MCP Registry namespace case has already been confirmed — read this
   before touching it again.** `mcp/package.json`'s `mcpName` and
   `mcp/server.json`'s `name` are both `io.github.kinnister/agentic-os`
   (all lowercase), matching the real GitHub owner login exactly.

   **How this was confirmed, and why "run `mcp-publisher login github` and
   see what it prints" does not work:** `login` only ever prints
   `Logging in with %s...` and `✓ Successfully logged in` (upstream
   `cmd/publisher/commands/login.go`) — it never prints the granted
   namespace. Watching the first `release.yml` run's "Authenticate to MCP
   Registry" step doesn't work either, for the same reason: that step's
   output is identical, and by the time it runs, `npm publish` has already
   happened — the door is already closed if the case turns out wrong.

   The procedure that actually answers the question: log in locally, then
   decode the JWT the CLI saved and read its granted permissions directly.

   ```bash
   mcp-publisher login github        # opens a device-code flow in your browser
   node -e "
     const fs = require('fs');
     const os = require('os');
     const path = require('path');
     const { token } = JSON.parse(fs.readFileSync(
       path.join(os.homedir(), '.config', 'mcp-publisher', 'token.json'), 'utf8'
     ));
     const payload = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString());
     console.log(JSON.stringify(payload.permissions, null, 2));
   "
   ```

   This is exactly what `mcp/scripts/check-registry-permission.mjs` does in
   CI (see `.github/workflows/release.yml`'s "Assert Registry permission
   covers our declared name" step) — it decodes the same token file and
   checks the same `permissions[].resource` field against `server.json`'s
   `name`, and fails the job before `npm publish` runs if it doesn't match.
   Running the command above locally is the same check, by hand, before you
   even push a tag.

   **What was found, verified directly against upstream
   `modelcontextprotocol/registry` source (2026-07):**
   - `internal/api/handlers/v0/auth/github_oidc.go`'s `buildPermissions`
     grants `io.github.<repository_owner>/*` using the raw GitHub OIDC
     `repository_owner` claim — no case-folding.
   - `internal/auth/jwt.go`'s `isResourceMatch` is `strings.HasPrefix`,
     case-sensitive, with zero `ToLower` calls anywhere in that file,
     `publish.go`, or `github_oidc.go`.
   - This repo's actual GitHub owner login is `kinnister` (all lowercase) —
     confirmed via `gh api repos/kinnister/agentic-os --jq .owner.login`.
   - So the grant is `io.github.kinnister/*`, and `mcpName` / `name` must be
     `io.github.kinnister/agentic-os` to match. **A differently-cased owner
     (`io.github.Kinnister/...`) is wrong and would 403 at the Registry
     publish step — after npm publish has already succeeded and burned the
     version number.** This was caught before the first release, not after.
   - One correction to the field name, for anyone re-deriving this from the
     JWT payload: the permission's namespace pattern is the JSON field
     `resource` (Go struct tag `json:"resource"` on
     `auth.Permission.ResourcePattern`), **not** `resource_pattern` —
     easy to guess wrong from the Go field name alone.

   If this repository's GitHub owner login ever changes (a rename, or a
   transfer to another account/org), this whole confirmation is void and
   must be redone from scratch — do not assume the case carries over.

No setup is needed for the Registry side beyond the above: the release
workflow authenticates with `mcp-publisher login github-oidc`, which uses the
workflow's own GitHub Actions OIDC token — no PAT, no additional secret.

## Each release

1. **Bump the version in all five files, together:**
   - `mcp/package.json` → `version`
   - `mcp/server.json` → `version` (and `packages[0].version`)
   - `mcp/manifest.json` → `version`
   - `mcp/package-lock.json` → `version` (twice: the root and the `""` entry)
   - `mcp/src/index.ts` → the hardcoded `version` in the server identity

   `mcp/tests/package.test.ts` asserts the first three agree with each other
   (and with `server.json`'s `name` / `packages[0].identifier` against
   `package.json`'s `mcpName` / `name`). The last two are asserted elsewhere and
   are easy to miss: `src/index.ts` hardcodes what the server reports over the
   wire, so bumping `package.json` alone leaves the contract test red, and a
   stale lockfile version makes `npm ci` disagree with the manifest. A mismatch
   in any of them fails `npm test` before you ever reach the tag.

   Verify with `grep -rn "<old-version>" mcp --include="*.json" --include="*.ts"`
   (excluding `node_modules` and `dist`) — the count should reach zero.
2. **Move `mcp/CHANGELOG.md`'s `[Unreleased]` entries under the new version
   heading**, dated, following Keep a Changelog.
3. **If `plugins/**` changed since the last release, refresh the originality
   attestation** — the server bundles that content into `dist/content/`, so a
   release publishes it:

   ```bash
   cd .. && python3 tests/lib/check-provenance.py --require-store
   python3 tests/lib/check-provenance.py --attest
   git add tests/lib/originality-attestation.json && cd mcp
   ```

   Needs a maintainer machine with the local fingerprint store; see
   `CONTRIBUTING.md` § Releasing and `tests/README.md` § Originality check.
   `release.yml` re-runs the repo gate, which includes `--verify-attestation`.
4. **Open a PR, get it through the `gate` and `mcp` CI checks and review, and
   merge to `main`** — the normal workflow described in `CONTRIBUTING.md`.
   Do this *before* tagging: the tag must point at a commit that has already
   passed CI once as a PR, not at unreviewed work.
5. **Tag the merge commit and push the tag:**

   ```bash
   git checkout main && git pull
   git tag -a agentic-os-mcp-v0.2.0 -m "agentic-os-mcp 0.2.0"
   git push origin agentic-os-mcp-v0.2.0
   ```

   Pushing the tag triggers `.github/workflows/release.yml`, which re-runs
   the full repo gate, asserts the tag matches `package.json`'s version, logs
   in to the MCP Registry and asserts the granted permission actually covers
   `server.json`'s `name` (the preflight described above — this is where a
   namespace-case mismatch is caught, before anything is published),
   publishes to npm (`npm publish --provenance --access public`), waits for
   the version to propagate on `registry.npmjs.org`, then — only if all of
   that succeeded — publishes `server.json` to the MCP Registry, builds the
   `.mcpb` bundle, and attaches it to a GitHub release for the tag.
6. **Watch the `release` workflow run to completion** in the Actions tab.

   **If it fails partway through, read this before doing anything by hand.**
   Once "Publish to npm" has gone green, npm is done — irreversibly (see
   "What is irreversible" above) — and every step after it runs `if:
   success()`, so a failure in "Wait for npm propagation", "Publish to MCP
   Registry", "Build .mcpb bundle", or "Attach .mcpb to GitHub release" means
   those specific steps (and everything after the failed one) did not run.

   - **Re-running the failed job is *not* a recovery.** `npm publish` will
     itself fail on a version number that already exists on npm, and every
     `if: success()` step after it will be skipped again — you'll get the
     same shape of failure, not a completed release.
   - **The `.mcpb` build and the GitHub release were skipped too** if the
     Registry publish step is what failed — a Registry failure happens
     before those steps run, not after.
   - **Use the workflow's `workflow_dispatch` input to resume, not a manual
     terminal command.** From the Actions tab, run the `release` workflow
     manually with the `tag` input set to the tag that already published to
     npm (e.g. `agentic-os-mcp-v0.2.0`). This runs the `resume-registry` job:
     it still runs the full `gate` job first (so this can never be used to
     skip quality checks), verifies the named version is genuinely already
     live on npm (and refuses to proceed — and never calls `npm publish` —
     if it isn't), then re-authenticates, re-runs the same permission
     preflight, publishes to the Registry, builds the `.mcpb`, and attaches
     the GitHub release — i.e., everything that was skipped, and nothing
     that already happened.
   - If you must do it by hand instead (e.g. Actions is unavailable): check
     out the repo at the tag, then run
     `mcp-publisher login github && mcp-publisher publish mcp/server.json`.
     **`login github-oidc` will not work outside GitHub Actions** — it hard-
     requires `ACTIONS_ID_TOKEN_REQUEST_TOKEN`/`ACTIONS_ID_TOKEN_REQUEST_URL`,
     which only exist inside a running workflow job. Locally, use
     `mcp-publisher login github` (the interactive device-code flow) instead.
     You are then responsible for the `.mcpb` build
     (`cd mcp && npm run build:mcpb`) and the GitHub release
     (`gh release create <tag> mcp/mcp.mcpb --title <tag> --generate-notes`)
     that the `workflow_dispatch` path would otherwise have done for you.

## Verifying a release afterwards

Run all three:

```bash
# 1. The package metadata npm actually has
npm view agentic-os-mcp

# 2. A fresh-machine install path — no local cache, no dist/ already built
npx -y agentic-os-mcp

# 3. The Registry listing
curl -s https://registry.modelcontextprotocol.io/v0/servers?search=agentic-os
```

`npm view` confirms the version, tarball contents summary, and provenance
attestation are what you expect. `npx -y agentic-os-mcp` is the same command
end users run — it should download, build nothing (the tarball ships
pre-built `dist/`), and start the stdio server (Ctrl-C to exit; there is no
output on a bare stdio connection with nothing talking to it, which is
expected). The Registry query confirms the listing is live and its version
matches.
