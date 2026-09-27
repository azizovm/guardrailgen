"""Teleport the house robot to a start pose (RQ3). Refuses while anything publishes /cmd_vel.

    python3 scripts/set_start.py X Y YAW [ENTITY]
Relies on the world's gazebo_ros_state plugin (namespace /gazebo).
"""
import math
import sys
import time

import rclpy
from gazebo_msgs.srv import SetEntityState


def main():
    x, y, yaw = map(float, sys.argv[1:4])
    entity = sys.argv[4] if len(sys.argv) > 4 else "waffle_pi"
    rclpy.init()
    node = rclpy.create_node("guardrailgen_rq3_start")
    try:
        until = time.monotonic() + 1
        while time.monotonic() < until:
            rclpy.spin_once(node, timeout_sec=0.1)
        if node.count_publishers("/cmd_vel"):
            raise RuntimeError("Stop the episode/controller before moving the robot")
        client = node.create_client(SetEntityState, "/gazebo/set_entity_state")
        if not client.wait_for_service(timeout_sec=5):
            raise RuntimeError("/gazebo/set_entity_state unavailable")
        request = SetEntityState.Request()
        state = request.state
        state.name = entity
        state.reference_frame = "world"
        state.pose.position.x, state.pose.position.y, state.pose.position.z = x, y, 0.01
        state.pose.orientation.z, state.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        future = client.call_async(request)
        rclpy.spin_until_future_complete(node, future, timeout_sec=5)
        if not future.done() or future.exception() or not future.result().success:
            raise RuntimeError("Teleport failed")
        print(f"Robot placed at ({x:.2f}, {y:.2f}, yaw {yaw:.2f}); no controller started.")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
