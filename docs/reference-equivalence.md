# Reference equivalence for numeric and Boolean rules

The optional validator checks whether a candidate expression and an independently
authored reference differ anywhere in explicit variable domains. It supports
the current `compare`, `not`, `and`, and `or` fragment. It preserves strict
versus inclusive comparisons and keeps state measurements separate from commands.

This checks formal expressions, not English intent. The reference must be reviewed
independently. It does not establish reachability coverage, backup feasibility,
floating-point implementation correctness, or equality of conservative UNKNOWN
verdicts over boxes. Spatial `inside` predicates and temporal operators are outside
this solver path. Existing spatial trace checks and Gazebo enforcement still work.

## Reproduce without model calls

The optional pinned dependency is [z3-solver 4.15.3.0](https://pypi.org/project/z3-solver/4.15.3.0/).
In Ubuntu from the project directory:

```bash
python3 -m pip install --no-deps --only-binary=:all: \
  --target "$HOME/.cache/guardrailgen/python310-packages" -r requirements-solver.txt
source scripts/stack_env.sh
python3 -m guardrailgen validate data/equivalence/command_speed_candidate.json \
  --scenario config/turtlebot_development.json \
  --reference data/equivalence/command_speed_reference.json \
  --domains data/equivalence/domains.json --require-rtamt \
  --output-dir artifacts/equivalence-demo
```

The two development fixtures express the same inclusive command-magnitude limit
using different Boolean forms. This command was executed successfully on
22 September 2026; RTAMT passed and equivalence returned `equivalent`. These are
hand-authored demonstration fixtures, not held-out translation evaluation data.
The declared command domain includes negative values to check expression meaning;
it does not claim that the published forward-only robot data cover reverse motion.

Domains are a separate required input for this check, leaving existing scenario
artifacts compatible:

```json
{"command.linear_speed": {"min": -0.5, "max": 0.5, "unit": "m/s"}}
```

Every variable in either expression needs a finite closed interval with its
schema unit. Missing variables, wrong units, unknown names, and empty intervals
are errors. A single-point interval is allowed. Restricting a domain can change
the result, so every report stores the domains and a digest of all proof inputs.

`compile` accepts the same `--reference`, `--domains`, and
`--solver-timeout-ms` options. It preflights the reference check before contacting
a model. Supplying neither option preserves the existing compilation workflow;
no reference proof is then claimed. Model calls still require their normal
credentials and authorization.

## Outcomes and repair evidence

The validator asks whether the domains and a disagreement between the two
predicates are satisfiable, using linear real arithmetic. Constants use exact
decimal-rational semantics, matching the mathematical literals emitted in STL.
The [Z3 solver interface](https://z3prover.github.io/api/html/classz3py_1_1_solver.html)
provides the satisfiability result, model, timeout setting, and unknown reason.

| Status | Meaning and activation behavior |
| --- | --- |
| `equivalent` | No disagreement exists in the declared domains; requested check passes. |
| `not_equivalent` | An exact rational counterexample is recorded; validation fails. |
| `unknown` | Solver could not conclude, including timeout; validation fails. |
| `unavailable` | Optional solver cannot be imported; requested validation fails. |
| `unsupported` | Spatial geometry is present; requested proof fails explicitly. |

The default solver timeout is 1000 ms, configurable from 1 to 60000 ms. It bounds
the solver query, not the whole compiler or a hard real-time control deadline.
Each call uses an independent solver context for concurrent validation.

A counterexample includes exact rational signal values, candidate/reference
verdicts, approximate JSON numbers, and `float_replay_verified`. That flag is
false when rounding cannot reproduce the rational disagreement within the
declared domain. Do not present rounded values as a verified trace in that case.
For example, a strict/inclusive boundary can differ only at an integer too large
for binary64 to represent exactly.

When compiler repair is enabled, the counterexample and validation errors reach
the model within its existing two-repair limit. The full reference expression is
removed from repair feedback and is never added to retrieval. Proof provenance
and complete local validation reports are preserved even for failed attempts.
Accepted proof evidence
still stores the reference, domains, solver version, timeout and input digest in
the accepted artifact. Reload rechecks the proof and digest; a passing status
string alone is insufficient. Such artifacts therefore require the optional
solver when loaded. Existing artifacts without this evidence retain their old
validation path.

## Verification

The full WSL Python 3.10 suite passed **204 tests**, including ROS, RTAMT and Z3.
New cases cover Boolean equivalence, strict boundaries, negative-bound omissions,
state/input confusion, domain restrictions, malformed domains, unsupported
geometry, missing dependencies, simulated solver timeout, rounded witnesses,
concurrent contexts, bounded compiler repair, reference-answer isolation,
artifact tampering/revalidation, and CLI failure before an unnecessary API call.
No new model call or Gazebo episode was used for this milestone.
