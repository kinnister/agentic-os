"""Standalone delivery must preserve the canonical bytes and reject drift."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class BundleTests(unittest.TestCase):
    def test_generator_exists(self):
        self.assertTrue((ROOT / 'runtime/generate_bundles.py').is_file(),
                        'canonical runtime needs a deterministic bundle generator')

    def test_generate_check_and_detect_drift(self):
        generator = ROOT / 'runtime/generate_bundles.py'
        if not generator.exists():
            self.skipTest('generator existence is tested separately')
        with tempfile.TemporaryDirectory() as temp:
            output = pathlib.Path(temp)
            command = [sys.executable, str(generator), '--output-root', temp]
            subprocess.run(command, check=True, capture_output=True)
            subprocess.run(command + ['--check'], check=True, capture_output=True)
            for plugin in ('agentic-os', 'agentic-sdlc'):
                package = output / 'plugins' / plugin / 'runtime/agentic_runtime'
                self.assertTrue((package.parent.parent / 'references/runtime-contracts.md').is_file())
                self.assertEqual((package / 'registry.json').read_bytes(),
                                 (ROOT / 'runtime/agentic_runtime/registry.json').read_bytes())
                result = subprocess.run([sys.executable, str(package.parent / 'run.py')],
                    input='{"api_version":"1.0.0","operation":"registry.get"}',
                    text=True, capture_output=True, cwd=temp)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('contract_version', result.stdout)
            (package / 'registry.json').write_text('{}')
            result = subprocess.run(command + ['--check'], capture_output=True)
            self.assertNotEqual(result.returncode, 0)

    def test_setup_template_uses_registry_defaults(self):
        import json
        registry = json.loads((ROOT / 'runtime/agentic_runtime/registry.json').read_text())
        self.assertIn('configuration_template', registry)
        config = registry['configuration_template']
        self.assertEqual(config['mode_defaults']['autonomous']['max_clarifying_questions_per_phase'], 3)
        self.assertEqual(config['model_tiers']['economy'], 'inherit')
        self.assertTrue(config['feature_verification']['allow_dynamic_playwright'])
