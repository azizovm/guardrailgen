# House integration results

These are development runs in the installed TurtleBot house, using an
operator-defined rectangular kitchen test zone. They are not a completed
thesis evaluation or a reproduced unmodified SafeLLMRA baseline.

## Latest successful live run

`results/development/house_20260921T181931_762807Z` used Groq `openai/gpt-oss-120b`, four
separate ROS processes, the prompting service, visible Gazebo, the saved
Groq-compiled kitchen rule, and external waypoint guidance. The model chose
all controller velocities and received no kitchen rule text or region geometry.
The original final goal was reached; three target revisions crossed ROS correctly.

| Measure | Result |
| --- | --- |
| Goal reached | Yes, final center distance 0.234 m (tolerance 0.30 m) |
| Navigation calls | 23 of 30 allowed |
| Recording including stopped settling | 169.5 simulation seconds (episode cap 180 s) |
| Executed path length | 7.402 m |
| Independent sampled rule violations | 0 |
| Collision contact events | 0, all six contact topics available |
| Filter interventions / checks | 1 / 327 (0.31%) |
| Nominal rule-only false-restriction proxy | 1 |
| Full counterfactual false-restriction rate | Not measured |
| Maximum filter latency | 109.20 ms |

This establishes one successful guided development episode. It does not
establish zero false restrictions, a hard 100 ms bound, continuous-time safety,
or repeatability across trials. The single intervention was conservative under
the nominal rule-only replay. Raw-mode failures remain recorded below.
The goal was reached after correcting stale target plans and the guided prompt's
turning-duration instructions. No source/configuration hash changed between
the run's manifest snapshot and completion. `trajectory.png` shows actual
Gazebo ground truth, not a planned path. The robot was stopped on completion.

## Retests and waypoint guidance, 21 September 2026

The user approved a separate geometric waypoint planner. Guidance supplies a
temporary target after a rule rejection; the model still chooses velocities,
and the final goal is unchanged. This is an additional navigation component,
so assisted results must be separated from the raw-velocity baseline.

| Run suffix (`runs/house_...`) | Navigation | Calls | Goal | Recorded seconds | Path m | Interventions/checks |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| `20260921T114909_448427Z` | Groq, raw | 21 | No, time limit | 181.7 | 7.654 | 301/470 |
| `20260921T121354_479725Z` | Groq, raw | 23 | No, diagnostic stop | 147.2 | 2.539 | 198/465 |
| `20260921T122231_492219Z` | Groq, raw | 22 | No, time limit | 182.0 | 4.204 | 197/419 |
| `20260921T124553_796682Z` | Offline, guided, single process | 0 | Yes | 35.1 | 7.747 | 40/334 |
| `20260921T124744_600212Z` | Groq, guided, separate processes | 15 | No, request cap | 101.4 | 3.814 | 97/215 |
| `20260921T175953_994931Z` | Offline, guided, separate processes | 0 | No, diagnostic stop | 157.9 | 2.635 | 359/445 |
| `20260921T180537_273122Z` | Offline, guided, separate processes, corrected | 0 | Yes | 97.7 | 7.348 | 1/315 |
| `20260921T181044_603277Z` | Groq, guided, target revisions + pivot reservation | 26 | No, time limit | 181.7 | 5.736 | 146/372 |
| `20260921T181931_762807Z` | Groq, guided, corrected waypoint prompt | 23 | Yes | 169.5 | 7.402 | 1/327 |

All nine runs above recorded zero independent sampled rule violations and zero
collision contact events, with all six contact topics present. Recording times
include stopped settling. The full counterfactual false-restriction rate is
unmeasured, and the nominal rule-only proxy is not zero. None establishes
continuous-time safety or the requested low-intervention success story.

The zero-call recovery attempt `20260921T123156_021875Z` failed initial state
feasibility before an episode began; it is not a successful safety trial.

The raw tests exposed rejected controller tails resuming after one corrective
input. The queue now retains and rechecks the full correction. The guided live
test then exposed commands continuing toward an old waypoint after a target
change. Target revisions now clear queued/held commands and reject stale model
responses and ROS plans. The subsequent offline four-process test reproduced
a search-timeout stall at (-1.109,-1.605): the candidate search could exhaust its
budget before testing a stationary turn. The next revision reserves a quarter
of that budget for one turn candidate, still subject to every normal check.
These policy changes mean rates across revisions are not paired comparisons.

The bounded live retesting allocation was 60 navigation calls in aggregate:
23 + 22 + 15, now exhausted. The user's earlier 21-call run is separate.
The user subsequently approved one additional waypoint-guided live episode,
capped at40 navigation calls and180 simulation seconds. Its outcome is recorded
separately; it is not part of the exhausted60-call allocation.

That additional live episode used 26 of 40 allowed calls and exhausted 180
simulation seconds. It stopped at (0.362,-0.954), 3.057 m from the goal. It made
five checked-pivot selections, 85 rule interventions, and 73 nominal rule-only
false-restriction proxy events. Maximum filter latency was 116.73 ms. Logs show
the model sometimes proposing 0.05 rad/s turns followed by straight motion even
with about 1.5 rad of heading error. Two such 0.1 s steps turn only 0.01 rad. The
guided prompt also inherited instructions to sustain detours, which conflict
with changing external targets. The next prompt revision explicitly prioritizes
the current target and supplies the minimum step count at the maximum turn
rate, with full-plan alignment guidance. Raw-mode prompting is preserved.
This next revision passes 175 tests and produced the successful run above.
One result alone does not isolate the prompt's causal benefit from run variation.

