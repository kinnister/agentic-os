# Adoption runbook

How to get `agentic-os-mcp` discovered, once it is published. This is a
maintainer runbook — every step here is an action **you** take from your own
accounts. Nothing in it can or should be automated by CI, because each channel
verifies that the submitter owns the repo.

**Do none of this until the package is actually published.** The prerequisite
is [RELEASE.md](RELEASE.md): npm shows the version (`npm view agentic-os-mcp`)
and the MCP Registry lists `io.github.kinnister/agentic-os`. Every directory
below either ingests from the Registry or links to a live package; submitting
earlier produces dead listings.

## Discovery order

The official Registry is the root of the graph — the directories feed from it —
so the release itself does most of the work. Do the channels in this order,
because each later one is easier once the earlier ones exist:

1. **Official MCP Registry** — already handled by the release workflow
   (`mcp-publisher publish` runs on the tag). Confirm the listing resolves
   before doing anything else here.
2. **Glama** — auto-syncs from GitHub after a one-time ownership submission.
3. **mcp.so** and **Smithery** — manual submissions.
4. **`awesome-mcp-servers`** — a pull request under your account.
5. **PulseMCP** — the highest-signal launch channel; pitch it last, once the
   listings above give it something to point at.

---

## 1. Glama — listed; scoring needs a release

**Listed:** <https://glama.ai/mcp/servers/kinnister/agentic-os> (submitted and
approved 2026-07-23). Glama clones and continuously syncs the repo from here on,
so pushes land in the listing without further action.

Notes for anyone repeating this, or listing a future server:

- Glama does **not** blanket-index every server. A maintainer with write/admin
  access submits at <https://glama.ai/mcp/servers> and authenticates through
  **GitHub OAuth** — their API is read-only and has no submit endpoint, so this
  cannot be automated or done by an agent on your behalf.
- Submissions are **human-reviewed** before becoming publicly visible; the
  listing URL 404s until approval. Check your Glama account for the status.
- The listing slug has **no `@`**: `/mcp/servers/kinnister/agentic-os`.
- The score badge is live and is on `mcp/README.md`:
  `https://glama.ai/mcp/servers/kinnister/agentic-os/badges/score.svg`

### Being listed is not being scored

Getting approved does **not** produce a quality score. Glama's overall score is
**70% Tool Definition Quality + 30% Server Coherence**, and *both* are computed
by actually building the server and introspecting it over stdio. Until a **Glama
release** exists, both are unscored, the listing's Schema tab reads "No tools /
No prompts / No resources", and the badge shows a placeholder grade — even
though the same server publishes 7 tools, 6 prompts, and 31 resources to every
other host.

The earlier note here claimed no `Dockerfile` was needed. That was true only of
getting *listed*; it is false for getting *scored*, which is why one now exists.

**In-repo, done:**

- **`/Dockerfile`** — a two-stage build of the server. It must run with the
  **repository root** as build context, not `mcp/`: `build-content.mjs` needs
  `plugins/**`, the root `LICENSE` and `NOTICE`, and a real `.git` directory
  plus the `git` binary (it enumerates bundled content with `git ls-files`).
  Verified end-to-end from a clean clone: the image builds, and a container
  answers `initialize` / `tools/list` / `prompts/list` / `resources/list` with
  all 7 tools, 6 prompts, and 31 resources.
  **Glama does not use this file** (see the form values below) — it is here for
  self-hosting, for directories that do consume a Dockerfile, and because
  `docker run --rm -i` is a genuinely useful way to try the server.
- **`/.dockerignore`** — note it deliberately does *not* exclude `.git`, per
  the point above; it does exclude `.claude/worktrees`, which would otherwise
  send a second full checkout as build context.
- **`/glama.json`** — `{"$schema": …, "maintainers": ["kinnister"]}`, the one
  required field of <https://glama.ai/mcp/schemas/server.json>. Glama detects
  it within minutes of the push.
- **Tool definitions hardened against the six TDQS dimensions** (purpose
  clarity, usage guidelines, behavioural transparency, parameter semantics,
  conciseness, contextual completeness). Every tool now states when to use it
  and what it does *not* do, carries `idempotentHint`/`destructiveHint`
  alongside `readOnlyHint`, and has a `description` on **every** input *and*
  output field. This matters disproportionately because the server-level score
  is *60% mean + 40% minimum* across tools — one thin description caps the
  whole grade, so the weakest tool is the one worth fixing first.

### Glama's build spec is a form, not your Dockerfile

This is the part that is easy to get wrong. **Admin → Dockerfile** does not ask
for a path to a Dockerfile in the repo. It *generates* one from a form and shows
a live preview. The generated file already does the clone for you:

```dockerfile
FROM debian:trixie-slim
# … installs ca-certificates, curl, git, Node (via NodeSource), mcp-proxy, uv/python
WORKDIR /app
RUN git clone https://github.com/kinnister/agentic-os . && git checkout <sha>
CMD ["mcp-proxy", "--", …your start command…]
```

Because it clones with `git`, into `/app`, with the repo root as the working
directory, every constraint that makes our own `Dockerfile` fiddly is already
satisfied — a real `.git`, the `git` binary, `plugins/**`, and both legal files.
Only two fields need our values; the rest keep their defaults:

| Field | Value |
| --- | --- |
| Base image | `debian:trixie-slim` — leave the default |
| Node.js version | `26` — leave the default (verified working; `engines` only requires >= 20) |
| Python version | leave the default; the build never invokes python |
| **Build steps** | `["cd mcp && npm ci && npm run build"]` |
| **CMD arguments** | `["node", "mcp/dist/index.js"]` |
| Environment variables JSON schema | leave the empty default — this server reads no environment variables |
| Placeholder parameters | leave `{}` — the server starts with no parameters, so there is nothing to fake |
| Pinned commit SHA | leave empty to track the latest commit |

