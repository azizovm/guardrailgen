"""Generate local house/robot assets with visual markers and measurement plugins.

The installed TurtleBot files are read only. The marked kitchen is a test zone,
not a discovered semantic kitchen. All markers are visual-only (no collisions).
"""
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def marker(world, name, x,y,z, geometry, color):
    model = ET.SubElement(world,'model',name=name)
    ET.SubElement(model,'static').text='true'
    ET.SubElement(model,'pose').text=f'{x} {y} {z} 0 0 0'
    link=ET.SubElement(model,'link',name='visual_only')
    visual=ET.SubElement(link,'visual',name='marker')
    geom=ET.SubElement(visual,'geometry')
    geom.append(ET.fromstring(geometry))
    material=ET.SubElement(visual,'material')
    ET.SubElement(material,'ambient').text=color
    ET.SubElement(material,'diffuse').text=color
    ET.SubElement(visual,'cast_shadows').text='false'


def main():
    from ament_index_python.packages import get_package_share_directory
    share=Path(get_package_share_directory('turtlebot3_gazebo'))
    cfg=json.loads((ROOT/'config/house_experiment.json').read_text())
    scenario=json.loads((ROOT/cfg['scenario']).read_text())
    out=ROOT/'generated/house'
    out.mkdir(parents=True,exist_ok=True)
    original=share/'worlds/turtlebot3_house.world'
    tree=ET.parse(original)
    world=tree.getroot().find('world')
    world.find('gui/camera/pose').text='0 -7 14 0 1.05 1.5708'
    plugin=ET.SubElement(world,'plugin',name='guardrailgen_ground_truth',filename='libgazebo_ros_state.so')
    ros=ET.SubElement(plugin,'ros')
    ET.SubElement(ros,'namespace').text='/gazebo'
    ET.SubElement(plugin,'update_rate').text='30'
    r=scenario['regions']['kitchen']
    marker(world,'kitchen_TEST_ZONE',(r['xmin']+r['xmax'])/2,(r['ymin']+r['ymax'])/2,0.009,
           f"<box><size>{r['xmax']-r['xmin']} {r['ymax']-r['ymin']} 0.01</size></box>",'1 0.55 0 0.55')
    gx,gy=cfg['goal']
    marker(world,'goal_red_circle',gx,gy,0.012,'<cylinder><radius>0.3</radius><length>0.02</length></cylinder>','1 0 0 1')
    tree.write(out/'house.world',encoding='utf-8',xml_declaration=True)
    robot_file=share/'models/turtlebot3_waffle_pi/model.sdf'
    robot=ET.parse(robot_file)
    contact_topics=[]
    for link in robot.getroot().findall('model/link'):
        collisions=link.findall('collision')
        if not collisions:
            continue
        lname=link.get('name')
        sensor=ET.SubElement(link,'sensor',name='guardrailgen_contact_'+lname,type='contact')
        ET.SubElement(sensor,'always_on').text='true'
        ET.SubElement(sensor,'update_rate').text='50'
        contact=ET.SubElement(sensor,'contact')
        for collision in collisions:
            ET.SubElement(contact,'collision').text=collision.get('name')
        p=ET.SubElement(sensor,'plugin',name='contact_'+lname,filename='libgazebo_ros_bumper.so')
        ros=ET.SubElement(p,'ros')
        ET.SubElement(ros,'namespace').text='/guardrailgen'
        ET.SubElement(ros,'remapping').text='bumper_states:=contacts_'+lname
        ET.SubElement(p,'frame_name').text=lname
        contact_topics.append('/guardrailgen/contacts_'+lname)
    # ROS Humble spawn_entity passes a Unicode string to lxml; an explicit
    # encoding declaration is rejected by that code path.
    robot.write(out/'robot.sdf',encoding='utf-8',xml_declaration=False)
    audit={'world_source':str(original),'world_source_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
           'robot_source':str(robot_file),'robot_source_sha256':hashlib.sha256(robot_file.read_bytes()).hexdigest(),
           'region_status':cfg['region_status'],'contact_topics':contact_topics,
           'ground_truth_topic':'/gazebo/model_states','odometry_world_alignment':'must be checked during stationary activation',
           'footprint_radius':scenario['footprint_radius'],'step_seconds':cfg['step_seconds'],
           'formal_guarantee':False}
    (out/'scene_audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    (out/'experiment.json').write_text(json.dumps(cfg,indent=2)+'\n')
    print(json.dumps(audit,indent=2))


if __name__=='__main__':
    main()
