"""
APOLLO-M: ground-truth simulation generator.

WHY THIS REPLACES prepare_data.py
---------------------------------
`prepare_data.py` produced a dataset that could not support any of the project's
claims, for three independent reasons:

  1. Comment text was assigned to communities at random
     (`idx = np.random.randint(0, len(jigsaw), size=n)`), so a community had no
     relationship to its own content — r/Astronomy rows contained tweets with
     racial slurs, r/politics rows contained tweets about exes.
  2. `toxicity_score` was never a model output. It was
     `np.random.uniform(0.75,0.99) / (0.50,0.74) / (0.01,0.25)`, selected by the
     Jigsaw class label.
  3. `created_utc` was a single `date_range` laid down in row order and then
     sorted by subreddit, so each community occupied its own contiguous block of
     time instead of running concurrently with the others.

Together those meant per-community differences were sampling noise. With ~40
comments per community the noise looked like signal (toxicity spread 0.67-0.83);
at 4,600 comments per community it collapsed to 0.543-0.559.

WHAT THIS GENERATES INSTEAD
---------------------------
A declared simulation with known ground truth, which is a legitimate way to
validate a forecasting pipeline when real labelled instability data is not
available. Three properties make the output meaningful where the old one was not:

  * Toxicity is REAL and text-derived. A pool of Jigsaw texts is scored once with
    the actual toxic-bert model; every generated comment carries the genuine
    score for the exact text it contains. No invented numbers.
  * Communities differ BY CONSTRUCTION. Each is given a latent toxicity
    propensity, and a named subset is given a rising trend over the final weeks.
    Those assignments are written to data/ground_truth.json.
  * All communities share one calendar, so the daily series are concurrent and a
    forecaster has a real trend to learn.

Because the ground truth is recorded, the honest claim becomes measurable: does
the pipeline recover the communities we destabilised? `validate_simulation.py`
answers that with precision/recall rather than assertion.

This file writes ONLY to data/. Nothing here should ever be described as real
Reddit activity — it is a benchmark, and the report must say so.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("data")
JIGSAW = DATA_DIR / "jigsaw_toxicity.csv"   # cols: class (0 hate, 1 offensive, 2 neither), tweet
REDDIT = DATA_DIR / "reddit_comments.csv"   # absent in this checkout; names then come from the
                                            # existing apollo_comments.csv (read before rewrite)
OUT_COMMENTS = DATA_DIR / "apollo_comments.csv"
OUT_DAILY = DATA_DIR / "apollo_daily.csv"
OUT_TRUTH = DATA_DIR / "ground_truth.json"

SEED = 42
N_COMMUNITIES = 60
N_DAYS = 120
POOL_SIZE = 12000          # unique texts scored by toxic-bert
DESTABILISING_FRAC = 0.25  # share of communities given a rising trend
START = "2026-03-01"

rng = np.random.default_rng(SEED)


# ---------------------------------------------------------------------------
# 1. Score a pool of real texts with the real model
# ---------------------------------------------------------------------------

def score_pool(texts: list[str]) -> np.ndarray:
    """
    Run toxic-bert over the text pool once.

    Every comment in the output reuses one of these (text, score) pairs, so the
    score always belongs to the text it is attached to. Falls back to a keyword
    heuristic only if transformers is unavailable, and says so loudly — a silent
    fallback here would reintroduce exactly the problem this file exists to fix.
    """
    try:
        from transformers import pipeline
    except Exception as exc:  # noqa: BLE001
        print(f"  !! transformers unavailable ({exc}); using keyword heuristic")
        return _heuristic(texts)

    print(f"  scoring {len(texts):,} unique texts with unitary/toxic-bert ...")
    clf = pipeline("text-classification", model="unitary/toxic-bert",
                   top_k=None, truncation=True, max_length=256)
    scores = np.zeros(len(texts), dtype=float)
    B = 128
    for i in range(0, len(texts), B):
        batch = [t[:512] for t in texts[i:i + B]]
        for j, res in enumerate(clf(batch, batch_size=B)):
            d = {r["label"].lower(): r["score"] for r in res}
            scores[i + j] = float(d.get("toxic", 0.0))
        if (i // B) % 10 == 0:
            print(f"    {min(i + B, len(texts)):,}/{len(texts):,}", flush=True)
    return scores


def _heuristic(texts: list[str]) -> np.ndarray:
    kw = ("idiot", "stupid", "hate", "bitch", "nigg", "fuck", "trash", "kill")
    return np.array([min(sum(k in t.lower() for k in kw) / 3.0, 1.0) for t in texts])


# ---------------------------------------------------------------------------
# 2. Ground truth: who is destabilising, and how badly
# ---------------------------------------------------------------------------

def make_ground_truth(subs: list[str]) -> dict:
    """
    Assign each community a latent toxicity propensity and a trajectory.

    'stable'       — flat propensity plus daily noise
    'destabilising'— propensity climbs over the final third of the window
    'improving'    — propensity falls (so the model must avoid alerting on it)

    Recording this is the whole point: it is what turns "our alerts fired" into
    "our alerts fired on the right communities, and here is the recall".
    """
    n = len(subs)
    n_bad = max(2, int(round(n * DESTABILISING_FRAC)))
    n_good = max(2, int(round(n * 0.15)))
    order = rng.permutation(n)
    bad = {subs[i] for i in order[:n_bad]}
    good = {subs[i] for i in order[n_bad:n_bad + n_good]}

    truth = {}
    for s in subs:
        base = float(np.clip(rng.beta(2.2, 5.0), 0.03, 0.72))
        if s in bad:
            traj, delta = "destabilising", float(rng.uniform(0.22, 0.45))
        elif s in good:
            traj, delta = "improving", -float(rng.uniform(0.10, 0.25))
        else:
            traj, delta = "stable", float(rng.normal(0, 0.02))
        truth[s] = {"baseline_toxicity": round(base, 4),
                    "trajectory": traj,
                    "delta_over_window": round(delta, 4)}
    return truth


def propensity_on(day: int, base: float, delta: float) -> float:
    """Toxic-comment probability for a community on a given day."""
    # Trend switches on for the final third of the window, so the first two
    # thirds give the forecaster a stable history to learn from.
    onset = int(N_DAYS * 0.66)
    ramp = 0.0 if day < onset else (day - onset) / max(1, N_DAYS - onset)
    val = base + delta * ramp + rng.normal(0, 0.03)
    # a mild weekly rhythm, so the series is not trivially smooth
    val += 0.02 * np.sin(2 * np.pi * day / 7)
    return float(np.clip(val, 0.01, 0.97))


# ---------------------------------------------------------------------------
# 3. Build the corpus
# ---------------------------------------------------------------------------

def main() -> None:
    print("[1/5] Loading source datasets ...")
    jig = pd.read_csv(JIGSAW)
    text_col = "tweet" if "tweet" in jig.columns else jig.columns[-1]
    label_col = "class" if "class" in jig.columns else "label"
    jig = jig.dropna(subset=[text_col])
    print(f"      Jigsaw rows: {len(jig):,}")

    subs = _pick_subreddits()
    print(f"      Communities: {len(subs)}")

    print("[2/5] Scoring the text pool with the real model ...")
    pool = jig.sample(min(POOL_SIZE, len(jig)), random_state=SEED)
    pool_text = pool[text_col].astype(str).tolist()
    pool_label = pool[label_col].to_numpy()
    pool_score = score_pool(pool_text)
    # Split the pool by the model's own score so sampling can target toxicity
    # without ever inventing a number.
    toxic_idx = np.where(pool_score >= 0.5)[0]
    clean_idx = np.where(pool_score < 0.5)[0]
    print(f"      pool: {len(toxic_idx):,} toxic / {len(clean_idx):,} clean "
          f"(mean score {pool_score.mean():.3f})")
    if len(toxic_idx) == 0 or len(clean_idx) == 0:
        raise SystemExit("text pool lacks both classes — cannot simulate")

    print("[3/5] Assigning ground truth ...")
    truth = make_ground_truth(subs)
    n_bad = sum(1 for v in truth.values() if v["trajectory"] == "destabilising")
    print(f"      {n_bad} destabilising / "
          f"{sum(1 for v in truth.values() if v['trajectory']=='improving')} improving / "
          f"{len(subs)-n_bad-sum(1 for v in truth.values() if v['trajectory']=='improving')} stable")

    print("[4/5] Generating comments ...")
    dates = pd.date_range(START, periods=N_DAYS, freq="D")
    rows = []
    cid = 0
    for s in subs:
        t = truth[s]
        # a stable core of authors plus newcomers; churn rises with instability
        core = [f"{s.lower()}_u{i}" for i in range(rng.integers(25, 70))]
        volume = int(rng.integers(18, 55))          # mean comments/day
        for day, date in enumerate(dates):
            p = propensity_on(day, t["baseline_toxicity"], t["delta_over_window"])
            n_today = max(1, int(rng.poisson(volume)))
            k_toxic = int(rng.binomial(n_today, p))
            picks = np.concatenate([
                rng.choice(toxic_idx, size=k_toxic, replace=True),
                rng.choice(clean_idx, size=n_today - k_toxic, replace=True),
            ])
            # author turnover: destabilising communities shed regulars
            churn_p = 0.15 + (0.35 if t["trajectory"] == "destabilising" else 0.0) * (day / N_DAYS)
            for pi in picks:
                author = (f"{s.lower()}_new{rng.integers(0, 9000)}"
                          if rng.random() < churn_p else core[rng.integers(0, len(core))])
                secs = int(rng.integers(0, 86400))
                rows.append((
                    cid, s, s, pool_text[pi], int(rng.integers(-5, 60)), author,
                    int(pool_label[pi]), round(float(pool_score[pi]), 4),
                    int(pool_score[pi] >= 0.5),
                    int(date.timestamp()) + secs,
                ))
                cid += 1
        print(f"      {s:<28} base={t['baseline_toxicity']:.2f} {t['trajectory']}", flush=True)

    comments = pd.DataFrame(rows, columns=[
        "id", "subreddit", "group_id", "body", "score", "author",
        "toxicity_label", "toxicity_score", "is_toxic", "created_utc",
    ]).sort_values(["subreddit", "created_utc"]).reset_index(drop=True)

    print(f"      {len(comments):,} comments across {comments.subreddit.nunique()} communities")

    print("[5/5] Writing outputs ...")
    comments.to_csv(OUT_COMMENTS, index=False)
    daily = _build_daily(comments)
    daily.to_csv(OUT_DAILY, index=False)
    OUT_TRUTH.write_text(json.dumps(truth, indent=2), encoding="utf-8")

    print(f"      {OUT_COMMENTS}  ({len(comments):,} rows)")
    print(f"      {OUT_DAILY}     ({len(daily):,} rows)")
    print(f"      {OUT_TRUTH}     ({len(truth)} communities)")

    obs = comments.groupby("subreddit")["toxicity_score"].mean()
    print(f"\n      observed per-community toxicity spread: "
          f"{obs.min():.3f} .. {obs.max():.3f}  (was 0.543 .. 0.559)")


def _pick_subreddits() -> list[str]:
    """Use real subreddit names, largest first, so the labels stay recognisable."""
    if REDDIT.exists():
        s = pd.read_csv(REDDIT, usecols=["subreddit"])["subreddit"]
        s = s.astype(str).str.replace(r"^r/", "", regex=True).str.strip()
        return s.value_counts().head(N_COMMUNITIES).index.tolist()
    if OUT_COMMENTS.exists():
        s = pd.read_csv(OUT_COMMENTS, usecols=["subreddit"])["subreddit"]
        s = s.astype(str).str.replace(r"^r/", "", regex=True).str.strip()
        return s.value_counts().head(N_COMMUNITIES).index.tolist()
    return [f"community_{i:02d}" for i in range(N_COMMUNITIES)]


def _build_daily(comments: pd.DataFrame) -> pd.DataFrame:
    df = comments.copy()
    df["date"] = pd.to_datetime(df["created_utc"], unit="s", errors="coerce").dt.floor("D")
    daily = (df.groupby(["subreddit", "date"], as_index=False)
               .agg(avg_toxicity=("toxicity_score", "mean"),
                    toxic_rate=("is_toxic", "mean"),
                    comment_count=("id", "count"),
                    avg_score=("score", "mean"),
                    unique_authors=("author", "nunique"))
               .sort_values(["subreddit", "date"]).reset_index(drop=True))
    daily["time_idx"] = daily.groupby("subreddit").cumcount()
    daily["group_id"] = daily["subreddit"]
    return daily


if __name__ == "__main__":
    main()
