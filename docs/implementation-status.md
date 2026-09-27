# Implementation status

## Status at thesis submission, 25 September 2026

All three evaluations have been run; the reported data is frozen in
[`results/`](../results/README.md). RQ1: one complete run of 50 rules x 4
configurations (two later repetition attempts are incomplete and not reported).
RQ2: offline analysis and the live repair experiment (40/40 repaired in one
round). RQ3: 40 episodes. The entries below are the dated development history;
their "not run" statements describe the state on that date.

Verification, 25 September 2026, on a clean export containing only the files
tracked by Git (no `.venv`, `runs/`, or other ignored outputs):

| Platform | Command | Result |
| --- | --- | --- |
| Ubuntu 22.04, Python 3.10.12, RTAMT, Z3, ROS 2 Humble | `bash scripts/test.sh --ros` | **242 passed** |
| Same, without ROS | `bash scripts/test.sh` | 240 passed, 1 skipped (ROS transport) |
| Windows 11, Python 3.14 (no RTAMT, Z3, or ROS) | `python -m pytest -q` | 200 passed, 17 skipped |

The offline `demo` also ran from the clean export. The colcon build and Gazebo
episodes were not rerun for this check.

## Status, 23 September 2026

RQ1 evaluation harness added (no live results yet): 50-rule corpus, 12-example
retrieval library, four configurations (full, no_retrieval, no_schema,
no_constrained), Z3 semantic scoring with region abstraction and concrete witness
confirmation. Compiler/backend gained opt-in ablation switches; defaults are
unchanged. 218 tests passed (Linux VM, Python 3.10, RTAMT and Z3; 2 ROS tests
skipped). [Details and commands](rq1-evaluation.md).

RQ2 fault-injection harness added and run offline: 269 injected faults over 16
reference families; always-on checks catch 31.2% (4.6% of semantic faults),
random 20-state traces 78.4%, boundary traces and the solver 100%; 0 false
rejections of correct references. Live repair experiment not run.
224 tests passed. [Details](rq2-evaluation.md).

RQ3 matrix prepared (not yet run): episode runner gained opt-in `--condition`
(unfiltered, physical_only, guardrailgen, oracle), `--scenario-rule`
(kitchen_keepout, kitchen_speed), start/goal overrides and output directory;
filter gained `enforce_rule`; teleport, rule-compilation, batch and analysis
scripts added. Legacy runs are unchanged. 236 tests passed (Linux VM; ROS/Gazebo
paths not exercised here). [Runbook](rq3-evaluation.md).

## Status, 22 September 2026

New validation milestone: optional solver-based reference equivalence for the
numeric-comparison/Boolean fragment over explicit finite domains. CLI validation
and compilation accept `--reference` and `--domains`; unknown, unavailable, and
unsupported checks cannot pass. Exact counterexamples reach bounded repair
without the complete reference answer, and saved proof inputs are rechecked on
artifact loading. Spatial geometry and temporal rules remain outside this proof
fragment. It is not a proof of English interpretation or floating-point runtime
correctness. [Scope and reproducible commands](reference-equivalence.md).

Verification: **204 tests passed** with ROS, RTAMT, and Z3 in WSL Python 3.10.
The documented offline CLI example passed RTAMT and reference equivalence and
wrote a reloadable artifact. No model call or new Gazebo episode was run today.
The prior live development result below is preserved.

Latest measured outcome: the four-process live Groq run
`house_20260921T181931_762807Z` reached the goal with waypoint guidance in
169.5 simulation seconds including settling, using 23 calls, with zero
independent sampled violations, zero collision contacts, and one intervention
in 327 checks. At that milestone, 175 tests passed. The full false-restriction metric remains
unmeasured (nominal rule-only proxy count: 1); maximum filter latency was
109.20 ms. This single successful assisted run does not establish a safety
guarantee, raw-mode success, or general reliability. Earlier outcomes follow.

Latest update: the [four-process plus prompting-terminal integration](four-terminal-setup.md)
uses an isolated compatibility overlay with the original service/controller
command names. The installed Groq-compatible SDK successfully compiled and
activated the kitchen rule and returned live navigation plans. It resolves the
earlier urllib HTTP 403 issue for this workflow. The numerical SafeLLMRA
predictor now supplies additional all-step checks, including the final set.
The controller has request caps, provider cooldowns, and explicitly logged
bounded held-input proposals. The filter alone owns `/cmd_vel`.

Independent sampled world-path checks, six contact topics, stationary rule
activation, finite candidate search, and JSONL logs are implemented. Earlier live runs avoided sampled violations and
contacts but exhausted their time budgets near the zone. The experimental
body-frame predictor subsequently reached the goal with the deterministic
controller in 45.2 simulation seconds, with zero violation samples and contacts.
See the run summaries for actual outcomes; compiler success is not goal success.

An earlier live verification used 25 Groq calls and cleared the zone,
with zero sampled violations and contacts, but ended 1.22 m from the goal at
the time limit. The request-level motion-history correction was made after
that run and is regression-tested. The latest successful guided run includes it.
See [the measured results](house-results.md).

The complete separate-process workflow then reached the goal in offline mode
in 120.3 simulation seconds, with zero sampled violations/contacts and zero
model calls. All ROS roles, stationary activation, plan transport, and request
history logging were exercised. The launch now accommodates slow WSL startup
with a 120-second robot-spawn timeout. The three-package overlay rebuilt.

Further retesting exposed a plan-execution defect: a rejected controller tail
could resume after just one corrective command. Rejections now replace the
entire remaining queue; the committed correction is rechecked at every step.
Regression coverage includes opposite-turn tails, emergency clearing, expiry,
heading wrapping, stalled-motion feedback, and request timing. Updated logs
label corrective rechecks, so intervention rates across the old and new
execution policies require care when comparing them.

