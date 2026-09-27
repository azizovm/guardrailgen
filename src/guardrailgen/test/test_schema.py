"""Independent boundary, grounding, and set-coverage regression cases."""
import copy
import math

import pytest

from guardrailgen.schema import Rule, RuleValidationError, Scenario, Verdict, compile_rule


@pytest.fixture
def scenario():
    return Scenario.from_dict({"schema_version": "1.0", "frame": "odom", "footprint_radius": 0.0,
        "regions": {"zone": {"kind": "rectangle", "xmin": 1, "xmax": 2, "ymin": -1, "ymax": 1},
                    "tiny": {"kind": "circle", "cx": 0.123, "cy": 0.123, "radius": 0.001}},
        "supported_variables": ["state.x", "state.y", "state.heading", "command.linear_speed"]})


def monitor(scenario, expression):
    return compile_rule(Rule.from_dict({"schema_version": "1.0", "id": "test", "text": "Reference rule",
        "expression": expression}, scenario), scenario)


def compare(comparator="le", value=0.2, **updates):
    return {"op": "compare", "variable": "command.linear_speed", "comparator": comparator,
            "value": value, "unit": "m/s", **updates}


@pytest.mark.parametrize("op,value,expected", [("lt", 0.2, Verdict.UNSAFE), ("le", 0.2, Verdict.SAFE),
    ("ge", 0.2, Verdict.SAFE), ("gt", 0.2, Verdict.UNSAFE), ("le", -0.5, Verdict.SAFE)])
def test_comparison_boundaries(scenario, op, value, expected):
    assert monitor(scenario, compare(op)).evaluate({"command.linear_speed": value}) == expected


@pytest.mark.parametrize("changes", [{"unit": "km/h"}, {"variable": "state.linear_speed"},
    {"value": True}, {"value": math.nan}, {"value": math.inf}, {"extra": "injected"}])
def test_bad_rule_rejected(scenario, changes):
    with pytest.raises(RuleValidationError):
        monitor(scenario, compare(**changes))


def test_unknown_region_and_temporal_operator_rejected(scenario):
    for expression in [{"op": "inside", "region": "invented"}, {"op": "eventually", "seconds": 5}]:
        with pytest.raises(RuleValidationError):
            monitor(scenario, expression)


def test_mixed_and_missing_speed_are_unknown(scenario):
    mon = monitor(scenario, compare())
    assert mon.check_bounds({"command.linear_speed": (0.1, 0.3)}) == Verdict.UNKNOWN
    assert mon.evaluate({}) == Verdict.UNKNOWN
    assert mon.evaluate({"command.linear_speed": math.nan}) == Verdict.UNKNOWN
    assert mon.check_bounds({"command.linear_speed": (1, 0)}) == Verdict.UNKNOWN


def test_tiny_unsafe_region_cannot_hide_between_grid_points(scenario):
    mon = monitor(scenario, {"op": "not", "arg": {"op": "inside", "region": "tiny"}})
    assert mon.check_bounds({"state.x": (-1, 1), "state.y": (-1, 1)}) == Verdict.UNKNOWN
    assert mon.evaluate({"state.x": 0.123, "state.y": 0.123}) == Verdict.UNSAFE


def test_robot_footprint_contact_and_corner_distance(scenario):
    config = scenario.to_dict()
    config["footprint_radius"] = 0.25
    mon = monitor(Scenario.from_dict(config), {"op": "not", "arg": {"op": "inside", "region": "zone"}})
    assert mon.evaluate({"state.x": 0.75, "state.y": 0}) == Verdict.UNSAFE
    assert mon.evaluate({"state.x": 0.749, "state.y": 0}) == Verdict.SAFE
    assert mon.evaluate({"state.x": 0.8, "state.y": 1.2}) == Verdict.SAFE


def test_conditional_limit_conservative_when_zone_membership_uncertain(scenario):
    mon = monitor(scenario, {"op": "or", "args": [{"op": "not", "arg": {"op": "inside", "region": "zone"}}, compare(value=0.1)]})
    assert mon.check_bounds({"state.x": (0.5, 1.5), "state.y": (0, 0), "command.linear_speed": (0.2, 0.2)}) == Verdict.UNKNOWN
    assert mon.check_bounds({"state.x": (0.5, 1.5), "state.y": (0, 0), "command.linear_speed": (0.05, 0.05)}) == Verdict.SAFE


def test_contradictory_conditions_do_not_accept(scenario):
    mon = monitor(scenario, {"op": "and", "args": [compare("lt", 0), compare("ge", 0)]})
    for speed in [-1, 0, 1]:
        assert mon.evaluate({"command.linear_speed": speed}) == Verdict.UNSAFE


def test_stl_signals_respect_footprint_and_interior(scenario):
    mon = monitor(scenario, {"op": "inside", "region": "zone"})
    assert mon.to_stl_signals({"state.x": 1.5, "state.y": 0})["region_zone"] == 0.5
    assert mon.to_stl_signals({"state.x": 1, "state.y": 0})["region_zone"] == 0
    assert mon.to_stl_signals({"state.x": 0.5, "state.y": 0})["region_zone"] == -0.5


def test_stl_does_not_round_threshold(scenario):
    assert "0.10000000000000002" in monitor(scenario, compare(value=0.10000000000000002)).stl


def test_lowering_copies_source_expression(scenario):
    expr = compare()
    mon = monitor(scenario, expr)
    expr["value"] = 99
    assert mon.evaluate({"command.linear_speed": 0.3}) == Verdict.UNSAFE
