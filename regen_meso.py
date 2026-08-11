"""Regenerate outputs/meso_report.csv with the corrected community selection.

Why this exists: main.py's loader used to read a 50k-row head of a CSV that is
sorted by subreddit name, so every published number described 33 communities
beginning with 'A'. The loader now selects the largest communities in the corpus
instead. This script re-runs just the EDA -> micro -> meso path so the dashboard,
the exporter and the database pick up the corrected set without retraining the
GNN, the clusterer or the TFT.
"""
import logging
import warnings

from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

from main import (Config, DataLoader_APOLLO, MesoLayer,  # noqa: E402
                  MicroLayer, UnsupervisedLayer)

log = logging.getLogger("regen")
logging.basicConfig(level=logging.INFO, format="%(message)s")

ROOT = Path(__file__).resolve().parent
cfg = Config()
loader = DataLoader_APOLLO(cfg)

comments = loader.load_reddit_comments()
comments = MicroLayer(cfg).analyze_batch(comments)

graph = loader.load_hyperlink_graph()
meso = MesoLayer(cfg)
results = meso.analyze_all_communities(comments, graph)

df = pd.DataFrame(results).sort_values("community_health_index").reset_index(drop=True)
out = cfg.OUTPUT_DIR / "meso_report.csv"
df.to_csv(out, index=False)

print(f"\nwrote {len(df)} communities -> {out}")
print(f"CHI   min/mean/max: {df.community_health_index.min():.1f} / "
      f"{df.community_health_index.mean():.1f} / {df.community_health_index.max():.1f}")
print(f"tox   min/mean/max: {df.toxicity_rate.min():.3f} / "
      f"{df.toxicity_rate.mean():.3f} / {df.toxicity_rate.max():.3f}")
print("\nworst 10 by CHI:")
print(df.head(10)[["subreddit", "community_health_index", "toxicity_rate",
                   "total_comments"]].to_string(index=False))
print("\nhealthiest 5:")
print(df.tail(5)[["subreddit", "community_health_index", "toxicity_rate",
                  "total_comments"]].to_string(index=False))

# Clusters must be regenerated in the same pass. clusters_report.csv is read
# directly by the dashboard's Clusters page, so leaving it behind means the
# dashboard shows one set of communities on Overview and a completely different,
# older set on Clusters — which is exactly what had happened (381 rows of
# subreddits that no longer appear anywhere else).
#
# The autoencoder step of run_unsupervised is deliberately skipped here: it trains
# on torch.randn(...), i.e. random noise rather than community data, so it cannot
# inform the clustering. KMeans/DBSCAN below operate on the real meso features.
# ── GNN structural risk ─────────────────────────────────────────────────────
# The trained GraphSAGE weights existed but were never consumed, because
# modules/gnn_model.py imports torch_geometric and the pipeline could not load
# it. modules/gnn_infer.py runs the same trained weights without that
# dependency, so the model finally contributes a column.
#
# The score is added ALONGSIDE the Community Health Index rather than folded
# into it. Changing the CHI formula would invalidate every validation figure
# already measured against ground truth, and re-deriving those hours before a
# demonstration is the wrong trade. Weighting it into CHI is a deliberate next
# step, not an oversight.
try:
    from modules.gnn_infer import community_risk
    risk = community_risk(graph, results)
    if risk:
        key = df["subreddit"].astype(str).str.replace(r"^r/", "", regex=True).str.lower()
        raw = key.map(risk)
        hit = int(raw.notna().sum())
        # The GNN was trained with "at risk" defined as CHI < 75, and almost all
        # of the 35,776 graph nodes carry no CHI at all, so they defaulted to the
        # safe class. That imbalance compresses every sigmoid into [0, 0.017]:
        # the model still separates communities (15,131 distinct outputs) but its
        # absolute scale is not a usable probability. We publish the percentile
        # rank among analysed communities and state why, rather than a number the
        # training set cannot support.
        df["gnn_risk_raw"] = raw.round(6)
        df["gnn_risk"] = raw.rank(pct=True).round(4)
        print(f"\nGNN structural risk: {hit}/{len(df)} communities present in the graph")
        if hit:
            print(f"  raw sigmoid {raw.min():.5f} .. {raw.max():.5f} "
                  f"(compressed by training-set imbalance)")
            print(f"  published as percentile rank "
                  f"{df['gnn_risk'].min():.2f} .. {df['gnn_risk'].max():.2f}")
        if False:
            print(f"  range {df['gnn_risk'].min():.3f} .. {df['gnn_risk'].max():.3f}")
    else:
        print("\nGNN: weights unavailable — column skipped")
