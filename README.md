# GuardrailGen

Implementation and evaluation data for the bachelor's thesis

> **GuardrailGen: From Human Safety Rules to Runtime Monitors for LLM-Controlled
> Cyber-Physical Systems**
> Mahammad Azizov, B.Sc. Information Engineering, Technical University of Munich,
> TUM Campus Heilbronn, Chair of Cyber-Physical Systems (Prof. Dr. Amr Alanwar).
> Advisor: Ahmad Hafez, M.Sc. Submitted 1 October 2026.

An operator types a safety rule in English. A hosted LLM compiles it into a
restricted JSON expression tree over a typed schema (strict JSON Schema
generation, schema grounding, lexical top-three retrieval, at most two repairs).
Python monitors and STL predicates are generated deterministically from the
validated tree; no generated code is executed and no model call happens in the
control loop. At runtime, a ROS 2 gate checks every proposed command of an
LLM-driven TurtleBot3 against all active rules, alongside SafeLLMRA's
physical-obstacle check.

**Scope.** Instantaneous invariants only: numeric limits, named regions,
region-conditioned limits, and Boolean combinations. Temporal operators (dwell,
deadlines) are refused as unsupported. Prediction is a heuristic nominal sweep,
the SafeLLMRA predictor is an experimental additional check, and a rejected
command is replaced by a zero Twist, which is not verified braking. No run
carries a formal safety guarantee. Evaluation is in Gazebo simulation only.

## Thesis results and how to reproduce them

The data behind every table and figure in Chapter 5 is frozen in
[`results/`](results/README.md). The thesis appendix "Supplementary Material"
lists the rule corpus, retrieval library, and RQ3 configurations. Commands run
in WSL (Ubuntu 22.04, Python 3.10, ROS 2 Humble); see the linked guides for
setup.

| Question | Headline result | Data | Reproduce |
| --- | --- | --- | --- |
| RQ1: compiler accuracy (50 rules, 4 configurations) | Full compiler 34/34 in-scope rules correct, 15/16 refusals; ablations 33, 32, 33 of 34 | `results/rq1/` | [docs/rq1-evaluation.md](docs/rq1-evaluation.md): `bash scripts/eval_rq1.sh run --config full ...` |
| RQ2: fault detection (269 injected faults) | Always-on checks 31.2%, with boundary and solver checks 100%; 40/40 repaired in one round | `results/rq2/` | [docs/rq2-evaluation.md](docs/rq2-evaluation.md): `bash scripts/eval_rq2.sh analyze` (offline), `... repair` (live) |
| RQ3: closed loop (2 scenarios x 4 conditions x 5 configurations) | 0 of 10 GuardrailGen episodes violate the rule versus 5/5 per scenario without it | `results/rq3/` | [docs/rq3-evaluation.md](docs/rq3-evaluation.md): `bash scripts/rq3_batch.sh` |
| Live case study (Groq in the loop) | Documented episodes and failures | `results/development/` | [docs/four-terminal-setup.md](docs/four-terminal-setup.md), [docs/house-results.md](docs/house-results.md) |

**API keys and cost.** RQ1, RQ2 repair, RQ3 rule compilation, and the live case
study call a hosted model (`openai/gpt-oss-120b`; RQ1 used OpenRouter pinned to
the Groq route, the live runs used Groq). Put your own key in `.env` (template:
`.env.example`). The RQ1 and RQ2 harnesses cap calls with `--max-calls`, the live
episodes have a navigation-call budget, and providers may
bill or rate-limit you. The RQ2 offline analysis, RQ3 episodes (deterministic
proposal source), the demo, and the tests need no key. Model outputs are not
deterministic, so a rerun of RQ1 can differ from the frozen results.

## Watch the robot in Gazebo

For your original **four processes plus one prompting terminal**, use the
[five-terminal integration guide](docs/four-terminal-setup.md). It preserves
the SafeLLMRA service/controller command names through an isolated overlay,
uses the installed Groq-compatible SDK, and integrates the numerical predictor
as an explicitly experimental additional check. The successful live run uses
waypoint guidance and a prompt calibrated to the actual turning time; raw mode
remains available for comparisons. Full false restrictions remain unmeasured.
See [the measured results, including failures](docs/house-results.md).
The older standalone runner remains documented below.

