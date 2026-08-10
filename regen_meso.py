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

import pandas as pd

warnings.filterwarnings("ignore")

from main import (Config, DataLoader_APOLLO, MesoLayer,  # noqa: E402
                  MicroLayer, UnsupervisedLayer)

log = logging.getLogger("regen")
logging.basicConfig(level=logging.INFO, format="%(message)s")

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
unsup = UnsupervisedLayer(cfg)
feat = unsup.cluster_communities(df.copy())
feat = unsup.detect_outlier_communities(feat)
feat.to_csv(cfg.OUTPUT_DIR / "clusters_report.csv", index=False)
print(f"\nwrote {len(feat)} rows -> outputs/clusters_report.csv")
if "cluster" in feat.columns:
    print("cluster sizes:", feat["cluster"].value_counts().sort_index().to_dict())
if "is_outlier" in feat.columns:
    print("outlier communities:", int(feat["is_outlier"].sum()))
