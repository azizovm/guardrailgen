"""Record source/data identity and observed training ranges; never infer certification."""
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
from scipy.io import loadmat

root=Path(__file__).resolve().parents[1]
upstream=Path.home()/'SafeLLMRA'
report={'repository':str(upstream),'revision':subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip(),
        'datasets':{},'formal_guarantee':False,
        'interpretation':'Observed sample extrema are not a certified model domain. Turning and lower-speed coverage must be established before data-driven enforcement claims.'}
for filename,key in [('U_full_TB.mat','U_full'),('X_0T_TB.mat','X_0T'),('X_1T_TB.mat','X_1T')]:
    path=upstream/'Turtlebot/pyzonotope/example'/filename
    data=loadmat(path)[key]
    report['datasets'][filename]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'shape':list(data.shape),'minimum':np.min(data,axis=1).tolist(),'maximum':np.max(data,axis=1).tolist()}
inputs=report['datasets']['U_full_TB.mat']
report['illustrative_left_turn_0_3mps_0_5radps_in_observed_input_box']=all(
    lo<=v<=hi for v,lo,hi in zip([0.3,0.5],inputs['minimum'],inputs['maximum']))
output=root/'data/safellmra_house_data_audit.json'
output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
