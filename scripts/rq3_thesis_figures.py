"""Thesis figures for RQ3 from recorded ground truth and executed commands (no simulation)."""
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
EP = ROOT / "runs/rq3/episodes"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "runs/rq3/plots"
OUT.mkdir(parents=True, exist_ok=True)
K = json.loads((ROOT / "config/turtlebot_house.json").read_text())["regions"]["kitchen"]
R = json.loads((ROOT / "config/turtlebot_house.json").read_text())["footprint_radius"]
COND = [("unfiltered", "No filter", "#d62728", "-"), ("physical_only", "SafeLLMRA only", "#ff7f0e", "--"),
        ("guardrailgen", "SafeLLMRA + GuardrailGen", "#1f77b4", "-"), ("oracle", "SafeLLMRA + reference rule", "#2ca02c", ":")]
plt.rcParams.update({"font.size": 9})


def points(scenario, cond, cfg):
    path = EP / scenario / cond / cfg / "trajectory.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def zone(ax, inflated=True):
    ax.add_patch(Rectangle((K["xmin"], K["ymin"]), K["xmax"] - K["xmin"], K["ymax"] - K["ymin"],
                           color="orange", alpha=0.35, lw=0, label="kitchen zone"))
    if inflated:
        ax.add_patch(Rectangle((K["xmin"] - R, K["ymin"] - R), K["xmax"] - K["xmin"] + 2 * R, K["ymax"] - K["ymin"] + 2 * R,
                               fill=False, ls="--", lw=0.8, color="darkorange", label="zone + footprint radius"))


fig, axes = plt.subplots(2, 1, figsize=(6.3, 6.2), layout="constrained")
for ax, cfg in zip(axes, ("c1", "c5")):
    zone(ax)
    summary = json.loads((EP / "kitchen_keepout/oracle" / cfg / "summary.json").read_text())
    for cond, label, color, style in COND:
        p = points("kitchen_keepout", cond, cfg)
        ax.plot([q["world_x"] for q in p], [q["world_y"] for q in p], color=color, ls=style, lw=1.6, label=label)
    ax.plot(*summary["start"][:2], "ks", ms=5, label="start")
    ax.plot(*summary["goal"], "k*", ms=9, label="goal")
    ax.set_aspect("equal"); ax.set_ylabel("y [m]"); ax.set_title(f"configuration {cfg}", fontsize=9)
axes[-1].set_xlabel("x [m]")
handles, labels = axes[0].get_legend_handles_labels()
fig.legend(handles, labels, fontsize=7, loc="outside lower center", ncol=4)
fig.savefig(OUT / "rq3_keepout_paths.png", dpi=200)

fig, ax = plt.subplots(figsize=(6.3, 2.8), layout="constrained")
ax.axvspan(K["xmin"], K["xmax"], color="orange", alpha=0.35, lw=0, label="kitchen zone (x extent)")
ax.axvspan(K["xmin"] - R, K["xmin"], color="orange", alpha=0.12, lw=0, label="footprint touches zone")
ax.axvspan(K["xmax"], K["xmax"] + R, color="orange", alpha=0.12, lw=0)
ax.axhline(0.1, color="k", lw=0.8, ls="--", label="limit 0.1 m/s")
for cond, label, color, style in COND:
    p = points("kitchen_speed", cond, "c1")
    ax.plot([q["world_x"] for q in p], [q["executed"][0] for q in p], color=color, ls=style, lw=1.4, label=label)
ax.set_xlabel("x [m]"); ax.set_ylabel("commanded v [m/s]"); ax.set_ylim(-0.02, 0.47)
ax.legend(fontsize=7, loc="upper center", ncol=3)
fig.savefig(OUT / "rq3_speed_profile.png", dpi=200)
print("written", OUT)
