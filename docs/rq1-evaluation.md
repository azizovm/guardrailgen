# RQ1 compiler evaluation

Evaluates rule compilation (thesis RQ1, Section 5.2) on a hand-authored corpus.
Added 23 September 2026. The results reported in the thesis are in
`results/rq1/` (single complete run); `results/README.md` explains the other folders.

## Inputs (`data/rq1/`)

| File | Content |
| --- | --- |
| `scenario.json` | Evaluation scenario: kitchen, loading_area, school_zone, corridor (rectangles), charging_dock (circle); footprint 0.25 m; no measured-speed variable. |
| `corpus.json` | 50 test rules in 24 paraphrase families: 7 spatial, 13 global limit, 8 region-conditioned, 6 compound (34 in scope), 10 unsupported, 6 ambiguous (16 refusals). Hand-authored reference expressions. |
| `retrieval_library.json` | 12 curated examples. Disjoint from test rules (checked on load); no shared paraphrase family. |
| `domains.json` | Finite domains for the solver. |

## Configurations

| Config | Change vs. full |
| --- | --- |
| `full` | Schema text, top-3 lexical retrieval, Groq strict JSON-schema decoding |
| `no_retrieval` | No retrieved examples |
| `no_schema` | Configured schema removed from the system prompt (decoder enums unchanged) |
| `no_constrained` | No `response_format`; response schema described in the prompt; text parsed afterwards, parse errors go to repair |

All configurations use the same validator (structure, RTAMT, direct contradictions)
and at most two repairs. References are never used during compilation, so repairs
cannot see the answer.

## Scoring

Semantic agreement uses Z3 over the declared domains. Region atoms are abstracted
to Booleans with mutual exclusion for regions that one footprint cannot touch at
once. `equivalent` is a proof over the domains. A disagreement counts as
`not_equivalent` only when a concrete state is found where the two Boolean monitors
disagree; otherwise it is `unconfirmed`. This checks agreement with the author's
reference, not English intent.

Outcomes: `correct`, `wrong_accept` (accepted with wrong meaning, or accepted
although a refusal was expected), `refused_in_scope` (coverage loss), `unverified`,
`correct_refusal`, `failed` (validation failed after repairs, or provider error).
Summary metrics: first-attempt well-formedness, semantic accuracy over all in-scope
rules, first-attempt semantic accuracy, accuracy among accepted, acceptance coverage,
refusal accuracy, wrong accepts, repairs, calls, tokens, median latency.

## Commands (WSL)

```bash
cd /path/to/guardrailgen
bash scripts/eval_rq1.sh run --config full --dry-run --out runs/rq1_dry   # no API calls
bash scripts/eval_rq1.sh run --config full --max-calls 100 --env-file .env
bash scripts/eval_rq1.sh run --config no_retrieval --max-calls 100 --env-file .env
bash scripts/eval_rq1.sh run --config no_schema --max-calls 100 --env-file .env
bash scripts/eval_rq1.sh run --config no_constrained --max-calls 100 --env-file .env
bash scripts/eval_rq1.sh summarize runs/rq1
```

Runs resume: rules already in `runs/rq1/<config>/results.jsonl` are skipped. The
harness stops before a rule if fewer than 3 authorized calls remain. HTTP 429/5xx
and timeouts are retried with backoff (up to 5 times); retried calls count against
the cap. Estimated cost: about 1.6k prompt tokens per call plus reasoning/output,
roughly 50 to 80 calls per configuration.

## Limits

One model (`openai/gpt-oss-120b`), provider-default sampling, one run per rule and
configuration. The author wrote both the rules and the references. Region
geometry is operator-defined test data.
