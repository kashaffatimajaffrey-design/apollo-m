"""Live Reddit ingestion via PRAW.

Pulls the most recent comments from one or more subreddits and returns them in the
same schema the pipeline expects (subreddit, body, score, author, created_utc), so
`main.py` can analyse *live* data instead of the static Kaggle dump. This is the
"real-time data processing" feature.

Credentials (register a script app at https://www.reddit.com/prefs/apps):
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
If they are missing, `fetch_recent` raises a clear error rather than failing
obscurely — the rest of the pipeline still runs on the static corpus.

  python ingest/praw_ingest.py --subreddits politics worldnews --limit 200
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

import pandas as pd


class RedditCredentialsMissing(RuntimeError):
    pass


def _client():
    import praw

    cid = os.getenv("REDDIT_CLIENT_ID")
    secret = os.getenv("REDDIT_CLIENT_SECRET")
    ua = os.getenv("REDDIT_USER_AGENT", "apollo-m/0.1 by fyp")
    if not (cid and secret):
        raise RedditCredentialsMissing(
            "Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET (register a 'script' app "
            "at https://www.reddit.com/prefs/apps). Read-only access needs no login."
        )
    return praw.Reddit(client_id=cid, client_secret=secret, user_agent=ua,
                       check_for_async=False)


def fetch_recent(subreddits: list[str], limit: int = 200) -> pd.DataFrame:
    """Return recent comments across `subreddits` as a pipeline-shaped DataFrame."""
    reddit = _client()
    rows = []
    for sub in subreddits:
        name = sub[2:] if sub.startswith("r/") else sub
        for c in reddit.subreddit(name).comments(limit=limit):
            rows.append({
                "subreddit": f"r/{name}",
                "body": c.body,
                "score": int(getattr(c, "score", 0) or 0),
                "author": str(c.author) if c.author else "[deleted]",
                "created_utc": datetime.fromtimestamp(
                    getattr(c, "created_utc", 0), tz=timezone.utc).isoformat(),
            })
    df = pd.DataFrame(rows)
    df["group_id"] = df["subreddit"] if not df.empty else None
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--subreddits", nargs="+", default=["politics", "worldnews"])
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--out", default="data/live_comments.csv")
    args = ap.parse_args()
    try:
        df = fetch_recent(args.subreddits, args.limit)
    except RedditCredentialsMissing as exc:
        raise SystemExit(f"[praw] {exc}")
    df.to_csv(args.out, index=False)
    print(f"[praw] fetched {len(df)} comments from {args.subreddits} -> {args.out}")


if __name__ == "__main__":
    main()
