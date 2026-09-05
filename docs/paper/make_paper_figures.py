#!/usr/bin/env python3
"""
Figures 2-10 of the audit paper, at 300 dpi, from the committed outputs.

    python docs/paper/make_paper_figures.py

Reads docs/paper/results.json and bootstrap_draws.npz (written by
bootstrap_ci.py; produced automatically here if missing) plus the same CSV
inputs. Figure 1 is reproduced from the source project report and is not
generated. Figure 7(a) needs data/apollo_daily.csv; without it the pre-built
figures/fig07_trajectories_prebuilt.png is used and a note is printed.
"""
from __future__ import annotations

import json
import runpy
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from scipy.stats import rankdata  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)

if not (HERE / "results.json").exists() or not (HERE / "bootstrap_draws.npz").exists():
    runpy.run_path(str(HERE / "bootstrap_ci.py"), run_name="__main__")
R = json.loads((HERE / "results.json").read_text())
D = np.load(HERE / "bootstrap_draws.npz")

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["DejaVu Serif", "Liberation Serif"],
    "font.size": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.08,
})
BLUE, RED, GREY, DARK = "#2b6cb0", "#c53030", "#a0aec0", "#2d3748"


def strip(name: str) -> str:
    return name[2:] if name.startswith("r/") else name


def save(fig, name: str) -> None:
    fig.savefig(FIG / name)
    plt.close(fig)
    print("wrote", (FIG / name).relative_to(ROOT))


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #
truth = json.loads((ROOT / "data" / "ground_truth.json").read_text())
meso = pd.read_csv(ROOT / "outputs" / "meso_report.csv")
meso["key"] = meso["subreddit"].map(strip)
y = meso["key"].map(lambda k: truth[k]["trajectory"] == "destabilising").astype(int).to_numpy()
real = pd.read_csv(ROOT / "outputs" / "real" / "meso_report.csv")
real_fc = pd.read_csv(ROOT / "outputs" / "real" / "forecast_results.csv")

# --------------------------------------------------------------------------- #
# Figure 2: the five-step audit
# --------------------------------------------------------------------------- #
steps = [
    ("Construct\nbenchmark", "60 communities,\nplanted ramps"),
    ("Withhold\nanswer", "ground_truth.json,\nread by no stage"),
    ("Run system\nunchanged", "no pipeline\nmodification"),
    ("Test each\ncomponent", "distinct values,\nstandalone AUC"),
    ("Compare vs\nbaseline", "OLS slope,\nsingle inputs"),
]
fig, ax = plt.subplots(figsize=(9, 2.2))
ax.set_xlim(0, 10)
ax.set_ylim(0, 2.2)
ax.axis("off")
for i, (title, sub) in enumerate(steps):
    x = 0.3 + i * 1.95
    box = FancyBboxPatch((x, 0.75), 1.5, 1.05, boxstyle="round,pad=0.04",
                         fc="white", ec=DARK, lw=1.2)
    ax.add_patch(box)
    ax.text(x + 0.75, 1.28, title, ha="center", va="center", fontsize=9.5, weight="bold", color=DARK)
    ax.text(x + 0.75, 0.42, sub, ha="center", va="center", fontsize=7.5, color="#4a5568")
    if i < len(steps) - 1:
        ax.annotate("", xy=(x + 1.95, 1.28), xytext=(x + 1.55, 1.28),
                    arrowprops=dict(arrowstyle="->", color=DARK, lw=1.2))
ax.text(5, 0.02, "Steps 4 and 5 have label-free counterparts in the checklist of §7 "
                  "(distinct-value counts, per-component orderings, a linear-fit baseline)",
        ha="center", va="bottom", fontsize=7.5, style="italic", color="#4a5568")
save(fig, "fig02_procedure.png")

# --------------------------------------------------------------------------- #
# Figure 3: component variation and weight
# --------------------------------------------------------------------------- #
t1 = R["table1"]
comps = [("Toxicity\nrate", "toxicity"), ("Polari-\nsation", "polarisation"),
         ("Echo-\nchamber", "echo"), ("Author\nchurn", "churn")]
