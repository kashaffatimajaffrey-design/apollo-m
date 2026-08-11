"""Prometheus exporter for APOLLO-M.

Exposes live pipeline KPIs and model metrics as Prometheus gauges on :9100/metrics
by reading the pipeline's outputs (meso_report.csv + metrics.json). Prometheus
scrapes this; Grafana visualizes it. Runs standalone — no database required — so
the monitoring stack is demoable on its own.

  python monitoring/exporter.py           # serves http://localhost:9100/metrics
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd
from prometheus_client import Gauge, start_http_server

ROOT = Path(__file__).resolve().parents[1]

# Which dataset the monitoring stack reflects. Grafana reads Prometheus, which
# scrapes this exporter, so the dashboard's dataset switch cannot reach it — the
# exporter has to be told directly. It follows the same variable as db_setup.py,
# so the API, the database and the monitoring stack always describe the same
# corpus rather than disagreeing with one another.
#   APOLLO_DATASET=real       -> outputs/real/   (default when present)
#   APOLLO_DATASET=benchmark  -> outputs/
_DS = os.getenv("APOLLO_DATASET", "real").lower()
_REAL = ROOT / "outputs" / "real"
OUT = _REAL if _DS == "real" and (_REAL / "meso_report.csv").exists() else ROOT / "outputs"
print(f"exporter dataset: {'real Reddit' if OUT.name == 'real' else 'benchmark'} ({OUT})")
PORT = 9100
REFRESH_SECONDS = 15

G = {
    "communities": Gauge("apollo_communities_total", "Communities analysed"),
    "critical": Gauge("apollo_critical_alerts", "Communities at CRITICAL alert"),
    "avg_tox": Gauge("apollo_avg_toxicity", "Mean toxicity rate across communities"),
    "avg_chi": Gauge("apollo_avg_chi", "Mean Community Health Index (0-100)"),
    "f1_macro": Gauge("apollo_toxicity_f1_macro", "Toxicity classifier macro F1"),
    "f1_micro": Gauge("apollo_toxicity_f1_micro", "Toxicity classifier micro F1"),
    "forecast_p50": Gauge("apollo_forecast_p50_day1", "Day-1 median toxicity forecast"),
    # Trend-aware signal. CHI describes present health and scored ROC-AUC 0.575
    # against planted ground truth; this ranks by direction of travel instead and
    # is the number that identifies a community worth acting on early.
    "rising": Gauge("apollo_rising_communities",
                    "Communities whose recent toxicity exceeds their baseline"),
    "max_instability": Gauge("apollo_max_instability",
                             "Highest instability score across communities"),
}


def _band(chi: float) -> str:
    return ("LOW" if chi >= 85 else "MEDIUM" if chi >= 75
            else "HIGH" if chi >= 65 else "CRITICAL")


def _f(x: str) -> float:
    try:
        return float(str(x).strip().rstrip("%"))
    except Exception:
        return 0.0


def refresh() -> None:
    try:
        meso = pd.read_csv(OUT / "meso_report.csv")
        G["communities"].set(len(meso))
        G["critical"].set(int(meso["community_health_index"].apply(_band).eq("CRITICAL").sum()))
        G["avg_tox"].set(float(meso["toxicity_rate"].mean()))
        G["avg_chi"].set(float(meso["community_health_index"].mean()))
        if "toxicity_trend" in meso.columns:
            G["rising"].set(int((meso["toxicity_trend"] > 0.02).sum()))
        if "instability_score" in meso.columns:
            G["max_instability"].set(float(meso["instability_score"].max()))
    except Exception:
        pass
    try:
        m = json.loads((ROOT / "outputs" / "metrics.json").read_text())
        tox = m.get("Toxicity (TF-IDF+LR, Jigsaw)", {})
        G["f1_macro"].set(_f(tox.get("F1 macro", 0)))
        G["f1_micro"].set(_f(tox.get("F1 micro", 0)))
    except Exception:
        pass
    try:
        fc = pd.read_csv(OUT / "forecast_results.csv")
        G["forecast_p50"].set(float(fc["p50"].iloc[0]))
    except Exception:
        pass


if __name__ == "__main__":
    start_http_server(PORT)
    print(f"APOLLO-M exporter on http://localhost:{PORT}/metrics")
    while True:
        refresh()
        time.sleep(REFRESH_SECONDS)
