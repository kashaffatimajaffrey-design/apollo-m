"""
Run the full pipeline on the REAL Reddit corpus.

Collecting real comments and displaying them on their own page proved the
ingestion path works, but it left the real data disconnected: the Community
Health Index, the clusters, the forecast, the alerts, the API, Grafana and
Prometheus all still described the simulation. A page that nothing downstream
consumes is a demonstration, not an integration.

This drives the real corpus through the same layers the benchmark uses:

    micro (already scored)  ->  meso (CHI, instability, polarisation, churn)
    ->  unsupervised (clusters, outliers)  ->  act (alerts, recommended action)

and writes the same output files, so every consumer -- dashboard, API, exporter,
database -- shows real communities without a single change to those components.
That is the point of keeping ingestion behind a narrow interface.

The declared simulation is retained, and remains the basis of the ground-truth
validation in the report: it is the only source where the answer is known in
advance. Real data is what the system runs on; the simulation is how its recall
is measured.

    python run_real_pipeline.py
"""

from __future__ import annotations

import json
import logging
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(message)s")

from main import Config, DataLoader_APOLLO, MesoLayer, UnsupervisedLayer  # noqa: E402

ROOT = Path(__file__).resolve().parent
SCORED = ROOT / "data" / "reddit_live_scored.csv"
OUT = ROOT / "outputs"
log = logging.getLogger("real-pipeline")


def main() -> None:
    if not SCORED.exists():
        raise SystemExit(
            "data/reddit_live_scored.csv not found — run score_real_reddit.py first")

    cfg = Config()
    df = pd.read_csv(SCORED)
    # The meso layer expects the pipeline's column names and an r/ prefix.
    df["subreddit"] = df["subreddit"].astype(str).apply(
        lambda s: s if s.startswith("r/") else f"r/{s}")
    df["created_utc"] = pd.to_datetime(df["created_utc"], unit="s", errors="coerce")
    df = df.dropna(subset=["created_utc", "subreddit", "toxicity_score"])
    print(f"real corpus: {len(df):,} comments, "
          f"{df['subreddit'].nunique()} communities, "
          f"{df['created_utc'].dt.date.nunique()} days")

    graph = DataLoader_APOLLO(cfg).load_hyperlink_graph()
    meso = MesoLayer(cfg)
    results = meso.analyze_all_communities(df, graph)
    if not results:
        raise SystemExit("meso layer produced nothing — check MIN_COMMENTS_PER_SUB")

    m = pd.DataFrame(results).sort_values("community_health_index").reset_index(drop=True)
    print(f"\nmeso: {len(m)} communities passed the minimum-comments filter")
    print(f"  CHI        {m.community_health_index.min():.1f} .. "
          f"{m.community_health_index.max():.1f}")
    print(f"  toxicity   {m.toxicity_rate.min():.3f} .. {m.toxicity_rate.max():.3f}")

    # GNN structural risk — same treatment as the benchmark run.
    try:
        from modules.gnn_infer import community_risk
        risk = community_risk(graph, results)
        if risk:
            key = m["subreddit"].str.replace(r"^r/", "", regex=True).str.lower()
            raw = key.map(risk)
            m["gnn_risk_raw"] = raw.round(6)
            m["gnn_risk"] = raw.rank(pct=True).round(4)
            print(f"  GNN        {int(raw.notna().sum())}/{len(m)} present in the graph")
    except Exception as exc:  # noqa: BLE001
        print(f"  GNN skipped: {exc}")

    # Recommended action from the trained policy model.
    try:
        import pickle
        rp = ROOT / "models" / "moderation_recommender.pkl"
        if rp.exists():
            with open(rp, "rb") as fh:
                rec = pickle.load(fh)
            ACTIONS = {0: "NO_ACTION", 1: "MONITOR", 2: "WARN",
                       3: "INCREASE_MODERATION", 4: "EMERGENCY_INTERVENTION"}
            X = m[["community_health_index", "toxicity_rate", "polarization",
                   "churn_rate", "echo_chamber_index"]].to_numpy()
            m["recommended_action"] = [ACTIONS.get(int(a), "UNKNOWN")
                                       for a in rec.predict(X)]
            print(f"  actions    {m['recommended_action'].value_counts().to_dict()}")
    except Exception as exc:  # noqa: BLE001
        print(f"  recommender skipped: {exc}")

    m.to_csv(OUT / "meso_report.csv", index=False)

    unsup = UnsupervisedLayer(cfg)
    feat = unsup.detect_outlier_communities(unsup.cluster_communities(m.copy()))
    feat.to_csv(OUT / "clusters_report.csv", index=False)
    print(f"  clusters   {feat['cluster'].value_counts().sort_index().to_dict()}"
          if "cluster" in feat else "  clusters   n/a")

    # Daily series for the forecaster, in the shape gen_forecasts.py expects.
    daily = (df.assign(date=df["created_utc"].dt.floor("D"))
               .groupby(["subreddit", "date"], as_index=False)
               .agg(avg_toxicity=("toxicity_score", "mean"),
                    toxic_rate=("is_toxic", "mean"),
                    comment_count=("id", "count"),
                    unique_authors=("author", "nunique")))
    daily["subreddit"] = daily["subreddit"].str.replace(r"^r/", "", regex=True)
    daily = daily.sort_values(["subreddit", "date"]).reset_index(drop=True)
    daily["time_idx"] = daily.groupby("subreddit").cumcount()
    daily["group_id"] = daily["subreddit"]
    daily.to_csv(ROOT / "data" / "apollo_daily.csv", index=False)
    print(f"\ndaily series -> data/apollo_daily.csv "
          f"({len(daily)} rows, {daily.subreddit.nunique()} communities)")

    (OUT / "data_provenance.json").write_text(json.dumps({
        "active_dataset": "real Reddit via Arctic Shift",
        "comments": int(len(df)),
        "communities_analysed": int(len(m)),
        "authors": int(df["author"].nunique()),
        "days": int(df["created_utc"].dt.date.nunique()),
        "date_range": [str(df["created_utc"].min().date()),
                       str(df["created_utc"].max().date())],
        "note": "CHI, clusters, alerts and forecasts on every page are computed "
                "from this corpus. The declared simulation is retained solely for "
                "ground-truth validation, where the answer is known in advance.",
    }, indent=2), encoding="utf-8")

    print("\nNext: python gen_forecasts.py  then  python database/db_setup.py")


if __name__ == "__main__":
    main()