fig, (a, b) = plt.subplots(2, 1, figsize=(6.4, 5.6), gridspec_kw={"height_ratios": [3, 1.6], "hspace": 0.75})
distinct = [t1[k]["distinct"] for _, k in comps]
colors = [BLUE if d > 30 else RED for d in distinct]
bars = a.bar([c for c, _ in comps], distinct, color=colors, width=0.62)
for bar, d in zip(bars, distinct):
    a.text(bar.get_x() + bar.get_width() / 2, d + 1.2, str(d), ha="center", va="bottom",
           fontsize=10, weight="bold", color=bar.get_facecolor())
a.axhline(R["n"], ls="--", color=GREY, lw=1)
a.text(1.5, R["n"] + 1.2, f"n = {R['n']} communities", ha="center", va="bottom", fontsize=8, color="#718096")
a.set_ylim(0, R["n"] + 10)
a.set_ylabel("distinct values")
a.set_title("(a) Component variation across the scored population", fontsize=10.5, pad=8)

left = 0
for (label, k), col in zip(comps, colors):
    w = t1[k]["weight"]
    b.barh([0], [w], left=left, color=col, height=0.6, edgecolor="white", lw=1.5)
    b.text(left + w / 2, 0, str(w), ha="center", va="center", fontsize=10, color="white", weight="bold")
    b.text(left + w / 2, 0.42, label.replace(chr(10), " ").replace("- ", ""), ha="center", va="bottom",
           fontsize=8, color=col)
    left += w
inert = sum(t1[k]["weight"] for _, k in comps if t1[k]["distinct"] <= 30)
b.set_xlim(0, 100)
b.set_yticks([])
b.set_xlabel("share of CHI penalty weight (%)")
b.set_title("(b) Weight carried by inert components", fontsize=10.5, pad=8)
b.text(50, -0.72, f"{inert}% of the index's weight is constant for {t1['polarisation']['modal_count']} "
                  f"of {R['n']} communities", ha="center", va="top", fontsize=9, color=RED, weight="bold")
b.set_ylim(-1.1, 0.85)
b.spines["left"].set_visible(False)
save(fig, "fig03_components.png")

# --------------------------------------------------------------------------- #
# Figure 4: ROC curves
# --------------------------------------------------------------------------- #
def roc(score: np.ndarray, y: np.ndarray):
    order = np.argsort(-score, kind="stable")
    s, yy = score[order], y[order]
    tps = np.cumsum(yy)
    fps = np.cumsum(1 - yy)
    # collapse ties: keep the last index of each distinct score
    keep = np.r_[np.diff(s) != 0, True]
    tpr = np.r_[0, tps[keep] / yy.sum()]
    fpr = np.r_[0, fps[keep] / (1 - yy).sum()]
    return fpr, tpr


t2 = R["table2"]
fig, ax = plt.subplots(figsize=(5.2, 5.0))
for name, key, s, col in [
    ("Instability score", "instability", meso["instability_score"].to_numpy(float), DARK),
    ("Raw toxicity rate", "toxicity", meso["toxicity_rate"].to_numpy(float), BLUE),
    ("CHI (low-first)", "chi_low_first", -meso["community_health_index"].to_numpy(float), RED),
]:
    f, t = roc(s, y)
    ax.step(f, t, where="post", color=col, lw=1.8, label=f"{name} — {t2[key]['auc']:.3f}")
ax.plot([0, 1], [0, 1], ls=":", color=GREY, lw=1, label="chance — 0.500")
ax.set_xlabel("false positive rate")
ax.set_ylabel("true positive rate")
ax.set_title("Detection of planted destabilisation", fontsize=11)
ax.legend(loc="lower right", frameon=False, fontsize=9)
ax.set_aspect("equal")
save(fig, "fig04_roc.png")

# --------------------------------------------------------------------------- #
# Figure 5: point estimates with intervals
# --------------------------------------------------------------------------- #
rows = [("Instability score", "instability", DARK), ("Raw toxicity rate", "toxicity", RED),
        ("CHI (low-first)", "chi_low_first", RED)]
