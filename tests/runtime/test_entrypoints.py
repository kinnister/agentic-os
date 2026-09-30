"""Shipped entry points must resolve policy through their standalone runtime."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class EntryPointTests(unittest.TestCase):
    def test_skills_use_shared_policy(self):
        registry = json.loads((ROOT / 'runtime/agentic_runtime/registry.json').read_text())
        for entrypoint in registry['entrypoints']:
            plugin = 'agentic-os' if entrypoint.startswith('agentic-') else 'agentic-sdlc'
            text = (ROOT / 'plugins' / plugin / 'skills' / entrypoint / 'SKILL.md').read_text()
            with self.subTest(entrypoint=entrypoint):
                self.assertTrue('policy.resolve' in text, 'missing policy.resolve')
                self.assertTrue('runtime/run.py' in text, 'missing runtime launcher')

    def test_wrappers_use_normalized_field_and_version(self):
        for name in ('sdlc-auto', 'sdlc-guided'):
            text = (ROOT / 'plugins/agentic-sdlc/skills' / name / 'SKILL.md').read_text()
            self.assertIn('"contract_version": "1.0.0"', text)
            self.assertIn('"task_input":', text)
            self.assertNotIn('"raw_input":', text)

    def test_read_only_roles_have_no_mutating_or_dispatch_tools(self):
        for role in ('codebase-scout', 'sizing-analyst'):
            text = (ROOT / 'plugins/agentic-sdlc/agents' / (role + '.md')).read_text()
            tools = next(line for line in text.splitlines() if line.startswith('tools:'))
            for forbidden in ('Write', 'Edit', 'Bash', 'Agent'):
                self.assertNotIn(forbidden, tools)
