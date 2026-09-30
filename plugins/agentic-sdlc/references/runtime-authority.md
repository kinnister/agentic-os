# Runtime authority for workflow skills

When a workflow has a managed run in `.agentic/state/runtime.sqlite3`, that
database is authoritative for lifecycle state, assignments, decisions, peer
messages, evidence, budgets, and external actions.

Skills must use the versioned `runtime/run.py` operations for mutations:

- `decision.record` for gate decisions;
- `evidence.record` or `evidence.ingest` for verification receipts;
- `event.record` for coordinator-owned workflow phase events;
- `assignment.*`, `message.*`, and `dispatch.*` for delegated work;
- `run.transition`, `run.resume`, `run.cancel`, and `run.complete` for lifecycle;
- `legacy.export` to refresh `meta.json`, `events.jsonl`, and `decisions.jsonl` compatibility views.

Those JSON and JSONL files are outputs for older readers. Editing or appending
them never advances a managed run. If the required runtime operation is absent,
the workflow must block and report the missing capability. Human-authored
specifications, plans, QA documents, and review reports remain ordinary files
under their documented locations.

Asynchronous compatibility hooks follow the same boundary: they may append
legacy ledgers only for unmanaged runs. A managed run without coordinator-fenced
runtime context must fail closed; it must not perform an external action or
write a receipt that could be mistaken for authoritative state.

The `scripts/external-action.py` adapter is the managed escape hatch for hooks
such as `ticket-sync`. It records `external.intent` before invoking the
declared adapter, reads the post-intent revision, and records
`external.reconcile` afterwards. A non-zero adapter exit is failed; launch
errors and timeouts are uncertain and move a running workflow to
`reconciliation_required`. The helper accepts an argv list for direct callers
or `--env` for the legacy hook (which executes its configured command through
`bash -c`), and requires coordinator ID, lease epoch, and expected revision in
both modes.
