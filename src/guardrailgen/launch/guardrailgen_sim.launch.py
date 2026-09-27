"""Launch only the development gate, not a complete simulation.

Explicitly pass operating_mode:=heuristic to forward eligible commands. Supply
use_sim_time:=true only with a simulation clock. The upstream plan-to-Twist
bridge and sole-publisher integration remain separate work.
"""
import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    rules = os.path.join(
        get_package_share_directory('guardrailgen'), 'rules', 'example_rules.yaml')
    return LaunchDescription([
        DeclareLaunchArgument('operating_mode', default_value='disabled',
            choices=['disabled', 'heuristic'],
            description='Heuristic is an uncertified development opt-in.'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('rules_file', default_value=rules),
        DeclareLaunchArgument('artifact_file', default_value=''),
        DeclareLaunchArgument('odom_frame', default_value='odom'),
        DeclareLaunchArgument('proposed_cmd_topic', default_value='/llm_cmd_vel'),
        DeclareLaunchArgument('safe_cmd_topic', default_value='/cmd_vel'),
        DeclareLaunchArgument('odom_topic', default_value='/odom'),
        Node(package='guardrailgen', executable='monitor_node',
             name='guardrailgen_monitor', output='screen', parameters=[{
                 'rules_file': ParameterValue(LaunchConfiguration('rules_file'), value_type=str),
                 'artifact_file': ParameterValue(LaunchConfiguration('artifact_file'), value_type=str),
                 'operating_mode': ParameterValue(LaunchConfiguration('operating_mode'), value_type=str),
                 'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool),
                 'odom_frame': ParameterValue(LaunchConfiguration('odom_frame'), value_type=str),
                 'proposed_cmd_topic': ParameterValue(LaunchConfiguration('proposed_cmd_topic'), value_type=str),
                 'safe_cmd_topic': ParameterValue(LaunchConfiguration('safe_cmd_topic'), value_type=str),
                 'odom_topic': ParameterValue(LaunchConfiguration('odom_topic'), value_type=str),
                 'control_hz': 20.0, 'reach_horizon': 6,
             }]),
    ])
