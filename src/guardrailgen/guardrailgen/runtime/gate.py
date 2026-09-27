"""Freshness checks and heuristic gating, importable without ROS.

Every rejection returns a zero emergency command. It is not verified braking,
and neither acceptance nor rejection carries a physical safety guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from guardrailgen.reachability import DiffDriveState, finite_number, predict_reachable_sequence
from guardrailgen.schema import Verdict


@dataclass(frozen=True)
class VelocityCommand:
    linear_x: float = 0.0
    angular_z: float = 0.0

    def __post_init__(self):
        for field in ('linear_x', 'angular_z'):
            object.__setattr__(self, field, finite_number(getattr(self, field), field))

    @classmethod
    def from_twist(cls, msg):
        """Validate all six components before retaining the supported two."""
        try:
            values = [finite_number(value, 'Twist component') for value in (
                msg.linear.x, msg.linear.y, msg.linear.z,
                msg.angular.x, msg.angular.y, msg.angular.z)]
        except (AttributeError, TypeError) as exc:
            raise ValueError('Malformed Twist') from exc
        if any(values[index] != 0.0 for index in (1, 2, 3, 4)):
            raise ValueError('Only planar linear.x and angular.z commands are supported')
        return cls(values[0], values[5])


def state_from_odometry(msg, *, expected_frame: str = 'odom'):
    """Validate planar odometry and return (pose, source_stamp).

    Measured twists are checked for malformed input but are deliberately not
    substituted for command-speed bounds. Covariance is not a proven bound.
    """
    try:
        if msg.header.frame_id != expected_frame:
            raise ValueError(f'Odometry frame must be {expected_frame!r}')
        sec, nanosec = msg.header.stamp.sec, msg.header.stamp.nanosec
        if (isinstance(sec, bool) or not isinstance(sec, int) or sec < 0
                or isinstance(nanosec, bool) or not isinstance(nanosec, int)
                or not 0 <= nanosec < 1_000_000_000):
            raise ValueError('Malformed odometry timestamp')
        position = msg.pose.pose.position
        x, y, z = [finite_number(value, 'position') for value in (
            position.x, position.y, position.z)]
        q = msg.pose.pose.orientation
        qx, qy, qz, qw = [finite_number(value, 'quaternion') for value in (
            q.x, q.y, q.z, q.w)]
        norm = math.hypot(qx, qy, qz, qw)
        if abs(norm - 1.0) > 1e-3:
            raise ValueError('Odometry quaternion must be normalized')
        if abs(z) > 0.1 or abs(qx) > 0.01 or abs(qy) > 0.01:
            raise ValueError('Odometry must be planar for the unicycle scaffold')
        twist = msg.twist.twist
        for value in (twist.linear.x, twist.linear.y, twist.linear.z,
                      twist.angular.x, twist.angular.y, twist.angular.z):
            finite_number(value, 'measured twist')
        for covariance in (msg.pose.covariance, msg.twist.covariance):
            if len(covariance) != 36:
                raise ValueError('Odometry covariance must contain 36 values')
            for value in covariance:
                finite_number(value, 'odometry covariance')
            if any(covariance[i] < 0 for i in (0, 7, 14, 21, 28, 35)):
                raise ValueError('Covariance diagonal must be nonnegative')
        yaw = math.atan2(2.0 * (qw * qz + qx * qy),
                         1.0 - 2.0 * (qy * qy + qz * qz))
        return DiffDriveState(x=x, y=y, theta=yaw), sec + nanosec * 1e-9
    except (AttributeError, TypeError, OverflowError) as exc:
        raise ValueError('Malformed odometry') from exc


def validate_topics(proposed: str, output: str):
    """Pass fully ROS-resolved names to also detect namespace/remap aliases."""
    if (not isinstance(proposed, str) or not proposed.strip()
            or not isinstance(output, str) or not output.strip()):
        raise ValueError('Input and output topics must be nonempty')
    if proposed.strip('/') == output.strip('/'):
        raise ValueError('Proposed and output command topics must be distinct')


@dataclass(frozen=True)
class Decision:
    command: VelocityCommand
    accepted: bool
    reason: str
    formal_guarantee: bool = False
    violated_rule: str | None = None
    prediction_step: int | None = None


class RuntimeGate:
    """Explicit heuristic opt-in, with no verified backup implementation.

    Timestamps and receipt times use the same control clock. Clock rollback
    drops both caches and requires fresh state and a fresh command. Invalid
    messages cannot update valid values or their timestamps; they also inhibit
    forwarding until a new valid message of that stream arrives.
    """

    def __init__(self, monitors: Sequence, *, operating_mode: str = 'disabled',
                 state_timeout: float = 0.5, command_timeout: float = 0.25,
                 future_tolerance: float = 0.02, horizon: int = 6,
                 prediction_dt: float = 0.05, model_unc: float = 0.03,
                 position_uncertainty: float = 0.03, robot_radius: float = 0.105):
        if operating_mode not in ('disabled', 'heuristic'):
            raise ValueError('Only disabled or heuristic operating_mode is implemented')
        if not monitors or any(not callable(getattr(m, 'check_over', None)) for m in monitors):
            raise ValueError('A nonempty validated monitor set is required')
        self.monitors = tuple(monitors)
        self.operating_mode = operating_mode
        self.state_timeout = finite_number(state_timeout, 'state_timeout')
        self.command_timeout = finite_number(command_timeout, 'command_timeout')
        self.future_tolerance = finite_number(future_tolerance, 'future_tolerance')
        if self.state_timeout <= 0 or self.command_timeout <= 0 or self.future_tolerance < 0:
            raise ValueError('Timeouts must be positive; future tolerance nonnegative')
        self.prediction_options = dict(horizon=horizon, dt=prediction_dt,
            model_unc=model_unc, position_uncertainty=position_uncertainty,
            robot_radius=robot_radius)
        # Validate prediction settings before the node can forward a command.
        predict_reachable_sequence(DiffDriveState(), 0.0, 0.0, **self.prediction_options)
        self.state = None
        self.command = None
        self.state_stamp = None
        self.state_received = None
        self.command_received = None
        self.state_fault = None
        self.command_fault = None
        self._last_now = None

    def _clock(self, now):
        try:
            now = finite_number(now, 'clock')
            if now < 0:
                raise ValueError('clock must be nonnegative')
        except ValueError:
            self._clear('invalid_clock')
            return False
        if self._last_now is not None and now < self._last_now:
            self._last_now = now
            self._clear('clock_rollback')
            return False
        self._last_now = now
        return True

    def _clear(self, reason):
        self.state = self.command = None
        self.state_stamp = self.state_received = self.command_received = None
        self.state_fault = self.command_fault = reason

    def invalidate_state(self, reason='invalid_odometry'):
        self.state_fault = reason

    def invalidate_command(self, reason='invalid_command'):
        self.command_fault = reason

    def update_state(self, state, source_stamp, now) -> bool:
        if not self._clock(now):
            return False
        try:
            if not isinstance(state, DiffDriveState):
                raise ValueError('Invalid state object')
            stamp = finite_number(source_stamp, 'odometry timestamp')
            if stamp < 0 or stamp > now + self.future_tolerance:
                raise ValueError('Odometry timestamp is invalid or in the future')
            if now - stamp > self.state_timeout:
                raise ValueError('Odometry is already stale on receipt')
            if self.state_stamp is not None and stamp < self.state_stamp:
                raise ValueError('Out-of-order odometry timestamp')
        except ValueError as exc:
            self.invalidate_state(str(exc))
            return False
        self.state, self.state_stamp, self.state_received = state, stamp, now
        self.state_fault = None
        return True

    def update_command(self, command, now) -> bool:
        if not self._clock(now):
            return False
        if not isinstance(command, VelocityCommand):
            self.invalidate_command()
            return False
        self.command, self.command_received = command, now
        self.command_fault = None
        return True

    @staticmethod
    def _stop(reason, rule=None, step=None):
        return Decision(VelocityCommand(), False, reason, violated_rule=rule,
                        prediction_step=step)

    def decide(self, now) -> Decision:
        if not self._clock(now):
            return self._stop(self.state_fault)
        if self.operating_mode != 'heuristic':
            return self._stop('heuristic_mode_not_enabled')
        if self.state_fault or self.command_fault:
            return self._stop(self.state_fault or self.command_fault)
        if self.state is None:
            return self._stop('odometry_not_ready')
        if self.command is None:
            return self._stop('command_not_ready')
        if (now - self.state_received > self.state_timeout
                or now - self.state_stamp > self.state_timeout):
            return self._stop('stale_odometry')
        if now - self.command_received > self.command_timeout:
            return self._stop('command_timeout')
        try:
            sequence = predict_reachable_sequence(self.state, self.command.linear_x,
                self.command.angular_z, **self.prediction_options)
            for step, box in enumerate(sequence):
                for monitor in self.monitors:
                    if callable(getattr(monitor, 'check_with_command', None)):
                        verdict = monitor.check_with_command(box, self.command.angular_z)
                    else:
                        verdict = monitor.check_over(box)
                    if verdict != Verdict.SAFE:
                        label = verdict.value if isinstance(verdict, Verdict) else 'invalid_verdict'
                        return self._stop(f'monitor_{label}', getattr(monitor, 'name', None), step)
        except Exception as exc:
            return self._stop(f'prediction_or_monitor_error:{type(exc).__name__}')
        return Decision(self.command, True, 'heuristic_checks_passed')
