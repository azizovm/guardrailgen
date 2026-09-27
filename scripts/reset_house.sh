#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID="${GUARDRAILGEN_HOUSE_DOMAIN:-218}"
export ROS_LOCALHOST_ONLY=1
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$repo_root/scripts/reset_house.py"
