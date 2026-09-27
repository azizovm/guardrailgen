#!/usr/bin/env bash
# RQ1 compiler evaluation (WSL, Python 3.10 cached deps incl. RTAMT and Z3).
#   bash scripts/eval_rq1.sh run --config full --max-calls 100 --env-file .env
#   bash scripts/eval_rq1.sh run --config full --dry-run
#   bash scripts/eval_rq1.sh summarize
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
dependency_dir="${GUARDRAILGEN_TEST_DEPS:-$HOME/.cache/guardrailgen/python310-packages}"
if [[ -d "$dependency_dir" ]]; then
    export PYTHONPATH="$dependency_dir${PYTHONPATH:+:$PYTHONPATH}"
fi
export PYTHONPATH="$repo_root/src/guardrailgen${PYTHONPATH:+:$PYTHONPATH}"
cd -- "$repo_root"
exec python3 -m guardrailgen.evaluation.rq1 "$@"