except Exception as exc:  # noqa: BLE001
    print(f"\nGNN inference skipped: {exc}")

# ── Misinformation classifier: measured, and deliberately NOT aggregated ────
# The supervised classifier is trained on long-form news articles (ISOT). Applied
# to this corpus of short social posts it labels 99.5% of them as misinformation,
# while classifying news-style claims correctly (verified separately). That is a
# textbook out-of-domain failure, not a property of the communities, so a
# per-community misinformation rate derived from it would be noise presented as a
# measurement. We record the diagnostic instead of publishing the rate.
try:
    import json as _json
    import pickle
    clf_path = ROOT / "models" / "cerebro_classifier.pkl"
    if clf_path.exists():
        with open(clf_path, "rb") as fh:
            clf = pickle.load(fh)
        sample = comments.groupby("subreddit").head(200)
        social_rate = float(pd.Series(
            clf.predict(sample["body"].astype(str).tolist())).mean())
        news_fake = clf.predict([
            "Scientists confirm 5G towers spread coronavirus and WHO is hiding it",
            "Secret documents reveal a government plot to control the population"])
        news_real = clf.predict([
            "The central bank raised interest rates by 25 basis points on Wednesday.",
            "Parliament passed the budget after a three-hour debate, officials said."])
        diag = {
            "classifier": "TF-IDF + LogisticRegression, trained on ISOT news articles",
            "news_style_fake_detected": int(sum(news_fake)) ,
            "news_style_fake_total": len(news_fake),
            "news_style_real_correct": int(sum(1 for v in news_real if v == 0)),
            "news_style_real_total": len(news_real),
            "flagged_rate_on_social_corpus": round(social_rate, 4),
            "conclusion": "Correct on news-style text; labels almost all short social "
                          "posts as misinformation. Out-of-domain. A per-community "
                          "rate is therefore not published; the classifier serves "
                          "news/claim verification, which is CEREBRO's input domain.",
        }
        (cfg.OUTPUT_DIR / "misinfo_domain_check.json").write_text(
            _json.dumps(diag, indent=2), encoding="utf-8")
        print("\nMisinformation classifier diagnostic:")
        print(f"  news-style: {diag['news_style_fake_detected']}/2 fake, "
              f"{diag['news_style_real_correct']}/2 real correct")
        print(f"  social corpus flagged rate: {social_rate:.3f}  -> out-of-domain")
        print(f"  wrote outputs/misinfo_domain_check.json")
    else:
        print("\nMisinformation: models/cerebro_classifier.pkl absent — skipped")
except Exception as exc:  # noqa: BLE001
    print(f"\nMisinformation diagnostic skipped: {exc}")

# ── Supervised moderation recommendation ────────────────────────────────────
# The RandomForest reproduces a documented threshold policy over the same five
# features. It is reported as a policy model rather than a predictive one: its
# training labels were generated by that policy, so its accuracy measures
# agreement with a rule and not agreement with reality (see the report).
try:
    import pickle
    rec_path = ROOT / "models" / "moderation_recommender.pkl"
    if rec_path.exists():
        with open(rec_path, "rb") as fh:
            rec = pickle.load(fh)
        ACTIONS = {0: "NO_ACTION", 1: "MONITOR", 2: "WARN",
                   3: "INCREASE_MODERATION", 4: "EMERGENCY_INTERVENTION"}
        X = df[["community_health_index", "toxicity_rate", "polarization",
                "churn_rate", "echo_chamber_index"]].to_numpy()
        df["recommended_action"] = [ACTIONS.get(int(a), "UNKNOWN")
                                    for a in rec.predict(X)]
        counts = df["recommended_action"].value_counts().to_dict()
        print(f"\nModeration recommender: {counts}")
    else:
        print("\nModeration recommender: model absent — skipped")
except Exception as exc:  # noqa: BLE001
    print(f"\nModeration recommendation skipped: {exc}")

df.to_csv(out, index=False)

unsup = UnsupervisedLayer(cfg)
feat = unsup.cluster_communities(df.copy())
feat = unsup.detect_outlier_communities(feat)
feat.to_csv(cfg.OUTPUT_DIR / "clusters_report.csv", index=False)
print(f"\nwrote {len(feat)} rows -> outputs/clusters_report.csv")
if "cluster" in feat.columns:
    print("cluster sizes:", feat["cluster"].value_counts().sort_index().to_dict())
if "is_outlier" in feat.columns:
    print("outlier communities:", int(feat["is_outlier"].sum()))
