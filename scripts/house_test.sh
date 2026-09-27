#!/usr/bin/env bash
set -eo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID="${GUARDRAILGEN_HOUSE_DOMAIN:-218}"
export ROS_LOCALHOST_ONLY=1
export GAZEBO_MASTER_URI="${GUARDRAILGEN_GAZEBO_MASTER:-http://127.0.0.1:11355}"
export PYTHONPATH="$repo_root/src/guardrailgen:$HOME/.cache/guardrailgen/python310-packages${PYTHONPATH:+:$PYTHONPATH}"
cd -- "$repo_root"
exec python3 -m guardrailgen.simulation.episode --root "$repo_root" "$@"
