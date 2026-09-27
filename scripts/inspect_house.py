"""Read the installed SDF and data; do not modify the source or simulator."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

home = Path.home()
model = home / 'turtlebot3_ws/src/turtlebot3_simulations/turtlebot3_gazebo/models/turtlebot3_house/model.sdf'
root = ET.parse(model).getroot().find('model')
print(json.dumps({'models': [{'name': e.get('name'), 'pose': e.findtext('pose', '0 0 0 0 0 0')}
                             for e in root.findall('model')],
                  'walls': [{'name': e.get('name'), 'pose': e.findtext('pose')}
                            for e in root.findall('link')],
                  'mesh_collisions': len(root.findall('.//collision/geometry/mesh'))}, indent=2))
from scipy.io import loadmat
import numpy as np
for name, key in [('U_full_TB.mat', 'U_full'), ('X_0T_TB.mat', 'X_0T'), ('X_1T_TB.mat', 'X_1T')]:
    data = loadmat(home / 'SafeLLMRA/Turtlebot/pyzonotope/example' / name)[key]
    print(name, data.shape, 'min', np.min(data, axis=1), 'max', np.max(data, axis=1))
