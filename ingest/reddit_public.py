"""Keyless live Reddit ingestion via Reddit's public JSON API.

No app, no client_id/secret, no OAuth — Reddit serves recent comments as JSON at
`https://www.reddit.com/r/<sub>/comments/.json`. This sidesteps the app-creation
gate entirely and still gives the pipeline live data. A descriptive User-Agent is
required (Reddit 429s the default one). Rate limits are light; fine for a demo.

PRAW (ingest/praw_ingest.py) remains the higher-throughput option if you ever get
API keys — this is the zero-setup path.

  python ingest/reddit_public.py --subreddits politics worldnews --limit 100
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

import pandas as pd
import requests

UA = "apollo-m/0.1 (community-health FYP; contact: student)"


def fetch_recent(subreddits: list[str], limit: int = 100) -> pd.DataFrame:
    """Return recent comments across `subreddits` as a pipeline-shaped DataFrame."""
    rows: list[dict] = []
    for sub in subreddits:
        name = sub[2:] if sub.startswith("r/") else sub
        url = f"https://www.reddit.com/r/{name}/comments/.json"
        try:
            r = requests.get(url, headers={"User-Agent": UA},
                             params={"limit": min(limit, 100)}, timeout=20)
            r.raise_for_status()
            children = r.json().get("data", {}).get("children", [])
        except requests.RequestException as exc:
            print(f"[reddit] {name}: {exc.__class__.__name__} — skipping")
            continue
        for ch in children:
            d = ch.get("data", {})
            body = d.get("body") or (d.get("title", "") + " " + d.get("selftext", "")).strip()
            if not body:
                continue
            rows.append({
                "subreddit": f"r/{name}",
                "body": body,
                "score": int(d.get("score", 0) or 0),
                "author": d.get("author", "[deleted]"),
                "created_utc": datetime.fromtimestamp(
                    d.get("created_utc", 0), tz=timezone.utc).isoformat(),
            })
        time.sleep(1)  # be polite to the public endpoint
    df = pd.DataFrame(rows)
    df["group_id"] = df["subreddit"] if not df.empty else None
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--subreddits", nargs="+", default=["politics", "worldnews"])
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--out", default="data/live_comments.csv")
    args = ap.parse_args()
    df = fetch_recent(args.subreddits, args.limit)
    df.to_csv(args.out, index=False)
    print(f"[reddit] fetched {len(df)} live comments from {args.subreddits} -> {args.out}")


if __name__ == "__main__":
    main()
