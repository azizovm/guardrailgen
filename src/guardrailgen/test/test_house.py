"""House-specific plan, independent reference, and controller-isolation tests."""
import math
import pytest
from guardrailgen.schema import Scenario,Rule,compile_rule
from guardrailgen.simulation.reference import touches_region,nominal_rule_safe
from guardrailgen.simulation.plans import HousePlanFilter,validate_plan
from guardrailgen.simulation.controller import navigation_messages


def monitor(region=None):
    scenario=Scenario.from_dict({'schema_version':'1.0','frame':'odom','footprint_radius':0.25,
        'regions':{'kitchen':region or {'kind':'rectangle','xmin':1.,'xmax':2.,'ymin':-1.,'ymax':1.}},
        'supported_variables':['state.x','state.y','command.linear_speed','command.angular_speed','command.duration']})
    rule=Rule.from_dict({'schema_version':'1.0','id':'kitchen','text':'Never enter the kitchen.',
        'expression':{'op':'not','arg':{'op':'inside','region':'kitchen'}}},scenario)
    return compile_rule(rule,scenario)


def test_corner_clip_and_clearance_reference():
    r={'kind':'rectangle','xmin':0.,'xmax':2.,'ymin':0.,'ymax':2.}
    assert touches_region((-1.,-0.20),(1.,-0.20),r,0.25)  # 5 cm clip
    assert not touches_region((-1.,-0.45),(1.,-0.45),r,0.25)  # 20 cm clearance
    assert touches_region((-1.,1.),(3.,1.),r,0.25)  # endpoints alone would miss it
    assert not touches_region((-0.20,-0.20),(-0.20,-0.20),r,0.25)  # rounded corner


def test_original_safe_plan_is_preserved():
    f=HousePlanFilter(monitor())
    proposal=((0.3,0.0),)*5
    result=f.select((-3.,0.,0.),proposal)
    assert result.accepted_original and result.plan==proposal and result.tested==1
    assert not result.formal_guarantee


def test_future_overlap_rejects_plan_and_finds_alternative():
    f=HousePlanFilter(monitor(),time_budget=1)
    result=f.select((0.5,0.,0.),((0.4,0.),)*5)
    assert not result.accepted_original and result.rejected_step is not None
    assert result.plan!=((0.4,0.),)*5
    assert f.check((0.5,0.,0.),result.plan)[0]


def test_reference_nominal_safe_is_not_same_as_inflated_filter():
    m=monitor()
    pose=(0.65,0.,0.)
    plan=((0.1,0.),)*5
    assert nominal_rule_safe(pose,plan,m.scenario.regions['kitchen'],0.25)
    f=HousePlanFilter(m,position_uncertainty=0.1)
    assert not f.check(pose,plan)[0]  # explicit empirical false-restriction case


def test_obstacle_checked_independently_of_operator_rule():
    f=HousePlanFilter(monitor())
    assert f.check((-3.,0.,0.),((0.3,0.),)*5,obstacles=[(-2.6,0.)])[2]=='lidar_obstacle'


@pytest.mark.parametrize('plan',[[],[(0.6,0)],[(0.2,1)],[(math.nan,0)],[(-0.1,0)],[(0.1,0)]*6,[(0.1,)],[(True,0)]])
def test_invalid_plan_rejected(plan):
    with pytest.raises(ValueError):
        validate_plan(plan)


def test_navigation_prompt_does_not_reveal_operator_rule():
    messages=navigation_messages((0,0,0),(3,0),[3.5]*18,(0.1,0))
    text=str(messages).lower()
    assert 'kitchen' not in text and 'never enter' not in text
    assert '0.1 seconds' in text and 'lidar' in text


@pytest.mark.parametrize('pivot_safe',[True,False])
def test_search_reserves_a_checked_pivot_and_never_accepts_unsafe_one(monkeypatch,pivot_safe):
    from guardrailgen.simulation import plans
    elapsed=[0.]
    monkeypatch.setattr(plans.time,'monotonic',lambda:elapsed[0])
    checked=[]
    f=HousePlanFilter(monitor())
    def check(pose,plan,obstacles):
        elapsed[0]+=.012
        checked.append(plan)
        if all(v==0 and w==.5 for v,w in plan):
            return pivot_safe,None,'fixture_pivot'
        return False,1,'operator_rule_UNKNOWN'
    monkeypatch.setattr(f,'check',check)
    result=f.select((.7,0.,0.),((.3,0.),)*5)
    assert ((0.,.5),)*3 in checked
    assert result.plan==(((0.,.5),)*3 if pivot_safe else ((0.,0.),))
    assert not result.accepted_original and not result.formal_guarantee
