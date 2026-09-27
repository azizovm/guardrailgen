"""Strict legacy YAML monitors with analytic closed-box intersection checks.

English in these files is metadata; this loader is not an NL compiler. New
versioned compiled artifacts are separate. No arbitrary Python is executed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Callable, Sequence
import yaml

from guardrailgen.reachability import ReachableSet, finite_number
from guardrailgen.schema import Verdict

Predicate = Callable[[Sequence[float]], bool]


class RuleConfigurationError(ValueError):
    """The entire configured rule set must be rejected."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in mapping:
            raise RuleConfigurationError('YAML mappings require unique string keys')
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


@dataclass(frozen=True)
class SafetyMonitor:
    name: str
    nl: str
    is_unsafe: Predicate

    def check_over(self, rset: ReachableSet) -> Verdict:
        checker = getattr(self.is_unsafe, 'intersects_box', None)
        if not isinstance(rset, ReachableSet) or checker is None:
            return Verdict.UNKNOWN
        try:
            result = checker(rset)
            if result is True:
                return Verdict.UNSAFE
            if result is False:
                return Verdict.SAFE
        except Exception:
            pass
        return Verdict.UNKNOWN

    def violated_over(self, rset: ReachableSet) -> bool:
        return self.check_over(rset) != Verdict.SAFE


@dataclass(frozen=True)
class _CirclePredicate:
    cx: float
    cy: float
    radius: float

    def __call__(self, state: Sequence[float]) -> bool:
        return math.hypot(state[0] - self.cx, state[1] - self.cy) <= self.radius

    def intersects_box(self, box: ReachableSet) -> bool:
        (xmin, xmax), (ymin, ymax) = box.bounds[:2]
        dx = max(xmin - self.cx, 0.0, self.cx - xmax)
        dy = max(ymin - self.cy, 0.0, self.cy - ymax)
        # Touching the closed exclusion boundary is a violation.
        return math.hypot(dx, dy) <= self.radius


@dataclass(frozen=True)
class _CommandSpeedPredicate:
    v_max: float

    def __call__(self, state: Sequence[float]) -> bool:
        return abs(state[3]) > self.v_max

    def intersects_box(self, box: ReachableSet) -> bool:
        lower, upper = box.bounds[3]
        return max(abs(lower), abs(upper)) > self.v_max


def keep_out_circle(cx: float, cy: float, radius: float) -> Predicate:
    cx, cy, radius = (finite_number(cx, 'cx'), finite_number(cy, 'cy'),
                      finite_number(radius, 'radius'))
    if radius <= 0:
        raise ValueError('radius must be positive')
    return _CirclePredicate(cx, cy, radius)


def command_speed_limit(v_max: float) -> Predicate:
    v_max = finite_number(v_max, 'v_max')
    if v_max < 0:
        raise ValueError('v_max must be nonnegative')
    return _CommandSpeedPredicate(v_max)


def speed_limit(v_max: float) -> Predicate:
    """Legacy Python alias for COMMAND speed only; YAML requires explicit name."""
    return command_speed_limit(v_max)


BUILDERS = {
    'keep_out_circle': (keep_out_circle, {'cx', 'cy', 'radius'}),
    'command_speed_limit': (command_speed_limit, {'v_max'}),
}


def compile_rules(rules_file: str, logger=None) -> list[SafetyMonitor]:
    """Load all rules or raise; never skip a rule or return an empty rule set."""
    if not rules_file:
        raise RuleConfigurationError('An explicit nonempty rules_file is required')
    try:
        with Path(rules_file).open('r', encoding='utf-8') as stream:
            cfg = yaml.load(stream, Loader=_UniqueKeyLoader)
        if not isinstance(cfg, dict) or set(cfg) != {'rules'}:
            raise RuleConfigurationError('Expected exactly one top-level rules field')
        if not isinstance(cfg['rules'], list) or not cfg['rules']:
            raise RuleConfigurationError('rules must be a nonempty list')
        monitors = []
        names = set()
        for index, rule in enumerate(cfg['rules']):
            if not isinstance(rule, dict) or set(rule) != {'name', 'nl', 'type', 'params'}:
                raise RuleConfigurationError(f'Rule {index} needs name, nl, type, params only')
            if not isinstance(rule['name'], str) or not rule['name'].strip():
                raise RuleConfigurationError(f'Rule {index} has an invalid name')
            if rule['name'] in names:
                raise RuleConfigurationError(f'Duplicate rule name: {rule["name"]}')
            if not isinstance(rule['nl'], str) or not rule['nl'].strip():
                raise RuleConfigurationError(f'Rule {index} needs nonempty nl metadata')
            if not isinstance(rule['type'], str) or rule['type'] not in BUILDERS:
                raise RuleConfigurationError(
                    f'Unknown rule type {rule["type"]!r}; command limits must use '
                    'command_speed_limit; actual speed requires another model')
            builder, required = BUILDERS[rule['type']]
            if not isinstance(rule['params'], dict) or set(rule['params']) != required:
                raise RuleConfigurationError(f'Invalid parameters for rule {rule["name"]}')
            monitors.append(SafetyMonitor(rule['name'], rule['nl'], builder(**rule['params'])))
            names.add(rule['name'])
        return monitors
    except (OSError, UnicodeError, yaml.YAMLError, TypeError, ValueError) as exc:
        if isinstance(exc, RuleConfigurationError):
            raise
        raise RuleConfigurationError(f'Invalid rule configuration: {exc}') from exc