Follow [the house experiment guide](docs/gazebo-house.md) to launch the 3D house
and run either an offline smoke episode or bounded Groq episode. The orange
area is a configurable kitchen **test zone**, not a verified room annotation.
The guide records actual outcomes and outstanding integration limits.

## Quick start: Windows

From this folder, the prepared environment runs the offline demonstration:

```powershell
.\.venv\Scripts\python.exe -m guardrailgen demo
.\.venv\Scripts\python.exe -m pytest -q
```

The demo is hand-authored, requires no API key, and demonstrates SAFE, UNSAFE,
and UNKNOWN. Only SAFE permits a candidate. To recreate the core environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "src/guardrailgen[test]"
```

RTAMT 0.3.5's ANTLR dependency cannot import under Windows Python 3.14
(`typing.io` was removed). Use Ubuntu Python 3.10 for STL validation and ROS.
`--require-rtamt` fails explicitly if the parser is unavailable.

## Validate and save an artifact in WSL

The existing Ubuntu-22.04 environment has isolated dependencies in the cache
location below. The install command recreates them without changing system Python.

```bash
cd /path/to/guardrailgen
python3 -m pip install --target "$HOME/.cache/guardrailgen/python310-packages" \
    -r requirements-validation.txt
bash scripts/run.sh demo
bash scripts/run.sh validate data/reference_rule.json \
    --scenario config/turtlebot_development.json \
    --traces data/reference_traces.json --require-rtamt
bash scripts/test.sh --ros
```

`validate` writes a content-addressed JSON artifact in `artifacts/`, including
schema, original text, expression, scenario, STL, provenance, and validation
report. Writes are atomic; failed candidates do not replace existing files.
Reloading checks the checksum, schema, deterministic STL and direct contradictions.
Integrity checks are not operator approval or proof of English semantics.

The nine supplied reference states are development cases, not held-out benchmark
data. The scenario geometry and 0.12 m footprint are examples, not a calibrated
map of the existing Gazebo world.

## Compile English

The default provider is **Groq**, using **`openai/gpt-oss-120b`**. Set
`GROQ_API_KEY` in the process environment. For PowerShell (replace the placeholder
locally; do not commit your key):

```powershell
$env:GROQ_API_KEY = 'your-groq-key'
.\.venv\Scripts\python.exe -m guardrailgen compile 'Keep commanded linear speed at or below 0.2 m/s.' --scenario config/turtlebot_development.json
```

For WSL, export `GROQ_API_KEY` in that shell; Windows environment changes do not
automatically configure an already-running WSL shell. Then run:

```bash
bash scripts/run.sh compile \
    'Keep the magnitude of commanded linear speed at or below 0.2 m/s.' \
    --id command-limit --scenario config/turtlebot_development.json \
    --require-rtamt --report artifacts/last-compilation.json
