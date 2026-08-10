"""
Does APOLLO-M recover the instability we planted?

This is the file that makes the simulation worth running. `simulate_data.py`
writes data/ground_truth.json recording which communities were given a rising
toxicity trend ("destabilising"), which were left stable, and which were made to
improve. The pipeline never sees that file. Here we compare what the pipeline
concluded against what was actually planted, and report precision/recall rather
than asserting that the system works.

Two things are measured:

  1. DETECTION — do the communities the meso layer ranks as least healthy match
     the communities we destabilised? Reported as precision/recall/F1 at k, plus
     ROC-AUC over the full CHI ranking, which is threshold-free.
  2. FORECAST — for communities with a TFT forecast, does the predicted
     direction of travel match the planted direction?

A negative result here is a real result. If recall is poor, that is a finding
about the pipeline, and reporting it honestly is worth more than a number that
cannot be reproduced.

HOW FAR THESE NUMBERS GO — read before quoting any of them.

The instability score reaches ROC-AUC 1.000 here. That is NOT evidence that
APOLLO-M detects real community instability, and it must never be reported as
accuracy on real data. The planted signal is a clean monotonic ramp, and the
instability score measures a recent-vs-baseline difference — it is looking for
the same shape that was planted, so a near-perfect score is close to circular.

What it does establish is worth stating precisely:

  * the pipeline is wired end to end and recovers a known signal, so a failure
    to alert on a real deteriorating community would be a modelling problem
    rather than a plumbing one;
  * ranking by CHI scored 0.575 against 0.649 for raw toxicity and 1.000 for the
    trend-aware score. That ordering is the finding: an index built from
    present-tense health cannot rank communities by how fast they are changing,
    which is what "forecasting instability" actually asks for.

Real-world performance is unmeasured, because no labelled dataset of genuinely
destabilising communities was available. Say that plainly.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
TRUTH_PATH = ROOT / "data" / "ground_truth.json"


def _norm(s: str) -> str:
    return str(s).replace("r/", "").strip().lower()


def roc_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    """AUC via the rank-sum identity — no sklearn dependency needed."""
    pos, neg = labels == 1, labels == 0
    if pos.sum() == 0 or neg.sum() == 0:
        return float("nan")
    order = scores.argsort()
    ranks = np.empty(len(scores), dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2)
                 / (pos.sum() * neg.sum()))


def main() -> None:
    if not TRUTH_PATH.exists():
        raise SystemExit("data/ground_truth.json missing — run simulate_data.py first")
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    truth = {_norm(k): v for k, v in truth.items()}

    meso = pd.read_csv(OUT / "meso_report.csv")
    meso["key"] = meso["subreddit"].map(_norm)
    meso = meso[meso["key"].isin(truth)].copy()
    if meso.empty:
        raise SystemExit("no overlap between meso_report and ground truth — "
                         "re-run the pipeline on the simulated data")

    meso["planted"] = meso["key"].map(
        lambda k: 1 if truth[k]["trajectory"] == "destabilising" else 0)
    n_pos = int(meso["planted"].sum())

    print("=" * 66)
    print("APOLLO-M — validation against planted ground truth")
    print("=" * 66)
    print(f"communities evaluated : {len(meso)}")
    print(f"planted destabilising : {n_pos}")
    print()

    # --- 1. detection ------------------------------------------------------
    # Lower CHI = less healthy, so CHI ascending should surface planted ones.
    ranked = meso.sort_values("community_health_index").reset_index(drop=True)
    auc = roc_auc(ranked["planted"].to_numpy(), -ranked["community_health_index"].to_numpy())

    print("DETECTION — ranking communities by Community Health Index")
    print(f"  ROC-AUC (threshold-free) : {auc:.3f}   (0.5 = chance)")
    for k in sorted({n_pos, 10, 15, 20}):
        if k < 1 or k > len(ranked):
            continue
        hits = int(ranked.head(k)["planted"].sum())
        prec, rec = hits / k, hits / max(1, n_pos)
        f1 = 0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec)
        print(f"  top-{k:<3} precision={prec:.2f}  recall={rec:.2f}  F1={f1:.2f}")

    # Toxicity alone, as a baseline the CHI must beat to justify its extra terms.
    auc_tox = roc_auc(ranked["planted"].to_numpy(), ranked["toxicity_rate"].to_numpy())
    print(f"  baseline: toxicity_rate alone ROC-AUC = {auc_tox:.3f}")
    print()

    # The instability score ranks by direction of travel rather than by current
    # level. Printed next to CHI so the comparison is explicit rather than
    # claimed — if it does not beat CHI here, it does not belong in the report.
    if "instability_score" in meso.columns:
        print("DETECTION — ranking by instability score (trend-aware)")
        r2 = meso.sort_values("instability_score", ascending=False).reset_index(drop=True)
        auc2 = roc_auc(r2["planted"].to_numpy(), r2["instability_score"].to_numpy())
        print(f"  ROC-AUC : {auc2:.3f}   (CHI was {auc:.3f}, toxicity {auc_tox:.3f})")
        for k in sorted({n_pos, 10, 20}):
            if 1 <= k <= len(r2):
                hits = int(r2.head(k)["planted"].sum())
                prec, rec = hits / k, hits / max(1, n_pos)
                f1 = 0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec)
                print(f"  top-{k:<3} precision={prec:.2f}  recall={rec:.2f}  F1={f1:.2f}")
        if "toxicity_trend" in meso.columns:
            auc3 = roc_auc(r2["planted"].to_numpy(), r2["toxicity_trend"].to_numpy())
            print(f"  toxicity_trend alone ROC-AUC = {auc3:.3f}")
        print("\n  top 12 by instability (* = planted destabilising):")
        for _, r in r2.head(12).iterrows():
            print(f"    {'*' if r['planted'] else ' '} {r['subreddit']:<26} "
                  f"inst={r['instability_score']:.3f}  trend={r.get('toxicity_trend', float('nan')):+.3f}")
        print()

    print("  worst 12 by CHI (* = planted destabilising):")
    for _, r in ranked.head(12).iterrows():
        print(f"    {'*' if r['planted'] else ' '} {r['subreddit']:<26} "
              f"CHI={r['community_health_index']:6.2f}  tox={r['toxicity_rate']:.3f}")
    print()

    # --- 2. forecast direction --------------------------------------------
    fc_path = OUT / "forecast_results.csv"
    if not fc_path.exists():
        print("FORECAST — forecast_results.csv absent; skipping")
        return
    fc = pd.read_csv(fc_path)
    if "subreddit" not in fc.columns:
        print("FORECAST — no per-community forecasts; skipping")
        return
    fc["key"] = fc["subreddit"].map(_norm)

    rows = []
    for key, g in fc.groupby("key"):
        if key not in truth:
            continue
        g = g.sort_values("day")
        if len(g) < 2:
            continue
        slope = float(np.polyfit(g["day"], g["p50"], 1)[0])
        planted_up = truth[key]["trajectory"] == "destabilising"
        rows.append({"key": key, "slope": slope,
                     "pred_up": slope > 0, "planted_up": planted_up,
                     "trajectory": truth[key]["trajectory"]})

    if not rows:
        print("FORECAST — no overlap with ground truth; skipping")
        return
    d = pd.DataFrame(rows)
    print("FORECAST — 5-day p50 trend vs planted direction")
    print(f"  communities forecast : {len(d)}")

    # Recall on the communities that actually deteriorate. This is the number
    # that matters operationally: missing a destabilising community is the
    # expensive error, and flagging a quiet one merely costs a look.
    dest = d[d["trajectory"] == "destabilising"]
    if len(dest):
        print(f"  destabilising predicted rising : "
              f"{int(dest['pred_up'].sum())}/{len(dest)} "
              f"({dest['pred_up'].mean():.0%})  <- recall")

    # Raw sign agreement is reported too, but it is a weak metric here and
    # saying so is part of the result: a 'stable' community has a true slope of
    # ~0, so the sign of its predicted slope is decided by noise. Counting those
    # as errors drags the headline down without indicating anything is wrong.
    agree = int((d["pred_up"] == d["planted_up"]).sum())
    print(f"  raw sign agreement (all)       : {agree}/{len(d)} ({agree/len(d):.0%}) "
          f"— depressed by stable communities whose true slope is ~0")

    # Threshold-free and immune to that problem: can the predicted slope
    # separate destabilising communities from the rest at all?
    auc_f = roc_auc((d["trajectory"] == "destabilising").to_numpy().astype(int),
                    d["slope"].to_numpy())
    print(f"  slope ROC-AUC (destabilising vs rest) : {auc_f:.3f}")
    print()
    for traj, g in d.groupby("trajectory"):
        print(f"    {traj:<15} mean slope = {g['slope'].mean():+.5f}  "
              f"({int(g['pred_up'].sum())}/{len(g)} predicted rising)")

    # Persist, so the dashboard, the exporter and the report quote a measured
    # file instead of a number somebody typed. Every value here is reproducible
    # by re-running simulate_data.py -> the pipeline -> this script.
    out = {
        "evaluated_on": "declared simulation with planted ground truth "
                        "(data/ground_truth.json) — NOT real Reddit instability",
        "communities": len(meso),
        "planted_destabilising": n_pos,
        "detection": {
            "instability_score_roc_auc": round(auc2, 4) if "instability_score" in meso.columns else None,
            "chi_roc_auc": round(auc, 4),
            "toxicity_only_roc_auc": round(auc_tox, 4),
        },
        "forecast_tft": {
            "destabilising_recall": round(float(dest["pred_up"].mean()), 4) if len(dest) else None,
            "slope_roc_auc": round(auc_f, 4),
            "mean_slope_by_trajectory": {
                t: round(float(g["slope"].mean()), 6) for t, g in d.groupby("trajectory")
            },
        },
        "caveat": "The instability score looks for the same shape that was planted, "
                  "so its ROC-AUC is close to circular and is a wiring check, not "
                  "real-world accuracy. The TFT slope AUC is an independent result: "
                  "the forecaster was never shown the ground truth.",
    }
    (OUT / "validation.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT / 'validation.json'}")


if __name__ == "__main__":
    main()
