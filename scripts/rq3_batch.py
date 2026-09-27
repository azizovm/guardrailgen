"""Run the RQ3 matrix: scenarios x conditions x start/goal configurations.

Needs the prepared house world running (scripts/house_environment.sh --prepared)
and no other controller. Uses the deterministic goal-seeking proposal source,
the experimental body-frame SafeLLMRA predictor and waypoint guidance in every
condition (guidance only activates after an operator-rule rejection in the
keep-out scenario). No model calls.

    bash scripts/rq3_batch.sh                       # whole matrix, resumes
    bash scripts/rq3_batch.sh --only c1 --scenarios kitchen_keepout   # smoke test
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = ("unfiltered", "physical_only", "guardrailgen", "oracle")
SCENARIOS = ("kitchen_keepout", "kitchen_speed")
# Outcomes caused by the test infrastructure rather than by the condition.
INFRASTRUCTURE = {"interrupted", "sensor_readiness_timeout", "sensor_freshness_fault",
                  "world_odom_frame_mismatch", "command_path_not_exclusive",
                  "wall_clock_budget_exceeded", "simulation_clock_rollback", "rule_activation_failed"}


def log(entry):
    entry["time"] = datetime.now(timezone.utc).isoformat()
    with (ROOT / "runs/rq3/batch_log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    print(json.dumps(entry), flush=True)


def run(cmd, timeout):
    return subprocess.run(cmd, cwd=ROOT, timeout=timeout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Comma-separated config ids")
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--conditions", default=",".join(CONDITIONS))
    parser.add_argument("--attempts", type=int, default=2, help="Tries per episode after infrastructure faults")
    args = parser.parse_args()
    configs = json.loads((ROOT / "config/rq3_configs.json").read_text(encoding="utf-8"))
    seconds = configs["episode_seconds"]
    wanted = set(args.only.split(",")) if args.only else None
    index_path = ROOT / "runs/rq3/rules/index.json"
    rules = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    (ROOT / "runs/rq3").mkdir(parents=True, exist_ok=True)
    for config in configs["configs"]:
        if wanted and config["id"] not in wanted:
            continue
        for scenario in args.scenarios.split(","):
            for condition in args.conditions.split(","):
                out = ROOT / "runs/rq3/episodes" / scenario / condition / config["id"]
                summary_path = out / "summary.json"
                if summary_path.exists():
                    status = json.loads(summary_path.read_text(encoding="utf-8")).get("status")
                    if status not in INFRASTRUCTURE:
                        continue
                artifact = None
                if condition == "guardrailgen":
                    artifact = (rules.get(scenario) or {}).get("artifact")
                    if not artifact:
                        log({"episode": str(out), "skipped": "no compiled artifact; run scripts/rq3_compile_rules.py"})
                        continue
                for attempt in range(1, args.attempts + 1):
                    if out.exists():
                        shutil.move(str(out), str(out) + f"_infra_{int(time.time())}")
                    if run([sys.executable, "scripts/reset_house.py"], 60).returncode:
                        log({"episode": str(out), "error": "reset failed"}); return 2
                    x, y, yaw = config["start"]
                    if run([sys.executable, "scripts/set_start.py", str(x), str(y), str(yaw)], 60).returncode:
                        log({"episode": str(out), "error": "teleport failed"}); return 2
                    time.sleep(3)
                    cmd = [sys.executable, "-m", "guardrailgen.simulation.episode", "--root", str(ROOT),
                           "--controller", "goal-seeking", "--condition", condition, "--scenario-rule", scenario,
                           "--predictor", "safellmra_body_frame_experimental", "--waypoint-guidance", "--guidance-sides", "top",
                           "--seconds", str(seconds), "--goal", *map(str, config["goal"]),
                           "--start", str(x), str(y), str(yaw), "--config-id", config["id"], "--out-dir", str(out)]
                    if artifact:
                        cmd += ["--rule-artifact", artifact]
                    started = time.monotonic()
                    try:
                        code = run(cmd, seconds * 4 + 120).returncode
                    except subprocess.TimeoutExpired:
                        code = "timeout"
                    status = None
                    if summary_path.exists():
                        status = json.loads(summary_path.read_text(encoding="utf-8")).get("status")
                    log({"episode": str(out.relative_to(ROOT)), "attempt": attempt, "exit": code, "status": status,
                         "wall_s": round(time.monotonic() - started, 1)})
                    if status and status not in INFRASTRUCTURE:
                        break
    return 0


if __name__ == "__main__":
    sys.exit(main())
