"""Create the README figure from saved outputs, without a basemap/downloads."""

import csv
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def main():
    with (ROOT / "outputs/v2/extended_candidates.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    colors = {"Sufficient": "#16816b", "Moderate": "#d48a16", "Congested": "#b94348"}
    fig = plt.figure(figsize=(13, 6.7), facecolor="#f5f7f8")
    grid = fig.add_gridspec(2, 2, width_ratios=[1.7, 1], hspace=0.5, wspace=0.35)
    ax = fig.add_subplot(grid[:, 0])
    for status, color in colors.items():
        selected = [r for r in rows if r["grid_status"] == status]
        ax.scatter([float(r["longitude"]) for r in selected],
                   [float(r["latitude"]) for r in selected],
                   s=19 if status == "Sufficient" else 35,
                   c=color, alpha=0.8, linewidths=0, label=f"{status} ({len(selected)})")
    ax.set(title="Proposed locations · saved grid classification",
           xlabel="Longitude (°)", ylabel="Latitude (°)")
    ax.set_aspect(1.3)
    ax.grid(alpha=0.15)
    ax.legend(loc="lower left", frameon=True, fontsize=9)
    for index, (column, title, labels) in enumerate([
        ("grid_status", "Modeled grid status", list(colors)),
        ("phase", "Proposed deployment phases", ["1", "2", "3"]),
    ]):
        panel = fig.add_subplot(grid[index, 1])
        counts = Counter(r[column] for r in rows)
        values = [counts[label] for label in labels]
        panel.barh(labels, values, color=list(colors.values()) if index == 0
                   else ["#1d5474", "#4f83a2", "#91aebf"], height=0.55)
        panel.invert_yaxis()
        panel.set(title=title, xlabel="Stations", xlim=(0, max(values) * 1.18))
        for y, value in enumerate(values):
            panel.text(value + max(values) * 0.02, y, f"{value:,}", va="center", fontsize=11)
        panel.spines[["top", "right"]].set_visible(False)
    chargers = sum(int(r["n_chargers_proposed"]) for r in rows)
    fig.suptitle(f"Spain EV charging network | {len(rows):,} proposed stations · {chargers:,} chargers",
                 x=0.07, ha="left", fontsize=18, fontweight="bold", color="#153849")
    fig.text(0.07, 0.035, "Source: committed outputs/v2/extended_candidates.csv | 2027 scenario; proposals, not installed assets.",
             fontsize=10, color="#445563")
    fig.subplots_adjust(left=0.07, right=0.96, bottom=0.14, top=0.86)
    target = ROOT / "docs/images/v2-network-summary.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target, dpi=170, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(target)


if __name__ == "__main__":
    main()
