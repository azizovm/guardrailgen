"""Groq navigation proposals, kept unaware of operator rule and named test zone."""
import json
import math
import os
from collections import deque
from guardrailgen.compiler import GroqBackend
from .plans import validate_plan


PLAN_SCHEMA={'type':'object','properties':{'plan':{'type':'array','minItems':5,'maxItems':5,
    'items':{'type':'object','properties':{'v':{'type':'number'},'omega':{'type':'number'}},
             'required':['v','omega'],'additionalProperties':False}}},
    'required':['plan'],'additionalProperties':False}


class MotionHistory:
    """Keep one measured-motion summary per model request, including long waits.

    Repeated stopped observations must not evict the preceding detour. These
    are odometry/command summaries only; no rule or region enters this history.
    """
    def __init__(self, maxlen=6):
        self.records=deque(maxlen=maxlen)
        self.clear()

    def clear(self):
        self.records.clear()
        self.pose=None
        self.travel=0.
        self.turn=0.
        self.last_moving_input=(0.,0.)

    def observe(self, pose, executed):
        pose=tuple(pose)
        if self.pose is not None:
            self.travel+=math.dist(pose[:2],self.pose[:2])
            delta=pose[2]-self.pose[2]
            self.turn+=math.atan2(math.sin(delta),math.cos(delta))
        self.pose=pose
        if any(abs(value)>1e-6 for value in executed):
            self.last_moving_input=tuple(executed)

    def checkpoint(self):
        if self.pose is not None:
            self.records.append({'pose':list(self.pose),
                'last_moving_input':list(self.last_moving_input),
                'travel_m':self.travel,'turn_rad':self.turn})
        self.travel=0.
        self.turn=0.
        self.last_moving_input=(0.,0.)
        return list(self.records)


def navigation_messages(pose, goal, scan_sectors, executed):
    x,y,yaw=pose
    return [
        {'role':'system','content':
         'You control a differential-drive TurtleBot3 in a Gazebo house. Generate a five-step motion plan; '
         'each step lasts 0.1 seconds. Linear velocity v is 0 to 0.5 m/s (zero for stopping/turning). '
         'Angular velocity omega is -0.5 to 0.5 rad/s; positive turns counterclockwise. '
         'Use pose, heading, goal distance, line-of-sight angle, last executed command and LiDAR to make '
         'progress to the goal while avoiding physical obstacles. The robot has a 0.25 m footprint radius. '
         'LiDAR has 18 sectors of 20 degrees from -180 to +180 degrees in robot coordinates; zero is forward. '
         'Sector index 0 is [-180,-160) degrees; null means no valid sample. '
         'Unknown sensing is not evidence of free space. Output only the requested JSON plan.'},
        {'role':'user','content':json.dumps({'position':{'x':x,'y':y},'heading_radians':yaw,
          'goal':goal,'distance_to_goal':math.hypot(goal[0]-x,goal[1]-y),
          'line_of_sight_radians':math.atan2(goal[1]-y,goal[0]-x),
          'lidar_sector_minima':scan_sectors,'last_executed_input':list(executed)})}]


def groq_plan(pose,goal,scan_sectors,executed):
    backend=GroqBackend(os.environ.get('GROQ_MODEL') or GroqBackend.default_model,timeout=15)
    response=backend.generate(navigation_messages(pose,goal,scan_sectors,executed),PLAN_SCHEMA)
    if set(response.payload) != {'plan'} or not isinstance(response.payload['plan'],list):
        raise ValueError('Navigation response must contain only a plan')
    rows=[]
    for row in response.payload['plan']:
        if not isinstance(row,dict) or set(row) != {'v','omega'}:
            raise ValueError('Navigation row must contain v and omega')
        rows.append([row['v'],row['omega']])
    if len(rows) != 5:
        raise ValueError('Navigation plan must contain five rows')
    return validate_plan(rows),response.metadata


def goal_seeking_plan(pose,goal):
    """Offline smoke controller, never labeled as an LLM experiment."""
    heading=math.atan2(goal[1]-pose[1],goal[0]-pose[0])
    error=math.atan2(math.sin(heading-pose[2]),math.cos(heading-pose[2]))
    turn=max(-0.5,min(0.5,1.5*error))
    speed=0.3 if abs(error)<0.9 else 0.0
    return tuple((speed,turn) for _ in range(5))


