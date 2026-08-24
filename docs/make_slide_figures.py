"""Two pastel figures for the presentation: the headline result, and the timeline."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

OUT = Path(__file__).resolve().parent / "slides_img"
OUT.mkdir(exist_ok=True)
plt.rcParams["font.family"] = "Times New Roman"

INK, MUTED = "#33415C", "#6B7A99"
BLUE, LAV, TEAL, APRICOT, SAGE = "#7FA8D4", "#A99BD1", "#7FC0BA", "#E8AF87", "#A9C79E"

# ── 1. The finding: four ranking signals on the same task ────────────────────
fig, ax = plt.subplots(figsize=(10, 5.2), dpi=200)
labels = ["GraphSAGE\nstructural risk", "Community\nHealth Index",
          "Raw toxicity\nrate", "Instability score\n(trend-aware)"]
vals = [0.4154, 0.5748, 0.6489, 1.000]
colors = [APRICOT, APRICOT, BLUE, TEAL]
bars = ax.barh(labels, vals, color=colors, edgecolor="white", height=0.62)
ax.axvline(0.5, color=MUTED, ls="--", lw=1.2)
ax.text(0.512, 3.42, "chance = 0.5", color=MUTED, fontsize=11.5, va="center")
for b, v in zip(bars, vals):
    ax.text(v + 0.012, b.get_y() + b.get_height()/2, f"{v:.3f}",
            va="center", fontsize=14, color=INK, fontweight="bold")
ax.set_xlim(0, 1.12)
ax.set_xlabel("ROC-AUC — ability to rank destabilising communities", fontsize=13, color=INK)
ax.tick_params(labelsize=12.5, colors=INK)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
for s in ("left", "bottom"):
    ax.spines[s].set_color("#D5DCE8")
ax.set_title("Same task, four signals — measured against withheld ground truth",
             fontsize=15.5, color=INK, pad=14, fontweight="bold")
fig.tight_layout()
fig.savefig(OUT / "finding_chart.png", facecolor="white")
print("  finding_chart.png")

# ── 2. Timeline: planned vs delivered ────────────────────────────────────────
fig, ax = plt.subplots(figsize=(11, 5.4), dpi=200)
tasks = [
    ("Data pipeline & toxicity scoring", 1, 2, SAGE),
    ("Community Health Index & graph metrics", 2, 2, SAGE),
    ("Forecasting, clustering, anomalies", 3, 2, SAGE),
    ("Data-integrity audit & rebuild", 4, 2, TEAL),
    ("Misinformation module integration", 5, 2, TEAL),
    ("CHI bug fix & alert verification", 6, 2, TEAL),
    ("PostgreSQL persistence", 7, 2, BLUE),
    ("REST API, JWT, role-based access", 8, 2, BLUE),
    ("Moderation recommender", 9, 2, BLUE),
    ("Dashboard, monitoring, deployment", 10, 2, LAV),
    ("Real Reddit ingestion & validation", 11, 2, LAV),
]
for i, (name, start, dur, col) in enumerate(tasks):
    y = len(tasks) - i - 1
    ax.barh(y, dur, left=start, color=col, edgecolor="white", height=0.6)
    ax.text(start + dur + 0.15, y, "done", va="center", fontsize=10.5, color=MUTED)
ax.set_yticks(range(len(tasks)))
ax.set_yticklabels([t[0] for t in reversed(tasks)], fontsize=11.5, color=INK)
ax.set_xticks(range(1, 14))
ax.set_xlabel("Project week", fontsize=13, color=INK)
ax.set_xlim(0.5, 14.5)
ax.tick_params(colors=INK, labelsize=11)
ax.grid(axis="x", color="#EBEFF6", lw=1)
ax.set_axisbelow(True)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color("#D5DCE8")
# The legend sits under the axes: inside the plot it lands on top of the last
# two bars and their "done" labels.
ax.legend(handles=[Patch(color=SAGE, label="Build"), Patch(color=TEAL, label="Audit & correct"),
                   Patch(color=BLUE, label="Serve"), Patch(color=LAV, label="Deploy & validate")],
          loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4,
          frameon=False, fontsize=11.5)
ax.set_title("Planned schedule against what was delivered — 11 workstreams, all complete",
             fontsize=15.5, color=INK, pad=14, fontweight="bold")
fig.tight_layout()
fig.savefig(OUT / "timeline_chart.png", facecolor="white")
print("  timeline_chart.png")
