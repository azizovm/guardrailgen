"""Behavioral regressions for unsafe acceptance and runtime readiness failures."""
import math
from types import SimpleNamespace as NS

import pytest

from guardrailgen.monitors import SafetyMonitor, RuleConfigurationError, command_speed_limit, compile_rules, keep_out_circle
from guardrailgen.reachability import DiffDriveState, ReachableSet, predict_reachable_sequence
from guardrailgen.runtime import RuntimeGate, VelocityCommand, state_from_odometry, validate_topics
from guardrailgen.schema import Rule, Scenario, Verdict, compile_rule


def gate(monitors=None, **options):
    defaults = dict(operating_mode="heuristic", model_unc=0, position_uncertainty=0, robot_radius=0)
    defaults.update(options)
    return RuntimeGate(monitors or [SafetyMonitor("speed", "command limit", command_speed_limit(0.22))], **defaults)


def ready(g, speed=0.1, now=10):
    assert g.update_state(DiffDriveState(), now, now)
    assert g.update_command(VelocityCommand(speed, 0), now)
    return g


def odometry():
    return NS(header=NS(frame_id="odom", stamp=NS(sec=10, nanosec=0)),
        pose=NS(pose=NS(position=NS(x=0, y=0, z=0), orientation=NS(x=0, y=0, z=0, w=1)), covariance=[0.0]*36),
        twist=NS(twist=NS(linear=NS(x=0, y=0, z=0), angular=NS(x=0, y=0, z=0)), covariance=[0.0]*36))


def test_requires_state_command_and_explicit_heuristic_mode():
    g = gate()
    assert g.decide(10).reason == "odometry_not_ready"
    assert g.update_state(DiffDriveState(), 10, 10)
    assert g.decide(10).reason == "command_not_ready"
    assert ready(g).decide(10).accepted
    assert ready(gate(operating_mode="disabled")).decide(10).reason == "heuristic_mode_not_enabled"


def test_command_timeout_and_stale_state_use_emergency_not_certificate():
    g = ready(gate())
    expired = g.decide(10.26)
    assert not expired.accepted and expired.reason == "command_timeout"
    assert expired.command == VelocityCommand() and not expired.formal_guarantee
    g.update_command(VelocityCommand(0.1), 10.51)
    assert g.decide(10.51).reason == "stale_odometry"


def test_stale_source_replayed_receipts_cannot_refresh_readiness():
    g = ready(gate())
    assert not g.update_state(DiffDriveState(x=99), 10, 11)
    assert g.state.x == 0 and g.state_received == 10
    assert not g.decide(11).accepted


def test_invalid_message_does_not_refresh_cache_or_keep_forwarding():
    g = ready(gate())
    assert not g.update_command(object(), 10.1)
    assert g.command_received == 10
    assert not g.decide(10.1).accepted
    assert g.update_command(VelocityCommand(0.1), 10.15)
    assert g.decide(10.15).accepted
    assert not g.update_state(DiffDriveState(), 10.5, 10.16)
    assert not g.decide(10.16).accepted


def test_clock_rollback_clears_both_caches():
    g = ready(gate())
    assert g.decide(1).reason == "clock_rollback"
    assert g.state is None and g.command is None
    assert g.update_state(DiffDriveState(), 1.1, 1.1)
    assert not g.decide(1.1).accepted
    assert g.update_command(VelocityCommand(0.1), 1.1)
    assert g.decide(1.1).accepted


def test_speed_limit_checked_even_without_obstacles():
    decision = ready(gate(), speed=0.23).decide(10)
    assert not decision.accepted and decision.violated_rule == "speed"


def test_tiny_circle_intersecting_box_is_not_missed():
    mon = SafetyMonitor("tiny", "tiny obstacle", keep_out_circle(0.123, 0.123, 0.001))
    assert mon.check_over(ReachableSet([0, 0, 0, 0], [1, 1, 0, 0])) != Verdict.SAFE


def test_intermediate_and_intersample_collision_rejected_with_clear_endpoint():
    mon = SafetyMonitor("middle", "obstacle between first samples", keep_out_circle(0.025, 0, 0.001))
    g = gate([mon], horizon=6, prediction_dt=0.05)
    sequence = predict_reachable_sequence(DiffDriveState(), 1, 0, horizon=6, model_unc=0,
                                         position_uncertainty=0, robot_radius=0)
    assert mon.check_over(sequence[-1]) == Verdict.SAFE
    decision = ready(g, speed=1).decide(10)
    assert not decision.accepted and decision.prediction_step == 1


