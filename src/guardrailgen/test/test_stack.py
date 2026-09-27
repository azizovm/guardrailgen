"""Numerical-adapter enforcement and the installed-SDK provider boundary."""
import sys
from array import array
from types import SimpleNamespace

import pytest

from guardrailgen.compiler.backend import BackendError
from guardrailgen.simulation.groq_compat import GroqCompatibilityBackend
from guardrailgen.simulation.plans import HousePlanFilter,decode_flat_plan,decode_plan_label,CheckedPlanQueue,PlanDecision
from test_house import monitor
from guardrailgen.simulation.controller import MotionHistory, compact_navigation_messages, paced_request_deadline, navigation_stalled, held_input_plan


def test_sdk_remains_strict_and_uses_only_groq(monkeypatch):
    calls=[]
    def create(**args):
        calls.append(args)
        return SimpleNamespace(to_dict_recursive=lambda: {'choices':[{
            'finish_reason':'stop','message':{'content':'{"answer": 1}'}}]})
    monkeypatch.setitem(sys.modules,'openai',SimpleNamespace(__version__='0.28.0',
        ChatCompletion=SimpleNamespace(create=create)))
    monkeypatch.setenv('GROQ_API_KEY','groq-fixture')
    monkeypatch.setenv('OPENAI_API_KEY','must-not-be-used')
    result=GroqCompatibilityBackend().generate([{'role':'user','content':'fixture'}],{'type':'object'})
    assert result.payload=={'answer':1}
    assert len(calls)==1
    assert calls[0]['api_base']=='https://api.groq.com/openai/v1'
    assert calls[0]['api_key']=='groq-fixture'
    assert calls[0]['response_format']['json_schema']['strict'] is True
    assert calls[0]['model']=='openai/gpt-oss-120b'


def test_ros_array_storage_decodes_in_row_order():
    assert decode_flat_plan(array('d',[.3,.5,.2,-.1]))==((.3,.5),(.2,-.1))


def test_plan_label_preserves_target_revision_and_legacy_scope():
    assert decode_plan_label('12:3')==(12,3)
    assert decode_plan_label('12')==(12,0)


@pytest.mark.parametrize('label',['-1:0','1:-2','1:2:3','1:','nan',''])
def test_invalid_target_revision_metadata_is_rejected(label):
    with pytest.raises(ValueError):
        decode_plan_label(label)


@pytest.mark.parametrize('data', [array('d',[.3,.2,.1]),array('d',[float('nan'),0.])])
def test_malformed_ros_array_is_rejected(data):
    with pytest.raises(ValueError):
        decode_flat_plan(data)


def test_sdk_rejects_an_unreviewed_version(monkeypatch):
    monkeypatch.setitem(sys.modules,'openai',SimpleNamespace(__version__='1.0.0'))
    monkeypatch.setenv('GROQ_API_KEY','fixture')
    with pytest.raises(BackendError,match='0.28.0'):
        GroqCompatibilityBackend().generate([], {})


def test_sdk_rate_limit_carries_only_provider_retry_timing(monkeypatch):
    class ProviderError(Exception):
        http_status=429
        headers={'retry-after':'12.5','authorization':'secret'}
    class Timeout(ProviderError):
        pass
    def create(**kwargs):
        raise ProviderError('secret provider body')
    monkeypatch.setitem(sys.modules,'openai',SimpleNamespace(__version__='0.28.0',
        ChatCompletion=SimpleNamespace(create=create),error=SimpleNamespace(Timeout=Timeout,OpenAIError=ProviderError)))
    monkeypatch.setenv('GROQ_API_KEY','fixture')
    with pytest.raises(BackendError) as caught:
        GroqCompatibilityBackend().generate([], {})
    assert caught.value.status=='rate_limited'
    assert caught.value.retry_after_seconds==12.5
    assert 'secret' not in str(caught.value)


def test_numerical_final_step_can_reject_a_nominally_safe_plan():
    class Predictor:
        def boxes(self,pose,plan,uncertainty):
            return [([-3.,0.,1.,0.],[0.,0.,0.,0.]) for _ in plan]+[([1.5,0.,1.,0.],[.02,.02,0.,0.])]
    plan=((.1,0.),)*5
    assert HousePlanFilter(monitor()).check((-3.,0.,0.),plan)[0]
    verdict,step,reason=HousePlanFilter(monitor(),predictor=Predictor()).check((-3.,0.,0.),plan)
    assert not verdict and step>=len(plan) and 'safellmra' in reason


