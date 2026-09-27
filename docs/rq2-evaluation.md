# RQ2 fault-injection evaluation

Measures which validation checks detect faulty compilations (thesis RQ2,
Section 5.3). Added 23 September 2026. Reported results: `results/rq2/`. Both the offline analysis and the live repair
experiment (40 injected faults, 40 repaired in one round) have been run.

## Method

For each of the 16 in-scope paraphrase families of the RQ1 corpus, 15 mutation
operators are applied at every applicable site of the hand-authored reference:

- Structural: `unknown_variable` (state.linear_speed, not configured),
  `unit_error` (km/h), `unknown_region` (garage), `temporal_operator` (eventually).
- Semantic (well-formed, wrong meaning): `flip_direction`, `strictness`,
  `threshold_x10`, `sign_flip`, `wrong_variable`, `swap_region`, `drop_negation`,
  `drop_condition`, `drop_conjunct`, `and_or_swap`, `contradiction`.

Duplicate mutants are removed. A mutant counts as a real fault only when a
concrete state is found where its monitor and the reference monitor disagree;
mutants the solver proves equivalent would be excluded (none occurred).

Layers, each run independently on every mutant:

| Layer | Needs a reference? | Check |
| --- | --- | --- |
| structural | no | schema, grounding, units, operators |
| validator | no | RTAMT parse + direct contradiction check |
| random20 | yes | 20 uniform random states labeled by the reference monitor |
| boundary | yes | boundary-value bank: thresholds, +-0.01, 0, domain ends, footprint touch/clear points of every region; labeled by the reference monitor (20 to 1620 states) |
| solver | yes | Z3 agreement, fail-closed |

Because real faults are defined by a concrete disagreement, the solver catches
all real faults by construction. The informative result is how many faults the
cheaper layers miss.

## Result (offline, deterministic)

269 mutants, all real faults (75 structural, 194 semantic); the 16 correct
references pass every layer (0 false rejections).

| Pipeline | All faults | Semantic faults |
| --- | --- | --- |
| always-on (structural + validator) | 31.2% | 4.6% |
| + random 20 states | 78.4% | 70.1% |
| + boundary bank | 100% | 100% |
| + boundary + solver | 100% | 100% |

Per operator: `runs/rq2/summary.md`. Strictness faults (`<=` vs `<`) are never
caught by random states (0/24); only boundary states or the solver catch them.

Interpretation limits: the boundary bank is generated from the reference's own
thresholds, so it is strong against single-constant mutations by design. Both
reference-based layers require an approved reference or test oracle; without
one, only the always-on layers apply, and they catch structural faults but
almost no semantic ones. Mutation operators approximate, but are not, the
errors a real LLM makes; RQ1 reports the real errors.

## Commands (WSL)

```bash
bash scripts/eval_rq2.sh analyze                      # offline, about 15 s
bash scripts/eval_rq2.sh repair --max-calls 80 --env-file .env   # optional, live (OpenRouter default)
```

`repair` injects one real fault per (family, operator), up to `--sample 40`, as
the compiler's first attempt; the model then gets up to two repairs with the
validation errors, failing test states and the solver counterexample, never the
reference itself. Output: `runs/rq2/repair.jsonl`, `repair_summary.json`.
