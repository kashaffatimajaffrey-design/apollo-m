"""Regenerate outputs/forecast_results.csv with the FIXED TFT quantile bands."""
import logging, warnings
from pathlib import Path
import pandas as pd
warnings.filterwarnings("ignore")
logging.getLogger("lightning.pytorch").setLevel(logging.ERROR)
from models.tft_forecaster import TFTForecaster, TFTConfig

df = pd.read_csv("outputs/timeseries_with_embeddings.csv")
f = TFTForecaster(TFTConfig(max_epochs=3, hidden_size=16))
f.train(df)
res = f.predict_quantiles(df, subreddit="r/AutoNewspaper")
out = f.save_forecast_csv(res, res["subreddit"], pd.Timestamp("2025-02-07"),
                          Path("outputs/forecast_results.csv"))
print(out[["day", "p10", "p50", "p90", "risk_level"]].to_string(index=False))
