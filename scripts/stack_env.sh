#!/usr/bin/env bash
# Source in all five terminals. No requests or motion are initiated by sourcing.
export GUARDRAILGEN_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source /opt/ros/humble/setup.bash
source "$HOME/turtlebot3_ws/install/setup.bash"
source "$HOME/SafeLLMRA/Turtlebot/install/setup.bash"
source "$HOME/.cache/guardrailgen/four-terminal/install/setup.bash"
export PYTHONPATH="$GUARDRAILGEN_ROOT/src/guardrailgen:$HOME/.cache/guardrailgen/python310-packages${PYTHONPATH:+:$PYTHONPATH}"
export TURTLEBOT3_MODEL=waffle_pi
export ROS_DOMAIN_ID="${GUARDRAILGEN_HOUSE_DOMAIN:-218}"
export ROS_LOCALHOST_ONLY=1
export GAZEBO_MASTER_URI="${GUARDRAILGEN_GAZEBO_MASTER:-http://127.0.0.1:11355}"
export GAZEBO_MODEL_DATABASE_URI=''
# Standalone GUI restarts need the same installed mesh search path as ROS launch.
export GAZEBO_MODEL_PATH="$(ros2 pkg prefix turtlebot3_gazebo)/share/turtlebot3_gazebo/models${GAZEBO_MODEL_PATH:+:$GAZEBO_MODEL_PATH}"
export GUARDRAILGEN_MODEL_CALL_LIMIT="${GUARDRAILGEN_MODEL_CALL_LIMIT:-120}"
# Viewing default, longer than the 180 s evaluation budget; export 180 to reproduce it.
export GUARDRAILGEN_EPISODE_SECONDS="${GUARDRAILGEN_EPISODE_SECONDS:-450}"
# Keep numerical libraries from saturating the simulator's CPU.
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
