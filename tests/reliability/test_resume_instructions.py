"""The resume entrypoint must restore durable state instead of mirroring it."""
from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNS = ' '.join((ROOT / 'plugins/agentic-sdlc/skills/sdlc-runs/SKILL.md').read_text().split())
ENGINE = ' '.join((ROOT / 'plugins/agentic-sdlc/skills/sdlc-engine/SKILL.md').read_text().split())
EVALS = json.loads((ROOT / 'plugins/agentic-sdlc/skills/sdlc-runs/evals/evals.json').read_text())


class ResumeInstructionTests(unittest.TestCase):
    def assertHas(self, document, phrase):
        self.assertTrue(phrase in document, f"missing resume-contract phrase: {phrase}")

    def test_authoritative_database_resume_has_an_explicit_runtime_sequence(self):
        for phrase in ('.agentic/state/runtime.sqlite3', 'run.status', 'run.resume',
                       'run.status` again', 'do not fall back to legacy files',
                       'select exactly one incomplete phase from coordinator-owned runtime phase events',
                       'stop for reconciliation while leaving the current lifecycle state unchanged'):
            self.assertHas(RUNS, phrase)
        self.assertHas(RUNS, 'transition the run to `interrupted` with `run.transition`')
        self.assertHas(RUNS, 'this bundle has no lease-expiry takeover operation')
        self.assertHas(RUNS, 'After a failed or unclear SQLite resume, re-read `run.status` and report its actual state')
        self.assertNotIn('A failed resume leaves the run `interrupted`', RUNS)
        managed = RUNS[RUNS.index('### SQLite-backed run inspection and resume'):
                      RUNS.index('### Legacy-file operating steps')]
        self.assertLess(managed.index('require a non-empty `task_input`'),
                        managed.index('run.resume'))
        self.assertLess(managed.index('select exactly one incomplete phase'), managed.index('run.resume'))
        self.assertHas(managed, 'If either check fails or phase selection is ambiguous, stop for reconciliation')

    def test_resumed_work_must_commit_assignment_results_to_runtime(self):
        for phrase in ('task.dispatch', 'dispatch.start', 'task.result', 'assignment.transition',
                       'assignment still pending, running, waiting',
                       'Before handoff or a completion claim'):
            self.assertHas(ENGINE, phrase)
        dispatch_sequence = ENGINE[ENGINE.index('For each actual worker dispatch'):]
        self.assertLess(dispatch_sequence.index('task.dispatch'), dispatch_sequence.index('dispatch.start'))
        self.assertLess(dispatch_sequence.index('dispatch.start'), dispatch_sequence.index('task.result'))

    def test_user_owned_files_are_not_mutable_resume_state(self):
        self.assertHas(RUNS, 'preserve them byte-for-byte')
        self.assertHas(RUNS, 'managed runtime state')

    def test_uncertain_external_actions_are_reconciled_before_resume(self):
        self.assertHas(RUNS, 'resolve each external action\'s real outcome with `external.reconcile`')
        self.assertHas(RUNS, 'never repeat the action or infer success')
        self.assertHas(RUNS, 'using the newly returned coordinator ID, lease epoch, and current revision')
        self.assertHas(RUNS, 'Do this before redispatch')
        managed = RUNS[RUNS.index('### SQLite-backed run inspection and resume'):
                      RUNS.index('### Legacy-file operating steps')]
        self.assertLess(managed.index('run.resume'), managed.index('external.reconcile'))

    def test_resume_intent_does_not_approve_a_waiting_gate(self):
        self.assertHas(RUNS, 'A resume request alone is not gate approval')
        self.assertHas(RUNS, 'it does not approve an unresolved gate')
        self.assertHas(RUNS, 'Carry the gate ID, artifact reference/hash, and exact user response into the handoff')
        self.assertHas(ENGINE, 'persist that exact decision with `decision.record`')

    def test_resume_confirmation_distinguishes_clear_intent_from_ambiguous_continue(self):
        self.assertHas(RUNS, 'explicitly names the run and asks')
        self.assertHas(RUNS, 'generic “continue”')
        self.assertHas(RUNS, '`task_input` sourced from authoritative runtime metadata')
        self.assertHas(RUNS, 'If an older managed run lacks it, stop')
        self.assertNotIn('`raw_input` sourced from `meta.json.task_input`', RUNS)

    def test_legacy_repair_is_fenced_off_from_sqlite_managed_runs(self):
        self.assertHas(RUNS, 'apply only when `.agentic/state/runtime.sqlite3`')
        self.assertHas(RUNS, '### Legacy-file operating steps (SQLite absent only)')
        self.assertLess(RUNS.index('### Legacy-file operating steps (SQLite absent only)'),
                        RUNS.index('1. **Enumerate.**'))
        self.assertNotIn('Always confirm before resuming', RUNS)
        self.assertHas(RUNS, 'legacy `aborted` status remains non-resumable')
        self.assertNotIn('Managed lifecycle operations are currently unavailable', ENGINE)
        self.assertHas(RUNS, 'resume is blocked until a supported migration exists')
        self.assertHas(ENGINE, 'runtime implements `run.complete`')
        self.assertHas(ENGINE, 'integrated path to produce its trusted host-signed gate')

    def test_compatibility_ledgers_are_not_authoritative_for_managed_runs(self):
        self.assertHas(RUNS, 'Legacy event log is append-only')
        self.assertHas(RUNS, 'Legacy log beats snapshot')
        self.assertNotIn('| Event log is append-only |', RUNS)
        self.assertNotIn('| Log beats snapshot |', RUNS)
        self.assertHas(RUNS, 'For managed runs, record changes through coordinator-fenced runtime operations')

    def test_status_output_includes_sqlite_lifecycle_states(self):
        self.assertHas(RUNS, 'status=<pending|running|waiting_for_user|interrupted|reconciliation_required|completed|failed|cancelled|aborted>')
        self.assertHas(RUNS, 'phase from the runtime phase events selected above')
        self.assertHas(RUNS, 'render any missing display field as `unknown`')

    def test_shipped_evaluations_distinguish_sqlite_from_legacy_authority(self):
        serialized = json.dumps(EVALS)
        self.assertHas(serialized, 'run.status first')
        self.assertHas(serialized, 'only when SQLite is absent')
        self.assertHas(serialized, 'does not repair exports or event logs directly')


if __name__ == '__main__':
    unittest.main()