def test_numerical_failure_is_not_silently_replaced_by_nominal_success():
    class Predictor:
        def boxes(self,*args):
            raise ValueError('invalid predictor output')
    assert HousePlanFilter(monitor(),predictor=Predictor()).check((-3.,0.,0.),((.1,0.),)*5)[2]=='safellmra_prediction_failed'


def test_rule_escape_does_not_oscillate_or_override_safe_originals():
    f=HousePlanFilter(monitor(),time_budget=1)
    first=f.select((.70,0.,0.),((.3,-.5),)*5)
    assert not first.accepted_original and first.plan[0][1]>=0
    safe=((0.,-.3),)*5
    result=f.select((-3.,0.,0.),safe)
    assert result.accepted_original and result.plan==safe


def test_exhausted_search_retains_original_rule_rejection_for_metrics():
    # Starting inside the forbidden region leaves no feasible candidate.
    f=HousePlanFilter(monitor(),time_budget=1)
    result=f.select((1.5,0.,0.),((.3,0.),)*5)
    assert result.reason=='no_candidate_emergency_uncertified'
    assert result.proposed_reason.startswith('operator_rule_')


def test_waiting_for_model_does_not_erase_the_executed_detour():
    history=MotionHistory()
    history.observe((0.,0.,0.),(0.,0.))
    history.checkpoint()
    history.observe((.3,0.,.4),(.3,.4))
    for _ in range(200):
        history.observe((.3,0.,.4),(0.,0.))
    last=history.checkpoint()[-1]
    assert last['last_moving_input']==[.3,.4]
    assert last['travel_m']==pytest.approx(.3)
    assert last['turn_rad']==pytest.approx(.4)
    # A subsequent idle interval is represented honestly, without reusing motion.
    assert history.checkpoint()[-1]['last_moving_input']==[0.,0.]


def test_motion_history_unwraps_heading_and_resets_between_episodes():
    import math
    history=MotionHistory()
    history.observe((0.,0.,math.pi-.05),(0.,.2))
    history.observe((0.,0.,-math.pi+.05),(0.,.2))
    assert history.checkpoint()[-1]['turn_rad']==pytest.approx(.1)
    for step in range(10):
        history.observe((step,0.,0.),(.3,0.))
        history.checkpoint()
    assert len(history.records)==6
    history.clear()
    assert history.checkpoint()==[]


def test_compact_prompt_does_not_include_rule_or_unrelated_request_fields():
    import json
    data={'pose':[0.,0.,0.],'goal':[3.,0.],'lidar':[None]*18,'executed':[0.,0.],
          'history':[],'rule':'Never enter the kitchen.','region':{'kitchen':[1,2,3,4]}}
    messages=compact_navigation_messages(data)
    serialized=json.dumps(messages)
    assert 'kitchen' not in serialized and 'Never enter' not in serialized
    assert 'one measured summary per request' in messages[0]['content']


def test_navigation_heading_error_wraps_and_preserves_measured_history():
    import json,math
    data={'pose':[0.,0.,math.pi-.1],'goal':[-1.,-.01],'lidar':[None]*18,'executed':[0.,0.],
          'history':[{'pose':[0.,0.,math.pi-.1],'last_moving_input':[.3,.2],'travel_m':.6,'turn_rad':.4}]}
    messages=compact_navigation_messages(data)
    state=json.loads(messages[1]['content'])
    assert state['heading_error']==pytest.approx(.11)
    assert state['recent_motion']==[[0.,0.,3.042,.3,.2,.6,.4]]
    assert 'at most 0.05 radians' in messages[0]['content']