The corrected four-process offline run completed all three target revisions,
with55 local offline requests and zero provider calls. It stopped within0.269m
of the goal center. Its single filter intervention was a nominal rule-only
false-restriction proxy; the full counterfactual metric is still unmeasured.
Maximum filter latency was113.77ms. No reserved pivot was needed in that run,
so its success alone does not establish the pivot policy's benefit. Its
`trajectory.png` plots actual Gazebo ground truth, and `source_manifest.json`
records the source/configuration snapshot taken during the episode.

## Final approved Groq verification, 20 September 2026

Run: `results/development/house_20260920T170054_560936Z`. Provider: Groq;
model: `openai/gpt-oss-120b`. Four ROS process roles and the prompting service
were used. The existing Groq-compiled kitchen artifact was activated as
version 1 before navigation. The navigation model received no kitchen rule
or region geometry. The Gazebo 3D view was inspected during the episode.

| Measure | Recorded result |
| --- | --- |
| Goal reached | No, episode time limit |
| Navigation calls | 25 (cap: 60) |
| Commanded episode budget | 180 simulation seconds |
| Total recording, including stopped settling | 182.0 simulation seconds |
| Executed path length | 7.035 m |
| Final distance to goal center | 1.221 m (goal tolerance: 0.30 m) |
| Independent reference violation samples | 0 |
| Collision contact events | 0; all six contact topics available |
| Interventions / decisions | 386 / 521 (74.1%) |
| Rule-related interventions | 137 |
| Nominal rule-only false-restriction count | 100 |
| Full counterfactual false-restriction rate | Not measured |
| Maximum measured filter latency | 106.48 ms |

The robot cleared the kitchen zone, spent time maneuvering near a physical
wall, then resumed toward the goal. This supports observed rule avoidance
for this recorded path. It does not establish goal completion, a small
intervention count, zero false restrictions, continuous-time safety, or a
hard 100 ms timing guarantee. The requested complete success story is still
unverified.

The run includes `summary.json`, `events.jsonl`, `trajectory.jsonl`,
`trajectory.png`, `active_rule.json`, `episode_start.json`,
`run_configuration.json`, and `source_manifest.json`. The manifest records
the source/configuration hashes before subsequent controller-history changes.

## Offline goal-reaching result

The complete four-process workflow also reached the goal on 21 September:
`results/development/house_20260920T225507_622421Z`, launched with `start_stack.ps1 -Offline`,
then activated and started through the prompting service. The service was
verified to have `GUARDRAILGEN_OFFLINE=1`.

- Goal reached in 120.3 simulation seconds including settling; 7.545 m traveled.
- Zero model calls, zero independent reference violation samples, zero contacts.
- 506 interventions in 888 decisions (57.0%); nominal rule-only proxy count 463.
- Full false restrictions remain unmeasured; maximum filter latency 129.91 ms.
- Request logs confirm that the new measured-motion history crosses the ROS
  service boundary correctly. The offline controller itself does not use that
  history, so this does not establish its benefit for Groq navigation.

Cold Gazebo startup initially exceeded the spawner's 30-second timeout.
The missing robot was successfully spawned after extending the wait to 120
seconds; the same timeout is now in the installed launch file. The episode
started only after all sensors were ready. Gazebo's 3D view was inspected.
The launcher started all process roles, but a visible Windows Terminal window
was not exposed to the inspection tool. The guide includes manual terminal
commands rather than claiming that five tabs were visually verified.

The earlier single-process result follows.

Run: `results/development/house_20260920T165131_781838Z`. Deterministic goal-seeking
controller, hand-written reference rule, zero model calls:

- Goal reached; 45.2 simulation seconds including settling; 7.262 m traveled.
- Zero independent reference violation samples and zero collision contacts.
- 268 interventions in 428 decisions (62.6%).
- Full counterfactual false restrictions remain unmeasured.

This verifies an offline simulator route with the experimental local-frame
predictor. It must not be labeled an LLM success.

## Predictor and subsequent controller correction

The adapter runs the installed numerical SafeLLMRA predictor in local robot
coordinates and rotates its complete sets back into the world. This adds a
translation/rotation-equivariance assumption. At one previously stuck pose,
the raw global predictor predicted 17.37 cm translation for a stationary
turn; the local-frame variant predicted 1.44 cm. Both variants remain
experimental: the supplied identification data do not cover the turning and
speed range, and no verified backup has been established.

On 21 September, the controller's motion history was corrected. Previously,
the last six half-second observations could all show the robot stopped during
an API wait, erasing the prior detour from the prompt. It now retains six
request-level summaries of measured travel, signed rotation, final pose, and
the last moving input. Exact simulated request inputs are logged locally.
This correction passed regression tests. The later live runs in the table
above include it and still failed to reach the goal within their budgets.