Both are **JSON arrays**, which is the easy thing to get wrong:

- **CMD arguments** is required — an empty `[]` shows *"At least one command
  argument is required"* and blocks the build. Glama prepends
  `mcp-proxy --` itself, so supply only the server's own argv.
- **Build steps** should stay as **one** element joined by `&&`. Each element
  runs as its own layer, so a bare `cd mcp` in one step would not carry into the
  next.

Then use **Build** first to run the build test, and only once it is green,
**Build & Release** — entering the version that matches npm.

Verified before deploying, against a local replica of the generated image
(debian:trixie-slim + Node 26 + a real `git clone` at the head commit): the
build prints `bundled 327 files`, the CMD serves 7 tools / 6 prompts / 31
resources, and it still does so wrapped as
`mcp-proxy --port 8080 -- node mcp/dist/index.js`, which is how Glama actually
runs it. Worth doing, because a failed Glama build makes a server
*undiscoverable* rather than merely unscored.

One harmless line in the build log: `npm warn allow-scripts esbuild@… (postinstall…)`.
That is npm 11 on Node 26 declining to run a dev dependency's install script.
`npm run build` only shells out to `tsc`, so it changes nothing — the build
completes and the server runs. Not worth chasing.

### Only you can do these

They need your Glama login, and their API is read-only:

1. **Claim the server**, if it is not already claimed.
2. **Admin → Dockerfile** → fill in the two fields above → **Build**.
3. Once the build test passes → **Build & Release**, entering the version that
   matches the current npm `latest` (`npm view agentic-os-mcp version` — do not
   copy a version out of this file, which is exactly how the wrong one gets
   used). This is what unlocks Tool Definition Quality and Server Coherence —
   and therefore the whole score.
4. **Admin → Profile** → **Categories** (up to 3; name and description are
   already filled). This is the rest of "profile completion".
5. **Related Servers** tab → **Suggest Server**. The algorithmic "Related
   Servers" list populates itself; the checklist row wants *user-submitted*
   ones.
6. **Recent usage** — zero by design until people call it; their **Try in
   Browser** feature seeds the first data point.

Two rows resolve without you: **License** now reads `Apache-2.0` in their API
even while the checklist still showed `F` (a stale scan, never a missing file —
`LICENSE` sits at both the repo root and in `mcp/`, and GitHub's API agrees),
and **glama.json** is detected on their next repo sync (`detectionFlags`
reported `glama_json: false` for a while after the file merged, which is sync
lag, not a rejected file).

## 2. mcp.so

- Submit via the **Submit** button on <https://mcp.so>, or open an issue on
  their GitHub submissions repo.
- Give the npm package name `agentic-os-mcp` and the repo URL.

## 3. Smithery

- <https://smithery.ai> — submit the server; Smithery offers a CLI installer
  and a hosted-remote option. This server is stdio-only, so it lists as a
  local/CLI-installed server, which is correct.

## 4. `awesome-mcp-servers` pull request

Repo: <https://github.com/punkpeye/awesome-mcp-servers>. House rules: entries
sit under a category, **alphabetically by the linked repo**, one per line,
name linked to the repo, concise description, matching the file's existing
style. The legend uses emoji for language / scope / OS.

**Category:** `Developer Tools` (its section heading is `💻`; the file's own
table of contents inconsistently shows `🛠️`, so search for the words, not the
glyph — the anchor is `#developer-tools`).

**Markers for this server**, from the legend:
- `📇` TypeScript codebase
- `🏠` Local service (stdio, runs on your machine)
- `🍎 🪟 🐧` cross-platform (pure Node, no native dependencies)
- no `🎖️` — this is not an official Anthropic implementation

**Ready-to-paste entry** (place it alphabetically among the `J` repos in the
Developer Tools section):

```
- [kinnister/agentic-os](https://github.com/kinnister/agentic-os) 📇 🏠 🍎 🪟 🐧 - Read-only server exposing the agentic-os governance, SDLC, and QE methodology to any MCP host; never writes to your repo and never executes code. Ships install planning and install verification.
```

Keep the description to one line and factual — over-claiming is the fastest way
to get a PR bounced. The "never writes / never executes" phrasing is the
server's genuine differentiator and is worth keeping.

## 5. PulseMCP

<https://www.pulsemcp.com> is hand-reviewed and run by people close to the MCP
Steering Committee; its weekly newsletter is the single highest-signal launch
channel. Submit through their site once the Registry listing and at least one
directory are live, so the entry has corroborating links. A short, honest pitch
— read-only, never-executes, a real test suite behind it — fits their editorial
bar better than a feature dump.

---

## The one differentiator to lead with everywhere

Every other MCP server that touches a repo can write to it. This one is
architecturally read-only and never executes code from a target repo — the
`run_doctor` tool hands verification commands back to the host rather than
running them, and a static test bans the write and process APIs in `src/`. That
is the line worth putting first in every submission, because no competing
listing can truthfully say it.

## After the first wave

Track, in rough order of signal: npm weekly downloads, the Registry and
directory listing states, the PulseMCP newsletter pickup, GitHub stars/issues,
and — uniquely for this project — the public CI pass rate as a trust signal.
None of that is a code task; it is why the testing story — the `mcp/tests`
suite and the `mcp` CI job in [ci.yml](../.github/workflows/ci.yml) — is worth
writing up publicly when there is something live to point at. No such write-up
exists yet; that is the natural first piece of content once the package is out.
