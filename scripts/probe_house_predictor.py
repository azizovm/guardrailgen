"""Offline numerical probe of the installed SafeLLMRA predictor, never an acceptance certificate."""
import json
from pathlib import Path
import time
import warnings
import numpy as np
from pyzonotope.NLReachability import NLReachability
from pyzonotope.Zonotope import Zonotope

root=Path(__file__).resolve().parents[1]
start=time.monotonic()
with warnings.catch_warnings():
    warnings.simplefilter('ignore',RuntimeWarning)
    predictor=NLReachability(str(Path.home()/'SafeLLMRA/Turtlebot/pyzonotope/example'))
initialization=time.monotonic()-start
R0=Zonotope(np.array([-3.,-2.5,1.,0.]).reshape(4,1),np.diag([.02,.02,.01,.01]))
start=time.monotonic()
sets,_=predictor.run_reachability(R0,np.array([[.3,0.]]*5))
report={'initialization_seconds':initialization,'prediction_seconds':time.monotonic()-start,
        'scope':'out-of-domain numerical diagnostic only','formal_guarantee':False,
        'sets':[{'center':np.asarray(s.center()).flatten().tolist(),
                 'interval_radius':np.abs(s.generators()).sum(axis=1).flatten().tolist()} for s in sets]}
(root/'data/house_predictor_probe.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
