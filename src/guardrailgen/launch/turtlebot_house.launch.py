"""Visible TurtleBot house with visual-only rule/goal markers and independent sensors."""
import json
import os
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def setup(context):
    assets=Path(LaunchConfiguration('assets_dir').perform(context)).resolve()
    cfg=json.loads((assets/'experiment.json').read_text())
    gz=Path(get_package_share_directory('gazebo_ros'))/'launch'
    tb=Path(get_package_share_directory('turtlebot3_gazebo'))/'launch'
    x,y,yaw=cfg['start']
    return [
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(gz/'gzserver.launch.py')),
            launch_arguments={'world':str(assets/'house.world')}.items()),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(gz/'gzclient.launch.py'))),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(tb/'robot_state_publisher.launch.py')),
            launch_arguments={'use_sim_time':'true'}.items()),
        Node(package='gazebo_ros',executable='spawn_entity.py',output='screen',
             arguments=['-entity',cfg['robot_entity'],'-file',str(assets/'robot.sdf'),
                        '-x',str(x),'-y',str(y),'-z','0.01','-Y',str(yaw),
                        '-timeout','120']),
    ]


def generate_launch_description():
    return LaunchDescription([DeclareLaunchArgument('assets_dir'),OpaqueFunction(function=setup)])
