"""
Real Reddit ingestion via Arctic Shift.

Reddit's own API requires credentials gated behind account age and karma
thresholds, which is why this project has been running on a declared simulation.
Arctic Shift is the community successor to Pushshift: it serves historical Reddit
comments and submissions over an open HTTP API with no key, and also publishes
bulk monthly dumps.

This module fetches genuine Reddit comments into the same normalised shape every
layer above ingestion already consumes:

    subreddit, author, body, score, created_utc

so nothing downstream changes. That is the whole point of keeping ingestion
behind a narrow interface: swapping the source is one adapter, not a rewrite.

    python ingest/arctic_shift.py --subreddits politics news --days 30 --per-sub 800

Scope note. The API returns pages of at most 100 comments, so a full 18-month
corpus across many subreddits is better collected from the bulk monthly dumps
than through this endpoint. This adapter exists to prove the path end to end and
to supply a real sample; the dumps are the route for the full corpus.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("APOLLO-M.arctic")

API = "https://arctic-shift.photon-reddit.com/api/comments/search"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reddit_live_sample.csv"
PAGE = 100          # server-side maximum
FIELDS = ["subreddit", "author", "body", "score", "created_utc", "id"]


def fetch_subreddit(subreddit: str, after: datetime, before: datetime,
                    target: int = 800, pause: float = 0.4) -> list[dict]:
    """
    Page through one subreddit's comments in a date window.

    Pagination advances the `after` cursor to the newest timestamp seen. A page
    that returns nothing new ends the loop, which also guards against a server
    that ignores the cursor and would otherwise loop forever.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    # The endpoint returns the newest comments below `before`, so paging means
    # walking the `before` cursor BACKWARDS in time. Timestamps are passed as
    # epoch seconds: date strings only resolve to a day, so a day's worth of
    # comments would be re-requested forever without ever advancing.
    lo = int(after.timestamp())
    cursor = int(before.timestamp())

    while len(rows) < target and cursor > lo:
        params = {
            "subreddit": subreddit,
            "after": lo,
            "before": cursor,
            "limit": PAGE,
        }
        # Retried rather than abandoned: a single DNS or timeout blip should not
        # discard a whole subreddit's collection, which is what happened on the
        # first run over an unreliable connection.
        batch = None
        for attempt in range(3):
            try:
                r = requests.get(API, params=params, timeout=30)
                if r.status_code == 200:
                    batch = r.json().get("data") or []
                    break
                if r.status_code in (429, 502, 503):
                    time.sleep(2 * (attempt + 1))
                    continue
                log.warning("r/%s: HTTP %s", subreddit, r.status_code)
                break
            except Exception:  # noqa: BLE001
                time.sleep(1.5 * (attempt + 1))
        if batch is None:
            break

        fresh = [c for c in batch if c.get("id") not in seen]
        if not fresh:
            break

        for c in fresh:
            seen.add(c.get("id"))
            body = (c.get("body") or "").strip()
            # [deleted] and [removed] carry no text to score.
            if not body or body in ("[deleted]", "[removed]"):
                continue
            rows.append({
                "id": c.get("id"),
                "subreddit": c.get("subreddit", subreddit),
                "author": c.get("author"),
                "body": body,
                "score": c.get("score", 0),
                "created_utc": c.get("created_utc"),
            })

        oldest = min((c.get("created_utc", 0) for c in fresh
                      if c.get("created_utc")), default=0)
        if not oldest or oldest - 1 >= cursor:
            break
        cursor = oldest - 1
        time.sleep(pause)          # deliberate: a public service, used politely

    log.info("r/%-16s %5d comments", subreddit, len(rows))
    return rows


