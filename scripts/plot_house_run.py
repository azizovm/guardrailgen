"""Plot recorded ground truth; never substitute a planned path for executed motion."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle,Circle

parser=argparse.ArgumentParser()
parser.add_argument('run',type=Path)
args=parser.parse_args()
run=args.run.resolve()
cfg=json.loads((run/'run_configuration.json').read_text())
summary=json.loads((run/'summary.json').read_text())
controller_label=summary['controller']
if controller_label=='external':
    events=[json.loads(line) for line in (run/'events.jsonl').read_text().splitlines()]
    offline=any(event.get('detail',{}).get('kind')=='offline_request' for event in events)
    controller_label='Offline / separate ROS processes' if offline else 'External ROS controller'
if summary.get('navigation_mode')=='waypoint_guidance':
    controller_label+=' + waypoint guidance'
artifact_path=cfg['rule_artifact']
if artifact_path=='None':
    artifact_path=json.loads((run/'active_rule.json').read_text())['artifact']
artifact=json.loads(Path(artifact_path).read_text())
region=artifact['scenario']['regions']['kitchen']
radius=artifact['scenario']['footprint_radius']
points=[json.loads(line) for line in (run/'trajectory.jsonl').read_text().splitlines()]
fig,ax=plt.subplots(figsize=(9,5.2),layout='constrained')
ax.add_patch(Rectangle((region['xmin'],region['ymin']),region['xmax']-region['xmin'],region['ymax']-region['ymin'],
    facecolor='#f6ad55',edgecolor='#c05621',alpha=.6,label='Kitchen test zone'))
ax.plot([p['world_x'] for p in points],[p['world_y'] for p in points],color='#126782',linewidth=2,label='Executed ground-truth path')
start=points[0]; end=points[-1]; goal=cfg['experiment']['goal']
ax.scatter(start['world_x'],start['world_y'],marker='s',color='#126782',label='Start',zorder=5)
ax.add_patch(Circle(goal,cfg['experiment']['goal_tolerance'],color='#c53030',alpha=.5,label='Goal tolerance'))
ax.add_patch(Circle((end['world_x'],end['world_y']),radius,fill=False,color='#126782',linewidth=1.5,label='Final robot footprint'))
ax.set_aspect('equal'); ax.grid(alpha=.2)
ax.set_xlabel('World / aligned odom x (m)'); ax.set_ylabel('World / aligned odom y (m)')
ax.set_title(('Goal reached' if summary['goal_reached'] else 'Goal not reached')+' | '+controller_label+
    '\n'+str(summary['reference_violation_samples'])+' sampled violations; '+str(summary['collision_contact_events'])+' contacts; experimental predictor')
ax.legend(loc='upper left',bbox_to_anchor=(1,1),frameon=False)
ax.margins(.12)
fig.savefig(run/'trajectory.png',dpi=160)
print(run/'trajectory.png')