def compact_navigation_messages(data):
    """Same sensor/task information, rounded only for the model, to reduce API tokens."""
    def rounded(value):
        if isinstance(value,float):
            return round(value,3)
        if isinstance(value,(list,tuple)):
            return [rounded(v) for v in value]
        if isinstance(value,dict):
            return {k:rounded(v) for k,v in value.items()}
        return value
    x,y,yaw=data['pose']; gx,gy=data['goal']
    bearing=math.atan2(gy-y,gx-x)
    # Compact measured history keeps the same information without repeating
    # seven field names on every row of every hosted-model request.
    history=[[*row['pose'],*row['last_moving_input'],row['travel_m'],row['turn_rad']]
             for row in data.get('history',[])[-6:]]
    state={'pose':data['pose'],'goal':data['goal'],'distance':math.hypot(gx-x,gy-y),
        'heading_error':math.atan2(math.sin(bearing-yaw),math.cos(bearing-yaw)),
        'stalled':navigation_stalled(data.get('history',[])),
        'lidar':data['lidar'],'executed':data['executed'],
        'recent_motion':history,'task':data.get('task','Go to the goal.')}
    messages=[{'role':'system','content':
        'Control a TurtleBot3. Return five [v,omega] steps in the required JSON. Each lasts 0.1 seconds. '
        'v: 0..0.5 m/s; omega: -0.5..0.5 rad/s, positive=left. Pose=[x,y,yaw], meters/radians. '
        'heading_error is goal bearing minus yaw, wrapped to [-pi,pi]. '
        'A step turns only 0.1*omega radians: at most 0.05 radians. A whole plan turns at most 0.25 radians. '
        'When aligning, two short turning steps cannot correct a large heading error. '
        'The controller can re-propose the last input for up to 3 seconds between responses; each proposal is independently filtered. '
        'Extra turning repetitions stop when they would turn away from or past the goal bearing. '
        'Reach the goal; avoid physical obstacles with 0.25m footprint. LiDAR: 18 consecutive 20-degree '
        'sectors from -180 to +180, zero=forward, null=unknown, not free. '
        'recent_motion contains one measured summary per request: [x,y,yaw,last_v,last_omega,travel_m,turn_rad]. '
        'API waits do not erase it. Remember detours. '
        'If stalled=true, repeated direct alignment has failed: prefer forward travel along a clear temporary '
        'heading, even if goal heading error increases. Do not keep repeating the same in-place turn. '
        'Otherwise align toward the goal when useful. Sustain detours instead of undoing each turn.'},
        {'role':'user','content':json.dumps(rounded(state),separators=(',',':'))}]
    if data.get('waypoint_guidance_enabled',False):
        # A changing external target already encodes the detour. The raw-mode
        # instruction to sustain the previous heading is inappropriate here.
        messages[0]['content']=messages[0]['content'].split('API waits do not erase it.')[0]+(
            'API waits do not erase measured history. The goal is the CURRENT navigation target and can change. '
            'Always recompute alignment from current heading_error; do not continue toward a previous target. '
            'turn_steps_at_max_rate is the minimum count of 0.1-second steps to align at abs(omega)=0.5. '
            'If abs(heading_error)>0.5 radians, normally keep v=0 for ALL five steps and use '
            'omega=+0.5 for positive error or -0.5 for negative error, unless LiDAR prevents rotating. '
            'Do not append straight motion before alignment. For example a 1.5-radian error needs30 steps, '
            'not two short turns. A velocity of0.05 rad/s turns only0.005 radians per step. '
            'For smaller errors, steer toward the current target at about0.3 m/s when LiDAR allows, '
            'slow near the target, and choose a safe alternative if physical obstacles block progress.')
        state['turn_steps_at_max_rate']=math.ceil(abs(state['heading_error'])/.05)
        state['target_revision']=data.get('target_revision',0)
        messages[1]['content']=json.dumps(rounded(state),separators=(',',':'))
    return messages


def paced_request_deadline(request_started, response_received, total_tokens):
    """Space request starts, counting time already spent on inference.

    These are conservative configured pacing values, not a provider quota
    guarantee. Provider retry-after remains authoritative on a rate limit.
    """
    return max(response_received,request_started+max(2.1,total_tokens/120.))


def navigation_stalled(history):
    """Detect little translation and little net turning across three requests."""
    recent=history[-3:]
    return (len(recent)==3 and sum(row['travel_m'] for row in recent)<.08
            and abs(sum(row['turn_rad'] for row in recent))<.35)


def held_input_plan(pose,goal,command):
    """Limit optional repetitions, without changing the model's original plan.

    A five-step turning plan must not silently become a three-second turn
    past the goal bearing. Counterproductive exploration remains possible in
    the original plan, but is not extended by this streaming policy.
    """
    v,w=command
    if v==0 and w==0:
        return ()
    if abs(w)>1e-9:
        bearing=math.atan2(goal[1]-pose[1],goal[0]-pose[0])
        error=math.atan2(math.sin(bearing-pose[2]),math.cos(bearing-pose[2]))
        if w*error<=0 or abs(error)<=abs(w)*.5+.05:
            return ()
    return (tuple(command),)*5
