"""
Quick smoke test — runs only 20 comments through the Micro Layer
to confirm everything (dependencies, model loading, scoring) works
before committing to the full 50k-row run.
"""

import pandas as pd
from main import Config, MicroLayer

cfg = Config()
cfg.setup_dirs()

print("Loading a small sample of comments...")
df = pd.read_csv(cfg.REDDIT_COMMENTS, nrows=20)
print(f"Loaded {len(df)} rows")
print(df[["subreddit", "body"]].head())

print("\nInitializing Micro Layer (downloads the BERT model on first run)...")
micro = MicroLayer(cfg)

print("\nScoring comments...")
result = micro.analyze_batch(df)

print("\nDone! Sample results:")
print(result[["subreddit", "body", "toxicity_score", "is_toxic"]].head(10))
print(f"\nToxic rate in this sample: {result['is_toxic'].mean():.2%}")