The user approved external waypoint guidance. The four-process filter enables
it by default, with the original raw-velocity mode selectable. It supplies
temporary targets after a rule rejection; the model still chooses velocities,
receives no kitchen rule/geometry, and the final goal remains unchanged. Target
revision metadata now discards stale held, queued, and in-flight plans when a
waypoint changes. The first offline guided run reached the goal in 35.1 seconds
with zero sampled violations/contacts and 40/334 interventions. The first live
guided run used its remaining 15-call budget without reaching the goal and led
to the revision fix. Full false restrictions remain unmeasured.

A separate-process offline test then found search starvation at the boundary:
the deadline could expire before a stationary turn was tested. The search now
reserves its final quarter-budget for one such candidate, which still passes
all normal checks. Unsafe pivot rejection is regression-tested. This is an
explicit search-policy change, not a verified backup or a hard timing bound.

The corrected four-process offline run reached the goal in 97.7 s with zero
sampled violations/contacts and one intervention in 315 checks. A subsequent
live run still exhausted the 180 s budget after 26 calls, with zero sampled
violations/contacts. Its model under-turned on large heading errors. Guided
prompting now supplies numeric turning-step hints and prioritizes the current
waypoint over the previous detour; raw-mode prompting remains available.

The installed identification data were audited and do not cover the proposed
turning controls. The numerical adapter therefore remains experimental
extrapolation. Validated coverage and a verified backup remain unfinished;
the house runner explicitly reports `formal_guarantee: false`.

Earlier provider milestone, 20 September 2026: the CLI now defaults to Groq-hosted
`openai/gpt-oss-120b` using `GROQ_API_KEY`. Strict structured generation,
validation, retrieval, repairs, and provenance remain in place. OpenAI requires
explicit `--provider openai`; no automatic fallback occurs. Groq transport is
tested with mocked HTTP, not live account credentials.
Verification after this update: **120 tests passed** in Ubuntu with ROS and
RTAMT enabled; Windows passed 117 tests with the two platform-dependent skips.

This implements the first usable slice of `GuardrailGen_Solution_Plan.md`.
The plan is not fully implemented; its completion gates are not replaced by
unit-test counts.

| Stage | Implemented | Remaining |
| --- | --- | --- |
| 1. Baseline | Upstream source/data audit, WSL/ROS checks, isolated compatibility overlay, installed numerical predictor exercised, sole house command publisher | Reproduce an unmodified baseline and validate model coverage |
| 2. Semantics | Versioned schema, units, named rectangles/circles, footprint semantics, Boolean invariants, deterministic Python/STL | Calibrated domains and model/data provenance; advisor review of English meanings |
| 3. Compiler | Hosted strict generation, schema prompting, lexical top-three retrieval, two repairs maximum, provenance/artifacts, live Groq kitchen compilation, optional numeric/Boolean reference equivalence and counterexample repair | Translation evaluation; retrieval currently has six examples; spatial/temporal equivalence not supported |
| 4. Enforcement | Initial/all nominal swept steps, numerical SafeLLMRA sequence checks, conservative boxes, finite candidate search, LiDAR, freshness and ROS transport | Validated data-driven coverage, complete obstacle model, timing/actuation bounds, verified braking/backup |
| 5. Temporal/API | CLI, atomic candidate artifact writes | Persistent dwell, FastAPI, complete rule-set activation after state/backup feasibility; no hot activation |
| 6. Evaluation | Behavioral tests and nine labeled development reference states | Reviewed family-disjoint 40/20/60 split, ablations, paired closed-loop runs and statistical analysis |

## Earlier core verification (before live house integration)

- Ubuntu 22.04.5 / Python 3.10.12 / ROS Humble: **97 tests passed**, including
  real RTAMT 0.3.5 parsing/evaluation and ROS transport with both rule sources.
- Windows Python 3.14.6: core tests pass. RTAMT's ANTLR dependency cannot import
  the removed `typing.io` module; RTAMT and ROS verification run in WSL.
- `bash scripts/setup.sh --existing-deps` built one package with colcon. Output
  is `~/.cache/guardrailgen/ros2-humble`, outside the Windows source.
- No live model API calls or physical motion commands were sent. API transport
  is mocked in tests; ROS tests use domain 217 and unique synthetic topic names.

Runtime decisions always report `formal_guarantee=False`. Zero commands are
uncertified emergency actions, not verified braking. The heuristic predictor
uses nominal constant-command unicycle motion and configured inflation; it has
no validated physical coverage. Schema constraints and finite labeled traces
do not prove agreement with English intent. The direct contradiction checker
is not a general Boolean/temporal equivalence solver. The separate optional
reference checker now covers numeric/Boolean point predicates only.

## Reproduce on this machine

```bash
cd /path/to/guardrailgen
bash scripts/test.sh --ros
bash scripts/run.sh validate data/reference_rule.json \
    --scenario config/turtlebot_development.json \
    --traces data/reference_traces.json --require-rtamt
bash scripts/setup.sh --existing-deps
```

Dependencies are recorded in `requirements-validation.txt` and installed in
`~/.cache/guardrailgen/python310-packages`. System Python and the existing
simulator were preserved. The test script disables unrelated pytest plugin
auto-loading because ROS Humble's optional launch-testing plugin targets an
older pytest API.

No repository, commits, tracked submodule, GitHub publication, or thesis-chapter
changes were created implicitly. The source folder is not a Git repository.
