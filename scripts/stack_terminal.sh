#!/usr/bin/env bash
set -eo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
source scripts/stack_env.sh
case "${1:-}" in
  world)
    python3 scripts/prepare_house.py
    ros2 launch guardrailgen turtlebot_house.launch.py "assets_dir:=$repo_root/generated/house"
    ;;
  service) ros2 run chat_gpt chat_gpt_service ;;
  controller) ros2 run my_robot_controller LLM_robot_controller ;;
  filter) ros2 run my_robot_controller safety_check_nonlinear_reachability ;;
  prompt)
    printf '\n%s\n' '1. python3 -m guardrailgen.simulation.stack rule "Never enter the kitchen."' \
      '2. python3 -m guardrailgen.simulation.stack go "Go to the goal."' \
      'Status: python3 -m guardrailgen.simulation.stack status' \
      'Stop: python3 -m guardrailgen.simulation.stack stop'
    exec bash --norc -i
    ;;
  *) echo 'Usage: stack_terminal.sh world|service|controller|filter|prompt' >&2; exit 2 ;;
esac
