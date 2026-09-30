# Shared runtime contracts

Status: experimental, incomplete implementation. SDLC/QA skills have a
managed-runtime boundary and guarded integration points, but full workflow
migration and live certification are not established. Host adapters can issue
short-lived signed dispatch records for
identity-bound mailbox reads and trusted completion gates; without a configured
host key those operations remain fail-closed.

`agentic_runtime/registry.json` is the canonical contract source. Run
`python3 runtime/generate_bundles.py` after a source change; CI uses `--check`
to reject drift. Each plugin receives its own runtime and generated contract
reference, so it can be installed without its sibling.

Python 3.10 or newer is required. The runtime uses only the standard library.
Requests and responses are versioned JSON on standard input/output. Invalid
requests fail with exit status 2 and a structured error. Registry inspection:

```sh
printf '%s\n' '{"api_version":"1.0.0","operation":"registry.get"}' | python3 runtime/run.py
```

The runtime lifecycle operations use SQLite as their state and require a
branch/worktree ownership precondition before export artifacts are written.
They check supplied coordinator revisions and lease epochs, reserve dispatches
transactionally, persist in-flight dispatch leases with concurrency and timeout
limits, and put uncertain external outcomes into
reconciliation. JSON exports are revision-labelled views; editing one never
changes the database. Host enforcement and installation operations remain
separate capabilities. An absent operation is an error; it must never fall
back to editing JSON state. Registry validation alone does not enforce worker
permissions or provide an operating-system sandbox.

Scored evaluation definitions remain frozen independently under
`tests/reliability/`. Passing contract tests earns no live evaluation points.

Supported operations use the same `api_version` envelope:

| Operation | Required fields beyond operation/version | Optional fields |
|---|---|---|
| `registry.get` | none | none |
| `contract.lookup` | `section`, `identifier` | none |
| `policy.resolve` | `entrypoint` | `overrides` |
| `input.normalize` | `payload` | `legacy` (boolean, default false) |
| `transition.validate` | `source`, `target` | none |
| `retry.allowed` | `loop_id`, `attempts_used` | none |

`attempts_used` includes the initial attempt. A false retry result prohibits another
attempt; it does not change the outcome of the previous attempt. Policy overrides
can reduce default budgets. Increasing a running budget requires a future recorded
user-decision operation; changing configuration must not silently reset counters.

Lifecycle requests include `run.start`, `run.status`, `run.resume`, `run.cancel`,
`run.complete`, `task.dispatch`, `task.result`, `dispatch.start`, `dispatch.finish`,
`dispatch.recover`, `decision.record`, `message.deliver`, `external.intent`,
`external.reconcile`, `legacy.import`, `legacy.export`, `evidence.ingest`, and
`event.record`, `run.export`.
`legacy.import` records
the source hash and receipt without replacing the original file. Mutating requests for an owned run carry
the coordinator identity, current `lease_epoch`, and expected revision; stale ownership or revisions fail atomically.
Assignments are owned by one worker and carry paths, context references,
acceptance criteria, limits, and dependencies. `assignment.create` rejects
unknown dependencies and cycles; `assignment.transition` requires the current
assignment revision. `message.send` accepts only registered typed messages and
rejects stale assignments, duplicate content changes, inconsistent sender labels, and
payloads over the registry limit. Worker-originated messages also require a
host-signed dispatch record bound to the assignment revision; only the fenced
coordinator may publish without a worker dispatch record.
Question correlations support the registry's bounded request/reply rounds; an
unanswered or cyclic exchange is escalated by `runtime.recover`.
`evidence.record` stores receipts bound to a run revision. A host-signed
`run.complete` record must name successful required evidence and an approved gate
before completion. Host adapters use the signing helpers in `agentic_runtime.host`
and keep the signing key outside repository state. Signed command receipts bind
the command, working directory, check type, and required flag as well as the
result. Failed required commands remain in the ledger; completion requires the
latest signed result for each required command stream to pass and be named by
the gate. Host adapters may explicitly mark exploratory command events
`required: false` before signing; the default is required. Unsigned required
failures remain rejected.
Completion rechecks the retained signed host claim against each evidence row.
Legacy receipts that did not sign the command identity cannot satisfy a new
completion gate; rerun the affected checks to create current receipts.
Before filtering required checks, completion also rejects modern persisted rows
whose stored fields disagree with their signed claims. This detects a damaged
row projection; it does not protect a database that a worker can rewrite or
delete directly. Worker access to coordinator state requires a separate host
isolation boundary.
Named optional results may remain in a gate for context, but at least one
successful signed required receipt is still required to prove completion.
`agentic_runtime.trace.command_receipt` accepts only explicit
`agentic.command.completed` adapter events, so model prose cannot become command
evidence by inference.
Host adapters can pass the same event to `agentic_runtime.trace.ingest_command_event`
or the versioned `evidence.ingest` operation; parsing happens before the
transaction and the store verifies the signed host claims.
Adapters may use `agentic_runtime.host.issue_evidence_record` to sign only the
validated explicit command fields before ingestion.
`agentic_runtime.adapter.adapt_json_lines` provides the stream boundary: unrelated
host output is ignored, explicit receipts are signed, and malformed JSON fails
closed.
The versioned `trace.adapt` operation exposes the same boundary to host launchers
and requires `AGENTIC_HOST_KEY`.
`install.plan` computes journal-aware file actions without writes. `install.apply`
recomputes that plan immediately before atomically applying create/managed-replace
actions and updates `.agentic/agentic-os/install.json`; user-modified files are
preserved. Managed journal entries record the file's device and inode. A
pre-existing file with identical desired bytes, or a later same-byte replacement
with a different recorded identity, remains user-owned. Legacy journal entries
without an identity are preserved rather than assumed safe to replace or delete.
Installer paths reject symlinked components. File mutations use verified
directory handles and bind the target and observed parent directory identities
through each mutation. A post-mutation check rejects a detected directory
move and conditionally undoes its file effect through the held handle.
Uninstall validates every selected leaf before it deletes the first file. Replacements
and deletions recheck the planned file hash, device, inode, and modification
time immediately before the
mutation, and abort on a mismatch observed at that check. The check and the
operating-system rename/unlink are separate operations; an unrelated writer
can still race between them, or move a directory after the post-mutation
check. The installer does not lock other processes out of the target repository.
Stored device, inode, and nanosecond modification time reduce accidental
identity reuse; a replacement that reproduces all those attributes and bytes
cannot be distinguished. Older journal entries without modification time are
preserved as user-owned rather than deleted or overwritten.
`install.remove` deletes only unchanged managed files; generated and user
files are kept, and a modified managed file is kept as user-owned. A kept
user-owned file's journal entry is updated to the bytes and identity on disk;
a kept generated file keeps its recorded hash so an edit stays detectable.

