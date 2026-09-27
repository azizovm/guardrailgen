#!/usr/bin/env bash
# Dedicated Gazebo Classic / ROS domain; no controller runs from this script.
set -eo pipefail
source /opt/ros/humble/setup.bash
if [[ -f "$HOME/turtlebot3_ws/install/setup.bash" ]]; then
    source "$HOME/turtlebot3_ws/install/setup.bash"
fi
export TURTLEBOT3_MODEL=waffle_pi
export ROS_DOMAIN_ID="${GUARDRAILGEN_HOUSE_DOMAIN:-218}"
export ROS_LOCALHOST_ONLY=1
export GAZEBO_MASTER_URI="${GUARDRAILGEN_GAZEBO_MASTER:-http://127.0.0.1:11355}"
# All assets are installed locally. Avoid Gazebo's remote model database delay.
export GAZEBO_MODEL_DATABASE_URI=''
if [[ "${1:-}" == "--prepared" ]]; then
    shift
    repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
    source "$HOME/.cache/guardrailgen/ros2-humble/install/setup.bash"
    python3 "$repo_root/scripts/prepare_house.py"
    exec ros2 launch guardrailgen turtlebot_house.launch.py "assets_dir:=$repo_root/generated/house" "$@"
fi
exec ros2 launch turtlebot3_gazebo turtlebot3_house.launch.py "$@"
