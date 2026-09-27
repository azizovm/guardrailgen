#!/usr/bin/env bash
# Install compatibility entry points in a dedicated overlay, leaving upstream intact.
set -eo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source /opt/ros/humble/setup.bash
source "$HOME/SafeLLMRA/Turtlebot/install/setup.bash"
python3 -c 'import custom_msgs.srv, openai; assert openai.__version__ == "0.28.0"'
build_root="$HOME/.cache/guardrailgen/four-terminal"
mkdir -p "$build_root"
colcon --log-base "$build_root/log" build --symlink-install \
    --base-paths "$repo_root/src/guardrailgen" "$repo_root/ros_overlay" \
    --packages-select guardrailgen chat_gpt my_robot_controller \
    --allow-overriding chat_gpt my_robot_controller \
    --build-base "$build_root/build" --install-base "$build_root/install"
printf '%s\n' 'Ready. In each terminal: source scripts/stack_env.sh'
