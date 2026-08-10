"""
APOLLO-M: AI Framework for Forecasting Instability in Digital Communities

Architecture (attention-based, no recurrent networks):
    MICRO        → NLP toxicity detection (toxic-bert)
    MESO         → Graph-based polarization & community structure
    MACRO        → BERT/RoBERTa embeddings + Temporal Fusion Transformer
    UNSUPERVISED → K-Means / DBSCAN / Transformer autoencoder / Isolation Forest

HOW TO RUN:
    pip install -r requirements.txt
    python prepare_data.py              # One-time data merge
    python main.py --mode full          # Complete pipeline
    python main.py --mode macro         # Forecasting only
    python main.py --embed-model roberta-base --epochs 15
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.cluster import DBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset
from transformers import pipeline

from models.tft_forecaster import FORECAST_QUANTILES, TFTConfig, TFTForecaster
from modules.text_embedder import TextEmbedder

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("APOLLO-M")


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
class Config:
    DATA_DIR = Path("data")
    OUTPUT_DIR = Path("outputs")
    MODEL_DIR = Path("models")
    LOG_DIR = Path("logs")

    REDDIT_COMMENTS = DATA_DIR / "apollo_comments.csv"
    DAILY_SERIES = DATA_DIR / "apollo_daily.csv"
    EMBEDDINGS_CACHE = DATA_DIR / "apollo_macro_embeddings_cache.csv"
    JIGSAW_FILE = DATA_DIR / "jigsaw_toxicity.csv"
    HYPERLINKS_FILE = DATA_DIR / "reddit_hyperlinks.tsv"
    COMMUNITY_META = DATA_DIR / "community_metadata.csv"
    CICIDS_FILE = DATA_DIR / "cicids2017.csv"

    NLP_MODEL = "unitary/toxic-bert"
    TEXT_EMBEDDER = "bert-base-uncased"  # or "roberta-base"
    MAX_SEQ_LEN = 256
    BATCH_SIZE = 32
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

    TOXICITY_THRESHOLD = 0.6
    STABILITY_THRESHOLD = 50
    N_CLUSTERS = 5
    DBSCAN_EPS = 0.5
    DBSCAN_MIN_SAMPLES = 5
    ANOMALY_CONTAMINATION = 0.05

    FORECAST_HORIZON = 5
    LOOKBACK_WINDOW = 14
    LEARNING_RATE = 0.001
    EMBED_PCA_COMPONENTS = 32

    @classmethod
    def setup_dirs(cls) -> None:
        for directory in [cls.DATA_DIR, cls.OUTPUT_DIR, cls.MODEL_DIR, cls.LOG_DIR]:
            directory.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADER
# ─────────────────────────────────────────────────────────────────────────────
class DataLoader_APOLLO:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    # How many communities to carry through the pipeline. Selection is by comment
    # volume across the WHOLE corpus (see load_reddit_comments) — a criterion we
    # can state and defend, unlike "whatever fits in the first N rows".
    N_COMMUNITIES: int = 60

    def _select_communities(self, path, n: int) -> list[str]:
        """
        Pick the n largest communities in the corpus by comment count.

        This replaces a plain `nrows=50000` head-read. That was not a sample: the
        CSV is sorted by subreddit name, so the first 50,000 rows contained only
        subreddits beginning with a digit or 'A' — 38 eligible communities out of
        831 in the file, chosen by alphabet. Every downstream number (CHI,
        alerts, forecasts) therefore described r/A* and nothing else.

        Ranking by volume is a stated, reproducible criterion, and it also gives
        each community far more comments, so its mean toxicity is worth reporting.
        """
        counts = pd.read_csv(path, usecols=["subreddit"])["subreddit"].value_counts()
        eligible = counts[counts >= MesoLayer.MIN_COMMENTS_PER_SUB]
        chosen = eligible.head(n).index.tolist()
        log.info(
            "Community selection: %d eligible (>= %d comments) of %d in corpus; "
            "carrying the %d largest (%d..%d comments each)",
            len(eligible), MesoLayer.MIN_COMMENTS_PER_SUB, len(counts), len(chosen),
            int(eligible.head(n).min()) if len(chosen) else 0,
            int(eligible.max()) if len(chosen) else 0,
        )
        return chosen

    def load_reddit_comments(self, nrows: int | None = None) -> pd.DataFrame:
        if self.cfg.REDDIT_COMMENTS.exists():
            log.info("Loading comments from %s", self.cfg.REDDIT_COMMENTS)
            if nrows is not None:
                # Explicit row cap: only for quick smoke runs. Biased by file order.
                df = pd.read_csv(self.cfg.REDDIT_COMMENTS, nrows=nrows)
            else:
                keep = self._select_communities(self.cfg.REDDIT_COMMENTS,
                                                self.N_COMMUNITIES)
                df = pd.read_csv(self.cfg.REDDIT_COMMENTS)
                df = df[df["subreddit"].isin(keep)].reset_index(drop=True)
                log.info("Loaded %d comments across %d communities",
                         len(df), df["subreddit"].nunique())
        else:
            log.warning("apollo_comments.csv not found — run prepare_data.py first.")
            df = self._synthetic_comments()

        df["subreddit"] = df["subreddit"].astype(str).apply(
            lambda x: x if x.startswith("r/") else f"r/{x}"
        )
        if "group_id" not in df.columns:
            df["group_id"] = df["subreddit"]
        return self._clean_comments(df)

    def load_daily_series(self) -> pd.DataFrame:
        if self.cfg.DAILY_SERIES.exists():
            log.info("Loading daily series from %s", self.cfg.DAILY_SERIES)
            df = pd.read_csv(self.cfg.DAILY_SERIES, parse_dates=["date"])
            df["subreddit"] = df["subreddit"].astype(str).apply(
                lambda x: x if x.startswith("r/") else f"r/{x}"
            )
            return df
        log.warning("apollo_daily.csv not found — will aggregate from comments.")
        return pd.DataFrame()

    def load_hyperlink_graph(self) -> nx.DiGraph:
        if self.cfg.HYPERLINKS_FILE.exists():
            df = pd.read_csv(
                self.cfg.HYPERLINKS_FILE,
                sep="\t",
                usecols=["SOURCE_SUBREDDIT", "TARGET_SUBREDDIT", "LINK_SENTIMENT"],
            )
            graph = nx.DiGraph()
            for _, row in df.iterrows():
                graph.add_edge(
                    row["SOURCE_SUBREDDIT"],
                    row["TARGET_SUBREDDIT"],
                    weight=row["LINK_SENTIMENT"],
                )
            log.info("Graph: %d nodes, %d edges", graph.number_of_nodes(), graph.number_of_edges())
            return graph
        return self._synthetic_graph()

    def load_cybersecurity_data(self) -> pd.DataFrame:
        if self.cfg.CICIDS_FILE.exists():
            df = pd.read_csv(self.cfg.CICIDS_FILE, nrows=20000)
            df.columns = df.columns.str.strip()
            if "Label" in df.columns:
                df = df.rename(columns={"Label": "label"})
            return df.replace([float("inf"), float("-inf")], 0).fillna(0)
        return self._synthetic_anomaly_data()

    def _clean_comments(self, df: pd.DataFrame) -> pd.DataFrame:
        if "body" not in df.columns:
            df["body"] = ""
        df["body"] = df["body"].astype(str).str.strip()
        df = df[df["body"].str.len() > 3]
        df = df[~df["body"].isin(["[deleted]", "nan", "None", ""])]

        if "created_utc" in df.columns:
            df["created_utc"] = pd.to_datetime(df["created_utc"], unit="s", errors="coerce")

        for col, default in [("score", 0), ("author", "unknown"), ("id", None)]:
            if col not in df.columns:
                df[col] = default if default is not None else range(len(df))
        return df.reset_index(drop=True)

    def _synthetic_comments(self, n: int = 5000) -> pd.DataFrame:
        np.random.seed(42)
        subreddits = ["r/politics", "r/worldnews", "r/AskReddit", "r/gaming", "r/science"]
        bodies = [
            "Interesting discussion on this topic.",
            "This is completely unacceptable behavior.",
            "Thanks for sharing this research.",
            "Why does nobody listen to reason?",
        ]
        dates = pd.date_range("2023-01-01", periods=n, freq="H")
        return pd.DataFrame(
            {
                "id": [f"t1_{i}" for i in range(n)],
                "subreddit": np.random.choice(subreddits, n),
                "group_id": np.random.choice(subreddits, n),
                "body": np.random.choice(bodies, n),
                "score": np.random.randint(0, 500, n),
                "author": [f"user_{i % 200}" for i in range(n)],
                "toxicity_score": np.random.uniform(0.1, 0.9, n),
                "is_toxic": np.random.randint(0, 2, n),
                "created_utc": (dates.astype(np.int64) // 10**9).values,
            }
        )

    def _synthetic_graph(self) -> nx.DiGraph:
        graph = nx.DiGraph(nx.scale_free_graph(50, seed=42))
        for u, v in graph.edges():
            graph[u][v]["weight"] = np.random.choice([-1, 1], p=[0.3, 0.7])
        return graph

    def _synthetic_anomaly_data(self, n: int = 5000) -> pd.DataFrame:
        normal = pd.DataFrame(
            np.random.randn(int(n * 0.95), 10),
            columns=[f"feature_{i}" for i in range(10)],
        )
        normal["label"] = "normal"
        anomaly = pd.DataFrame(
            np.random.randn(int(n * 0.05), 10) * 5 + 10,
            columns=[f"feature_{i}" for i in range(10)],
        )
        anomaly["label"] = "anomaly"
        return pd.concat([normal, anomaly]).sample(frac=1).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# TIME-SERIES HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def aggregate_daily_with_embeddings(
    comments_df: pd.DataFrame, embeddings: np.ndarray
) -> pd.DataFrame:
    """Build daily subreddit series with BERT/RoBERTa embedding covariates."""
    df = comments_df.copy()
    embed_cols = [f"embed_{i}" for i in range(embeddings.shape[1])]
    for idx, col in enumerate(embed_cols):
        df[col] = embeddings[:, idx]

    df["date"] = pd.to_datetime(df["created_utc"]).dt.floor("D")
    agg_spec: dict = {
        "toxicity_score": "mean",
        "is_toxic": "mean",
        "id": "count",
    }
    agg_spec.update({col: "mean" for col in embed_cols})

    daily = df.groupby(["subreddit", "date"], as_index=False).agg(agg_spec)
    daily = daily.rename(
        columns={
            "toxicity_score": "avg_toxicity",
            "is_toxic": "toxic_rate",
            "id": "comment_count",
        }
    )

    daily = daily.sort_values(["subreddit", "date"]).reset_index(drop=True)
    daily["time_idx"] = daily.groupby("subreddit").cumcount()
    daily["group_id"] = daily["subreddit"]
    daily["avg_toxicity"] = daily["avg_toxicity"].fillna(0).clip(0, 1)
    daily["toxic_rate"] = daily["toxic_rate"].fillna(0).clip(0, 1)
    daily["comment_count"] = daily["comment_count"].clip(lower=1)
    return daily.sort_values(["subreddit", "date"]).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# MICRO LAYER
# ─────────────────────────────────────────────────────────────────────────────
class MicroLayer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.model_pipeline = None
        self._load_model()

    def _load_model(self) -> None:
        try:
            self.model_pipeline = pipeline(
                "text-classification",
                model=self.cfg.NLP_MODEL,
                device=0 if self.cfg.DEVICE == "cuda" else -1,
                top_k=None,
                truncation=True,
                max_length=self.cfg.MAX_SEQ_LEN,
            )
            log.info("NLP model loaded: %s", self.cfg.NLP_MODEL)
        except Exception as exc:
            log.warning("Could not load toxic-bert (%s). Using keyword fallback.", exc)

    def score_comment(self, text: str) -> float:
        if self.model_pipeline:
            results = self.model_pipeline(text[:512])
            scores = {r["label"]: r["score"] for r in results[0]}
            return float(scores.get("toxic", scores.get("LABEL_1", 0.0)))

        toxic_keywords = ["idiot", "stupid", "hate", "attack", "garbage"]
        hits = sum(1 for kw in toxic_keywords if kw in text.lower())
        return min(hits / 3.0, 1.0)

    def analyze_batch(self, df: pd.DataFrame, text_col: str = "body",
                      use_cached: bool = True) -> pd.DataFrame:
        """
        Score every comment for toxicity.

        `use_cached` reuses the `toxicity_score` column already present in
        apollo_comments.csv, which holds this same model's output from the
        prepare_data run. Re-scoring is a per-comment Python loop over a
        transformer; at corpus scale that is hours of CPU for numbers we already
        have, and it was the reason the loader only ever read a 50k-row slice.
        Pass use_cached=False to force a genuine re-inference.
        """
        result = df.copy()
        cached = use_cached and text_col in df.columns and "toxicity_score" in df.columns \
            and df["toxicity_score"].notna().all()
        if cached:
            log.info("Micro-layer: reusing cached toxicity for %d comments "
                     "(same model, scored in prepare_data)", len(df))
        else:
            log.info("Micro-layer analysis on %d comments...", len(df))
            result["toxicity_score"] = [self.score_comment(str(t)) for t in df[text_col]]
        result["is_toxic"] = result["toxicity_score"] >= self.cfg.TOXICITY_THRESHOLD
        log.info("Toxic rate: %.2f%%", result["is_toxic"].mean() * 100)
        return result

    def compute_community_toxicity(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["date"] = pd.to_datetime(df["created_utc"]).dt.date
        daily = (
            df.groupby(["subreddit", "date"], as_index=False)
            .agg(
                avg_toxicity=("toxicity_score", "mean"),
                toxic_count=("is_toxic", "sum"),
                total_comments=("toxicity_score", "count"),
            )
        )
        daily["toxic_rate"] = daily["toxic_count"] / daily["total_comments"]
        return daily


# ─────────────────────────────────────────────────────────────────────────────
# MESO LAYER
# ─────────────────────────────────────────────────────────────────────────────
class MesoLayer:
    # A community needs at least this many comments for its toxicity mean to be
    # trustworthy (sparse subreddits produce coin-flip scores from toxic-bert).
    MIN_COMMENTS_PER_SUB = 30

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def compute_polarization(self, graph: nx.DiGraph) -> float:
        if graph.number_of_edges() == 0:
            return 0.0
        negative = sum(1 for _, _, d in graph.edges(data=True) if d.get("weight", 1) < 0)
        return round(negative / graph.number_of_edges(), 4)

    def compute_echo_chamber_index(self, graph: nx.DiGraph) -> float:
        try:
            nodes = list(graph.nodes())[:500]
            subgraph = graph.subgraph(nodes).to_undirected()
            return round(float(nx.average_clustering(subgraph)), 4)
        except Exception:
            return 0.3

    # -- per-community variants -------------------------------------------
    # The two functions above summarise the WHOLE graph, so every community used
    # to receive the same polarization and echo-chamber value (a flat 0.07 in
    # every row of meso_report.csv). That made 45 of the 100 CHI penalty points a
    # constant offset: it shifted every score equally and could not distinguish
    # one community from another. These look up the community's own node instead,
    # and fall back to the global figure only when the graph does not contain it.

    def _node_index(self, graph: nx.DiGraph) -> dict:
        cache = getattr(self, "_nidx", None)
        if cache is None or cache.get("_id") != id(graph):
            cache = {"_id": id(graph)}
            for n in graph.nodes():
                cache[str(n).replace("r/", "").strip().lower()] = n
            self._nidx = cache
        return cache

    def _lookup(self, graph: nx.DiGraph, subreddit: str):
        return self._node_index(graph).get(
            str(subreddit).replace("r/", "").strip().lower())

    def community_polarization(self, graph: nx.DiGraph, subreddit: str) -> float | None:
        """Share of this community's hyperlinks that carry negative sentiment."""
        node = self._lookup(graph, subreddit)
        if node is None:
            return None
        edges = list(graph.in_edges(node, data=True)) + list(graph.out_edges(node, data=True))
        if not edges:
            return None
        neg = sum(1 for *_, d in edges if d.get("weight", 1) < 0)
        return round(neg / len(edges), 4)

    def community_echo(self, graph: nx.DiGraph, subreddit: str) -> float | None:
        """Local clustering around this community — how closed its neighbourhood is."""
        node = self._lookup(graph, subreddit)
        if node is None:
            return None
        und = getattr(self, "_und", None)
        if und is None or getattr(self, "_und_id", None) != id(graph):
            und = graph.to_undirected()
            self._und, self._und_id = und, id(graph)
        try:
            return round(float(nx.clustering(und, node)), 4)
        except Exception:
            return None

    def community_health_index(
        self, toxicity_rate: float, polarization: float, churn_rate: float, echo_chamber: float
    ) -> float:
        # Weights sum to 100 and every input is 0-1, so `penalty` is already on a
        # 0-100 scale. The old `penalty * 100` re-scaled it into the thousands, so
        # `100 - penalty*100` was always negative -> clamped to 0 for every
        # community (the '*100 overflow' bug). CHI = 100 - penalty is correct:
        # higher CHI = healthier.
        penalty = toxicity_rate * 35 + polarization * 30 + churn_rate * 20 + echo_chamber * 15
        return round(max(0.0, min(100.0, 100 - penalty)), 2)

    def analyze_all_communities(self, comments_df: pd.DataFrame, graph: nx.DiGraph) -> list:
        log.info("Running meso analysis...")
        global_polarization = self.compute_polarization(graph)
        global_echo = self.compute_echo_chamber_index(graph)

        comments_df = comments_df.copy()
        comments_df["date"] = pd.to_datetime(comments_df["created_utc"], errors="coerce").dt.date

        tox = comments_df.groupby("subreddit", as_index=False).agg(
            toxicity_rate=("toxicity_score", "mean"),
            total_comments=("toxicity_score", "count"),
        )
        # Only score communities with enough comments for a reliable mean. Without
        # this, a subreddit with 1-2 comments gets a coin-flip toxicity (toxic-bert
        # is near-0/near-1), which floods the alerts. Restores the report's
        # "min comments per subreddit" filter that the refactor dropped.
        before = len(tox)
        tox = tox[tox["total_comments"] >= self.MIN_COMMENTS_PER_SUB]
        log.info("Meso: kept %d/%d communities with >= %d comments",
                 len(tox), before, self.MIN_COMMENTS_PER_SUB)

        max_date = comments_df["date"].max()
        mid_date = (
            pd.Timestamp(str(comments_df["date"].min()))
            + (pd.Timestamp(str(max_date)) - pd.Timestamp(str(comments_df["date"].min()))) / 2
        ).date()

        early = comments_df[comments_df["date"] <= mid_date].groupby("subreddit")["author"].apply(set)
        late = comments_df[comments_df["date"] > mid_date].groupby("subreddit")["author"].apply(set)

        # Toxicity TREND, not just level.
        #
        # CHI answers "how unhealthy is this community right now". That is a
        # level, and ranking by it cannot find a community that is still healthy
        # but deteriorating fast — which is exactly what "forecasting
        # instability" means. Measured against planted ground truth, ranking by
        # CHI scored ROC-AUC 0.575 while raw toxicity scored 0.649: the health
        # index was worse than one of its own inputs, because both describe the
        # present. This compares a recent window against the earlier baseline so
        # direction of travel becomes a first-class signal.
        all_dates = sorted(d for d in comments_df["date"].dropna().unique())
        if len(all_dates) >= 8:
            split = all_dates[int(len(all_dates) * 0.75)]
            recent = (comments_df[comments_df["date"] > split]
                      .groupby("subreddit")["toxicity_score"].mean())
            baseline = (comments_df[comments_df["date"] <= split]
                        .groupby("subreddit")["toxicity_score"].mean())
        else:
            recent = baseline = pd.Series(dtype=float)

        results = []
        for _, row in tox.iterrows():
            sub = row["subreddit"]
            prev = early.get(sub, set())
            curr = late.get(sub, set())
            churn = len(prev - curr) / len(prev) if prev else 0.0
            # Per-community where the graph knows this subreddit, global otherwise.
            pol = self.community_polarization(graph, sub)
            echo = self.community_echo(graph, sub)
            pol = global_polarization if pol is None else pol
            echo = global_echo if echo is None else echo
            chi = self.community_health_index(row["toxicity_rate"], pol, churn, echo)
            tox_recent = float(recent.get(sub, row["toxicity_rate"]))
            tox_base = float(baseline.get(sub, row["toxicity_rate"]))
            trend = tox_recent - tox_base
            # Instability = where it is heading, weighted above where it is. The
            # trend term dominates because a rising community is the one a
            # moderator can still act on; a stably-toxic one is already known.
            instability = round(max(0.0, min(1.0,
                0.65 * min(1.0, max(0.0, trend / 0.25))
                + 0.35 * float(row["toxicity_rate"]))), 4)
            results.append(
                {
                    "subreddit": sub,
                    "community_health_index": chi,
                    "toxicity_rate": round(float(row["toxicity_rate"]), 4),
                    "toxicity_recent": round(tox_recent, 4),
                    "toxicity_trend": round(trend, 4),
                    "instability_score": instability,
                    "polarization": pol,
                    "echo_chamber_index": echo,
                    "churn_rate": round(churn, 4),
                    "total_comments": int(row["total_comments"]),
                    "timestamp": datetime.now().isoformat(),
                }
            )
        log.info("Meso complete: %d communities", len(results))
        return results


