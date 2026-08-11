import pandas as pd
import numpy as np

df = pd.read_csv("outputs/community_health_report.csv")

def new_chi(toxicity_rate, polarization, churn_rate, echo_chamber):
    penalty = (
        toxicity_rate * 70 +
        polarization  * 30 +
        churn_rate    * 5  +
        echo_chamber  * 5
    )
    return round(max(0.0, min(100.0, 100 - penalty)), 2)
df["new_chi"] = df.apply(
    lambda r: new_chi(r["toxicity_rate"], r["polarization"],
                      r["churn_rate"], r["echo_chamber_index"]), axis=1
)

def alert_level(chi):
    if chi < 65: return "CRITICAL"
    elif chi < 75: return "HIGH"
    elif chi < 85: return "MEDIUM"
    else: return "LOW"

df["new_alert"] = df["new_chi"].apply(alert_level)

print(df[["subreddit", "toxicity_rate", "churn_rate",
          "new_chi", "new_alert"]].to_string(index=False))
print("\nAlert distribution:")
print(df["new_alert"].value_counts())