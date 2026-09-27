"""Reset only the dedicated house simulation, with no active command publisher."""
import rclpy
from std_srvs.srv import Empty


def main():
    rclpy.init()
    node=rclpy.create_node('guardrailgen_house_reset')
    try:
        import time
        until=time.monotonic()+1
        while time.monotonic()<until:
            rclpy.spin_once(node,timeout_sec=0.1)
        if node.count_publishers('/cmd_vel'):
            raise RuntimeError('Stop the episode/controller before resetting its world')
        client=node.create_client(Empty,'/reset_world')
        if not client.wait_for_service(timeout_sec=5):
            raise RuntimeError('House reset service unavailable')
        future=client.call_async(Empty.Request())
        rclpy.spin_until_future_complete(node,future,timeout_sec=5)
        if not future.done() or future.exception():
            raise RuntimeError('World reset failed')
        print('Dedicated house reset to configured spawn; no controller started.')
    finally:
        node.destroy_node(); rclpy.shutdown()


if __name__=='__main__':
    main()