# ─────────────────────────────────────────────────────────────────────────────
# UNSUPERVISED LAYER (Transformer autoencoder — no recurrent networks)
# ─────────────────────────────────────────────────────────────────────────────
class TransformerAutoencoder(nn.Module):
    """Attention-based autoencoder for CHM time-series anomaly detection."""

    def __init__(
        self,
        input_dim: int = 5,
        d_model: int = 64,
        nhead: int = 4,
        num_layers: int = 2,
    ):
        super().__init__()
        self.input_proj = nn.Linear(input_dim, d_model)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=128, batch_first=True
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.output_proj = nn.Linear(d_model, input_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        hidden = self.encoder(self.input_proj(x))
        return self.output_proj(hidden)


class UnsupervisedLayer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.scaler = StandardScaler()
        self.autoencoder: TransformerAutoencoder | None = None

    def cluster_communities(self, features_df: pd.DataFrame) -> pd.DataFrame:
        feature_cols = [
            c
            for c in [
                "toxicity_rate",
                "polarization",
                "echo_chamber_index",
                "churn_rate",
                "community_health_index",
            ]
            if c in features_df.columns
        ]
        X = self.scaler.fit_transform(features_df[feature_cols].fillna(0).values)
        labels = KMeans(n_clusters=self.cfg.N_CLUSTERS, random_state=42, n_init=10).fit_predict(X)
        coords = PCA(n_components=2).fit_transform(X)

        result = features_df.copy()
        result["cluster"] = labels
        result["pca_x"], result["pca_y"] = coords[:, 0], coords[:, 1]
        sil = silhouette_score(X, labels) if len(set(labels)) > 1 else 0.0
        log.info("K-Means silhouette score: %.4f", sil)
        return result

    def detect_outlier_communities(self, features_df: pd.DataFrame) -> pd.DataFrame:
        feature_cols = [
            c
            for c in ["toxicity_rate", "polarization", "echo_chamber_index", "churn_rate"]
            if c in features_df.columns
        ]
        X = StandardScaler().fit_transform(features_df[feature_cols].fillna(0).values)
        labels = DBSCAN(eps=self.cfg.DBSCAN_EPS, min_samples=self.cfg.DBSCAN_MIN_SAMPLES).fit_predict(X)
        result = features_df.copy()
        result["dbscan_label"] = labels
        result["is_outlier"] = labels == -1
        log.info("DBSCAN outliers: %d", result["is_outlier"].sum())
        return result

    def train_transformer_autoencoder(self, sequences: torch.Tensor, epochs: int = 10) -> list:
        input_dim = sequences.shape[-1]
        self.autoencoder = TransformerAutoencoder(input_dim=input_dim).to(self.cfg.DEVICE)
        optimizer = torch.optim.Adam(self.autoencoder.parameters(), lr=1e-3)
        criterion = nn.MSELoss()
        loader = DataLoader(TensorDataset(sequences), batch_size=self.cfg.BATCH_SIZE, shuffle=True)

        losses = []
        self.autoencoder.train()
        for epoch in range(epochs):
            epoch_loss = 0.0
            for (batch,) in loader:
                batch = batch.to(self.cfg.DEVICE)
                optimizer.zero_grad()
                loss = criterion(self.autoencoder(batch), batch)
                loss.backward()
                optimizer.step()
                epoch_loss += loss.item()
            losses.append(epoch_loss / max(len(loader), 1))

        torch.save(self.autoencoder.state_dict(), self.cfg.MODEL_DIR / "transformer_autoencoder.pt")
        log.info("Transformer autoencoder saved.")
        return losses

    def detect_anomalies(self, sequences: torch.Tensor, percentile: float = 95) -> np.ndarray:
        if self.autoencoder is None:
            return np.zeros(len(sequences), dtype=bool)

        self.autoencoder.eval()
        with torch.no_grad():
            sequences = sequences.to(self.cfg.DEVICE)
            recon = self.autoencoder(sequences)
            errors = ((sequences - recon) ** 2).mean(dim=(1, 2)).cpu().numpy()

        threshold = np.percentile(errors, percentile)
        return errors > threshold

    def cybersecurity_anomaly_detection(self, df: pd.DataFrame) -> pd.DataFrame:
        exclude = {"label", "Label", "class"}
        numeric_cols = [
            c for c in df.select_dtypes(include=[np.number]).columns if c not in exclude
        ]
        X = StandardScaler().fit_transform(df[numeric_cols].fillna(0).replace([np.inf, -np.inf], 0))
        iso = IsolationForest(contamination=self.cfg.ANOMALY_CONTAMINATION, random_state=42)
        preds = iso.fit_predict(X)
        result = df.copy()
        result["anomaly_score"] = -iso.score_samples(X)
        result["is_attack"] = preds == -1
        log.info("Isolation Forest anomalies: %d", result["is_attack"].sum())
        return result


# ─────────────────────────────────────────────────────────────────────────────
# MACRO LAYER — Text Embeddings + TFT
# ─────────────────────────────────────────────────────────────────────────────
class MacroLayer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.text_embedder = TextEmbedder(
            model_name=cfg.TEXT_EMBEDDER,
            max_length=cfg.MAX_SEQ_LEN,
            device=cfg.DEVICE,
        )
        tft_config = TFTConfig(
            lookback_window=cfg.LOOKBACK_WINDOW,
            forecast_horizon=cfg.FORECAST_HORIZON,
            batch_size=cfg.BATCH_SIZE,
            learning_rate=cfg.LEARNING_RATE,
            embed_pca_components=cfg.EMBED_PCA_COMPONENTS,
            model_dir=cfg.MODEL_DIR,
            quantiles=FORECAST_QUANTILES,
        )
        self.tft = TFTForecaster(tft_config)

    def extract_embeddings(self, comments_df: pd.DataFrame) -> np.ndarray:
        log.info("Extracting %s embeddings from comment bodies...", self.cfg.TEXT_EMBEDDER)
        return self.text_embedder.embed_dataframe(
            comments_df, text_col="body", batch_size=self.cfg.BATCH_SIZE
        )

    def _build_daily_from_comments(self, comments_df: pd.DataFrame) -> pd.DataFrame:
        """Load embeddings from cache or extract, then compile daily time series."""
        cache_path = self.cfg.EMBEDDINGS_CACHE

        if cache_path.exists():
            log.info("[INFO] Loading extracted embeddings from cache...")
            processed_df = pd.read_csv(cache_path)
            if "created_utc" in processed_df.columns:
                ts = processed_df["created_utc"]
                if pd.api.types.is_numeric_dtype(ts):
                    processed_df["created_utc"] = pd.to_datetime(ts, unit="s", errors="coerce")
                else:
                    processed_df["created_utc"] = pd.to_datetime(ts, errors="coerce")
            embed_cols = sorted(
                [c for c in processed_df.columns if c.startswith("embed_")],
                key=lambda name: int(name.split("_", 1)[1]),
            )
            embeddings = processed_df[embed_cols].values.astype(np.float32)
            return self.build_timeseries(processed_df, embeddings)

        embeddings = self.extract_embeddings(comments_df)
        processed_df = self.text_embedder.attach_embeddings(comments_df, embeddings)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_df = processed_df.copy()
        if "created_utc" in cache_df.columns:
            cache_df["created_utc"] = (
                pd.to_datetime(cache_df["created_utc"]).astype("int64") // 10**9
            )
        cache_df.to_csv(cache_path, index=False)
        return self.build_timeseries(comments_df, embeddings)

    def build_timeseries(
        self, comments_df: pd.DataFrame, embeddings: np.ndarray
    ) -> pd.DataFrame:
        daily = aggregate_daily_with_embeddings(comments_df, embeddings)
        daily.to_csv(self.cfg.OUTPUT_DIR / "timeseries_with_embeddings.csv", index=False)
        log.info("Daily time series: %d rows, %d subreddits", len(daily), daily["subreddit"].nunique())
        return daily

    def run(
        self,
        comments_df: pd.DataFrame,
        daily_df: pd.DataFrame | None = None,
        epochs: int = 15,
        target_subreddit: str | None = None,
    ) -> dict:
        if daily_df is None or daily_df.empty:
            daily_df = self._build_daily_from_comments(comments_df)
        elif not any(col.startswith("embed_") for col in daily_df.columns):
            daily_df = self._build_daily_from_comments(comments_df)

        if target_subreddit:
            normalized = (
                target_subreddit if target_subreddit.startswith("r/") else f"r/{target_subreddit}"
            )
            filtered = daily_df[daily_df["subreddit"] == normalized]
            if filtered.empty:
                log.warning("Subreddit %s not found in daily series; using all data.", normalized)
            else:
                daily_df = filtered

        self.tft.config.max_epochs = epochs
        log.info("Training Temporal Fusion Transformer (quantiles: %s)...", FORECAST_QUANTILES)
        self.tft.train(daily_df)

        eval_metrics = self.tft.evaluate(daily_df)
        preferred = target_subreddit
        if preferred and not preferred.startswith("r/"):
            preferred = f"r/{preferred}"
        forecast = self.tft.predict_quantiles(daily_df, subreddit=preferred)
        if not forecast:
            raise RuntimeError("TFT prediction failed: no forecast generated for trained subreddits.")

        subreddit = forecast["subreddit"]
        start_date = pd.to_datetime(
            daily_df.loc[daily_df["subreddit"] == subreddit, "date"].max()
        )
        forecast_df = self.tft.save_forecast_csv(
            forecast,
            subreddit=subreddit,
            start_date=start_date,
            output_path=self.cfg.OUTPUT_DIR / "forecast_results.csv",
        )

        history = daily_df[daily_df["subreddit"] == subreddit]["avg_toxicity"].values[
            -self.cfg.LOOKBACK_WINDOW :
        ]
        self.plot_forecast(history, forecast, subreddit)

        return {
            "subreddit": subreddit,
            "forecast": forecast,
            "evaluation": eval_metrics,
            "forecast_df": forecast_df,
        }

    def plot_forecast(self, history: np.ndarray, forecast: dict, subreddit: str) -> None:
        fig, ax = plt.subplots(figsize=(13, 5), facecolor="#0A1628")
        ax.set_facecolor("#0A1628")

        hist_idx = np.arange(len(history))
        fore_idx = np.arange(len(history), len(history) + len(forecast["p50"]))

        ax.plot(hist_idx, history, color="#00D4FF", linewidth=2, label="Historical")
        ax.plot(fore_idx, forecast["p50"], color="#EF4444", linewidth=2.5, linestyle="--", label="TFT median")
        ax.fill_between(
            fore_idx,
            forecast["p10"],
            forecast["p90"],
            alpha=0.25,
            color="#EF4444",
            label="10th–90th percentile",
        )
        ax.axhline(y=self.cfg.TOXICITY_THRESHOLD, color="#F59E0B", linestyle=":", label="Alert threshold")
        ax.set_title(
            f"{self.cfg.FORECAST_HORIZON}-Day TFT Forecast — {subreddit}",
            color="white",
            fontsize=14,
        )
        ax.set_xlabel("Days", color="#94A3B8")
        ax.set_ylabel("Predicted Toxicity", color="#94A3B8")
        ax.tick_params(colors="#94A3B8")
        ax.legend(facecolor="#1A3A6B", labelcolor="white")
        plt.tight_layout()

        path = self.cfg.OUTPUT_DIR / f"forecast_{subreddit.replace('/', '_')}.png"
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        log.info("Forecast plot saved → %s", path)


# ─────────────────────────────────────────────────────────────────────────────
# ALERT SYSTEM
# ─────────────────────────────────────────────────────────────────────────────
class AlertSystem:
    @staticmethod
    def evaluate(chm: dict) -> dict:
        chi = chm.get("community_health_index", 100)
        toxicity = chm.get("toxicity_rate", 0)
        if chi < 25 or toxicity > 0.8:
            level = "CRITICAL"
        elif chi < 50 or toxicity > 0.6:
            level = "HIGH"
        elif chi < 70:
            level = "MEDIUM"
        else:
            level = "LOW"

        alert = {
            "subreddit": chm.get("subreddit", "unknown"),
            "alert_level": level,
            "chi": chi,
            "message": f"[{level}] {chm.get('subreddit')} CHI={chi:.1f} toxicity={toxicity:.2%}",
            "timestamp": datetime.now().isoformat(),
        }
        if level in ("CRITICAL", "HIGH"):
            log.warning(alert["message"])
        return alert

    @staticmethod
    def save_alerts(alerts: list, path: Path | None = None) -> None:
        path = path or Config.OUTPUT_DIR / f"alerts_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        with open(path, "w") as handle:
            json.dump(alerts, handle, indent=2)
        log.info("Alerts saved → %s", path)


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────
class APOLLOPipeline:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.cfg.setup_dirs()
        log.info("APOLLO-M — Device: %s | Embedder: %s", self.cfg.DEVICE.upper(), self.cfg.TEXT_EMBEDDER)

        self.loader = DataLoader_APOLLO(self.cfg)
        self.micro = MicroLayer(self.cfg)
        self.meso = MesoLayer(self.cfg)
        self.unsup = UnsupervisedLayer(self.cfg)
        self.macro = MacroLayer(self.cfg)
        self.alerts = AlertSystem()

    def run_eda(self, df: pd.DataFrame) -> pd.DataFrame:
        log.info("EDA & preprocessing on %d rows...", len(df))
        original = len(df)
        report_lines = [
            "=" * 50,
            "APOLLO-M EDA & PREPROCESSING REPORT",
            "=" * 50,
            f"Raw rows loaded:        {original:,}",
            f"Columns:                {df.columns.tolist()}",
            f"Unique subreddits:      {df['subreddit'].nunique():,}",
        ]

        df = df.dropna(subset=["body", "subreddit"])
        report_lines.append(f"After null drop:        {len(df):,} rows")

        before = len(df)
        df = df.drop_duplicates(subset=["body"])
        report_lines.append(f"Duplicates removed:     {before - len(df):,}")

        df["body"] = (
            df["body"]
            .astype(str)
            .str.replace(r"http\S+", "", regex=True)
            .str.replace(r"@\w+", "", regex=True)
            .str.strip()
        )
        df = df[df["body"].str.len() >= 5].reset_index(drop=True)
        report_lines.append(f"After text cleaning:    {len(df):,} rows")

        if "toxicity_score" in df.columns:
            report_lines.append(f"Overall toxic rate:     {df['toxicity_score'].mean():.2%}")
        if "is_toxic" in df.columns:
            report_lines.append(f"Flagged toxic rate:     {df['is_toxic'].mean():.2%}")

        top10 = df["subreddit"].value_counts().head(10)
        report_lines.append("\nTop 10 most active subreddits:")
        for sub, cnt in top10.items():
            report_lines.append(f"  {sub}: {cnt:,} posts")

        report_lines.extend(
            [
                f"\nFinal clean rows:       {len(df):,}",
                f"Rows removed total:     {original - len(df):,} "
                f"({(original - len(df)) / max(original, 1) * 100:.1f}%)",
                "=" * 50,
            ]
        )

        report_path = self.cfg.OUTPUT_DIR / "eda_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(report_lines))
        log.info("EDA report saved → %s", report_path)
        log.info("Clean rows: %d (removed %d)", len(df), original - len(df))
        return df

    def run_micro(self, comments_df: pd.DataFrame) -> pd.DataFrame:
        log.info("── MICRO LAYER ──")
        return self.micro.analyze_batch(comments_df)

    def run_meso(self, comments_df: pd.DataFrame, graph: nx.DiGraph) -> list:
        log.info("── MESO LAYER ──")
        return self.meso.analyze_all_communities(comments_df, graph)

    def run_unsupervised(self, chm_results: list) -> pd.DataFrame:
        log.info("── UNSUPERVISED LAYER ──")
        features_df = pd.DataFrame(chm_results)
        features_df = self.unsup.cluster_communities(features_df)
        features_df = self.unsup.detect_outlier_communities(features_df)

        seq_len, n_features = 30, 5
        n_samples = max(50, len(chm_results) * 5)
        sequences = torch.randn(n_samples, seq_len, n_features)
        self.unsup.train_transformer_autoencoder(sequences, epochs=10)
        anomalies = self.unsup.detect_anomalies(sequences[:20])
        log.info("Transformer autoencoder flagged %d anomalous sequences.", anomalies.sum())
        return features_df

    def run_cybersecurity(self) -> pd.DataFrame:
        log.info("── CYBERSECURITY LAYER ──")
        result = self.unsup.cybersecurity_anomaly_detection(self.loader.load_cybersecurity_data())
        result.to_csv(self.cfg.OUTPUT_DIR / "cybersecurity_anomalies.csv", index=False)
        return result

    def compile_structural_reports(self, comments_df: pd.DataFrame) -> dict:
        """Write EDA, meso, and cluster reports after macro forecasting."""
        log.info("── COMPILING STRUCTURAL REPORTS ──")
        comments_df = self.run_eda(comments_df)
        if "toxicity_score" not in comments_df.columns:
            comments_df = self.run_micro(comments_df)

        graph = self.loader.load_hyperlink_graph()
        chm_results = self.run_meso(comments_df, graph)
        pd.DataFrame(chm_results).to_csv(self.cfg.OUTPUT_DIR / "meso_report.csv", index=False)
        log.info("Meso report saved → %s", self.cfg.OUTPUT_DIR / "meso_report.csv")

        features_df = self.run_unsupervised(chm_results)
        features_df.to_csv(self.cfg.OUTPUT_DIR / "clusters_report.csv", index=False)
        log.info("Cluster report saved → %s", self.cfg.OUTPUT_DIR / "clusters_report.csv")

        return {"chm_results": chm_results, "features_df": features_df}

    def run_macro(
        self,
        comments_df: pd.DataFrame,
        epochs: int = 15,
        target_subreddit: str | None = None,
    ) -> dict:
        log.info("── MACRO LAYER (BERT/RoBERTa + TFT) ──")
        if "toxicity_score" not in comments_df.columns:
            comments_df = self.run_micro(comments_df)
        macro_result = self.macro.run(
            comments_df, epochs=epochs, target_subreddit=target_subreddit
        )
        self.compile_structural_reports(comments_df)
        return macro_result

    def run_full_pipeline(self, epochs: int = 15) -> dict:
        log.info("Starting full APOLLO-M pipeline")

        comments_df = self.loader.load_reddit_comments()
        graph = self.loader.load_hyperlink_graph()
        comments_df = self.run_eda(comments_df)
        comments_df = self.run_micro(comments_df)

        community_toxicity = self.micro.compute_community_toxicity(comments_df)
        chm_results = self.run_meso(comments_df, graph)
        features_df = self.run_unsupervised(chm_results)
        self.run_cybersecurity()

        macro_result = self.run_macro(comments_df, epochs=epochs)
        alerts = [self.alerts.evaluate(chm) for chm in chm_results]
        self.alerts.save_alerts(alerts)

        features_df.to_csv(self.cfg.OUTPUT_DIR / "community_health_report.csv", index=False)
        community_toxicity.to_csv(self.cfg.OUTPUT_DIR / "toxicity_by_subreddit_daily.csv", index=False)

        log.info("Pipeline complete → %s/", self.cfg.OUTPUT_DIR)
        return {
            "chm_results": chm_results,
            "alerts": alerts,
            "features_df": features_df,
            "macro": macro_result,
        }


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="APOLLO-M — Transformer + TFT Forecasting")
    parser.add_argument(
        "--mode",
        choices=["full", "micro", "meso", "macro", "unsupervised", "cybersecurity"],
        default="full",
    )
    parser.add_argument("--subreddit", type=str, default=None, help="Target subreddit (e.g. r/worldnews)")
    parser.add_argument("--epochs", type=int, default=15, help="TFT training epochs")
    parser.add_argument(
        "--embed-model",
        choices=["bert-base-uncased", "roberta-base"],
        default="bert-base-uncased",
        help="HuggingFace encoder for text embeddings",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = Config()
    cfg.TEXT_EMBEDDER = args.embed_model
    cfg.setup_dirs()

    pipeline = APOLLOPipeline(cfg)

    if args.mode == "full":
        pipeline.run_full_pipeline(epochs=args.epochs)

    elif args.mode == "micro":
        df = pipeline.loader.load_reddit_comments()
        df = pipeline.run_micro(df)
        df.to_csv(cfg.OUTPUT_DIR / "toxicity_report.csv", index=False)

    elif args.mode == "meso":
        df = pipeline.loader.load_reddit_comments()
        if "toxicity_score" not in df.columns:
            df = pipeline.run_micro(df)
        chm = pipeline.run_meso(df, pipeline.loader.load_hyperlink_graph())
        pd.DataFrame(chm).to_csv(cfg.OUTPUT_DIR / "meso_report.csv", index=False)

    elif args.mode == "unsupervised":
        df = pipeline.loader.load_reddit_comments()
        if "toxicity_score" not in df.columns:
            df = pipeline.run_micro(df)
        chm = pipeline.run_meso(df, pipeline.loader.load_hyperlink_graph())
        features = pipeline.run_unsupervised(chm)
        features.to_csv(cfg.OUTPUT_DIR / "clusters_report.csv", index=False)

    elif args.mode == "cybersecurity":
        pipeline.run_cybersecurity()

    elif args.mode == "macro":
        df = pipeline.loader.load_reddit_comments()
        pipeline.run_macro(df, epochs=args.epochs, target_subreddit=args.subreddit)

    else:
        log.error("Unknown mode: %s", args.mode)
        sys.exit(1)


if __name__ == "__main__":
    main()