@pytest.mark.parametrize('goal,expected_error', [([0.,3.],1.571),([0.,-3.],-1.571)])
def test_guided_prompt_uses_current_target_turn_duration_without_rule_leakage(goal,expected_error):
    import json
    data={'pose':[0.,0.,0.],'goal':goal,'lidar':[3.5]*18,'executed':[0.,0.],
          'waypoint_guidance_enabled':True,'target_revision':2,'rule':'Never enter the kitchen.'}
    messages=compact_navigation_messages(data);state=json.loads(messages[1]['content'])
    assert state['heading_error']==expected_error
    assert state['turn_steps_at_max_rate']==32 and state['target_revision']==2
    assert 'Sustain detours' not in messages[0]['content']
    assert 'ALL five steps' in messages[0]['content']
    assert 'kitchen' not in json.dumps(messages)


def test_pacing_counts_inference_time_without_bursting_after_a_fast_response():
    assert paced_request_deadline(100.,102.,960)==108.
    assert paced_request_deadline(100.,109.,960)==109.
    assert paced_request_deadline(100.,100.1,0)==102.1


def test_rejected_right_turn_cannot_resume_after_checked_left_correction():
    queue=CheckedPlanQueue()
    queue.replace(((0.,-.5),)*5,'controller',10.)
    proposal,source=queue.take(10.)
    assert proposal==((0.,-.5),)*5 and source=='controller'
    queue.apply(PlanDecision(((.1,.3),)*3,False,'alternative',1,2,.01),10.)
    remaining,source=queue.take(10.1)
    assert remaining==((.1,.3),)*2 and source=='filter_correction'
    queue.apply(PlanDecision(remaining,True,'safe',None,1,.01),10.1)
    assert queue.take(10.2)[0]==((.1,.3),)
    assert not queue


def test_emergency_and_expiry_discard_the_old_plan_completely():
    queue=CheckedPlanQueue()
    queue.replace(((.5,0.),)*5,'controller',10.)
    queue.take(10.)
    queue.apply(PlanDecision(((0.,0.),),False,'emergency',1,2,.01),10.)
    assert not queue
    queue.replace(((.1,.3),)*3,'filter_correction',20.)
    assert queue.take(22.1)[0]==() and not queue


def test_stall_feedback_distinguishes_oscillation_from_useful_turning():
    assert navigation_stalled([{'travel_m':.001,'turn_rad':t} for t in [.2,-.2,.1]])
    assert not navigation_stalled([{'travel_m':0.,'turn_rad':.5}]*3)
    assert not navigation_stalled([{'travel_m':.1,'turn_rad':0.}]*3)
    assert not navigation_stalled([])


def test_optional_turn_repetitions_end_before_overshoot_or_direction_reversal():
    # At zero yaw a left turn toward a northward goal is useful.
    assert held_input_plan((0.,0.,0.),(0.,3.),(0.,.5))==((0.,.5),)*5
    # Near north, another 0.25-radian turn would overshoot; no extra plan.
    assert held_input_plan((0.,0.,1.4),(0.,3.),(0.,.5))==()
    assert held_input_plan((0.,0.,1.8),(0.,3.),(0.,.5))==()
    assert held_input_plan((0.,0.,0.),(0.,3.),(.3,0.))==((.3,0.),)*5
    assert held_input_plan((0.,0.,0.),(0.,3.),(0.,0.))==()


def test_installed_body_frame_predictor_preserves_pose_and_stationary_turn():
    import math
    from pathlib import Path
    np=pytest.importorskip('numpy')
    pytest.importorskip('pyzonotope')
    data=Path.home()/'SafeLLMRA/Turtlebot/pyzonotope/example'
    if not data.is_dir():
        pytest.skip('Installed SafeLLMRA identification dataset required')
    from guardrailgen.simulation.safellmra import SafeLLMRAExperimentPredictor
    predictor=SafeLLMRAExperimentPredictor(data,body_frame=True)
    pose=(-.489389,-1.297152,-.771268)
    boxes=predictor.boxes(pose,((0.,.3),)*5,.02)
    assert np.allclose(boxes[0][0],[*pose[:2],math.cos(pose[2]),math.sin(pose[2])])
    assert np.allclose(boxes[0][1][:2],[.02,.02])
    # Regression: global-state extrapolation predicted 17 cm translation for
    # this stationary turn. Localizing the same data reduces it below 2.5 cm.
    assert math.dist(pose[:2],boxes[-1][0][:2])<.025