def collect(subreddits: list[str], days: int, per_sub: int) -> pd.DataFrame:
    """
    Sample each day separately rather than paging back from the present.

    The forecaster consumes a DAILY series, and a busy subreddit produces
    thousands of comments a day — so paging backwards from now returns a few
    hours of one day and no time series at all. Requesting a slice per day
    yields even coverage across the window, which is what the macro layer needs.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    per_day = max(40, per_sub // max(1, days))
    log.info("window %s .. %s  (%d days, ~%d comments/day/subreddit)",
             start.date(), end.date(), days, per_day)

    all_rows: list[dict] = []
    for s in subreddits:
        got = 0
        for d in range(days):
            day_start = start + timedelta(days=d)
            day_end = day_start + timedelta(days=1)
            rows = fetch_subreddit(s, day_start, day_end, target=per_day, pause=0.15)
            all_rows.extend(rows)
            got += len(rows)
        log.info("r/%-16s %5d comments across %d days", s, got, days)

    df = pd.DataFrame(all_rows, columns=FIELDS)
    if not df.empty:
        df = df.drop_duplicates("id").sort_values(["subreddit", "created_utc"])
    return df.reset_index(drop=True)


def merge_into(path: Path, fresh: pd.DataFrame) -> pd.DataFrame:
    """
    Append only comments not already stored.

    Keeping one growing corpus rather than overwriting means the collection
    deepens on every run, which is what makes an unattended schedule useful: the
    history accumulates instead of being replaced by the latest window.
    """
    if path.exists():
        try:
            existing = pd.read_csv(path)
            fresh = pd.concat([existing, fresh], ignore_index=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not read existing corpus (%s) — writing fresh", exc)
    fresh = fresh.drop_duplicates("id").sort_values(["subreddit", "created_utc"])
    return fresh.reset_index(drop=True)


def run_once(subs: list[str], days: int, per_sub: int, out: Path) -> pd.DataFrame:
    df = collect(subs, days, per_sub)
    if df.empty:
        log.error("no comments returned — API unreachable or window empty")
        return df
    out.parent.mkdir(parents=True, exist_ok=True)
    merged = merge_into(out, df)
    merged.to_csv(out, index=False)
    added = len(merged) - (len(merged) - len(df)) if not out.exists() else None
    log.info("corpus now %d comments (this run fetched %d)", len(merged), len(df))
    return merged


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Fetch real Reddit comments via Arctic Shift")
    ap.add_argument("--subreddits", nargs="+", default=[
        "politics", "news", "worldnews", "technology", "science", "movies"])
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--per-sub", type=int, default=800)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--watch", action="store_true",
                    help="collect continuously instead of exiting after one pass")
    ap.add_argument("--every-hours", type=float, default=12.0,
                    help="hours between passes in --watch mode")
    a = ap.parse_args()
    out = Path(a.out)

    if not a.watch:
        df = run_once(a.subreddits, a.days, a.per_sub, out)
        if df.empty:
            return
        _summarise(df, out)
        return

    # Unattended mode. Each pass re-scans a short recent window and merges, so
    # the corpus extends itself without anyone choosing dates. A failed pass is
    # logged and the schedule continues rather than terminating the collector.
    log.info("watch mode: every %.1f h over a %d-day window; Ctrl-C to stop",
             a.every_hours, a.days)
    while True:
        try:
            df = run_once(a.subreddits, a.days, a.per_sub, out)
            if not df.empty:
                _summarise(df, out)
        except KeyboardInterrupt:
            log.info("stopped")
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("pass failed (%s) — retrying next cycle", exc)
        time.sleep(a.every_hours * 3600)


def _summarise(df: pd.DataFrame, out: Path) -> None:
    days = pd.to_datetime(df["created_utc"], unit="s").dt.date.nunique()
    print(f"\ncorpus: {len(df):,} REAL Reddit comments -> {out}")
    print(f"  {df['subreddit'].nunique()} subreddits, {df['author'].nunique():,} authors, "
          f"{days} distinct days")
    print(df["subreddit"].value_counts().to_string())


if __name__ == "__main__":
    main()
