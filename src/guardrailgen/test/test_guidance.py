"""Check the optional route generator against the independent footprint oracle."""
import pytest
from guardrailgen.simulation.guidance import RectangleGuidance
from guardrailgen.simulation.reference import touches_region


REGION={'kind':'rectangle','xmin':-.8,'xmax':.8,'ymin':-3.4,'ymax':-1.6}


def test_route_around_house_zone_preserves_footprint_clearance():
    start=(-3.,-2.5); goal=(3.,-2.5)
    guidance=RectangleGuidance(start,goal,REGION,.25)
    assert len(guidance.targets)==3
    assert guidance.targets[0][1]>REGION['ymax']
    previous=start
    for point in guidance.targets:
        assert not touches_region(previous,point,REGION,.25)
        previous=point
    assert guidance.targets[-1]==goal


def test_clear_goal_does_not_gain_unnecessary_waypoints():
    guidance=RectangleGuidance((-3.,0.),(3.,0.),REGION,.25)
    assert guidance.targets==[(3.,0.)]


def test_waypoint_pruning_cannot_cut_the_forbidden_corner():
    guidance=RectangleGuidance((-3.,-2.5),(3.,-2.5),REGION,.25)
    first=guidance.target((-1.3,-2.))
    assert first[0]<REGION['xmin']
    second=guidance.target((-1.4,-1.1))
    assert second[0]>REGION['xmax']
    assert not touches_region((-1.4,-1.1),second,REGION,.25)
    assert guidance.target((1.5,-1.1))==(3.,-2.5)


@pytest.mark.parametrize('start,goal', [((0.,-2.5),(3.,-2.5)),((-3.,-2.5),(0.,-2.5))])
def test_inside_region_does_not_produce_a_fake_route(start,goal):
    with pytest.raises(ValueError,match='No waypoint route'):
        RectangleGuidance(start,goal,REGION,.25)
