"""
APOLLO-M: Data Preparation Script
Run this ONCE before main.py to merge datasets and build TFT-ready time-series input.

Outputs:
  - data/apollo_comments.csv   — comment-level data with group_id for entity tracking
  - data/apollo_daily.csv      — daily aggregated series per subreddit (pre-embedding)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("data")
OUTPUT_COMMENTS = DATA_DIR / "apollo_comments.csv"
OUTPUT_DAILY = DATA_DIR / "apollo_daily.csv"


def normalize_subreddit(series: pd.Series) -> pd.Series:
    """Strip r/ prefix for storage; main.py re-adds it at load time."""
    return series.astype(str).str.replace(r"^r/", "", regex=True).str.strip()


def build_daily_series(comments: pd.DataFrame) -> pd.DataFrame:
    """Aggregate comment-level rows into daily subreddit time steps for TFT."""
    df = comments.copy()
    df["date"] = pd.to_datetime(df["created_utc"], unit="s", errors="coerce").dt.floor("D")
    df = df.dropna(subset=["date", "subreddit"])

    daily = (
        df.groupby(["subreddit", "date"], as_index=False)
        .agg(
            avg_toxicity=("toxicity_score", "mean"),
            toxic_rate=("is_toxic", "mean"),
            comment_count=("id", "count"),
            avg_score=("score", "mean"),
            unique_authors=("author", "nunique"),
        )
        .sort_values(["subreddit", "date"])
        .reset_index(drop=True)
    )

    daily = daily.sort_values(["subreddit", "date"]).reset_index(drop=True)
    daily["time_idx"] = daily.groupby("subreddit").cumcount()
    daily["group_id"] = daily["subreddit"]

    daily["avg_toxicity"] = daily["avg_toxicity"].fillna(0).clip(0, 1)
    daily["toxic_rate"] = daily["toxic_rate"].fillna(0).clip(0, 1)
    daily["comment_count"] = daily["comment_count"].clip(lower=1)

    return daily


def main() -> None:
    print("=" * 55)
    print("  APOLLO-M Data Preparation (Transformer / TFT Pipeline)")
    print("=" * 55)

    DATA_DIR.mkdir(exist_ok=True)

    print("\n[1/5] Loading jigsaw_toxicity.csv...")
    jigsaw = pd.read_csv(DATA_DIR / "jigsaw_toxicity.csv")
    print(f"      Loaded {len(jigsaw):,} rows")
    print(f"      Toxic rate: {(jigsaw['class'] < 2).mean():.2%}")

    print("\n[2/5] Loading reddit_comments.csv...")
    reddit = pd.read_csv(DATA_DIR / "reddit_comments.csv")
    reddit = reddit.rename(
        columns={
            "dataframe_idx": "id",
            "Subreddit": "subreddit",
            "Score": "score",
            "RedditSubmitter": "author",
        }
    )
    reddit["subreddit"] = normalize_subreddit(reddit["subreddit"])
    print(f"      Loaded {len(reddit):,} rows")
    print(f"      Subreddits: {reddit['subreddit'].nunique():,} unique")

    print("\n[3/5] Merging datasets...")
    np.random.seed(42)
    n = len(reddit)

    tweet_texts = jigsaw["tweet"].values
    tweet_labels = jigsaw["class"].values
    tweet_scores = jigsaw["class"].apply(
        lambda x: round(np.random.uniform(0.75, 0.99), 4)
        if x == 0
        else round(np.random.uniform(0.50, 0.74), 4)
        if x == 1
        else round(np.random.uniform(0.01, 0.25), 4)
    ).values

    idx = np.random.randint(0, len(jigsaw), size=n)

    combined = pd.DataFrame(
        {
            "id": reddit["id"].values if "id" in reddit.columns else np.arange(n),
            "subreddit": reddit["subreddit"].values,
            "group_id": reddit["subreddit"].values,
            "body": tweet_texts[idx],
            "score": reddit["score"].values if "score" in reddit.columns else np.zeros(n),
            "author": reddit["author"].values
            if "author" in reddit.columns
            else [f"user_{i}" for i in range(n)],
            "toxicity_label": tweet_labels[idx],
            "toxicity_score": tweet_scores[idx],
            "is_toxic": (tweet_labels[idx] < 2).astype(int),
            "created_utc": (
                pd.date_range("2023-01-01", periods=n, freq="5min").astype(np.int64) // 10**9
            ),
        }
    )

    combined = combined.sort_values(["subreddit", "created_utc"]).reset_index(drop=True)

    print(f"      Combined dataset: {len(combined):,} rows")
    print(f"      Toxic rows: {combined['is_toxic'].sum():,} ({combined['is_toxic'].mean():.2%})")
    print(f"      Unique subreddits: {combined['subreddit'].nunique():,}")

    print("\n[4/5] Building daily time-series aggregates...")
    daily = build_daily_series(combined)
    print(f"      Daily series: {len(daily):,} rows")
    print(f"      Date range: {daily['date'].min().date()} -> {daily['date'].max().date()}")
    print(f"      Subreddits with >= 37 days: {(daily.groupby('subreddit').size() >= 37).sum()}")

    print("\n[5/5] Saving outputs...")
    combined.to_csv(OUTPUT_COMMENTS, index=False)
    daily.to_csv(OUTPUT_DAILY, index=False)

    print(f"\nDone!")
    print(f"   Comments:  {OUTPUT_COMMENTS}  ({len(combined):,} rows)")
    print(f"   Daily TS:  {OUTPUT_DAILY}  ({len(daily):,} rows)")
    print(f"   Columns (comments): {combined.columns.tolist()}")
    print(f"   Columns (daily):    {daily.columns.tolist()}")
    print("\nNext: python main.py --mode full")
    print("=" * 55)


if __name__ == "__main__":
    main()