def test_initial_occupancy_checked_before_first_future_step():
    mon = SafetyMonitor("initial", "already in obstacle", keep_out_circle(0, 0, 0.01))
    decision = ready(gate([mon])).decide(10)
    assert not decision.accepted and decision.prediction_step == 0


def test_unbounded_point_callable_cannot_certify_box():
    mon = SafetyMonitor("point-only", "no sound bounds", lambda _: False)
    assert mon.check_over(ReachableSet([0]*4, [0]*4)) == Verdict.UNKNOWN
    assert not ready(gate([mon])).decide(10).accepted


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True])
def test_nonfinite_commands_states_boxes_rejected(bad):
    for constructor in [lambda: VelocityCommand(bad), lambda: DiffDriveState(x=bad),
                        lambda: ReachableSet([bad,0,0,0], [0]*4)]:
        with pytest.raises(ValueError):
            constructor()


@pytest.mark.parametrize("mutate", [
    lambda msg: setattr(msg.header, "frame_id", "map"),
    lambda msg: setattr(msg.header.stamp, "nanosec", 1_000_000_000),
    lambda msg: setattr(msg.pose.pose.orientation, "w", 0),
    lambda msg: setattr(msg.pose.pose.position, "x", math.nan),
    lambda msg: setattr(msg.twist.twist.linear, "x", math.inf),
    lambda msg: msg.pose.covariance.__setitem__(0, -1),
])
def test_malformed_odometry_is_rejected(mutate):
    msg = odometry()
    mutate(msg)
    with pytest.raises(ValueError):
        state_from_odometry(msg)


def test_valid_odometry_and_planar_twist():
    msg = odometry()
    assert state_from_odometry(msg) == (DiffDriveState(), 10)
    assert VelocityCommand.from_twist(msg.twist.twist) == VelocityCommand()
    msg.twist.twist.linear.y = 0.1
    with pytest.raises(ValueError):
        VelocityCommand.from_twist(msg.twist.twist)


def test_command_loop_topics_rejected():
    with pytest.raises(ValueError):
        validate_topics("/cmd_vel", "cmd_vel")


@pytest.mark.parametrize("text", ["", "rules: []", "rules: []\nrules: []", "rules:\n - {name: bad, nl: text, type: invented, params: {}}",
    "rules:\n - {name: speed, nl: text, type: speed_limit, params: {v_max: 0.2}}",
    "rules:\n - {name: speed, nl: text, type: command_speed_limit, params: {v_max: .nan}}"])
def test_invalid_rule_file_is_atomic_failure(tmp_path, text):
    path = tmp_path / "rules.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(RuleConfigurationError):
        compile_rules(str(path))


def test_missing_configuration_is_not_an_empty_rule_set(tmp_path):
    for path in ["", str(tmp_path / "missing.yaml")]:
        with pytest.raises(RuleConfigurationError):
            compile_rules(path)


def test_compiled_angular_input_checked_and_actual_velocity_not_substituted():
    scenario = Scenario.from_dict({"schema_version": "1.0", "frame": "odom", "footprint_radius": 0,
        "regions": {}, "supported_variables": ["state.linear_speed", "command.angular_speed"]})
    def mon(variable, unit):
        rule = Rule.from_dict({"schema_version": "1.0", "id": "test", "text": "Reference",
            "expression": {"op": "compare", "variable": variable, "unit": unit, "comparator": "le", "value": 0.1}}, scenario)
        return compile_rule(rule, scenario)
    g = ready(gate([mon("command.angular_speed", "rad/s")]))
    assert g.update_command(VelocityCommand(0, 0.2), 10)
    assert not g.decide(10).accepted
    assert ready(gate([mon("state.linear_speed", "m/s")])).decide(10).reason == "monitor_UNKNOWN"


def test_monitor_failure_cannot_forward_command():
    class BrokenMonitor:
        def check_over(self, _):
            raise RuntimeError("test failure")
    decision = ready(gate([BrokenMonitor()])).decide(10)
    assert not decision.accepted and decision.reason == "prediction_or_monitor_error:RuntimeError"
