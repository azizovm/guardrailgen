"""Finite candidate search over full 0.1 s plans, with an explicit heuristic backend."""
from dataclasses import dataclass
import math
import time

from guardrailgen.reachability import DiffDriveState, ReachableSet, finite_number
from guardrailgen.schema import Verdict


def validate_plan(plan, max_steps=5):
    if not isinstance(plan, (list, tuple)) or not 1 <= len(plan) <= max_steps:
        raise ValueError('A plan must have 1 to 5 control rows')
    result = []
    for row in plan:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError('Each plan row must be [linear_speed, angular_speed]')
        v, w = [finite_number(item, 'plan input') for item in row]
        if not 0 <= v <= 0.5 or not -0.5 <= w <= 0.5:
            raise ValueError('House experiment inputs require v in [0,0.5], omega in [-0.5,0.5]')
        result.append((v,w))
    return tuple(result)


def decode_flat_plan(data):
    """Decode ROS Float64MultiArray's array.array without weakening validation."""
    if len(data)%2:
        raise ValueError('Plan array must have two columns')
    return validate_plan([list(data[i:i+2]) for i in range(0,len(data),2)])


def decode_plan_label(label):
    """Sequence and target revision; legacy integer labels belong to revision 0."""
    parts=label.split(':')
    if len(parts) not in (1,2) or any(not part.isdecimal() for part in parts):
        raise ValueError('Invalid plan sequence/target revision')
    return int(parts[0]),int(parts[1]) if len(parts)==2 else 0


def advance(pose, v, w, dt):
    x,y,yaw = pose
    a = w*dt/2
    travel = v*dt*(math.sin(a)/a if a else 1.0)
    return x+travel*math.cos(yaw+a), y+travel*math.sin(yaw+a), yaw+w*dt


@dataclass(frozen=True)
class PlanDecision:
    plan: tuple
    accepted_original: bool
    reason: str
    rejected_step: int | None
    tested: int
    latency_seconds: float
    formal_guarantee: bool = False
    proposed_reason: str = ''


class CheckedPlanQueue:
    """A rejected plan is replaced, never resumed after one corrective step."""
    def __init__(self):
        self.rows=[]
        self.source='controller'
        self.received=0.

    def __bool__(self):
        return bool(self.rows)

    def replace(self, rows, source, now):
        self.rows=list(validate_plan(rows)) if rows else []
        self.source=source
        self.received=now

    def take(self, now):
        if now-self.received>2:
            self.rows=[]
        proposal=tuple(self.rows)
        if self.rows:
            self.rows.pop(0)
        return proposal,self.source

    def apply(self, decision, now):
        if not decision.accepted_original:
            self.replace(decision.plan[1:],'filter_correction',now)


