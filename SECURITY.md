# Security policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for a suspected security
vulnerability. Instead, use
[GitHub's private vulnerability reporting](https://github.com/kinnister/agentic-os/security/advisories/new)
for this repository, or email the maintainer directly at the address on the
[owner's GitHub profile](https://github.com/kinnister).

Include:

- What you found and why it's a security issue (not just a bug).
- Steps to reproduce, ideally against a throwaway repo (see the README's
  "Try it in two minutes" fixture) rather than a real project.
- The plugin version (`plugins/agentic-os/.claude-plugin/plugin.json` /
  `plugins/agentic-sdlc/.claude-plugin/plugin.json`) you tested against.

You should get an initial response within a few days. This project is
solo-maintained; there is no formal SLA, but security reports are
prioritized above other work.

## What counts as a security issue here

`agentic-os` scaffolds enforcement hooks (git hooks, Claude Code hooks) and
governance policy into a target repository, and its `agentic-sdlc` plugin can
run subagents autonomously under the `gated-autonomous`/`autonomous` HITL
modes. Reports of particular interest:

- A way to make an enforcement hook (write-scope guard, blind pre-commit
  review gate, instruction-quality spawn gate) silently pass when it
  shouldn't — i.e., a bypass of a gate documented as hard/fail-closed in
  [`docs/PRINCIPLES.md`](docs/PRINCIPLES.md).
- A way for scaffolded content (a generated agent contract, a rendered
  template) to cause command injection, path traversal outside the declared
  `write_scope`, or exfiltration of secrets from the target repo.
- A way for the gate-arbiter's autonomous mode to escalate to
  human-equivalent trust (e.g., resolve a `security`/`breaking-change`
  risk-flagged gate) without actually meeting the documented escalation
  condition.
- Any script under `.claude/hooks/`, `.githooks/`, or `scripts/` that
  executes untrusted input unsafely.
- A way to bypass either of the MCP server's (`mcp/`) two file readers. It
  has two, gated differently, because they read from two different places:
  - The **bundle reader** (`mcp/src/content.ts`) serves the plugin content
    this repo ships. A path is servable only if it is a literal key of the
    build-time `content-index.json` — that membership check is its entire
    access-control model; there is no path arithmetic against caller input,
    so traversal and absolute paths are inexpressible.
  - The **target reader** (`mcp/src/target.ts`), added in Phase 2b for
    `run_doctor`, opens a directory the *caller* names — a repo to audit —
    so index membership doesn't apply; there is no build-time index of
    someone else's repository. It is gated instead by root containment,
    checked on every access: the requested path is resolved against the
    canonicalized root, then canonicalized itself (`fs.realpath`, so a
    symlink is resolved to what it actually points at) and verified to still
    be inside the canonicalized root before any read. An absolute input is
    rejected outright. Any violation returns `undefined`/`false` rather than
    throwing, and no error message ever carries a filesystem path.
  - **The server never writes**, to the bundle or to a target repo, and
    **never executes** anything — `run_doctor`'s three checks that require
    running Python are returned as commands for the host to run, not
    executed by the server. A static test (`mcp/tests/readonly.test.ts`,
    pattern in `mcp/tests/banned-pattern.ts`) bans both write APIs
    (`writeFile`, `mkdir`, `rm`, `rename`, `symlink`, `cp`, `mkdtemp`, etc.)
    and code-execution surfaces — the `child_process`, `vm`, and
    `worker_threads` module specifiers in any quoting, plus `eval(`,
    `new Function`, and dynamic `import(` — across `mcp/src/**`.
  - **Accepted risk, disclosed, not a bug:** the target reader has a
    TOCTOU window between validating a path's containment and the
    subsequent read (each read is an independent `stat`/`readFile` call on
    the already-validated path string). An attacker with concurrent write
    access to the repo being audited could in principle swap a file for an
    out-of-root symlink between those two steps. Exploiting it requires
    write access to the very tree `run_doctor` is auditing at the caller's
    own request — i.e., an attacker who already controls the thing being
    inspected. This is documented in `mcp/src/target.ts` and considered
    acceptable given that threat model. Closing the window properly would
    mean holding file descriptors open across validation and read (open,
    then fstat, then read from that same fd) — real complexity for no gain
    against this threat model, which is why it hasn't been done. A report
    proposing a cheaper way to close the window — one that doesn't require
    that open-fstat-read-from-fd approach — is still welcome.
  - A bypass of either reader's gate — bundle membership or target
    containment — is a security bug and should be reported.

Prompt-injection resistance of the underlying LLM is out of scope for this
project specifically — report those upstream to the model provider — but a
case where this project's *own* enforcement layer fails to catch a
consequence of prompt injection (e.g., a hook that should have blocked a
scope violation but didn't) is in scope.

## Supported versions

Only the latest published version of each plugin (`agentic-os`,
`agentic-sdlc`, `agentic-qe`) and of the `agentic-os-mcp` server (tagged
`agentic-os-mcp-v<X.Y.Z>`) receives security fixes. There is no
long-term-support branch at this stage of the project.