```

The Groq adapter sends strict JSON Schema to Groq's Chat Completions endpoint,
preserving constrained generation. The `openai/` prefix identifies the model's
publisher; requests are billed/limited by Groq, not an OpenAI API account.
See [Groq's Structured Outputs documentation](https://console.groq.com/docs/structured-outputs).

Optionally override the model with `GROQ_MODEL` or `--model MODEL_ID`. This command
calls Groq and is subject to the Groq account's limits and billing. Credentials are
not loaded implicitly from `.env` and are never included in artifacts. The
existing `.env` is left untouched; `.env.example` contains a blank key and the
default Groq model. OpenAI is available only with explicit `--provider openai`
and its own `OPENAI_API_KEY` / `OPENAI_MODEL`; there is no automatic fallback.

Results distinguish compilation, clarification, unsupported requests, and
provider/validation failures. Reports preserve attempts, actual returned model
IDs, usage, prompt/schema hashes, and retrieved example IDs. Mocked tests assert
the strict-schema API request. The live house attempt returned HTTP 403 (edge
access denied, code 1010); successful live compatibility and translation quality
remain unmeasured. Optional `--traces FILE` adds independent labels for that
particular rule, with failures returned as repair feedback.

## Semantics

- Measurements (`state.*`) and inputs (`command.*`) are separate. The development
  predictor supplies pose and commanded speeds, not future measured velocity.
- Comparisons require exact units: m, rad, m/s, rad/s, or s. Strict and inclusive
  boundaries remain distinct in the Boolean monitor.
- `inside` means the circular robot footprint overlaps or touches a closed named
  rectangle/circle. Negating it requires clearance. Geometry uses an explicit frame.
- Expressions allow compare, inside, not, and, or. Missing signals or uncertain
  interval verdicts cannot permit a command.
- STL is an instantaneous predicate evaluated at each observation. Derived
  `region_NAME` signals are signed footprint-overlap distances from the configured
  geometry, not invented sensors. RTAMT robustness zero cannot distinguish strict
  and inclusive boundaries; labeled cases also check exact Boolean truth.
- A Twist has no action duration. Rules using `command.duration` can be checked
  offline when supplied, but remain UNKNOWN in this development runtime.
- Optional [reference equivalence](docs/reference-equivalence.md) checks numeric
  comparisons and Boolean combinations over explicit variable domains using Z3.
  It returns exact counterexamples and rejects unknown/unsupported results.
  Spatial footprint predicates are outside that solver fragment. It checks a
  supplied formal reference, not English intent or floating-point correctness.
- Temporal dwell and deadlines/eventually/until are not implemented. The separate
  consistency check detects direct contradictory conjuncts and affine bounds.
  Passing finite traces is not a semantic proof.

## Build and run the ROS development gate

```bash
bash scripts/setup.sh --existing-deps
source "$HOME/.cache/guardrailgen/ros2-humble/install/setup.bash"
```

`--existing-deps` explicitly verifies installed imports and skips rosdep installation.
This machine's rosdep database is uninitialized. With configured rosdep, use
`bash scripts/setup.sh`. Only GuardrailGen is built; outputs stay in Linux storage.

The gate consumes a proposed Twist and fresh odometry and publishes a checked
Twist. To load a compiled artifact, substitute its actual absolute path:

```bash
ros2 launch guardrailgen guardrailgen_sim.launch.py \
    operating_mode:=heuristic rules_file:='' \
    artifact_file:=/absolute/path/to/artifact.json \
    proposed_cmd_topic:=/guardrailgen_dev/proposal \
    safe_cmd_topic:=/guardrailgen_dev/output \
    odom_topic:=/guardrailgen_dev/odom
```

The artifact frame must match `odom_frame` (default odom). Set `use_sim_time:=true`
only with a matching simulation clock. Omit artifact_file to use the included
legacy YAML examples; do not supply both sources. The default mode is disabled.

The node checks readiness, source/receipt freshness, command expiry, malformed
messages, clock rollback, initial occupancy, and every nominal swept prediction
interval. All rules apply even without sensed obstacles. Compiled predicates
include their artifact footprint; legacy rules use predictor footprint inflation.
Every rejection publishes a zero emergency command, which is **not verified
physical braking**. Physical obstacle sensing and a certified backup are pending.

This legacy launch starts only the gate. The upstream controller publishes plan
arrays on `/parsed_plan`, not Twist on `/llm_cmd_vel`; its adapter is still pending.
The current four-process house integration consumes structured Groq plans,
adapts `/parsed_plan`, and checks the installed numerical predictor before
publishing `/cmd_vel` in domain 218. Use the linked integration guide for it.

## Status and layout

Verified on 2026-09-25 from a clean export of the tracked files: 242 tests
passed in Ubuntu Python 3.10 with RTAMT, ROS, and Z3; Windows Python 3.14 passed
200 with 17 platform-dependent skips. The three-package overlay previously built.
The house guide records offline goal-reaching and live bounded-run results.

See [implementation status](docs/implementation-status.md) for pending stages and
[integration baseline](docs/integration-baseline.md) for the exact upstream pin,
source defects, state/topic mappings, and remaining integration gates.

Evaluation results reported in the thesis are in [`results/`](results/README.md).
```text
src/guardrailgen/guardrailgen/
  schema/       versioned rule tree, monitors, STL
  compiler/     hosted adapter, retrieval, prompting, repairs
  validation/   RTAMT, reference states, direct contradictions
  runtime/      readiness, freshness, command gate
  api/          CLI
  artifacts.py  atomic content-addressed storage
  monitor_node.py / reachability.py / monitors.py
config/         example scenario and verified upstream revision
data/           hand-authored reference rule, labeled states, RQ1 corpus
results/        frozen thesis results (RQ1-RQ3, live case study); see results/README.md
scripts/        build, tests, CLI, optional pinned upstream fetch
```
