"""Read-only diagnosis of the house ROS graph and sensor freshness."""
import json
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from gazebo_msgs.msg import ContactsState,ModelStates
from std_msgs.msg import String
from tf2_ros import Buffer,TransformListener
from rclpy.time import Time

rclpy.init(); node=Node('guardrailgen_health')
node.set_parameters([rclpy.parameter.Parameter('use_sim_time',value=True)])
counts={}; last={}; details={}
def observe(topic,msg):
    counts[topic]=counts.get(topic,0)+1; last[topic]=time.monotonic()
    if topic=='/odom':
        details['odom']={'frame':msg.header.frame_id,'stamp':msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,
            'speed':msg.twist.twist.linear.x,'turn':msg.twist.twist.angular.z}
    elif topic=='/scan':
        details['scan_frame']=msg.header.frame_id
    elif topic=='/guardrailgen/observation':
        details['observation']=json.loads(msg.data)
for topic,kind in [('/odom',Odometry),('/scan',LaserScan),('/gazebo/model_states',ModelStates),
                   ('/guardrailgen/observation',String)]+[(f'/guardrailgen/contacts_{link}',ContactsState) for link in
                    ['base_link','base_scan','wheel_left_link','wheel_right_link','caster_back_right_link','caster_back_left_link']]:
    node.create_subscription(kind,topic,lambda msg,t=topic:observe(t,msg),qos_profile_sensor_data)
buffer=Buffer(); listener=TransformListener(buffer,node)
deadline=time.monotonic()+5
while time.monotonic()<deadline:
    rclpy.spin_once(node,timeout_sec=.1)
details.update(counts=counts,ages={t:time.monotonic()-stamp for t,stamp in last.items()},
    simulation_time=node.get_clock().now().nanoseconds*1e-9,
    scan_transform=buffer.can_transform('odom',details.get('scan_frame','base_scan'),Time()),
    command_publishers=[n.node_name for n in node.get_publishers_info_by_topic('/cmd_vel')])
print(json.dumps(details,indent=2))
node.destroy_node(); rclpy.shutdown()
