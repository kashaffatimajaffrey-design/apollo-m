"""Live replay — real-time processing of the real corpus (no Reddit API needed).

Streams the team's real, already-toxicity-scored comments through a live feed at a
steady rate, as if they were arriving now. It maintains a rolling window and
writes two files the dashboard reads on a timer:

    outputs/live_feed.csv   — the last N comments (ticker)
    outputs/live_stats.json — rolling counts + toxic rate + hottest community

This is honest "real-time data processing": real comments, real toxicity scores,
flowing through in real time — just sourced from the corpus instead of Reddit's
(now credential-gated) API. Reddit-API ingestion (ingest/praw_ingest.py) drops in
unchanged the moment valid keys exist.

  python ingest/live_replay.py            # streams ~6 comments/sec, Ctrl-C to stop
"""
from __future__ import annotations

import argparse
import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "outputs"
SRC = Path(__file__).resolve().parents[1] / "data" / "apollo_comments.csv"
WINDOW = 120


def _load_stream(sample: int) -> pd.DataFrame:
    cols = ["subreddit", "body", "toxicity_score", "is_toxic", "score", "author"]
    df = pd.read_csv(SRC, usecols=lambda c: c in cols, nrows=sample * 3)
    df = df.dropna(subset=["body", "toxicity_score"])
    df = df.sample(min(sample, len(df)), random_state=7).reset_index(drop=True)
    df["subreddit"] = df["subreddit"].astype(str).apply(
        lambda s: s if s.startswith("r/") else f"r/{s}")
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rate", type=float, default=6.0, help="comments per second")
    ap.add_argument("--sample", type=int, default=40000, help="corpus rows to cycle")
    args = ap.parse_args()

    stream = _load_stream(args.sample)
    print(f"[live] streaming {len(stream)} real comments at ~{args.rate}/s "
          f"(Ctrl-C to stop) -> {OUT}/live_feed.csv")

    window: deque[dict] = deque(maxlen=WINDOW)
    processed = 0
    per_batch = max(1, int(args.rate))
    i = 0
    while True:
        for _ in range(per_batch):
            row = stream.iloc[i % len(stream)]
            i += 1
            processed += 1
            window.append({
                "subreddit": row["subreddit"],
                "body": str(row["body"])[:160],
                "toxicity": round(float(row["toxicity_score"]), 3),
                "is_toxic": bool(row.get("is_toxic", float(row["toxicity_score"]) > 0.5)),
                "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            })
        wdf = pd.DataFrame(list(window))
        wdf.to_csv(OUT / "live_feed.csv", index=False)

        toxic_rate = float(wdf["is_toxic"].mean()) if len(wdf) else 0.0
        hot = (wdf.groupby("subreddit")["toxicity"].mean().sort_values(ascending=False)
               if len(wdf) else pd.Series(dtype=float))
        stats = {
            "processed": processed,
            "window": len(window),
            "rolling_toxic_rate": round(toxic_rate, 3),
            "rolling_avg_toxicity": round(float(wdf["toxicity"].mean()), 3) if len(wdf) else 0.0,
            "hottest_community": (hot.index[0] if len(hot) else None),
            "hottest_toxicity": (round(float(hot.iloc[0]), 3) if len(hot) else None),
            "updated": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
        }
        (OUT / "live_stats.json").write_text(json.dumps(stats))
        time.sleep(1.0)


if __name__ == "__main__":
    main()