class HousePlanFilter:
    def __init__(self, monitor, *, dt=0.1, position_uncertainty=0.02,
                 per_step_inflation=0.005, braking_deceleration=0.5, time_budget=0.09, predictor=None,
                 enforce_rule=True):
        # enforce_rule=False is the RQ3 physical-only baseline: LiDAR and predictor
        # obstacle checks stay; operator-rule verdicts are ignored.
        self.monitor = monitor
        self.enforce_rule = bool(enforce_rule)
        self.predictor = predictor
        self.escape_turn = 0
        self.safe_streak = 0
        self.dt = finite_number(dt, 'dt')
        self.uncertainty = finite_number(position_uncertainty, 'position_uncertainty')
        self.inflation = finite_number(per_step_inflation, 'per_step_inflation')
        self.deceleration = finite_number(braking_deceleration, 'braking_deceleration')
        self.time_budget = finite_number(time_budget, 'time_budget')
        if self.dt != 0.1 or min(self.uncertainty, self.inflation) < 0 or min(self.deceleration, self.time_budget) <= 0:
            raise ValueError('Invalid house prediction configuration')

    def check(self, pose, plan, obstacles=()):
        x,y,yaw = pose
        checked = [(x,y,yaw,plan[0][0],plan[0][1],self.uncertainty)]
        # A nominal braking suffix is checked, but deceleration is an unverified
        # development assumption. This is NOT a certified SafeLLMRA backup.
        extension = list(plan)
        v = plan[-1][0]
        while v > 0:
            v = max(0, v-self.deceleration*self.dt)
            extension.append((v, 0.0))
        for j,(v,w) in enumerate(extension, 1):
            x,y,yaw = advance((x,y,yaw), v,w,self.dt)
            width = self.uncertainty + j*self.inflation + abs(v)*self.dt
            checked.append((x,y,yaw,v,w,width))
        for j,(x,y,yaw,v,w,width) in enumerate(checked):
            box = ReachableSet((x,y,yaw,v), (width,width,0.1+abs(w)*self.dt,0))
            bounds = {'state.x':box.bounds[0], 'state.y':box.bounds[1], 'state.heading':box.bounds[2],
                      'command.linear_speed':(v,v), 'command.angular_speed':(w,w),
                      'command.duration':(len(plan)*self.dt,len(plan)*self.dt)}
            verdict = self.monitor.check_bounds(bounds) if self.enforce_rule else Verdict.SAFE
            if verdict != Verdict.SAFE:
                return False, j, 'operator_rule_' + verdict.value
            # LiDAR returns are sampled obstacles, not a complete free-space certificate.
            radius = self.monitor.scenario.footprint_radius + 0.03
            for ox,oy in obstacles:
                dx,dy = max(abs(ox-x)-width,0), max(abs(oy-y)-width,0)
                if math.hypot(dx,dy) <= radius:
                    return False,j,'lidar_obstacle'
        if self.predictor is not None:
            try:
                # Numerical check covers every commanded step. The appended
                # braking suffix above uses only the explicitly nominal model.
                boxes=self.predictor.boxes(pose,plan,self.uncertainty)
            except Exception:
                return False,None,'safellmra_prediction_failed'
            for j,(center,radius) in enumerate(boxes):
                v,w=plan[max(0,j-1)]
                # Same explicitly unverified intersample inflation as the nominal path.
                margin=abs(v)*self.dt if j else 0.
                rx,ry=radius[0]+margin,radius[1]+margin
                bounds={'state.x':(center[0]-rx,center[0]+rx),'state.y':(center[1]-ry,center[1]+ry),
                    'state.heading':(-math.pi,math.pi),'command.linear_speed':(v,v),
                    'command.angular_speed':(w,w),'command.duration':(len(plan)*self.dt,len(plan)*self.dt)}
                verdict=self.monitor.check_bounds(bounds) if self.enforce_rule else Verdict.SAFE
                if verdict!=Verdict.SAFE:
                    return False,j,'operator_rule_safellmra_'+verdict.value
                for ox,oy in obstacles:
                    if math.hypot(max(abs(ox-center[0])-rx,0),max(abs(oy-center[1])-ry,0))<=self.monitor.scenario.footprint_radius+.03:
                        return False,j,'safellmra_lidar_obstacle'
        return True,None,'safellmra_experimental_checks_passed' if self.predictor else 'heuristic_checks_passed'

    def select(self, pose, proposal, obstacles=()):
        proposal = validate_plan(proposal)
        start = time.monotonic()
        safe, step, reason = self.check(pose,proposal,obstacles)
        if safe:
            self.safe_streak += 1
            if self.safe_streak >= 10:
                self.escape_turn = 0
            return PlanDecision(proposal,True,reason,None,1,time.monotonic()-start,proposed_reason=reason)
        self.safe_streak = 0
        # A finite candidate family must not alternate left/right forever at a
        # forbidden boundary. Keep one turn direction during consecutive rule
        # interventions. Original SAFE commands still pass unchanged; distance
        # ordering is preserved within this explicitly restricted candidate set.
        if reason.startswith('operator_rule_') and self.escape_turn == 0:
            self.escape_turn = 1
        first_failure = step
        candidates = []
        for speed in sorted(set([proposal[0][0],0.1,0.2,0.3,0.4,0.0])):
            for turn in [-0.5,-0.3,0.0,0.3,0.5]:
                if reason.startswith('operator_rule_') and turn*self.escape_turn<0:
                    continue
                if speed == 0 and turn == 0:
                    continue  # An emergency zero is only used if search fails.
                distance = sum(((v-speed)/0.5)**2+((w-turn)/0.5)**2 for v,w in proposal)
                # Try full-horizon alternatives first, then shorter corrective
                # plans. Every returned step and its nominal braking suffix is
                # checked; a shorter plan expires after its last executed row.
                for length in sorted({len(proposal),min(3,len(proposal)),1},reverse=True):
                    candidate = tuple((speed,turn) for _ in range(length))
                    candidates.append((distance, -length, -turn, -speed, candidate))
        tested = 1
        # Preserve part of the finite search budget for one checked stationary
        # turn. Otherwise dense moving candidates can time out indefinitely
        # before this feasible boundary escape is ever considered.
        turn_sign=self.escape_turn or (1 if proposal[0][1]>=0 else -1)
        pivot=tuple((0.,turn_sign*.5) for _ in range(min(3,len(proposal))))
        for _,_,_,_,candidate in sorted(candidates):
            elapsed=time.monotonic()-start
            # Reserve room for the pivot using the measured per-check cost, so a
            # slow predictor (CPU load) still reaches the stationary-turn escape.
            if elapsed >= self.time_budget*.75 or elapsed+elapsed/tested >= self.time_budget*.75:
                if time.monotonic()-start < self.time_budget:
                    tested+=1
                    safe,_,_=self.check(pose,pivot,obstacles)
                    if safe:
                        return PlanDecision(pivot,False,'checked_pivot_after_'+reason,first_failure,
                            tested,time.monotonic()-start,proposed_reason=reason)
                return PlanDecision(((0.,0.),),False,'search_timeout_emergency_uncertified',first_failure,tested,time.monotonic()-start,proposed_reason=reason)
            tested += 1
            safe,_,_ = self.check(pose,candidate,obstacles)
            if safe:
                return PlanDecision(candidate,False,'alternative_after_'+reason,first_failure,tested,time.monotonic()-start,proposed_reason=reason)
        return PlanDecision(((0.,0.),),False,'no_candidate_emergency_uncertified',first_failure,tested,time.monotonic()-start,proposed_reason=reason)
