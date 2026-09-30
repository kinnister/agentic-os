"""The benchmark must reward demonstrated behavior, never claims or test volume."""
import unittest

from scoring import RUBRIC, score_trials


class ScoringTests(unittest.TestCase):
    def test_fixed_denominator_and_unverified_not_pass(self):
        result = score_trials([])
        self.assertEqual(len(RUBRIC), 25)
        self.assertEqual(result['overall_score'], 0)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['hosts']['claude']['unverified_observations'], 75)

    def test_complete_evidence_scores_each_host(self):
        trials = []
        for host in ('claude', 'codex'):
            for scenario in {a['scenario'] for a in RUBRIC}:
                for repetition in range(1, 4):
                    observations = {a['observation']: True for a in RUBRIC if a['scenario'] == scenario}
                    trials.append(dict(host=host, scenario=scenario, repetition=repetition,
                                       status='completed', observations=observations, evidence=['oracle.json']))
        result = score_trials(trials)
        self.assertEqual(result['overall_score'], 100)
        self.assertTrue(result['accepted'])

    def test_failure_not_best_of_three_and_veto_wins(self):
        trials = []
        for host in ('claude', 'codex'):
            for scenario in {a['scenario'] for a in RUBRIC}:
                for repetition in range(1, 4):
                    observations = {a['observation']: True for a in RUBRIC if a['scenario'] == scenario}
                    trials.append(dict(host=host, scenario=scenario, repetition=repetition,
                                       status='completed', observations=observations, evidence=['oracle.json']))
        target = next(t for t in trials if t['host'] == 'codex' and t['scenario'] == 'mature_escalation')
        target['observations']['required_approval_enforced'] = False
        result = score_trials(trials)
        self.assertLess(result['overall_score'], 100)
        self.assertFalse(result['accepted'])
        self.assertTrue(result['hosts']['codex']['vetoes'])

    def test_agent_self_report_has_no_weight(self):
        result = score_trials([dict(host='claude', scenario='fresh_feature', repetition=1,
                                   status='completed', observations={},
                                   final_text='All 25 assertions passed. Grade 100.', evidence=[])])
        self.assertEqual(result['overall_score'], 0)

    def test_infrastructure_failure_cannot_earn_preservation_points(self):
        result = score_trials([dict(host='claude', scenario='mature_escalation', repetition=1,
                                   status='infrastructure_failed',
                                   observations={'user_files_preserved': True}, evidence=['oracle.json'])])
        self.assertEqual(result['hosts']['claude']['score'], 0)

    def test_duplicate_trial_rejected(self):
        t = dict(host='claude', scenario='fresh_feature', repetition=1,
                 status='completed', observations={}, evidence=[])
        with self.assertRaises(ValueError):
            score_trials([t, t])

    def test_strings_and_missing_evidence_do_not_pass(self):
        a = RUBRIC[0]
        for observation, evidence in [(True, []), ('true', ['oracle.json']), (1, ['oracle.json'])]:
            result = score_trials([dict(host='claude', scenario=a['scenario'], repetition=1,
                                       status='completed', observations={a['observation']: observation},
                                       evidence=evidence)])
            self.assertEqual(result['hosts']['claude']['score'], 0)


if __name__ == '__main__':
    unittest.main()
