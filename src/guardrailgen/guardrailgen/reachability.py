"""Heuristic unicycle prediction for development, never formal reachability.

The fourth box coordinate is COMMANDED linear speed, not measured motion.
Fixed inflation is not identified from data and is not a physical error bound.
Each future box encloses the nominal constant-command motion during one sample
interval, plus heuristic inflation and a configured circular robot footprint.
This handles nominal motion between samples; it does not establish coverage of
the real robot, tracking/braking dynamics, timing error, or sensed obstacles.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Callable, Sequence

DT = 0.05


def finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f'{name} must be a finite number')
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f'{name} must be a finite number')
    return number


@dataclass(frozen=True)
class DiffDriveState:
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0

    def __post_init__(self):
        for field in ('x', 'y', 'theta'):
            object.__setattr__(self, field, finite_number(getattr(self, field), field))


@dataclass(frozen=True)
class ReachableSet:
    """Closed box in (x, y, heading, commanded_linear_speed).

    A valid box is an enclosure to check, not a claim that its source predictor
    covers physical motion. ``contains_unsafe`` rejects unsupported predicates.
    """

    center: Sequence[float]
    radius: Sequence[float]

    def __post_init__(self):
        if len(self.center) != 4 or len(self.radius) != 4:
            raise ValueError('ReachableSet requires four center and radius coordinates')
        center = tuple(finite_number(v, 'center') for v in self.center)
        radius = tuple(finite_number(v, 'radius') for v in self.radius)
        if any(r < 0 for r in radius):
            raise ValueError('Box radii must be nonnegative')
        if any(not math.isfinite(c - r) or not math.isfinite(c + r)
               for c, r in zip(center, radius)):
            raise ValueError('Box bounds must be finite')
        object.__setattr__(self, 'center', center)
        object.__setattr__(self, 'radius', radius)

    @property
    def bounds(self) -> tuple[tuple[float, float], ...]:
        return tuple((c - r, c + r) for c, r in zip(self.center, self.radius))

    def contains_unsafe(self, is_unsafe: Callable[[Sequence[float]], bool],
                        grid: int = 5) -> bool:
        """Conservative compatibility API; ``grid`` is ignored, never sampled.

        A callable without an analytic ``intersects_box`` method cannot certify
        a whole box and therefore returns True (reject) rather than guessing.
        """
        checker = getattr(is_unsafe, 'intersects_box', None)
        if checker is None:
            return True
        try:
            return checker(self) is not False
        except Exception:
            return True


def predict_reachable_sequence(
        s: DiffDriveState, v: float, w: float, horizon: int = 6,
        model_unc: float = 0.03, *, dt: float = DT,
        position_uncertainty: float = 0.03,
        heading_uncertainty: float = 0.1,
        robot_radius: float = 0.105) -> tuple[ReachableSet, ...]:
    """Return initial occupancy and every nominal swept interval enclosure.

    ``model_unc`` is an arbitrary per-step position inflation in meters. The
    caller must explicitly opt into heuristic operation. No verified backup or
    SafeLLMRA model is present. A zero input does not prove physical stopping.
    """
    if not isinstance(s, DiffDriveState):
        raise ValueError('A validated DiffDriveState is required')
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise ValueError('horizon must be a positive integer')
    v, w, dt = (finite_number(v, 'command speed'),
                finite_number(w, 'command turn rate'), finite_number(dt, 'dt'))
    if dt <= 0:
        raise ValueError('dt must be positive')
    widths = [finite_number(value, name) for value, name in (
        (model_unc, 'model_unc'), (position_uncertainty, 'position_uncertainty'),
        (heading_uncertainty, 'heading_uncertainty'), (robot_radius, 'robot_radius'))]
    if any(value < 0 for value in widths):
        raise ValueError('Uncertainty and footprint radii must be nonnegative')
    model_unc, position_uncertainty, heading_uncertainty, robot_radius = widths
    x, y, theta = s.x, s.y, s.theta
    initial_width = position_uncertainty + robot_radius
    sequence = [ReachableSet((x, y, theta, v),
                             (initial_width, initial_width, heading_uncertainty, 0.0))]
    travel = abs(v) * dt
    for step in range(1, horizon + 1):
        angle = w * dt
        # Midpoint/sinc form of the exact constant-command unicycle solution.
        half_angle = angle / 2.0
        scale = math.sin(half_angle) / half_angle if half_angle else 1.0
        x += v * dt * scale * math.cos(theta + half_angle)
        y += v * dt * scale * math.sin(theta + half_angle)
        theta += angle
        # Every nominal point since the previous step is at most |v|*dt from
        # the endpoint. Physical uncertainty remains an unvalidated heuristic.
        width = initial_width + model_unc * step + travel
        sequence.append(ReachableSet((x, y, theta, v),
            (width, width, heading_uncertainty + abs(angle), 0.0)))
    return tuple(sequence)


def predict_reachable(s: DiffDriveState, v: float, w: float,
                      horizon: int = 6, model_unc: float = 0.03) -> ReachableSet:
    """Legacy final-box API; filtering must use predict_reachable_sequence."""
    return predict_reachable_sequence(s, v, w, horizon, model_unc)[-1]
