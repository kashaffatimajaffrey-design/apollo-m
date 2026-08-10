"""Smoke test: train the TFT on the real embedded daily series and forecast.

Bypasses main.py's synthetic/HF-download path by feeding the precomputed
outputs/timeseries_with_embeddings.csv straight into TFTForecaster. Proves the
headline forecasting feature runs end-to-end on this machine with no network.
"""
import logging
import warnings
import pandas as pd

warnings.filterwarnings("ignore")
logging.getLogger("lightning.pytorch").setLevel(logging.ERROR)
logging.getLogger("pytorch_lightning").setLevel(logging.ERROR)

from models.tft_forecaster import TFTForecaster, TFTConfig  # noqa: E402

df = pd.read_csv("outputs/timeseries_with_embeddings.csv")
print(f"loaded {len(df)} rows, {df['subreddit'].nunique()} subreddits")

cfg = TFTConfig(max_epochs=2, lookback_window=14, forecast_horizon=5, hidden_size=16)
f = TFTForecaster(cfg)

print("training TFT (2 epochs, CPU)...")
f.train(df)
print("training done")

target = "r/AutoNewspaper"
res = f.predict_quantiles(df, subreddit=target)
if not res:
    print("no forecast produced")
else:
    print(f"\n=== 5-day toxicity forecast for {res['subreddit']} ===")
    print(" day   p10     p50     p90")
    for i in range(len(res["p50"])):
        print(f"  {i+1}   {res['p10'][i]:.3f}   {res['p50'][i]:.3f}   {res['p90'][i]:.3f}")
