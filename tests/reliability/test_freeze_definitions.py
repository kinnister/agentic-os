"""Real temporary Git repositories and archive corruption controls; no model calls."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import freeze_definitions as frozen


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        folder = self.root / 'tests/reliability'
        folder.mkdir(parents=True)
        for name in frozen.FILES:
            shutil.copyfile(Path(__file__).parent / name, folder / name)
        frozen.git(self.root, 'init', '--template=', '--initial-branch=main')
        frozen.git(self.root, 'add', '.')
        frozen.git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com',
                   '-c', 'commit.gpgsign=false', 'commit', '-m', 'Original')
        self.revision = frozen.git(self.root, 'rev-parse', 'HEAD').decode().strip()
        self.dep = Path(self.temp.name) / 'dependency'
        self.dep.mkdir()
        (self.dep / '.claude-plugin').mkdir()
        (self.dep / '.claude-plugin/plugin.json').write_text('{"version":"1.0.0"}')
        (self.dep / 'skill.txt').write_text('original dependency')
        frozen.git(self.dep, 'init', '--template=', '--initial-branch=main')
        frozen.git(self.dep, 'add', '.')
        frozen.git(self.dep, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com',
                   '-c', 'commit.gpgsign=false', 'commit', '-m', 'Dependency')
        self.snapshot = self.root / '.agentic/work/frozen-baseline'
        self.record = self.root / 'tests/reliability/frozen-definitions.json'

    def freeze(self):
        return frozen.freeze(self.root, self.dep, self.snapshot, self.record, self.revision)

    def test_real_archive_and_observer_development(self):
        result = self.freeze()
        original = frozen.git(self.root, 'archive', '--format=tar', self.revision)
        self.assertEqual(result['archives']['baseline.tar'], frozen.digest(original))
        (self.root / 'tests/reliability/observations.py').write_text('new observer implementation')
        self.assertEqual(frozen.verify(self.root, self.snapshot, self.record), result)
        self.assertNotIn(str(Path(self.temp.name)), self.record.read_text())

    def test_definition_edits_rejected(self):
        self.freeze()
        for name in frozen.FILES:
            path = self.root / 'tests/reliability' / name
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.assertRaisesRegex(ValueError, 'definitions changed'):
                frozen.verify(self.root, self.snapshot, self.record)
            path.write_bytes(original)

    def test_snapshot_corruption_rejected(self):
        self.freeze()
        for name in ('baseline.tar', 'superpowers.tar'):
            path = self.snapshot / name
            original = path.read_bytes()
            path.chmod(0o644)
            path.write_bytes(original + b'corrupt')
            with self.assertRaisesRegex(ValueError, 'snapshot changed'):
                frozen.verify(self.root, self.snapshot, self.record)
            path.write_bytes(original)

    def test_refreeze_refused(self):
        self.freeze()
        with self.assertRaisesRegex(ValueError, 'refusing to replace'):
            self.freeze()

    def test_dependency_actual_changes_and_metadata_exclusion(self):
        (self.dep / 'skill.txt').write_text('actual installed change')
        first = frozen.dependency_archive(self.dep)
        (self.dep / '.git/private-canary').write_text('must not archive metadata')
        self.assertEqual(first, frozen.dependency_archive(self.dep))
        self.assertIn(b'actual installed change', first)
        result = self.freeze()
        self.assertEqual(result['dependency']['tracked_changes'], ['M\tskill.txt'])

    def test_dependency_symlink_rejected(self):
        (self.dep / 'escape').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            self.freeze()
        self.assertFalse(self.snapshot.exists())

    def test_archive_link_substitution_rejected(self):
        self.freeze()
        path = self.snapshot / 'baseline.tar'
        copy = self.root / 'copy.tar'
        copy.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(copy)
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            frozen.verify(self.root, self.snapshot, self.record)

    def test_challenges_cover_frozen_rubric(self):
        spec = json.loads((self.root / 'tests/reliability/challenge-spec.json').read_text())
        self.assertEqual(len(spec['assertions']), 25)
        self.assertEqual(len(spec['scenarios']), 4)
        self.assertEqual(spec['budget']['baseline_trials'] + spec['budget']['candidate_trials'], 48)
        for scenario in spec['scenarios'].values():
            self.assertEqual(scenario['task'], scenario['files']['TASK.md'])

    def test_checked_in_definition_hashes_are_current(self):
        root = Path(__file__).resolve().parents[2]
        record = json.loads((root / 'tests/reliability/frozen-definitions.json').read_text())
        self.assertEqual(frozen.definitions(root), record['definitions'])
        self.assertEqual(record['baseline_revision'], frozen.BASELINE)

    def test_legacy_inputs_validate_against_original_baseline(self):
        source_root = Path(__file__).resolve().parents[2]
        spec = json.loads((source_root / 'tests/reliability/challenge-spec.json').read_text())
        validator = Path(self.temp.name) / 'baseline-validator.py'
        validator.write_bytes(frozen.git(source_root, 'show', frozen.BASELINE +
                                        ':plugins/agentic-sdlc/scripts/validate-run-artifact.py'))
        for suffix, schema_name in (('meta.json', 'meta.schema.json'),
                                    ('events.jsonl', 'event-line.schema.json')):
            schema = Path(self.temp.name) / schema_name
            schema.write_bytes(frozen.git(source_root, 'show', frozen.BASELINE +
                               ':plugins/agentic-sdlc/references/schemas/' + schema_name))
            content = next(value for name, value in spec['legacy_fixture']['files'].items()
                           if name.endswith('/' + suffix))
            artifact = Path(self.temp.name) / suffix
            artifact.write_text(content)
            result = subprocess.run([sys.executable, '-I', str(validator), str(schema),
                                     str(artifact)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            if suffix == 'meta.json':
                self.assertEqual(json.loads(content)['loops'], {
                    'evidence.retry:text_ops': {'cap': 2, 'count': 1, 'on_cap': 'escalate'}})


if __name__ == '__main__':
    unittest.main()