fig, ax = plt.subplots(figsize=(6.2, 2.6))
for i, (name, key, col) in enumerate(rows):
    a_, (lo, hi) = t2[key]["auc"], t2[key]["ci"]
    yy = len(rows) - 1 - i
    ax.plot([lo, hi], [yy, yy], color=col, lw=1.8)
    ax.plot([lo, lo], [yy - 0.15, yy + 0.15], color=col, lw=1.8)
    ax.plot([hi, hi], [yy - 0.15, yy + 0.15], color=col, lw=1.8)
    ax.plot(a_, yy, "o" if key != "instability" else "D", color=col, ms=7)
    ax.text(min(hi + 0.02, 1.02), yy, f"{a_:.3f}", va="center", ha="left", fontsize=9, color=col)
ax.axvline(0.5, ls=":", color=GREY, lw=1)
ax.text(0.5, len(rows) - 0.45, "chance", ha="center", fontsize=8, color="#718096")
ax.set_yticks(range(len(rows)))
ax.set_yticklabels([r[0] for r in rows][::-1])
ax.set_xlim(0.3, 1.12)
ax.set_xticks([0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
ax.set_xlabel("ROC-AUC (point estimate, 95% bootstrap CI)")
save(fig, "fig05_intervals.png")

# --------------------------------------------------------------------------- #
# Figure 6: paired-difference distributions
# --------------------------------------------------------------------------- #
mask = D["mask"]
t3 = R["table3"]
fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.2))
for ax, (a_, b_, title, col, key) in zip(axes, [
    ("auc_toxicity", "auc_chi_low_first", "(a) Toxicity − CHI: interval crosses zero", RED,
     "toxicity_minus_chi_low_first"),
    ("auc_instability", "auc_chi_low_first", "(b) Instability − CHI: interval excludes zero", DARK,
     "instability_minus_chi_low_first"),
]):
    d = (D[a_] - D[b_])[mask]
    ax.hist(d, bins=60, color=col, alpha=0.75)
    lo, hi = t3[key]["ci"]
    for v in (lo, hi):
        ax.axvline(v, color="black", ls="--", lw=1)
    ax.axvline(0, color="black", lw=1.2)
    ax.set_title(title, fontsize=9.5)
    ax.set_xlabel("Δ AUC")
    right = key.startswith("toxicity")
    ax.text(0.97 if right else 0.03, 0.95,
            f"Δ = {t3[key]['delta']:+.3f}\n95% CI [{lo:+.3f}, {hi:+.3f}]\nP(Δ>0) = {t3[key]['p_gt_0']:.3f}",
            transform=ax.transAxes, va="top", ha="right" if right else "left", fontsize=7.5, family="monospace")
axes[0].set_ylabel("bootstrap resamples")
fig.tight_layout()
save(fig, "fig06_paired.png")

# --------------------------------------------------------------------------- #
# Figure 7: planted ramps and slope AUC
# --------------------------------------------------------------------------- #
daily_path = ROOT / "data" / "apollo_daily.csv"
t4 = R["table4"]
if daily_path.exists() and "ols_full" in t4:
    daily = pd.read_csv(daily_path)
    daily["key"] = daily["subreddit"].map(strip)
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.2, 3.6), gridspec_kw={"width_ratios": [1.6, 1]})
    for key, g in daily.sort_values("time_idx").groupby("key"):
        planted = truth[key]["trajectory"] == "destabilising"
        a.plot(g["time_idx"], g["avg_toxicity"].rolling(7, min_periods=1).mean(),
               color=RED if planted else GREY, alpha=0.8 if planted else 0.5, lw=1 if planted else 0.7)
    a.plot([], [], color=GREY, label="stable / improving")
    a.plot([], [], color=RED, label="planted destabilising")
    a.legend(frameon=False, fontsize=8, loc="upper left")
    a.set_xlabel("day")
    a.set_ylabel("mean toxicity (7-day rolling)")
    a.set_title("(a) Planted ramps are visible in the raw series", fontsize=9.5)
    names = ["OLS slope\n(full window)", "OLS slope\n(final 30 d)", "Temporal Fusion\nTransformer"]
    vals = [t4["ols_full"]["auc"], t4["ols_last30"]["auc"], t4["tft"]["auc"]]
    bars = b.bar(names, vals, color=[DARK, DARK, RED], width=0.6)
    for bar, v in zip(bars, vals):
        b.text(bar.get_x() + bar.get_width() / 2, v + 0.01, f"{v:.3f}", ha="center", fontsize=9, weight="bold")
    b.axhline(0.5, ls=":", color=GREY, lw=1)
    b.set_ylim(0, 1.08)
    b.set_ylabel("slope ROC-AUC")
    b.set_title("(b) Deep model vs. a straight line", fontsize=9.5)
    b.tick_params(axis="x", labelsize=8)
    fig.tight_layout()
    save(fig, "fig07_trajectories.png")
