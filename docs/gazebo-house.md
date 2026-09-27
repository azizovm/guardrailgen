# Visible TurtleBot house experiments

For the current four-process plus prompting-terminal workflow, use
[the integration guide](four-terminal-setup.md). Its installed-SDK Groq
transport resolves the HTTP 403 encountered by the standalone transport
described below, and its experimental body-frame predictor has reached the
goal in an offline Gazebo run. The earlier results below remain historical.

The prepared launch opens Gazebo Classic through WSLg, spawns TurtleBot3
Waffle Pi, adds an orange forbidden test zone and a red goal circle, and records
ground-truth poses and robot contacts. The installed TurtleBot and SafeLLMRA
files are not modified. This is a GuardrailGen development experiment using the
installed TurtleBot house assets, not a reproduced SafeLLMRA baseline.

## Start the 3D world

Run in Ubuntu-22.04 / WSL, from this project folder:

```bash
cd /path/to/guardrailgen
bash scripts/setup.sh --existing-deps
bash scripts/house_environment.sh --prepared
```

Keep this terminal running. The Windows window is named **Gazebo (Ubuntu-22.04)**.
The launch includes the GUI, so this is a live simulation rather than a recorded
animation. Use the mouse to inspect the house while the robot moves. The world
must be unpaused for the controller's simulation-time timer to run.

The dedicated ROS domain is 218 and Gazebo master is port 11355. Regression
tests use domain 217. Do not start a second controller in the house domain.

## Run an episode

In another Ubuntu terminal, in the same project folder:

```bash
# Reset only after an earlier controller has exited.
bash scripts/reset_house.sh

# Offline smoke test: no model calls, reference rule and greedy goal controller.
bash scripts/house_test.sh --controller goal-seeking --rule-source reference --seconds 30

# Live Groq: compiler and navigation use openai/gpt-oss-120b.
# This transmits the rule/config to the compiler and simulated pose, heading,
# LiDAR sectors, goal, and last executed command to the navigation model.
bash scripts/reset_house.sh
bash scripts/house_test.sh --env-file .env --controller groq --rule-source groq \
    --seconds 90 --max-model-calls 12
```

The live command uses only `GROQ_API_KEY` and optional `GROQ_MODEL` from the
explicitly selected env file. No OpenAI endpoint or fallback is used. Twelve
is a cap on navigation requests; compilation has one initial request and up
to two validation repairs. Transport failures are not automatically retried.
The robot stops while waiting for model responses. Ctrl+C ends the episode
and publishes zero; this is not a certified physical braking procedure.

## Configuration and enforcement

`config/turtlebot_house.json` defines `kitchen` as a rectangle in `odom` and a
0.25 m circular footprint. `config/house_experiment.json` defines spawn, goal,
time budget, and explicit development prediction assumptions. The current
zone is x [-0.8, 0.8], y [-3.4, -1.6], with spawn (-3, -2.5, 0) and goal
(3, -2.5). **The installed house has no semantic room labels: this is an
operator-defined kitchen TEST ZONE, not a verified kitchen location.**
Choose the actual kitchen coordinates before thesis evaluation. Restart the
prepared world after editing either config so visual markers and evaluation
settings agree. The runner checks odometry against world position and rejects
a mismatched frame. The conservative footprint is based on the installed
Waffle Pi collision geometry; it still needs experimental calibration.

Compilation happens before the ROS controller starts. RTAMT parsing and four
labeled development states must pass, including 5 cm footprint overlap and
20 cm clearance. The offline source explicitly uses a hand-written AST.
Activation requires fresh sensing, stationary measured motion, matching world
and odometry coordinates, and a feasible stationary check. The active artifact
is saved as episode version 1 and its STL is printed.

The navigation prompt receives pose, heading, LiDAR, goal distance, goal angle,
and executed input. It contains no kitchen rule. Five commands represent
0.1 s each; v is [0, 0.5] m/s and omega is [-0.5, 0.5] rad/s. The filter checks
the current footprint, all remaining nominal swept intervals, sampled LiDAR
obstacles, and an assumed braking suffix. SAFE originals pass unchanged.
Rejected plans trigger a bounded search ordered by normalized command distance.
The runner executes the first approved step and checks again at the next tick.
Missing/stale sensing, multiple command publishers, time rollback, and provider
failure stop the experiment.

## Evidence and limits

Each episode writes `runs/house_<UTC>/`:

- `compilation.json`: hosted compiler status and provenance, when applicable.
- `rules/` and `active_rule.json`: validated artifact and activation record.
- `run_configuration.json`: scenario provenance and experiment settings.
- `events.jsonl`: proposals, decisions, interventions, model usage and contacts.
- `trajectory.jsonl`: sampled Gazebo world positions and independent rule checks.
- `summary.json`: measured outcome, including explicit failures before activation.

The reference checker is independently implemented and tests circular-footprint
contact along linearly interpolated ground-truth segments. It does not call the
generated monitor. Sampling and interpolation remain limitations. Contact
counts cover six robot collision sensors and exclude the ground plane; absent
measurements are not reported as zero collisions.

Full counterfactual false restrictions are **not implemented** and are logged
as null. A separately named nominal rule-only replay proxy is provided; it
does not test a Gazebo candidate-plus-backup counterfactual.

The backend is `heuristic_development`, always `formal_guarantee: false`.
`data/safellmra_house_data_audit.json` records upstream revision, data hashes,
and observed input ranges. The installed identification data cover only
approximately v [0.49, 0.51] and omega [-0.01, 0.01]. They do not validate
the slower turning candidates in this experiment. Integrating the numerical
predictor, collecting suitable coverage, calibrating uncertainty and actuation,
and verifying a backup remain required for a formal SafeLLMRA claim.

## Recorded results, 20 September 2026

The 30 s offline run `house_20260920T133028_056446Z` recorded:

| Measurement | Observed result |
| --- | --- |
| Sampled reference violations | 0 |
| Non-ground contact events | 0, all six contact topics available |
| Goal reached | No, episode budget exceeded |
| Driven path length | 1.865 m |
| Interventions / decisions | 232 / 292 |
| Nominal rule-only false restrictions | 8 |
| Full counterfactual false-restriction rate | Not measured |
| Maximum measured filter selection time | 6.79 ms |

The greedy controller stalled near the forbidden boundary. This demonstrates
closed-loop rejection and logging, not the requested successful hallway route.
Passing safe commands and nearest-command selection do not guarantee progress.

The approved live Groq attempt failed during compilation with HTTP 403.
A diagnostic retry identified **edge access denied, code 1010**. Both stopped
before activation: zero navigation calls and no model-controlled motion.
See `house_20260920T133634_251100Z/compilation.json` and `summary.json`.
Do not interpret this as exhausted OpenAI credit or a successful Groq test.
Resolve the Groq access denial before rerunning; the implementation does not
switch provider, identity, or model to work around it. Groq documents HTTP 403
as permission denial: https://console.groq.com/docs/errors.

Regression verification after this integration: **139 tests passed** with ROS
Humble and RTAMT in Ubuntu Python 3.10. These tests do not establish empirical
translation accuracy, physical safety, or goal success.
