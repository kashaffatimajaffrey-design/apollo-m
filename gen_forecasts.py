"""Generate a 5-day TFT forecast for EVERY reliable community (not just one), so
the Forecast page, the Actions page, and the LLM briefings all have a real trend
signal. Writes outputs/forecast_results.csv with one block of rows per community.
"""
import logging
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
logging.getLogger("lightning.pytorch").setLevel(logging.ERROR)
from models.tft_forecaster import TFTForecaster, TFTConfig  # noqa: E402

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
HORIZON, LOOKBACK = 5, 14

# Reliable communities (from the meso layer) — bare names to match apollo_daily.
meso = pd.read_csv(OUT / "meso_report.csv")
targets = {s[2:] if s.startswith("r/") else s for s in meso["subreddit"].astype(str)}

daily = pd.read_csv(ROOT / "data" / "apollo_daily.csv")
daily["subreddit"] = daily["subreddit"].astype(str).str.replace(r"^r/", "", regex=True)
d = daily[daily["subreddit"].isin(targets)].copy()
counts = d.groupby("subreddit").size()
keep = counts[counts >= LOOKBACK + HORIZON].index.tolist()
d = d[d["subreddit"].isin(keep)]
print(f"training TFT on {len(keep)} communities with >= {LOOKBACK + HORIZON} daily points…")

f = TFTForecaster(TFTConfig(max_epochs=6, lookback_window=LOOKBACK, forecast_horizon=HORIZON))
f.train(d)

start = datetime(2026, 8, 11)
rows = []
for sub in keep:
    sub_df = d[d["subreddit"] == sub]          # forecast each community from ITS OWN series
    res = f.predict_quantiles(sub_df, subreddit=f"r/{sub}")
    if not res:
        continue
    name = res["subreddit"]
    for i in range(len(res["p50"])):
        p50 = float(res["p50"][i])
        rows.append({
            "day": i + 1,
            "date": (start + timedelta(days=i + 1)).strftime("%Y-%m-%d"),
            "predicted_toxicity": round(p50, 4),
            "p10": round(float(res["p10"][i]), 4),
            "p50": round(p50, 4),
            "p90": round(float(res["p90"][i]), 4),
            "risk_level": ("CRITICAL" if p50 > 0.8 else "HIGH" if p50 > 0.6
                           else "MEDIUM" if p50 > 0.4 else "LOW"),
            "method": "TFT",
            "subreddit": name,
        })

df = pd.DataFrame(rows)
df.to_csv(OUT / "forecast_results.csv", index=False)
n = df["subreddit"].nunique() if not df.empty else 0
print(f"wrote forecasts for {n} communities -> outputs/forecast_results.csv")
if n:
    print(df.groupby("subreddit")["p50"].mean().round(3).sort_values(ascending=False).head(6).to_string())
