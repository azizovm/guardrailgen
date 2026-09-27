"""RQ3 analysis: aggregate episode summaries and plot paired trajectories.

    python -m guardrailgen.evaluation.rq3 summarize [runs/rq3]
    python -m guardrailgen.evaluation.rq3 plot [runs/rq3]      # needs matplotlib
"""
import argparse
import json
from pathlib import Path
import statistics
import sys

CONDITIONS = ("unfiltered", "physical_only", "guardrailgen", "oracle")


def load(base):
    rows = []
    for path in sorted((Path(base) / "episodes").glob("*/*/*/summary.json")):
        if "_infra_" in str(path):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_dir"] = str(path.parent)
        rows.append(data)
    return rows


def _mean(values):
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 4) if values else None


def aggregate(rows):
    table = {}
    for scenario in sorted({r["scenario_rule"] for r in rows}):
        for condition in CONDITIONS:
            group = [r for r in rows if r["scenario_rule"] == scenario and r["condition"] == condition]
            if not group:
                continue
            oracle_safe = sum(r.get("oracle_safe_decisions_nominal_replay") or 0 for r in group)
            false_r = sum(r.get("rule_false_restrictions_nominal_replay") or 0 for r in group)
            decisions = sum(r.get("decisions") or 0 for r in group)
            reached = [r for r in group if r.get("goal_reached")]
            table.setdefault(scenario, {})[condition] = {
                "episodes": len(group),
                "goal_reached": len(reached),
                "episodes_with_violation": sum(bool(r.get("any_actual_rule_violation")) for r in group),
                "violation_samples": sum(r.get("reference_violation_samples") or 0 for r in group),
                "measured_speed_violation_samples": (sum(r.get("measured_speed_violation_samples") or 0 for r in group)
                                                     if scenario == "kitchen_speed" else None),
                "collision_events": sum(r.get("collision_contact_events") or 0 for r in group),
                "collision_measurement_complete": all(r.get("collision_measurement_complete") for r in group),
                "intervention_rate_pooled": round(sum(r.get("interventions") or 0 for r in group) / decisions, 4) if decisions else None,
                "rule_interventions": sum(r.get("rule_interventions") or 0 for r in group),
                "false_restriction_rate_nominal_pooled": round(false_r / oracle_safe, 4) if oracle_safe else None,
                "mean_time_to_goal_s": _mean([r.get("elapsed_sim_seconds") for r in reached]),
                "mean_path_length_m": _mean([r.get("path_length_m") for r in group]),
                "max_filter_latency_ms": max((r.get("max_filter_latency_ms") or 0 for r in group), default=None),
                "end_reasons": {s: sum(r["status"] == s for r in group) for s in sorted({r["status"] for r in group})},
            }
    return table


def markdown(table):
    keys = ["episodes", "goal_reached", "episodes_with_violation", "violation_samples",
            "measured_speed_violation_samples", "collision_events", "intervention_rate_pooled",
            "rule_interventions", "false_restriction_rate_nominal_pooled", "mean_time_to_goal_s",
            "max_filter_latency_ms"]
    out = []
    for scenario, block in table.items():
        conditions = [c for c in CONDITIONS if c in block]
        out += [f"### {scenario}", "", "| metric | " + " | ".join(conditions) + " |",
                "|---|" + "---|" * len(conditions)]
        for key in keys:
            out.append(f"| {key} | " + " | ".join(str(block[c][key]) for c in conditions) + " |")
        out.append("| end_reasons | " + " | ".join(
            ", ".join(f"{k}:{v}" for k, v in block[c]["end_reasons"].items()) for c in conditions) + " |")
        out.append("")
    return "\n".join(out)


def summarize(base):
    rows = load(base)
    table = aggregate(rows)
    (Path(base) / "summary.json").write_text(json.dumps(table, indent=2), encoding="utf-8")
    text = markdown(table)
    (Path(base) / "summary.md").write_text(text, encoding="utf-8")
    print(text)


def plot(base):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    rows = load(base)
    colors = {"unfiltered": "#d62728", "physical_only": "#ff7f0e", "guardrailgen": "#1f77b4", "oracle": "#2ca02c"}
    out_dir = Path(base) / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)
    for scenario in sorted({r["scenario_rule"] for r in rows}):
        for config in sorted({r["config_id"] for r in rows if r["scenario_rule"] == scenario}):
            group = [r for r in rows if r["scenario_rule"] == scenario and r["config_id"] == config]
            fig, ax = plt.subplots(figsize=(8, 4.2), layout="constrained")
            cfg = json.loads((Path(group[0]["_dir"]) / "run_configuration.json").read_text(encoding="utf-8"))
            region = json.loads(Path(cfg["experiment"]["scenario"]).read_text(encoding="utf-8")
                                if Path(cfg["experiment"]["scenario"]).is_absolute() else
                                (Path(base).resolve().parents[1] / cfg["experiment"]["scenario"]).read_text(encoding="utf-8"))["regions"]["kitchen"]
            ax.add_patch(Rectangle((region["xmin"], region["ymin"]), region["xmax"] - region["xmin"],
                                   region["ymax"] - region["ymin"], color="orange", alpha=0.35, label="kitchen zone"))
            for r in sorted(group, key=lambda r: CONDITIONS.index(r["condition"])):
                points = [json.loads(l) for l in (Path(r["_dir"]) / "trajectory.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
                if not points:
                    continue
                ax.plot([p["world_x"] for p in points], [p["world_y"] for p in points], color=colors[r["condition"]],
                        lw=1.8, label=f"{r['condition']} ({'goal' if r.get('goal_reached') else r['status']})")
            start, goal = group[0].get("start"), group[0].get("goal")
            if start:
                ax.plot(start[0], start[1], "ks", ms=6, label="start")
            ax.plot(goal[0], goal[1], "k*", ms=11, label="goal")
            ax.set_aspect("equal"); ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
            ax.set_title(f"{scenario}, configuration {config}: executed ground-truth paths")
            ax.legend(fontsize=7, loc="best")
            fig.savefig(out_dir / f"{scenario}_{config}.png", dpi=160)
            plt.close(fig)
    print("plots written to", out_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("summarize", "plot"))
    parser.add_argument("base", nargs="?", default="runs/rq3")
    args = parser.parse_args(argv)
    summarize(args.base) if args.command == "summarize" else plot(args.base)


if __name__ == "__main__":
    sys.exit(main())
