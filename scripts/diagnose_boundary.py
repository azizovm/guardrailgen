"""Compare unmodified global-state extrapolation with an explicit body-frame hypothesis."""
import json
from pathlib import Path
import math
from guardrailgen.artifacts import read_json
from guardrailgen.schema import Scenario,Rule,compile_rule
from guardrailgen.simulation.safellmra import SafeLLMRAExperimentPredictor
from guardrailgen.simulation.plans import HousePlanFilter

root=Path(__file__).resolve().parents[1]
s=Scenario.from_dict(read_json(root/'config/turtlebot_house.json'))
r=Rule.from_dict({'schema_version':'1.0','id':'diagnostic','text':'Never enter the kitchen.',
    'expression':{'op':'not','arg':{'op':'inside','region':'kitchen'}}},s)
monitor=compile_rule(r,s)
pose=(-.489389,-1.297152,-.771268)
plan=((0.,.3),)*5
results={}
for body_frame in (False,True):
    predictor=SafeLLMRAExperimentPredictor(body_frame=body_frame)
    boxes=predictor.boxes(pose,plan,.02)
    check=HousePlanFilter(monitor,predictor=predictor,time_budget=1).check(pose,plan)
    results['body_frame' if body_frame else 'global_extrapolation']={
        'stationary_turn_check':check,'predicted_last_center':boxes[-1][0],
        'predicted_center_translation_m':math.dist(pose[:2],boxes[-1][0][:2]),
        'final_radius':boxes[-1][1], 'formal_guarantee':False}
path=root/'data/boundary_predictor_diagnostic.json'
path.write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