Operator decisions are compare-and-swap on content. On `install.apply`, a file
spec may carry `expect_sha256`, the SHA-256 of the exact bytes an operator
reviewed; the file is replaced only while it still has those bytes, and if any
confirmed file in a request is stale or absent, nothing in the request is
written (`install.plan` reports it as `stale_confirmation`). A confirmation
never raises ownership: the file is journaled user-owned unless the request
states `managed` or `generated` and the journal already records that owner for
the path, and a file that existed before agentic-os keeps
`origin: adopted-existing`, including after later applies over it. A
confirmed apply whose bytes already match disk does not change an existing
journal entry; a plain apply may still demote an entry whose recorded identity
no longer matches. Unknown file-spec fields are rejected.
Shared files such as `CLAUDE.md` therefore stay user-owned and are edited only
by confirmed apply.

On `install.remove`, `confirm` maps selected journaled paths to reviewed
digests. A confirmed path is deleted only while its bytes match, a stale
confirmation deletes nothing, and a confirmation for an absent file is listed
in `unapplied_confirmations`. Any journaled entry accepts a confirmation except
files that existed before agentic-os (`origin: adopted-existing`, or a
user-owned entry with no origin); a demoted managed or generated entry from an
older journal without an origin stays confirmable. A managed or generated entry is dropped from
the journal (`missing`) only when its directory is reachable and the file is
absent; user entries are never dropped. Replaying an applied confirmed request
fails closed; plan again before retrying an interrupted request.

`install.record` replaces named top-level journal fields (`answers`,
`stack_discovery`, `adoption`, `follow_ups`, `sdlc_skills`, `qe_blueprints`,
`phase`, `agentic_os_version`), accepts only standard JSON values, and never
accepts `files`. A journal containing NaN, Infinity or an out-of-range number
is refused by every operation before any write, and `install.merge-settings` neither reads nor writes a settings
file containing them. `confirm` keys must be canonical relative paths. It lets setup, upgrade and uninstall stop editing
`install.json` directly; the agentic-os setup, upgrade and uninstall skills
now use these operations.

New installed files are created with mode `0666` minus the umask. A
replacement keeps the destination's mode without setuid/setgid, applied after
the content is written. The journal file is rewritten `0600` on every write;
its directory follows the umask, so a permissive umask still exposes the
journal to replacement by group members.

`install.merge-settings` performs the same
deterministic recursive object/unique-array merge used by setup, writes the
result atomically after validating the journal, and preserves ownership of
pre-existing or user-modified settings while retaining existing user scalar
values. Each applied file is journaled before the next file; a journal conflict
aborts and conditionally restores the immediately affected file. Journal
replacements also check the journal hash and inode read at validation. A
temporary hard link holds an existing file's inode until its journal update
commits, so a failed update can restore its prior managed identity. File and
directory changes are fsynced. If a journal write fails after its rename, the
installer inspects the visible journal entry before deciding whether rollback
is safe; ambiguous outcomes require reconciliation. A process
crash between a file effect and its journal write still needs recovery evidence;
the installer does not claim a multi-file transaction. Skills remain responsible
for interviews and stack-specific
rendering.
`legacy.export` regenerates `meta.json`, `events.jsonl`, and `decisions.jsonl`
as compatibility views from SQLite; edits to those files are overwritten on
the next export and never affect authoritative state.
Setup uses `host.preflight` to report observed Python, SQLite, Git, and host
launch capabilities. Passing `required_capabilities` makes the check fail closed
when a workflow depends on an unavailable control; unsupported OS sandboxing is
reported explicitly, and `control_matrix` names each control's enforcement
boundary and evidence source. Peer
work also exposes `assignment.create`, `assignment.transition`, `message.send`,
`message.receive`, and `runtime.recover`.
