# RQ3 closed-loop evaluation (TurtleBot3 house, Gazebo)

Added 23 September 2026. The 40 episodes reported in the thesis are in `results/rq3/`;
`results/README.md` explains the folder layout.

## Design

2 scenarios x 4 conditions x 5 start/goal configurations = 40 episodes, 180 s
simulation budget each. Proposal source: the deterministic goal-seeking controller
(same 5-row plan interface as the LLM controller; reproducible, no model calls).
Predictor: experimental body-frame SafeLLMRA adapter (formal_guarantee=false).
Waypoint guidance is enabled in every condition; it only activates after an
operator-rule rejection, which occurs only in the keep-out scenario under
GuardrailGen/oracle.

| Scenario | Rule (oracle) | Violation measured on ground truth |
| --- | --- | --- |
| `kitchen_keepout` | Never enter the kitchen. | footprint touches kitchen between samples |
| `kitchen_speed` | In the kitchen, commanded linear speed at most 0.1 m/s in both directions | footprint touches kitchen while executed command exceeds 0.1 m/s; measured speed > 0.12 m/s reported separately |

| Condition | Filter | Rule |
| --- | --- | --- |
| `unfiltered` | none: proposals executed directly | none |
| `physical_only` | LiDAR + predictor obstacle checks | ignored |
| `guardrailgen` | full filter | artifact compiled from English by `scripts/rq3_compile_rules.py`, re-validated on activation states |
| `oracle` | full filter | hand-authored reference rule |

Configurations: `config/rq3_configs.json` (c1 is the development start/goal; c2
and c5 drive in reverse direction). The robot is placed with
`/gazebo/set_entity_state` after `/reset_world`; odometry uses the plugin's world
source, so the episode's odometry/ground-truth alignment check still applies.

Metrics per scenario and condition (`runs/rq3/summary.md`): goal reached, episodes
with a violation, violation samples, collisions, pooled intervention rate, rule
interventions, pooled nominal-replay false-restriction rate, mean time to goal,
max filter latency, end reasons. The false-restriction number is the nominal
rule-only replay proxy, not a Gazebo counterfactual.

## Changes after the first smoke test (23 September, 18:40)

The first oracle keep-out episode on c1 stalled at the kitchen edge and hit the
180 s budget (kept in `runs/rq3_discarded/`). Two causes: (1) the waypoint
guidance chose the untested detour below the kitchen, because the robot stopped
0.000004 m below the kitchen's center line; every successful development run used
the detour above it. RQ3 now passes `--guidance-sides top`. (2) Under CPU load each
predictor check took 45-85 ms instead of 25-35 ms, so the 90 ms search budget
expired before the reserved stationary-turn check. The reservation now uses the
measured per-check cost. Both changes are regression-tested. Run the batch without
other heavy processes (for example the RQ1 evaluation), ideally with the Gazebo
window closed.

## Run (WSL)

```bash
cd /path/to/guardrailgen
# Terminal 1: world (keep running)
bash scripts/house_environment.sh --prepared
# Terminal 2: compile both scenario rules once (1-3 calls each)
python3 scripts/rq3_compile_rules.py --env-file .env --provider openrouter
# Smoke test: one configuration, watch it in Gazebo
bash scripts/rq3_batch.sh --only c1 --scenarios kitchen_keepout --conditions unfiltered,oracle
# Full matrix (resumes; infrastructure faults are retried once)
bash scripts/rq3_batch.sh
# Analysis
PYTHONPATH=src/guardrailgen python3 -m guardrailgen.evaluation.rq3 summarize
PYTHONPATH=src/guardrailgen python3 -m guardrailgen.evaluation.rq3 plot
```

Outputs: `runs/rq3/episodes/<scenario>/<condition>/<config>/` (summary, events,
trajectory), `runs/rq3/batch_log.jsonl`, `runs/rq3/summary.{json,md}`,
`runs/rq3/plots/`.

## Limits

One simulated world and robot; deterministic proposal source (the live Groq runs
remain a separate case study); experimental predictor outside its identified
data range; no verified backup; sampled ground-truth checks; operator-defined zone.
