"""Compile the two RQ3 scenario rules with the production compiler (1 to 3 calls each).

    python3 scripts/rq3_compile_rules.py --env-file .env [--provider openrouter]
Writes runs/rq3/rules/<scenario>/<sha>.json and runs/rq3/rules/index.json.
Each artifact must pass the same activation test states as the oracle rule.
"""
import argparse
import json
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src/guardrailgen"))
deps = Path.home() / ".cache/guardrailgen/python310-packages"  # RTAMT for activation tests
if deps.is_dir():
    sys.path.insert(1, str(deps))

from guardrailgen.artifacts import read_json, save_artifact, write_json_atomic  # noqa: E402
from guardrailgen.compiler import Compiler, GroqBackend, OpenRouterBackend  # noqa: E402
from guardrailgen.evaluation.rq1 import load_groq_env  # noqa: E402
from guardrailgen.schema import Scenario  # noqa: E402
from guardrailgen.simulation.episode import SCENARIO_RULES, scenario_traces  # noqa: E402
from guardrailgen.validation import validate_rule  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(root / ".env"))
    parser.add_argument("--provider", choices=("groq", "openrouter"), default="openrouter")
    args = parser.parse_args()
    load_groq_env(args.env_file)
    backend_class = OpenRouterBackend if args.provider == "openrouter" else GroqBackend
    if not os.environ.get(backend_class.key_env, "").strip():
        raise SystemExit(backend_class.key_env + " is not set")
    scenario = Scenario.from_dict(read_json(root / "config/turtlebot_house.json"))
    out = root / "runs/rq3/rules"
    index = {}
    for name, spec in SCENARIO_RULES.items():
        traces = scenario_traces(scenario, name)
        compiler = Compiler(backend_class(max_output_tokens=2500), scenario,
                            validator=lambda rule, s, t=traces: validate_rule(rule, s, require_rtamt=True, traces=t))
        result = compiler.compile(spec["text"], spec["id"])
        write_json_atomic(out / name / "compilation.json", result.to_dict())
        entry = {"text": spec["text"], "status": result.status, "attempts": len(result.attempts)}
        if result.ok:
            path = save_artifact(result.artifact, out / name)
            entry.update(artifact=str(path.resolve()), expression=result.artifact["rule"]["expression"],
                         stl=result.artifact["stl"])
        index[name] = entry
        print(json.dumps({name: entry}, indent=2))
    write_json_atomic(out / "index.json", index)
    return 0 if all(e["status"] == "compiled" for e in index.values()) else 2


if __name__ == "__main__":
    sys.exit(main())
