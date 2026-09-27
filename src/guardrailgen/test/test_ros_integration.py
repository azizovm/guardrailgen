"""ROS transport smoke tests on synthetic topics, never the robot command topic."""
from pathlib import Path
import time
import uuid

import pytest

rclpy = pytest.importorskip("rclpy", reason="ROS transport tests run in Ubuntu/ROS Humble")
from rclpy.executors import SingleThreadedExecutor
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from guardrailgen.monitor_node import GuardrailMonitor
from guardrailgen.artifacts import build_artifact, read_json, save_artifact
from guardrailgen.schema import Rule, Scenario
from guardrailgen.validation import validate_rule

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("compiled", [False, True])
def test_ros_forwards_then_rejects_and_watchdog_stops(compiled, tmp_path):
    namespace = "/guardrailgen_test_" + uuid.uuid4().hex
    args = ["--ros-args", "-p", "operating_mode:=heuristic",
            "-p", "command_timeout:=0.15", "-p", "state_timeout:=1.0",
            "-p", "model_unc:=0.0", "-p", "position_uncertainty:=0.0", "-p", "robot_radius:=0.0",
            "-r", "/llm_cmd_vel:=" + namespace + "/proposal",
            "-r", "/cmd_vel:=" + namespace + "/output",
            "-r", "/odom:=" + namespace + "/odom"]
    if compiled:
        scenario = Scenario.from_dict(read_json(ROOT / "config/turtlebot_development.json"))
        rule = Rule.from_dict(read_json(ROOT / "data/reference_rule.json"), scenario)
        path = save_artifact(build_artifact(rule, scenario, validate_rule(rule, scenario)), tmp_path)
        args += ["-p", "artifact_file:=" + str(path)]
    else:
        args += ["-p", "rules_file:=" + str(ROOT / "src/guardrailgen/rules/example_rules.yaml")]
    rclpy.init(args=args)
    monitor = harness = executor = None
    try:
        monitor = GuardrailMonitor()
        assert monitor.gate is not None, monitor._configuration_fault
        harness = rclpy.create_node("harness_" + uuid.uuid4().hex)
        proposals = harness.create_publisher(Twist, namespace + "/proposal", 10)
        odometry = harness.create_publisher(Odometry, namespace + "/odom", 10)
        received = []
        harness.create_subscription(Twist, namespace + "/output", lambda msg: received.append(msg.linear.x), 10)
        executor = SingleThreadedExecutor()
        executor.add_node(monitor)
        executor.add_node(harness)

        def exercise(speed, predicate, publish_command=True):
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                msg = Odometry()
                msg.header.frame_id = "odom"
                msg.header.stamp = harness.get_clock().now().to_msg()
                msg.pose.pose.orientation.w = 1.0
                odometry.publish(msg)
                if publish_command:
                    cmd = Twist()
                    cmd.linear.x = speed
                    proposals.publish(cmd)
                executor.spin_once(timeout_sec=0.02)
                if predicate():
                    return
            pytest.fail("ROS transport did not reach expected behavior")

        exercise(0.1, lambda: any(v == 0.1 for v in received))
        assert not monitor.gate.decide(monitor._now()).formal_guarantee
        received.clear()
        exercise(0.4, lambda: monitor._last_status is not None and monitor._last_status.startswith("monitor_") and 0.0 in received)
        assert 0.4 not in received
        received.clear()
        exercise(0.1, lambda: 0.1 in received)
        received.clear()
        exercise(0, lambda: monitor._last_status == "command_timeout" and 0.0 in received, publish_command=False)
    finally:
        if executor is not None:
            executor.shutdown()
        for node in (monitor, harness):
            if node is not None:
                node.destroy_node()
        rclpy.shutdown()
