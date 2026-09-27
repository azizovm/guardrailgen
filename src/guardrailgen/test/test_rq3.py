"""RQ3 condition/scenario contracts without ROS or Gazebo."""
import json
from pathlib import Path

import pytest

from guardrailgen.artifacts import read_json
from guardrailgen.evaluation.rq3 import aggregate
from guardrailgen.schema import Rule, Scenario
from guardrailgen.simulation.episode import SCENARIO_RULES, main as episode_main, scenario_traces
from guardrailgen.simulation.plans import HousePlanFilter
from guardrailgen.simulation.reference import nominal_speed_rule_safe
from guardrailgen.schema import compile_rule
from guardrailgen.validation import validate_rule

ROOT = Path(__file__).resolve().parents[3]
SCENARIO = Scenario.from_dict(read_json(ROOT / "config/turtlebot_house.json"))
KITCHEN = SCENARIO.regions["kitchen"]


def monitor(name):
    spec = SCENARIO_RULES[name]
    return compile_rule(Rule.from_dict({"schema_version": "1.0", "id": spec["id"], "text": spec["text"],
                                        "expression": spec["expression"]}, SCENARIO), SCENARIO)


@pytest.mark.parametrize("name", sorted(SCENARIO_RULES))
def test_oracle_rules_pass_their_activation_states(name):
    report = validate_rule(monitor(name).rule, SCENARIO, traces=scenario_traces(SCENARIO, name))
    assert report["errors"] == []


def test_speed_rule_states_reject_a_keepout_rule_and_vice_versa():
    keepout, speed = monitor("kitchen_keepout").rule, monitor("kitchen_speed").rule
    assert validate_rule(keepout, SCENARIO, traces=scenario_traces(SCENARIO, "kitchen_speed"))["errors"]
    assert validate_rule(speed, SCENARIO, traces=scenario_traces(SCENARIO, "kitchen_keepout"))["errors"]


def pose_before_kitchen():
    return (KITCHEN["xmin"] - SCENARIO.footprint_radius - 0.08, (KITCHEN["ymin"] + KITCHEN["ymax"]) / 2, 0.0)


def test_physical_only_ignores_rule_but_enforcing_filter_does_not():
    plan = tuple((0.3, 0.0) for _ in range(5))
    enforcing = HousePlanFilter(monitor("kitchen_keepout"))
    physical = HousePlanFilter(monitor("kitchen_keepout"), enforce_rule=False)
    assert not enforcing.check(pose_before_kitchen(), plan)[0]
    assert physical.check(pose_before_kitchen(), plan)[0]


def test_speed_scenario_filter_slows_down_at_the_kitchen():
    decision = HousePlanFilter(monitor("kitchen_speed")).select(pose_before_kitchen(), tuple((0.3, 0.0) for _ in range(5)))
    assert not decision.accepted_original
    assert decision.proposed_reason.startswith("operator_rule_")
    assert all(v <= 0.1 for v, _ in decision.plan)


def test_nominal_speed_replay():
    pose = pose_before_kitchen()
    assert not nominal_speed_rule_safe(pose, ((0.3, 0.0),) * 5, KITCHEN, SCENARIO.footprint_radius, 0.1)
    assert nominal_speed_rule_safe(pose, ((0.1, 0.0),) * 5, KITCHEN, SCENARIO.footprint_radius, 0.1)
    far = (-3.0, -2.5, 0.0)
    assert nominal_speed_rule_safe(far, ((0.5, 0.0),) * 5, KITCHEN, SCENARIO.footprint_radius, 0.1)


@pytest.mark.parametrize("argv", [
    ["--scenario-rule", "kitchen_speed"],
    ["--condition", "guardrailgen"],
    ["--condition", "oracle", "--rule-artifact", "x.json"],
])
def test_invalid_condition_combinations_are_refused(argv):
    with pytest.raises(SystemExit):
        episode_main(["--root", str(ROOT), "--controller", "goal-seeking", *argv])


def test_aggregate_pools_rates_per_condition():
    rows = [
        {"scenario_rule": "kitchen_keepout", "condition": "oracle", "status": "goal_reached", "goal_reached": True,
         "any_actual_rule_violation": False, "reference_violation_samples": 0, "collision_contact_events": 0,
         "collision_measurement_complete": True, "decisions": 100, "interventions": 10, "rule_interventions": 8,
         "oracle_safe_decisions_nominal_replay": 80, "rule_false_restrictions_nominal_replay": 4,
         "elapsed_sim_seconds": 50.0, "path_length_m": 7.0, "max_filter_latency_ms": 90.0},
        {"scenario_rule": "kitchen_keepout", "condition": "oracle", "status": "episode_budget_exceeded",
         "goal_reached": False, "any_actual_rule_violation": True, "reference_violation_samples": 3,
         "collision_contact_events": 1, "collision_measurement_complete": True, "decisions": 100,
         "interventions": 30, "rule_interventions": 20, "oracle_safe_decisions_nominal_replay": 20,
         "rule_false_restrictions_nominal_replay": 6, "elapsed_sim_seconds": 180.0, "path_length_m": 3.0,
         "max_filter_latency_ms": 110.0},
    ]
    block = aggregate(rows)["kitchen_keepout"]["oracle"]
    assert block["goal_reached"] == 1 and block["episodes_with_violation"] == 1
    assert block["intervention_rate_pooled"] == 0.2
    assert block["false_restriction_rate_nominal_pooled"] == 0.1
    assert block["mean_time_to_goal_s"] == 50.0 and block["max_filter_latency_ms"] == 110.0


def test_guidance_can_be_restricted_to_the_top_detour():
    from guardrailgen.simulation.guidance import RectangleGuidance
    below_center = (-1.33, -2.5000043, 0.0)   # the pose that produced a bottom detour
    both = RectangleGuidance(below_center, (3.0, -2.5), KITCHEN, SCENARIO.footprint_radius)
    top = RectangleGuidance(below_center, (3.0, -2.5), KITCHEN, SCENARIO.footprint_radius, sides=("top",))
    assert both.initial_targets[0][1] < KITCHEN["ymin"]
    assert all(t[1] > KITCHEN["ymax"] for t in top.initial_targets[:-1])


def test_slow_checks_still_reach_the_pivot_escape(monkeypatch):
    import time as real_time
    from guardrailgen.simulation import plans
    clock = [0.0]
    monkeypatch.setattr(plans.time, "monotonic", lambda: clock[0])
    flt = HousePlanFilter(monitor("kitchen_keepout"))
    original = flt.check

    def slow_check(pose, plan, obstacles=()):
        clock[0] += 0.045          # 45 ms per check, as measured under load
        return original(pose, plan, obstacles)
    monkeypatch.setattr(flt, "check", slow_check)
    edge = (KITCHEN["xmin"] - SCENARIO.footprint_radius - 0.06, -2.5, 0.0)   # facing the kitchen
    decision = flt.select(edge, tuple((0.3, 0.0) for _ in range(5)))
    assert not decision.accepted_original
    assert "timeout" not in decision.reason and "emergency" not in decision.reason
    assert decision.latency_seconds <= flt.time_budget + 1e-9
