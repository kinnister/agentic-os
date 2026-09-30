"""Pure validation APIs. Retry admission never decides the outcome of an attempt."""
import copy
import json
from pathlib import Path
import re

VERSION = '1.0.0'


def load_registry():
    """Return an independent canonical registry, rejecting unsupported versions."""
    registry = json.loads(Path(__file__).with_name('registry.json').read_text(encoding='utf-8'))
    if registry.get('contract_version') != VERSION:
        raise ValueError('unsupported registry contract_version')
    return registry


def validate_identifier(value):
    """Validate a path-safe identifier of at most 128 ASCII characters."""
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
        raise ValueError('invalid identifier')
    return value


def _choice(value, choices, field):
    if not isinstance(value, str) or value not in choices:
        raise ValueError('unknown ' + field)


def resolve_policy(entrypoint, overrides=None):
    """Resolve flat policy; numeric overrides may only lower the common ceilings."""
    registry = load_registry()
    _choice(entrypoint, registry['entrypoints'], 'entrypoint')
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        raise ValueError('overrides must be an object')
    defaults = registry['policy_defaults']
    if set(overrides) - set(defaults):
        raise ValueError('unknown policy field')
    policy = copy.deepcopy({**defaults, **registry['entrypoints'][entrypoint], **overrides})
    _choice(policy['classification'], registry['classifications'], 'classification')
    _choice(policy['mode'], ('hitl', 'autonomous'), 'mode')
    # Entry points are fixed to their declared mode except the engine, which is
    # deliberately callable by both guided and autonomous adapters.
    if entrypoint != 'sdlc-engine' and policy['mode'] != registry['entrypoints'][entrypoint]['mode']:
        raise ValueError('mode conflicts with entrypoint')
    risks = policy['escalate_on']
    if not isinstance(risks, list) or any(not isinstance(r, str) or r not in registry['risk_classes'] for r in risks) or len(set(risks)) != len(risks):
        raise ValueError('escalate_on must contain unique known risk classes')
    for key, ceiling in defaults.items():
        if type(ceiling) is int and (type(policy[key]) is not int or not 1 <= policy[key] <= ceiling):
            raise ValueError(key + ' must be a positive integer within the default ceiling')
    policy['max_concurrent_workers'] = min(policy['max_concurrent_workers'], registry['classifications'][policy['classification']]['max_concurrent_workers'])
    return policy


def normalize_input(payload, legacy=False):
    """Validate the versioned input envelope; raw_input requires explicit legacy=True."""
    if type(legacy) is not bool or not isinstance(payload, dict):
        raise ValueError('payload must be an object and legacy must be boolean')
    allowed = {'contract_version', 'task_input', 'entrypoint', 'classification', 'run_id', 'policy', 'mode', 'mode_flag', 'escalate_on'}
    if legacy:
        allowed.add('raw_input')
    if set(payload) - allowed:
        raise ValueError('unknown input field')
    result = copy.deepcopy(payload)
    if 'raw_input' in result:
        if 'task_input' in result:
            raise ValueError('raw_input and task_input cannot coexist')
        result['task_input'] = result.pop('raw_input')
    if result.get('contract_version') != VERSION:
        raise ValueError('unsupported or missing contract_version')
    if not isinstance(result.get('task_input'), str) or not result['task_input'].strip():
        raise ValueError('task_input must be a nonempty string')
    registry = load_registry()
    for field, choices in [('entrypoint', registry['entrypoints']), ('classification', registry['classifications']), ('mode', ('hitl', 'autonomous'))]:
        if field in result:
            _choice(result[field], choices, field)
    if 'mode_flag' in result and result['mode_flag'] not in (None, '--greenfield'):
        raise ValueError('unknown mode_flag')
    if 'escalate_on' in result:
        risks = result['escalate_on']
        if not isinstance(risks, list) or any(not isinstance(r, str) or r not in registry['risk_classes'] for r in risks) or len(set(risks)) != len(risks):
            raise ValueError('escalate_on must contain unique known risk classes')
    if 'run_id' in result:
        validate_identifier(result['run_id'])
    if 'entrypoint' in result and 'mode' in result:
        resolve_policy(result['entrypoint'], {'mode': result['mode']})
    if 'policy' in result:
        if not isinstance(result['policy'], dict):
            raise ValueError('policy must be an object')
        resolved = resolve_policy(result.get('entrypoint', 'sdlc-guided'), result['policy'])
        for key in ('mode', 'classification'):
            if key in result and key in result['policy'] and result[key] != resolved[key]:
                raise ValueError('conflicting ' + key)
    return result


def validate_transition(source, target):
    """Return True for an allowed edge; reject unknown and forbidden transitions."""
    states = load_registry()['run_states']
    _choice(source, states, 'source state')
    _choice(target, states, 'target state')
    if target not in states[source]:
        raise ValueError('forbidden state transition: ' + source + ' -> ' + target)
    return True


def retry_allowed(loop_id, attempts_used):
    """Can another attempt start? attempts_used includes the initial attempt (zero before it)."""
    loops = load_registry()['loops']
    if isinstance(loop_id, str) and loop_id.startswith('evidence.retry:'):
        validate_identifier(loop_id.partition(':')[2])
        loop_id = 'evidence.retry:<task-id>'
    _choice(loop_id, loops, 'loop identifier')
    if type(attempts_used) is not int or attempts_used < 0:
        raise ValueError('attempts_used must be a nonnegative integer')
    return attempts_used <= loops[loop_id]['max_retries']


def lookup_contract(section, identifier):
    """Resolve a declared contract identifier, never an inferred or invented name."""
    _choice(section, ('phases', 'gates', 'loops', 'run_states', 'entrypoints',
                      'classifications', 'roles', 'role_capabilities'), 'contract section')
    values = load_registry()[section]
    _choice(identifier, values, 'contract identifier')
    return values[identifier]
