#!/usr/bin/env python3
"""ROS command gate for explicit heuristic development experiments.

This node has no data-driven reachable model or verified braking backup.
Faults publish a zero emergency command, without a physical safety guarantee.
The controller and any teleoperation source must not bypass this command path.
"""
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry

from guardrailgen.monitors import compile_rules
from guardrailgen.artifacts import load_monitor
from guardrailgen.reachability import finite_number
from guardrailgen.runtime import RuntimeGate, VelocityCommand, state_from_odometry, validate_topics


class GuardrailMonitor(Node):
    def __init__(self):
        super().__init__('guardrailgen_monitor')
        defaults = {
            'rules_file': '', 'artifact_file': '', 'operating_mode': 'disabled',
            'proposed_cmd_topic': '/llm_cmd_vel', 'safe_cmd_topic': '/cmd_vel',
            'odom_topic': '/odom', 'odom_frame': 'odom', 'control_hz': 20.0,
            'reach_horizon': 6, 'state_timeout': 0.5, 'command_timeout': 0.25,
            'future_tolerance': 0.02, 'model_unc': 0.03,
            'position_uncertainty': 0.03, 'robot_radius': 0.105,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        gp = lambda name: self.get_parameter(name).value
        # Resolve actual graph names, including remaps, before checking aliases.
        proposed_topic = self.resolve_topic_name(gp('proposed_cmd_topic'))
        output_topic = self.resolve_topic_name(gp('safe_cmd_topic'))
        validate_topics(proposed_topic, output_topic)
        self.pub = self.create_publisher(Twist, output_topic, 10)
        self.gate = None
        self._configuration_fault = None
        self._last_status = None
        self.odom_frame = gp('odom_frame')
        period = 0.05
        try:
            hz = finite_number(gp('control_hz'), 'control_hz')
            if hz <= 0:
                raise ValueError('control_hz must be positive')
            period = 1.0 / hz
            if not isinstance(self.odom_frame, str) or not self.odom_frame.strip():
                raise ValueError('odom_frame must be nonempty')
            monitors = self._load_monitors(gp('rules_file'), gp('artifact_file'))
            if gp('artifact_file') and monitors[0].scenario.frame != self.odom_frame:
                raise ValueError('Artifact coordinate frame does not match odom_frame')
            self.gate = RuntimeGate(monitors, operating_mode=gp('operating_mode'),
                state_timeout=gp('state_timeout'), command_timeout=gp('command_timeout'),
                future_tolerance=gp('future_tolerance'), horizon=gp('reach_horizon'),
                prediction_dt=period, model_unc=gp('model_unc'),
                position_uncertainty=gp('position_uncertainty'),
                # Compiled region predicates include the artifact footprint.
                # Legacy predicates instead consume footprint-inflated boxes.
                robot_radius=0.0 if gp('artifact_file') else gp('robot_radius'))
        except Exception as exc:
            self._configuration_fault = f'configuration_error:{exc}'
            self.get_logger().error(self._configuration_fault)
        self.create_subscription(Twist, proposed_topic, self._on_cmd, 10)
        self.create_subscription(Odometry, gp('odom_topic'), self._on_odom, 10)
        self.create_timer(period, self._tick)
        self.get_logger().warn(
            'Heuristic development gate only. Zero-command emergency action is not '
            'verified braking; physical safety is not certified. Explicit '
            'operating_mode:=heuristic is required to forward commands.')
        self.get_logger().info(f'Command path {proposed_topic!r} -> {output_topic!r}')

    @staticmethod
    def _load_monitors(rules_file, artifact_file):
        if artifact_file:
            if rules_file:
                raise ValueError('Choose either rules_file or artifact_file, not both')
            return [load_monitor(artifact_file)]
        return compile_rules(rules_file)

    def _now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def _on_cmd(self, msg: Twist):
        if self.gate is None:
            return
        try:
            command = VelocityCommand.from_twist(msg)
        except ValueError as exc:
            self.gate.invalidate_command(f'invalid_command:{exc}')
            return
        self.gate.update_command(command, self._now())

    def _on_odom(self, msg: Odometry):
        if self.gate is None:
            return
        try:
            state, stamp = state_from_odometry(msg, expected_frame=self.odom_frame)
        except ValueError as exc:
            self.gate.invalidate_state(f'invalid_odometry:{exc}')
            return
        self.gate.update_state(state, stamp, self._now())

    def _tick(self):
        output = Twist()
        if self.gate is None:
            status = self._configuration_fault
        else:
            decision = self.gate.decide(self._now())
            output.linear.x = decision.command.linear_x
            output.angular.z = decision.command.angular_z
            status = decision.reason
            if decision.violated_rule:
                status += f':{decision.violated_rule}:step={decision.prediction_step}'
        # Publish even before readiness and after watchdog expiry.
        self.pub.publish(output)
        if status != self._last_status:
            self._last_status = status
            if status == 'heuristic_checks_passed':
                self.get_logger().info(status)
            else:
                self.get_logger().warn(f'{status}; zero emergency command (uncertified)')


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = GuardrailMonitor()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.pub.publish(Twist())
            node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
