# Results reported in the thesis

This folder is a frozen copy of the `runs/` output directory at thesis
submission. The evaluation scripts still write to `runs/` (gitignored); rerunning
them does not change this folder. A path written as `runs/X` in `docs/` refers
to `results/X` here.

The logs are unmodified raw output. They contain absolute paths from the machine
that produced them (for example ROS workspace and rule-artifact paths); these
were left as recorded so the logs stay unaltered.

| Folder | Thesis section | Content |
| --- | --- | --- |
| `rq1/` | RQ1 compiler accuracy (Ch. 5) | Single reported run: 50 rules x 4 configurations (full, no_retrieval, no_schema, no_constrained). `summary.md` is the table source; per-rule `results.jsonl` and provider `invocations.jsonl`. |
| `rq1_rep2/`, `rq1_rep3/` | not reported | Incomplete repetition attempts (rep2: 28/18/4/8 rules, rep3: 3/6/5/0 rules per configuration). Kept for transparency; the thesis reports the single complete run. |
| `rq1_dry/` | none | Dry run of the RQ1 harness without API calls. |
| `rq2/` | RQ2 fault injection (Ch. 5) | `mutants.jsonl` (269 faults), `summary.md` per operator/detector, `repair.jsonl` and `repair_summary.json`. |
| `rq2_discarded/` | none | Repair run aborted by Groq rate limiting; superseded by `rq2/repair.jsonl`. |
| `rq3/` | RQ3 closed-loop episodes (Ch. 5) | 2 scenarios x 4 conditions x 5 configurations = 40 episodes under `episodes/<scenario>/<condition>/<config>/`; `summary.md`, `batch_log.jsonl`, compiled rules in `rules/`, per-configuration plots in `plots/`. |
| `rq3_discarded/` | Ch. 5 (discarded episode) | Oracle keep-out episode recorded before a fix; see `docs/rq3-evaluation.md`. |
| `development/house_*` | live case study (Ch. 5) and development history | Gazebo house episodes, including the live Groq runs. The documented runs are listed in `docs/house-results.md` and `docs/four-terminal-setup.md`. |
| `development/compilation_*` | development history | Rule-compilation reports and content-addressed artifacts. |

Regenerating summaries from these logs (writes back into the given folder):

```bash
python3 -m guardrailgen.evaluation.rq1 summarize results/rq1
python3 -m guardrailgen.evaluation.rq3 summarize results/rq3
```
