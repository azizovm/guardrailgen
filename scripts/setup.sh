#!/usr/bin/env bash
# Build only GuardrailGen in an existing ROS 2 Humble environment.
# Upstream fetching is separate; see docs/integration-baseline.md.
set -euo pipefail

existing_deps=false
if [[ "${1:-}" == "--existing-deps" && "$#" == 1 ]]; then
    existing_deps=true
elif [[ "$#" != 0 ]]; then
    echo "Usage: bash scripts/setup.sh [--existing-deps]" >&2
    exit 1
fi

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
build_root="${GUARDRAILGEN_BUILD_ROOT:-${HOME}/.cache/guardrailgen/ros2-humble}"

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "Run this script inside Ubuntu 22.04 / ROS 2 Humble (WSL2 is supported)." >&2
    exit 1
fi
if [[ ! -f /opt/ros/humble/setup.bash ]]; then
    echo "Missing /opt/ros/humble/setup.bash. Install ROS 2 Humble first." >&2
    exit 1
fi
# ROS-generated setup files are not compatible with Bash nounset.
set +u
source /opt/ros/humble/setup.bash
set -u
if [[ "${ROS_DISTRO:-}" != "humble" ]]; then
    echo "ROS_DISTRO must be humble." >&2
    exit 1
fi
for executable in python3 rosdep colcon; do
    command -v "$executable" >/dev/null || { echo "Missing $executable" >&2; exit 1; }
done
if [[ "$build_root" != /* || "$build_root" == /mnt/* ]]; then
    echo "GUARDRAILGEN_BUILD_ROOT must be an absolute Linux filesystem path outside /mnt/." >&2
    exit 1
fi

if [[ "$existing_deps" == true ]]; then
    # Explicit offline path: verify imports rather than hiding rosdep failures.
    python3 -c 'import rclpy, geometry_msgs.msg, nav_msgs.msg, std_msgs.msg, launch, launch_ros, ament_index_python, yaml, setuptools'
    echo "Existing runtime/build dependencies verified; rosdep installation explicitly skipped."
else
    rosdep install --from-paths "$repo_root/src/guardrailgen" --ignore-src --rosdistro humble -y
fi
mkdir -p -- "$build_root"
colcon --log-base "$build_root/log" build \
    --base-paths "$repo_root/src/guardrailgen" \
    --packages-select guardrailgen \
    --build-base "$build_root/build" \
    --install-base "$build_root/install" \
    --symlink-install
printf 'Build complete. Source this overlay: %s\n' "$build_root/install/setup.bash"
printf '%s\n' 'This does not certify or start the simulator or the upstream safety filter.'
