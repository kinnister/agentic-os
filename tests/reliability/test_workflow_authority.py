import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILLS = (
    "sdlc-engine", "sdlc-runs", "sdlc-auto", "gate-arbiter",
    "qa-case-generator", "qa-e2e-generator", "qa-scoping",
    "code-review", "gate-runner", "story-intake", "acceptance-check",
    "test-heal", "telemetry-export",
)


class WorkflowAuthorityTests(unittest.TestCase):
    def test_runtime_authority_reference_and_mutating_skills_are_aligned(self):
        reference = ROOT / "plugins/agentic-sdlc/references/runtime-authority.md"
        self.assertTrue(reference.is_file())
        content = reference.read_text(encoding="utf-8")
        for operation in ("decision.record", "event.record", "evidence.ingest", "legacy.export"):
            self.assertIn(operation, content)
        for skill in SKILLS:
            path = ROOT / "plugins/agentic-sdlc/skills" / skill / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            with self.subTest(skill=skill):
                self.assertIn("legacy.export", text)
                self.assertNotIn("supports contract validation and policy resolution only", text)

    def test_legacy_readers_state_the_managed_runtime_boundary(self):
        for skill, marker in {
            "story-intake": "event.record",
            "sdlc-runs": "versioned runtime status/export operations",
            "telemetry-export": "legacy.export` before reading",
        }.items():
            text = (ROOT / "plugins/agentic-sdlc/skills" / skill / "SKILL.md").read_text(
                encoding="utf-8")
            with self.subTest(skill=skill):
                self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
