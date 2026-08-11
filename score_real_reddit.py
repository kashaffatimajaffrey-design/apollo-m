"""
Score the real Reddit corpus with the micro layer and build a daily series.

This is the proof that the pipeline is not tied to the simulation. The same
toxicity model, the same aggregation and the same daily structure are applied to
genuine Reddit comments collected through ingest/arctic_shift.py — so the only
thing that changed between the declared benchmark and real data is the ingestion
adapter, which is exactly what the architecture claims.

Writes:
    data/reddit_live_daily.csv        per-subreddit daily series (TFT-ready)
    outputs/real_reddit_summary.json  headline comparison against the simulation

    python score_real_reddit.py [--limit N]
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "data" / "reddit_live_sample.csv"
DAILY = ROOT / "data" / "reddit_live_daily.csv"
SUMMARY = ROOT / "outputs" / "real_reddit_summary.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="cap comments scored (0 = all)")
    a = ap.parse_args()

    df = pd.read_csv(SRC)
    if a.limit:
        # Sample evenly across communities so no subreddit dominates the cap.
        df = df.groupby("subreddit", group_keys=False).head(
            max(1, a.limit // df["subreddit"].nunique()))
    print(f"scoring {len(df):,} real Reddit comments "
          f"({df['subreddit'].nunique()} subreddits)...")

    from transformers import pipeline
    clf = pipeline("text-classification", model="unitary/toxic-bert",
                   top_k=None, truncation=True, max_length=256)

    texts = df["body"].astype(str).str.slice(0, 512).tolist()
    scores, B = [], 64
    for i in range(0, len(texts), B):
        for res in clf(texts[i:i + B], batch_size=B):
            d = {r["label"].lower(): r["score"] for r in res}
            scores.append(float(d.get("toxic", 0.0)))
        if (i // B) % 20 == 0:
            print(f"  {min(i + B, len(texts)):,}/{len(texts):,}", flush=True)

    df["toxicity_score"] = scores
    df["is_toxic"] = (df["toxicity_score"] >= 0.5).astype(int)
    df["date"] = pd.to_datetime(df["created_utc"], unit="s").dt.floor("D")

    daily = (df.groupby(["subreddit", "date"], as_index=False)
               .agg(avg_toxicity=("toxicity_score", "mean"),
                    toxic_rate=("is_toxic", "mean"),
                    comment_count=("id", "count"),
                    unique_authors=("author", "nunique"))
               .sort_values(["subreddit", "date"]))
    daily["time_idx"] = daily.groupby("subreddit").cumcount()
    daily["group_id"] = daily["subreddit"]
    DAILY.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(DAILY, index=False)

    per_sub = (df.groupby("subreddit")
                 .agg(comments=("id", "count"),
                      authors=("author", "nunique"),
                      mean_toxicity=("toxicity_score", "mean"),
                      toxic_rate=("is_toxic", "mean"))
                 .sort_values("mean_toxicity", ascending=False).round(4))

    print("\nREAL Reddit — toxicity by community")
    print(per_sub.to_string())

    spread = float(per_sub["mean_toxicity"].max() - per_sub["mean_toxicity"].min())
    summary = {
        "source": "Arctic Shift (Pushshift successor) — public HTTP API, no key",
        "comments_scored": int(len(df)),
        "subreddits": int(df["subreddit"].nunique()),
        "authors": int(df["author"].nunique()),
        "days_covered": int(df["date"].nunique()),
        "date_range": [str(df["date"].min().date()), str(df["date"].max().date())],
        "model": "unitary/toxic-bert",
        "mean_toxicity_overall": round(float(df["toxicity_score"].mean()), 4),
        "toxic_rate_overall": round(float(df["is_toxic"].mean()), 4),
        "per_community": {k: {kk: float(vv) for kk, vv in v.items()}
                          for k, v in per_sub.to_dict("index").items()},
        "between_community_spread": round(spread, 4),
        "note": "Real Reddit comments, real authors, real timestamps, scored by the "
                "same micro layer the simulation uses. Demonstrates that only the "
                "ingestion adapter differs between the declared benchmark and live "
                "data; every layer above it is unchanged.",
    }
    SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\ndaily series -> {DAILY}  ({len(daily)} rows, "
          f"{daily['subreddit'].nunique()} communities x {df['date'].nunique()} days)")
    print(f"summary      -> {SUMMARY}")
    print(f"\noverall mean toxicity {summary['mean_toxicity_overall']:.4f} | "
          f"toxic rate {summary['toxic_rate_overall']:.1%} | "
          f"between-community spread {spread:.4f}")


if __name__ == "__main__":
    main()
