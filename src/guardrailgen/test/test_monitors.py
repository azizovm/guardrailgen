"""Pure-Python test of the rule compiler + reachable-set check (no ROS needed).
Run with:  python -m pytest src/guardrailgen/test
"""
from guardrailgen.monitors import compile_rules, keep_out_circle, SafetyMonitor
from guardrailgen.reachability import ReachableSet


def test_keep_out_triggers_inside():
    mon = SafetyMonitor('t', 'stay away', keep_out_circle(1.5, 0.0, 0.5))
    near = ReachableSet(center=[1.5, 0.0, 0.0, 0.1], radius=[0.1, 0.1, 0.0, 0.0])
    far = ReachableSet(center=[5.0, 5.0, 0.0, 0.1], radius=[0.1, 0.1, 0.0, 0.0])
    assert mon.violated_over(near) is True
    assert mon.violated_over(far) is False
