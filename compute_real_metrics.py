"""Make the dashboard numbers real:
  1. Recompute Community Health Index from the real meso features (the stored CHI
     was 0 for every row — a broken aggregation, not real data).
  2. Train a real toxicity classifier on the Jigsaw/Davidson tweets the team used
     and report genuine accuracy + macro/micro F1 into outputs/metrics.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"

# ── 1. Report CHI as the pipeline computed it ───────────────────────────────
# This script used to RECOMPUTE CHI here with weights (70/30/5/5) that differ
# from the pipeline's own (35/30/20/15 in MesoLayer.community_health_index) and
# then overwrite meso_report.csv in place. That gave the project two different
# CHI definitions and made the published numbers depend on whether this script
# had been run since the pipeline. main.py is the single source of truth; this
# script now only reads and summarises.
meso = pd.read_csv(OUT / "meso_report.csv")


def band(chi: float) -> str:
    return ("LOW" if chi >= 85 else "MEDIUM" if chi >= 75
            else "HIGH" if chi >= 65 else "CRITICAL")


dist = meso["community_health_index"].apply(band).value_counts().to_dict()
print("CHI recomputed. range %.1f-%.1f | alerts: %s"
      % (meso["community_health_index"].min(), meso["community_health_index"].max(), dist))

# ── 2. Real toxicity classifier on Jigsaw (Davidson) → macro/micro F1 ───────
jig = pd.read_csv(ROOT / "data" / "jigsaw_toxicity.csv")
X, y = jig["tweet"].fillna("").astype(str), jig["class"].astype(int)
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
vec = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=2)
clf = LogisticRegression(max_iter=1000, C=4.0)
clf.fit(vec.fit_transform(Xtr), ytr)
pred = clf.predict(vec.transform(Xte))

acc = accuracy_score(yte, pred)
f1_macro = f1_score(yte, pred, average="macro")
f1_micro = f1_score(yte, pred, average="micro")
prec = precision_score(yte, pred, average="macro", zero_division=0)
rec = recall_score(yte, pred, average="macro", zero_division=0)
print("Toxicity classifier (Jigsaw held-out %d): acc %.3f | F1 macro %.3f micro %.3f"
      % (len(yte), acc, f1_macro, f1_micro))

# ── 3. Write metrics.json ───────────────────────────────────────────────────
metrics = {
    "Toxicity (TF-IDF+LR, Jigsaw)": {
        "accuracy": f"{acc:.1%}", "F1 macro": f"{f1_macro:.3f}",
        "F1 micro": f"{f1_micro:.3f}", "precision": f"{prec:.3f}", "recall": f"{rec:.3f}",
    },
}

# Everything below was previously written here as a hardcoded string literal —
# "99.07%", "99.77%", "0.0077" — and then displayed in the dashboard, exported to
# Grafana and quoted in the technical report as if it had been measured. Nothing
# computed those numbers. They are replaced with an explicit status so an
# unmeasured module can never again be mistaken for an evaluated one.
#
# To turn any of these into a real metric, the module has to actually run and be
# scored on held-out data; until then "not_evaluated" is the honest value.
metrics["CEREBRO misinfo (TF-IDF+LR)"] = {
    "status": "not_evaluated",
    "reason": "ISOT fake-news corpus (data/fake_news_corpus.csv) is not present in "
              "this checkout, and modules/cerebro_detector.py is not called by the "
              "pipeline. No held-out score exists.",
}
metrics["Moderation (RandomForest)"] = {
    "status": "not_evaluated",
    "reason": "modules/moderation_recommender.py has no callers and no saved model; "
              "its training data is generated with np.random, so any accuracy from "
              "it would be self-labelled noise.",
}
metrics["GNN (GraphSAGE)"] = {
    "status": "not_run",
    "reason": "modules/gnn_model.py is implemented but never invoked; no weights "
              "are saved and no gnn_risk column reaches any output.",
}
metrics["TFT forecaster"] = {
    "horizon": "5d", "bands": "p10/p50/p90",
    "status": "measured against planted ground truth — see outputs/validation.json "
              "(destabilising recall, slope ROC-AUC). Evaluated on the declared "
              "simulation, not on real Reddit instability.",
}
(OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))
print("wrote outputs/metrics.json")
