# Integration baseline

Update, 20 September 2026: the installed numerical predictor is now exercised
inside the [four-terminal integration](four-terminal-setup.md), with an
experimental local-frame adapter. The original baseline has still not been
reproduced unchanged, and validated reachability coverage remains pending.
The source audit below records the earlier checkpoint.

Audit date: 2026-09-19. **Stage 1 is source-audited, not reproduced.** The
compiler and development filter can be exercised separately from ROS. A pinned
SafeLLMRA closed-loop experiment and the formal-enforcement gate remain pending.

## Exact upstream dependency

The public repository is
[TUM-CPS-HN/SafeLLMRA](https://github.com/TUM-CPS-HN/SafeLLMRA).
`git ls-remote ... HEAD` returned
`9e9eee5431ee08830f6524d6b09d2014bc3e343b`. The recursive GitHub tree and the
source files below were read at that exact revision. The machine-readable pin
and interface summary are in `config/upstream.json`.

The supplied Windows source folder had no initialized parent Git repository or
tracked submodule gitlink. A `.gitmodules` entry alone did not pin anything.
The replacement fetch helper creates an independent, shallow, sparse dependency
checkout in `external/SafeLLMRA`, with `COLCON_IGNORE`. It does not initialize or
publish the parent project. It refuses to change an existing checkout with an
unexpected revision, origin, or modified files.

```bash
# Run from the guardrailgen source directory. Requires Git and network access.
python3 scripts/fetch_upstream.py
python3 scripts/fetch_upstream.py --check
```

Fetching and executing this revision are separate operations. The audit read
selected source files remotely; it did not download or run the dependency.

## Verified source interfaces

All paths in this table are relative to the pinned upstream repository.

| Interface | Verified behavior |
| --- | --- |
| `Turtlebot/my_robot_controller/my_robot_controller/LLM_robot_controller.py` | Publishes `/parsed_plan` as `std_msgs/msg/Float64MultiArray`. Each row is `[linear velocity, angular velocity]`; `flatten()` gives row-major serialization. Subscribes to odometry, scan, and executed commands. |
| `Turtlebot/my_robot_controller/my_robot_controller/safety_check_nonlinear_reachability.py` | `DataLoggerNode` subscribes to `/parsed_plan`, `/odom`, `/scan`, and `/cmd_vel`. Publishes `geometry_msgs/msg/Twist` on `/cmd_vel`. Reshapes plans into two columns. |
| `Turtlebot/pyzonotope/pyzonotope/NLReachability.py` | `NLReachability(path)` loads the data files below. `run_reachability(R0, plan)` returns `(R_data, derivatives)`. `R_data[0]` is the initial set, followed by one reachable set per plan row. Configured `dt` is 0.1 seconds. |
| `Turtlebot/pyzonotope/pyzonotope/Zonotope.py` | The safety node constructs `Zonotope(center, generators)`; reachable sets expose `center()` and `generators()`. |
| `Turtlebot/pyzonotope/example/` | Contains `U_full_TB.mat` (MAT key `U_full`), `X_0T_TB.mat` (key `X_0T`), and `X_1T_TB.mat` (key `X_1T`). Dimensions, sample coverage, and model assumptions still need an executable data audit. |

The predictor state is `[x, y, cos(yaw), sin(yaw)]`. Position is taken from
`Odometry.pose.pose.position`; yaw is obtained from the orientation quaternion.
The upstream node initializes a diagonal generator matrix with entries
`[0.25, 0.25, 0.01, 0.01]`. These are observed upstream settings, not validated
error bounds for a new scenario. The predictor input is `[v_command, omega_command]`.

The four-dimensional predictor does **not** include measured speed. The
`/cmd_vel` callback stores the last commanded Twist; it is not a measurement of
motion. Actual signed linear/angular speed must come from odometry twist or a
validated tracking-error/augmented-state model. A rule over measured speed must
not be silently rewritten into a command constraint. The input data's reverse
coverage has not been verified.

The plan message has no header or duration field. The adapter needs receipt
timestamps, a fixed verified sampling period, dimensional checks, finite-value
checks, a model-domain check, and a command-expiry policy. Coordinate-frame
agreement between odometry, map regions, scan, and robot footprint remains an
integration gate. The upstream scan conversion assumes a particular angular
span; the actual `LaserScan` angle metadata must be checked.

Source references:

- [Controller](https://github.com/TUM-CPS-HN/SafeLLMRA/blob/9e9eee5431ee08830f6524d6b09d2014bc3e343b/Turtlebot/my_robot_controller/my_robot_controller/LLM_robot_controller.py)
- [ROS safety node](https://github.com/TUM-CPS-HN/SafeLLMRA/blob/9e9eee5431ee08830f6524d6b09d2014bc3e343b/Turtlebot/my_robot_controller/my_robot_controller/safety_check_nonlinear_reachability.py)
- [Predictor](https://github.com/TUM-CPS-HN/SafeLLMRA/blob/9e9eee5431ee08830f6524d6b09d2014bc3e343b/Turtlebot/pyzonotope/pyzonotope/NLReachability.py)
- [SafetyLayer](https://github.com/TUM-CPS-HN/SafeLLMRA/blob/9e9eee5431ee08830f6524d6b09d2014bc3e343b/Turtlebot/pyzonotope/pyzonotope/SafetyLayer.py)

## Concrete upstream adaptation work

These findings come from source inspection and have not been patched upstream.

1. `SafetyLayer.__init__` hard-codes
   `/home/ali/zonotope/pyzonotope/example`. Use the direct
   `NLReachability(configured_data_path)` interface in the adapter.
2. `SafetyLayer.enforce_safety_nonlinear` predicts only when sensed obstacles
   exist. Operator rules must be checked even when this obstacle list is empty.
3. That method builds position sets from `new_states[0:]` (initial plus all
   future steps), but zips them with `len(new_states[1:])` repetitions of the
   obstacles. The resulting pairs omit the final reachable step. GuardrailGen
   must enumerate the complete sequence independently.
4. The upstream ROS node clips the selected first speed to `[0, 0.1]` after
   checking the plan. Any change to the executed input needs a new check or an
   explicit proof that the change preserves the guarantee. Reverse is excluded
   by this clip.
5. Upstream initial/old plans are initialized without a demonstrated braking
   certificate. Preserving an array named `old_plan` is insufficient evidence
   that a backup remains feasible from the current state.
6. `Turtlebot/my_robot_controller/package.xml` names `geometry_msg` (singular),
   while the imported package is `geometry_msgs`. It also omits runtime imports
   such as `nav_msgs` and `sensor_msgs`. Dependency repair must be recorded as an
   explicit patch before building the selected upstream packages.
7. The upstream `safe_LLM_controller` console entry points to a Python module
   absent from the audited tree. Its launch file is under `launch/` instead.
   Use verified entry points, not this console alias.
8. Both the controller and `chat_gpt_service` advertise `chat_gpt_ask`. The
   README starts both. Choose and test a single service endpoint for experiments.
   Their source uses the legacy `openai.ChatCompletion` API; the README pins
   `openai==0.28`. Isolate it from the new compiler's model client. Credentials
   must be injected through environment configuration, not copied into source.

This is why the project does not label an unmodified upstream safety-node
wrapper as certified integration.

## Local environment: verified and pending

The initial sandboxed `wsl --list --verbose` returned `E_ACCESSDENIED`. The
authorized retry outside the sandbox succeeded; WSL itself is available.

| Check | Status on 2026-09-19 |
| --- | --- |
| WSL distribution | **VERIFIED:** running `Ubuntu-22.04`, Ubuntu 22.04.5 LTS. |
| Base tools | **VERIFIED:** `/opt/ros/humble`, `colcon`, `gazebo`, Python 3.10.12. |
| ROS packages | **VERIFIED:** `turtlebot3_gazebo`, `gazebo_ros`, `geometry_msgs`, `nav_msgs`, `sensor_msgs` resolve under `/opt/ros/humble`. |
| Base overlay upstream packages | **ABSENT:** `custom_msgs`, `my_robot_controller` do not resolve when only `/opt/ros/humble/setup.bash` is sourced. Other pre-existing overlays may contain them. |
| Existing simulator | **OBSERVED:** an already-running `gzserver` referenced `~/turtlebot3_ws/install/turtlebot3_gazebo/.../turtlebot3_house.world`. It was left untouched. |
| Existing command graph | **OBSERVED SNAPSHOT:** `/cmd_vel` had one publisher, `data_logger`, and subscribers `turtlebot3_diff_drive`, `data_logger`, `safe_robot_controller`. `/parsed_plan`, `/odom`, and `/scan` appeared in the topic list. A later short discovery check did not see `/odom` or `/parsed_plan`, so continuous graph/data readiness is unverified. No motion commands were sent. |
| Pinned baseline execution | **PENDING:** the existing processes were not started by this implementation and their revision is unknown. They are not evidence of reproducing the pin. |
| Sole GuardrailGen output path | **PENDING:** the snapshot's publisher is the upstream-style node, not GuardrailGen. The existing process must not be silently displaced. |

## Build and launch boundary

Keep Windows source in the requested directory. Run ROS commands inside WSL.
The guarded setup builds **only** `src/guardrailgen`; its default output directory
is `$HOME/.cache/guardrailgen/ros2-humble`, on the Linux filesystem.

```bash
cd /path/to/guardrailgen
bash scripts/setup.sh
source "$HOME/.cache/guardrailgen/ros2-humble/install/setup.bash"
```

`GUARDRAILGEN_BUILD_ROOT` can select another absolute Linux output directory.
The script stops on dependency failure. It does not start any robot, fetch
upstream, recursively discover `external`, build JetRacer, or install a second
ROS distribution. Upstream source packages, once patched and tested, belong in
a separate explicitly selected TurtleBot workspace. Upstream `pyzonotope`
declares NumPy, SciPy, CVXPY, and Matplotlib but does not pin their versions;
record a tested compatibility lock before reporting reproducible experiments.

The [upstream README](https://github.com/TUM-CPS-HN/SafeLLMRA/blob/9e9eee5431ee08830f6524d6b09d2014bc3e343b/README.md)
specifies Ubuntu 22.04.5, ROS 2 Humble, Gazebo 11.10.2, TurtleBot3, and a supplied
`turtlebot3_waffle.zip` model modification. Its simulator command is
`TURTLEBOT3_MODEL=waffle_pi ros2 launch turtlebot3_gazebo turtlebot3_house.launch.py`.
The archive contents and installed simulator model changes have not been
compared. Launch this only in an isolated experiment once the existing
simulation is no longer needed. The installed house launch starts a GUI as
well as `gzserver`; a headless experiment needs an explicit launch configuration.

The upstream proposal interface is a plan on `/parsed_plan`, while the initial
GuardrailGen development interface is a Twist on `/llm_cmd_vel`. They are not
interchangeable. The plan adapter must be implemented and tested before wiring
the existing LLM controller directly to GuardrailGen. Start a fresh isolated
ROS domain for integration tests, remap all controller output through the
filter, and verify `/cmd_vel` publishers and continuous odometry/scan freshness.

Stage 1 completes after the pinned dependency runs with recorded patches/data
and the entire command graph is verified. Stage 4 additionally requires sound
reachable-set coverage, model-domain validation, all-step checking, explicit
intersample coverage, and a valid backup plan. A successful simulator launch
alone does not establish those properties.
