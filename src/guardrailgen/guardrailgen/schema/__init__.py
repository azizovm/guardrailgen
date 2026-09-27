"""Versioned, ROS-independent invariant language and conservative monitors.

Expressions describe SAFE behavior. SAFE means every point in the supplied
box satisfies the expression; UNSAFE means every point violates it; UNKNOWN
includes mixed boxes and missing signals. Only SAFE can permit a command.
Region membership means intersection with the circular robot footprint,
including contact. The same signed-distance signals are used by STL lowering.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import copy
from decimal import Decimal
import math
import re
from typing import Mapping

SCHEMA_VERSION = "1.0"


class RuleValidationError(ValueError):
    """A rule or scenario is outside the explicitly supported language."""


class Verdict(str, Enum):
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    UNKNOWN = "UNKNOWN"


VARIABLES = {
    "state.x": {"unit": "m", "source": "odometry position in scenario frame"},
    "state.y": {"unit": "m", "source": "odometry position in scenario frame"},
    "state.heading": {"unit": "rad", "source": "odometry yaw"},
    "state.linear_speed": {"unit": "m/s", "source": "measured signed speed"},
    "state.angular_speed": {"unit": "rad/s", "source": "measured yaw rate"},
    "command.linear_speed": {"unit": "m/s", "source": "proposed signed input"},
    "command.angular_speed": {"unit": "rad/s", "source": "proposed yaw input"},
    "command.duration": {"unit": "s", "source": "proposed action duration"},
}
DEFAULT_VARIABLES = tuple(k for k in VARIABLES if not k.startswith("state.") or k in ("state.x", "state.y", "state.heading"))


def _fields(data, required, optional=()):
    if not isinstance(data, dict):
        raise RuleValidationError("Expected a JSON object")
    if set(data) - set(required) - set(optional) or set(required) - set(data):
        raise RuleValidationError(f"Expected fields {sorted(required)}; got {sorted(data)}")


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuleValidationError(f"{label} must be a finite number")
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise RuleValidationError(f"{label} must be a finite number") from exc
    if not math.isfinite(value):
        raise RuleValidationError(f"{label} must be finite")
    return value


def _name(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]{0,63}", value):
        raise RuleValidationError(f"Invalid {label}: use a letter followed by letters, digits, underscores or hyphens")
    return value


@dataclass(frozen=True)
class Scenario:
    frame: str
    footprint_radius: float
    regions: dict
    supported_variables: tuple

    @classmethod
    def from_dict(cls, data):
        _fields(data, ("schema_version", "frame", "footprint_radius", "regions", "supported_variables"))
        if data["schema_version"] != SCHEMA_VERSION:
            raise RuleValidationError("Unsupported scenario schema_version")
        if not isinstance(data["frame"], str) or not data["frame"].strip():
            raise RuleValidationError("Scenario requires an explicit coordinate frame")
        radius = _number(data["footprint_radius"], "footprint_radius")
        if radius < 0:
            raise RuleValidationError("footprint_radius must be nonnegative")
        variables = data["supported_variables"]
        if not isinstance(variables, list) or not variables or any(not isinstance(v, str) or v not in VARIABLES for v in variables):
            raise RuleValidationError("supported_variables must list known schema variables")
        if len(set(variables)) != len(variables):
            raise RuleValidationError("Duplicate supported_variables")
        if not isinstance(data["regions"], dict):
            raise RuleValidationError("regions must be an object")
        regions = {}
        for name, region in data["regions"].items():
            _name(name, "region name")
            if "-" in name:
                raise RuleValidationError("Region names may not contain hyphens (STL signal identifiers)")
            if not isinstance(region, dict):
                raise RuleValidationError("Region geometry must be an object")
            if region.get("kind") == "rectangle":
                _fields(region, ("kind", "xmin", "xmax", "ymin", "ymax"))
                r = {k: _number(v, k) for k, v in region.items() if k != "kind"}
                if r["xmin"] >= r["xmax"] or r["ymin"] >= r["ymax"]:
                    raise RuleValidationError("Rectangle bounds must have positive area")
            elif region.get("kind") == "circle":
                _fields(region, ("kind", "cx", "cy", "radius"))
                r = {k: _number(v, k) for k, v in region.items() if k != "kind"}
                if r["radius"] <= 0:
                    raise RuleValidationError("Circle radius must be positive")
            else:
                raise RuleValidationError("Only rectangle and circle regions are supported")
            regions[name] = {"kind": region["kind"], **r}
        return cls(data["frame"], radius, regions, tuple(variables))

    def to_dict(self):
        return {"schema_version": SCHEMA_VERSION, "frame": self.frame,
                "footprint_radius": self.footprint_radius, "regions": copy.deepcopy(self.regions),
                "supported_variables": list(self.supported_variables)}


def _validate_expression(expr, scenario, depth=0, budget=None):
    budget = [128] if budget is None else budget
    budget[0] -= 1
    if depth > 12 or budget[0] < 0:
        raise RuleValidationError("Expression exceeds depth/node limit")
    if not isinstance(expr, dict):
        raise RuleValidationError("Expression must be an object")
    op = expr.get("op")
    if op == "compare":
        _fields(expr, ("op", "variable", "comparator", "value", "unit"))
        var = expr["variable"]
        if not isinstance(var, str) or var not in scenario.supported_variables:
            raise RuleValidationError(f"Unsupported variable: {var!r}")
        if expr["unit"] != VARIABLES[var]["unit"]:
            raise RuleValidationError(f"{var} requires unit {VARIABLES[var]['unit']}")
        if expr["comparator"] not in ("lt", "le", "gt", "ge"):
            raise RuleValidationError("Comparator must be lt, le, gt or ge")
        _number(expr["value"], "Comparison value")
    elif op == "inside":
        _fields(expr, ("op", "region"))
        if not isinstance(expr["region"], str) or expr["region"] not in scenario.regions:
            raise RuleValidationError(f"Unknown map region: {expr['region']!r}")
        if not {"state.x", "state.y"}.issubset(scenario.supported_variables):
            raise RuleValidationError("Region checks require state.x and state.y")
    elif op == "not":
        _fields(expr, ("op", "arg"))
        _validate_expression(expr["arg"], scenario, depth + 1, budget)
    elif op in ("and", "or"):
        _fields(expr, ("op", "args"))
        if not isinstance(expr["args"], list) or not 2 <= len(expr["args"]) <= 8:
            raise RuleValidationError("Boolean operators require 2 to 8 arguments")
        for arg in expr["args"]:
            _validate_expression(arg, scenario, depth + 1, budget)
    else:
        raise RuleValidationError(f"Unsupported operator: {op!r}; this milestone supports invariants only")


@dataclass(frozen=True)
class Rule:
    id: str
    text: str
    expression: dict

    @classmethod
    def from_dict(cls, data, scenario):
        _fields(data, ("schema_version", "id", "text", "expression"))
        if data["schema_version"] != SCHEMA_VERSION:
            raise RuleValidationError("Unsupported rule schema_version")
        _name(data["id"], "rule id")
        if not isinstance(data["text"], str) or not data["text"].strip() or len(data["text"]) > 8000:
            raise RuleValidationError("Rule text must contain 1 to 8000 characters")
        _validate_expression(data["expression"], scenario)
        return cls(data["id"], data["text"], copy.deepcopy(data["expression"]))

    def to_dict(self):
        return {"schema_version": SCHEMA_VERSION, "id": self.id, "text": self.text,
                "expression": copy.deepcopy(self.expression)}


def _negate(verdict):
    return {Verdict.SAFE: Verdict.UNSAFE, Verdict.UNSAFE: Verdict.SAFE, Verdict.UNKNOWN: Verdict.UNKNOWN}[verdict]


def _interval(bounds, key):
    try:
        lo, hi = bounds[key]
        lo, hi = _number(lo, key), _number(hi, key)
        return (lo, hi) if lo <= hi else None
    except (KeyError, TypeError, ValueError):
        return None


def _distance_interval(lo, hi, target_lo, target_hi):
    nearest = max(target_lo - hi, lo - target_hi, 0.0)
    farthest = max(target_lo - lo, hi - target_hi, 0.0)
    return nearest, farthest


def _region_distances(region, x, y):
    if region["kind"] == "circle":
        dx = _distance_interval(*x, region["cx"], region["cx"])
        dy = _distance_interval(*y, region["cy"], region["cy"])
    else:
        dx = _distance_interval(*x, region["xmin"], region["xmax"])
        dy = _distance_interval(*y, region["ymin"], region["ymax"])
    return math.hypot(dx[0], dy[0]), math.hypot(dx[1], dy[1])


def _check(expr, bounds, scenario):
    op = expr["op"]
    if op == "compare":
        interval = _interval(bounds, expr["variable"])
        if interval is None:
            return Verdict.UNKNOWN
        lo, hi = interval
        val, cmp = expr["value"], expr["comparator"]
        safe, unsafe = {"lt": (hi < val, lo >= val), "le": (hi <= val, lo > val),
                        "gt": (lo > val, hi <= val), "ge": (lo >= val, hi < val)}[cmp]
        return Verdict.SAFE if safe else Verdict.UNSAFE if unsafe else Verdict.UNKNOWN
    if op == "inside":
        x, y = _interval(bounds, "state.x"), _interval(bounds, "state.y")
        if x is None or y is None:
            return Verdict.UNKNOWN
        region = scenario.regions[expr["region"]]
        near, far = _region_distances(region, x, y)
        radius = scenario.footprint_radius + (region["radius"] if region["kind"] == "circle" else 0.0)
        if not all(math.isfinite(v) for v in (near, far, radius)):
            return Verdict.UNKNOWN
        return Verdict.SAFE if far <= radius else Verdict.UNSAFE if near > radius else Verdict.UNKNOWN
    if op == "not":
        return _negate(_check(expr["arg"], bounds, scenario))
    verdicts = [_check(e, bounds, scenario) for e in expr["args"]]
    if op == "and":
        return Verdict.UNSAFE if Verdict.UNSAFE in verdicts else Verdict.SAFE if all(v == Verdict.SAFE for v in verdicts) else Verdict.UNKNOWN
    return Verdict.SAFE if Verdict.SAFE in verdicts else Verdict.UNSAFE if all(v == Verdict.UNSAFE for v in verdicts) else Verdict.UNKNOWN


def _stl(expr):
    op = expr["op"]
    if op == "compare":
        operator = {"lt": "<", "le": "<=", "gt": ">", "ge": ">="}[expr["comparator"]]
        literal = format(Decimal(str(expr['value'])), "f")
        return f"({expr['variable'].replace('.', '_')} {operator} {literal})"
    if op == "inside":
        return f"(region_{expr['region']} >= 0)"
    if op == "not":
        return f"(not {_stl(expr['arg'])})"
    return "(" + f" {op} ".join(_stl(arg) for arg in expr["args"]) + ")"


class CompiledMonitor:
    def __init__(self, rule, scenario):
        # Revalidate and copy: lowering must not trust an arbitrary constructed Rule.
        self.scenario = Scenario.from_dict(scenario.to_dict())
        self.rule = Rule.from_dict(rule.to_dict(), self.scenario)
        self.name, self.nl = self.rule.id, self.rule.text
        self.stl = _stl(self.rule.expression)

    def evaluate(self, values: Mapping[str, float]):
        return self.check_bounds({key: (value, value) for key, value in values.items()})

    def check_bounds(self, bounds):
        return _check(self.rule.expression, bounds, self.scenario)

    def _box_bounds(self, box):
        # The development predictor covers pose and COMMAND speed only.
        names = ("state.x", "state.y", "state.heading", "command.linear_speed")
        if len(box.center) != 4 or len(box.radius) != 4:
            return None
        bounds = {}
        for name, center, radius in zip(names, box.center, box.radius):
            try:
                center, radius = _number(center, name), _number(radius, name)
            except RuleValidationError:
                return None
            if radius < 0:
                return None
            bounds[name] = (center - radius, center + radius)
        return bounds

    def check_over(self, box):
        bounds = self._box_bounds(box)
        return Verdict.UNKNOWN if bounds is None else self.check_bounds(bounds)

    def check_with_command(self, box, angular_speed):
        bounds = self._box_bounds(box)
        if bounds is None:
            return Verdict.UNKNOWN
        bounds['command.angular_speed'] = (angular_speed, angular_speed)
        # Twist carries no action duration; that signal intentionally stays absent.
        return self.check_bounds(bounds)

    def violated_over(self, box):
        return self.check_over(box) != Verdict.SAFE

    def to_stl_signals(self, values):
        signals = {key.replace(".", "_"): _number(value, key) for key, value in values.items() if key in VARIABLES}
        if "state.x" in values and "state.y" in values:
            x, y = _number(values["state.x"], "x"), _number(values["state.y"], "y")
            for name, region in self.scenario.regions.items():
                distance, _ = _region_distances(region, (x, x), (y, y))
                radius = self.scenario.footprint_radius + (region["radius"] if region["kind"] == "circle" else 0.0)
                signed = radius - distance
                if region["kind"] == "rectangle" and distance == 0:
                    signed = self.scenario.footprint_radius + min(x - region["xmin"], region["xmax"] - x,
                                                               y - region["ymin"], region["ymax"] - y)
                signals[f"region_{name}"] = signed
        return signals


def compile_rule(rule, scenario):
    return CompiledMonitor(rule, scenario)
