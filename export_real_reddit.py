"""
Publish the real-Reddit corpus into outputs/ for the dashboard.

data/ is gitignored — the corpus is large and regenerates — so a hosted dashboard
would find nothing there. This copies the small, display-sized artifacts into
outputs/, which is committed, so the Real Reddit page works on the deployed app
and not only on the machine that collected the data.

Writes:
    outputs/real_reddit_daily.csv    per-community daily series
    outputs/real_reddit_recent.csv   a scored slice for the live feed

    python export_real_reddit.py
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "data" / "reddit_live_sample.csv"
DAILY_SRC = ROOT / "data" / "reddit_live_daily.csv"
OUT = ROOT / "outputs"
N_RECENT = 60


def main() -> None:
    OUT.mkdir(exist_ok=True)

    if DAILY_SRC.exists():
        d = pd.read_csv(DAILY_SRC)
        d.to_csv(OUT / "real_reddit_daily.csv", index=False)
        print(f"daily series -> outputs/real_reddit_daily.csv "
              f"({len(d)} rows, {d['subreddit'].nunique()} communities)")
    else:
        print("data/reddit_live_daily.csv not found — run score_real_reddit.py first")

    if not SAMPLE.exists():
        print("no corpus to slice")
        return

    df = pd.read_csv(SAMPLE).sort_values("created_utc", ascending=False)
    # Spread across communities so the feed does not show one busy subreddit.
    recent = df.groupby("subreddit", group_keys=False).head(
        max(1, N_RECENT // max(1, df["subreddit"].nunique())))
    recent = recent.sort_values("created_utc", ascending=False).head(N_RECENT).copy()

    # Score just this slice: seconds, and it keeps the feed honest — the numbers
    # shown next to each comment are that comment's own toxicity, not a stand-in.
    try:
        from transformers import pipeline
        clf = pipeline("text-classification", model="unitary/toxic-bert",
                       top_k=None, truncation=True, max_length=256)
        scores = []
        for res in clf(recent["body"].astype(str).str.slice(0, 512).tolist(),
                       batch_size=32):
            d = {r["label"].lower(): r["score"] for r in res}
            scores.append(round(float(d.get("toxic", 0.0)), 4))
        recent["toxicity_score"] = scores
    except Exception as exc:  # noqa: BLE001
        print(f"scoring skipped ({exc}); feed will show comments without scores")
        recent["toxicity_score"] = None

    cols = ["subreddit", "author", "body", "toxicity_score", "created_utc"]
    recent[cols].to_csv(OUT / "real_reddit_recent.csv", index=False)
    print(f"recent feed  -> outputs/real_reddit_recent.csv ({len(recent)} comments)")
    if recent["toxicity_score"].notna().any():
        print(f"  toxicity {recent['toxicity_score'].min():.3f} .. "
              f"{recent['toxicity_score'].max():.3f}")


if __name__ == "__main__":
    main()
