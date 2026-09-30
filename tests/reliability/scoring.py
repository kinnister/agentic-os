"""Aggregate harness-owned observations using the frozen, fixed denominator.

This module consumes trusted oracle output, not a candidate agent's response.
Evidence paths identify raw records; callers are responsible for producing and
retaining them outside the candidate workspace. Missing proof never earns credit.
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG = json.loads(Path(__file__).with_name('rubric.json').read_text())
RUBRIC = CONFIG['assertions']


def grade(score: float) -> str:
    return next((letter for threshold, letter in ((90, 'A'), (80, 'B'), (70, 'C'), (60, 'D'))
                if score >= threshold), 'F')


def score_trials(trials: list[dict]) -> dict:
    """Missing trials/observations retain their denominator; duplicates are errors."""
    index = {}
    scenarios = {a['scenario'] for a in RUBRIC}
    for trial in trials:
        key = trial['host'], trial['scenario'], trial['repetition']
        if (key[0] not in CONFIG['hosts'] or key[1] not in scenarios
                or type(key[2]) is not int or not 1 <= key[2] <= CONFIG['repetitions']):
            raise ValueError(f'unknown trial coordinates: {key}')
        if key in index:
            raise ValueError(f'duplicate trial: {key}')
        index[key] = trial
    hosts = {}
    for host in CONFIG['hosts']:
        dimensions = {a['dimension']: 0.0 for a in RUBRIC}
        results, vetoes, unverified = [], [], 0
        for assertion in RUBRIC:
            outcomes = []
            for repetition in range(1, CONFIG['repetitions'] + 1):
                trial = index.get((host, assertion['scenario'], repetition), {})
                observation = trial.get('observations', {}).get(assertion['observation'])
                observable = (trial.get('status') in ('completed', 'product_failed', 'timed_out')
                              and bool(trial.get('evidence')))
                outcome = 'unverified'
                if observable and type(observation) is bool:
                    outcome = 'pass' if observation else 'fail'
                outcomes.append(outcome)
                unverified += outcome == 'unverified'
                if outcome == 'fail' and assertion.get('veto_on_fail'):
                    vetoes.append({'assertion': assertion['id'], 'repetition': repetition})
            earned = CONFIG['points_per_assertion'] * outcomes.count('pass') / CONFIG['repetitions']
            dimensions[assertion['dimension']] += earned
            results.append({'id': assertion['id'], 'points': round(earned, 4),
                            'passed': outcomes.count('pass'), 'denominator': CONFIG['repetitions'],
                            'outcomes': outcomes})
        score = sum(dimensions.values())
        accepted = (score >= CONFIG['minimum_host_score']
                    and all(v >= CONFIG['minimum_dimension_score'] for v in dimensions.values())
                    and not vetoes and all(
                        all(o == 'pass' for o in r['outcomes'])
                        for a, r in zip(RUBRIC, results) if a.get('veto_on_fail')))
        hosts[host] = {'score': round(score, 4), 'grade': grade(score),
                       'dimensions': {k: round(v, 4) for k, v in dimensions.items()},
                       'assertions': results, 'vetoes': vetoes,
                       'unverified_observations': unverified, 'accepted': accepted}
    minimum = min(h['score'] for h in hosts.values())
    return {'schema': 1, 'hosts': hosts, 'overall_score': minimum, 'grade': grade(minimum),
            'accepted': all(h['accepted'] for h in hosts.values()),
            'coverage_complete': all(h['unverified_observations'] == 0 for h in hosts.values())}