else:
    shutil.copy(FIG / "fig07_trajectories_prebuilt.png", FIG / "fig07_trajectories.png")
    print("note: data/apollo_daily.csv absent; Figure 7 copied from the pre-built image")

# --------------------------------------------------------------------------- #
# Figure 8: five-day quantile forecasts, real corpus, four most toxic communities
# --------------------------------------------------------------------------- #
top4 = list(real.sort_values("toxicity_rate", ascending=False)["subreddit"][:4])
fig, axes = plt.subplots(1, 4, figsize=(9.6, 2.7), sharey=True)
for ax, sub in zip(axes, top4):
    g = real_fc[real_fc["subreddit"] == sub].sort_values("day")
    ax.fill_between(g["day"], g["p10"], g["p90"], color=BLUE, alpha=0.18, label="p10–p90")
    ax.plot(g["day"], g["p50"], "-o", color=BLUE, ms=3.5, lw=1.4, label="p50")
    ax.set_title(sub, fontsize=9.5)
    ax.set_xticks([1, 3, 5])
    ax.set_xlabel("horizon (days)")
axes[0].set_ylabel("predicted toxicity")
axes[0].legend(frameon=False, fontsize=7.5, loc="upper left")
fig.suptitle("Five-day quantile forecasts on the real corpus — bands widen with horizon", fontsize=10, y=1.02)
fig.tight_layout()
save(fig, "fig08_forecasts_real.png")

# --------------------------------------------------------------------------- #
# Figure 9: mean toxicity by real community
# --------------------------------------------------------------------------- #
srt = real.sort_values("toxicity_rate", ascending=True)
fig, ax = plt.subplots(figsize=(6.4, 5.8))
ax.barh(srt["subreddit"], srt["toxicity_rate"] * 100, color=BLUE, height=0.7)
ax.set_xlabel("mean toxicity (%)")
prov = R["real"].get("provenance", {})
ax.set_title(f"Real corpus: {R['real']['comments']:,} comments, {R['real']['n']} communities\n"
             "(ordering not supplied to the system)", fontsize=10)
ax.tick_params(axis="y", labelsize=8.5)
save(fig, "fig09_real_toxicity.png")

# --------------------------------------------------------------------------- #
# Figure 10: two orderings of the same communities
# --------------------------------------------------------------------------- #
rc, ri = R["real"]["rank_by_chi"], R["real"]["rank_by_instability"]
subs = list(rc)
n = len(subs)
fig, ax = plt.subplots(figsize=(6.6, 8.2))
for s in subs:
    y0, y1 = n - rc[s], n - ri[s]
    big = abs(rc[s] - ri[s]) >= 5
    ax.plot([0, 1], [y0, y1], color=RED if big else "#cbd5e0", lw=2 if big else 1, alpha=0.9 if big else 0.8, zorder=2 if big else 1)
    ax.text(-0.03, y0, s, ha="right", va="center", fontsize=8.5, color=RED if big else DARK)
    ax.text(1.03, y1, s, ha="left", va="center", fontsize=8.5, color=RED if big else DARK)
ax.set_xlim(-0.55, 1.55)
ax.set_ylim(-0.8, n)
ax.axis("off")
ax.text(0, -0.55, "ranked by CHI\n(what the dashboard shows)", ha="center", va="top", fontsize=9.5)
ax.text(1, -0.55, "ranked by instability\n(trend-aware)", ha="center", va="top", fontsize=9.5)
ax.set_title(f"Two orderings of the same {n} communities\nred = moves 5+ places", fontsize=11)
save(fig, "fig10_two_orderings.png")
