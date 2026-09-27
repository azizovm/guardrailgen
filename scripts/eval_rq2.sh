#!/usr/bin/env bash
# RQ2 fault injection (offline analyze; optional live repair).
#   bash scripts/eval_rq2.sh analyze
#   bash scripts/eval_rq2.sh repair --max-calls 80 --env-file .env

set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
dependency_dir="${GUARDRAILGEN_TEST_DEPS:-$HOME/.cache/guardrailgen/python310-packages}"
if [[ -d "$dependency_dir" ]]; then
    export PYTHONPATH="$dependency_dir${PYTHONPATH:+:$PYTHONPATH}"
fi
export PYTHONPATH="$repo_root/src/guardrailgen${PYTHONPATH:+:$PYTHONPATH}"
cd -- "$repo_root"
exec python3 -m guardrailgen.evaluation.rq2 "$@"
