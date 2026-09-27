#!/usr/bin/env bash
# Use existing dependencies only. Optional ROS smoke tests use synthetic topics.
set -eo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == "--ros" ]]; then
    source /opt/ros/humble/setup.bash
    # A separate domain, plus UUID topic names, isolates transport tests.
    export ROS_DOMAIN_ID="${GUARDRAILGEN_TEST_DOMAIN:-217}"
    export ROS_LOCALHOST_ONLY=1
    python3 -c 'import rclpy, geometry_msgs.msg, nav_msgs.msg'
elif [[ "$#" != 0 ]]; then
    echo "Usage: bash scripts/test.sh [--ros]" >&2
    exit 1
fi
dependency_dir="${GUARDRAILGEN_TEST_DEPS:-$HOME/.cache/guardrailgen/python310-packages}"
if [[ -d "$dependency_dir" ]]; then
    export PYTHONPATH="$dependency_dir${PYTHONPATH:+:$PYTHONPATH}"
fi
export PYTHONPATH="$repo_root/src/guardrailgen${PYTHONPATH:+:$PYTHONPATH}"
# ROS Humble's optional pytest plugins target an older pytest. These tests use
# only pytest's built-in plugins and exercise rclpy directly.
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
cd -- "$repo_root"
python3 -m pytest -q -rs -o "cache_dir=$HOME/.cache/guardrailgen/pytest"
