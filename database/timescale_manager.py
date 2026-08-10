"""
APOLLO-M TimescaleDB Manager
Handles time-series data storage for efficient temporal queries.
Runs alongside PostgreSQL (port 5433) for time-series specific data.
"""

import logging
import psycopg2
from psycopg2.extras import execute_values
import pandas as pd
from datetime import datetime

log = logging.getLogger("APOLLO-M.TimescaleDB")


class TimescaleManager:
    """
    Manages time-series data in TimescaleDB.
    Stores: toxicity trends, community health over time, forecast history.
    """

    def __init__(self, host="localhost", port="5433", dbname="apollo_tsdb",
                 user="apollo", password="apollo_pass"):
        self.conn_params = {
            "host":     host,
            "port":     port,
            "dbname":   dbname,
            "user":     user,
            "password": password
        }
        self.conn = None
        self.connect()

    def connect(self):
        try:
            self.conn = psycopg2.connect(**self.conn_params)
            self.conn.autocommit = True
            log.info("TimescaleDB connected successfully.")
        except Exception as e:
            log.warning(f"TimescaleDB connection failed: {e}")
            self.conn = None

    def is_connected(self) -> bool:
        return self.conn is not None and not self.conn.closed

    # ── Toxicity time-series ──────────────────────────────────
    def insert_toxicity_timeseries(self, community_toxicity_df: pd.DataFrame):
        """
        Insert daily toxicity aggregates per subreddit.
        Input: community_toxicity DataFrame with columns:
               subreddit, date, avg_toxicity, toxic_count, total_comments
        """
        if not self.is_connected() or community_toxicity_df.empty:
            return

        query = """
            INSERT INTO toxicity_timeseries
                (time, subreddit, avg_toxicity, toxic_count,
                 total_count, toxic_rate)
            VALUES %s
            ON CONFLICT DO NOTHING
        """
        records = []
        for _, row in community_toxicity_df.iterrows():
            records.append((
                pd.to_datetime(row.get("date", datetime.now())),
                str(row.get("subreddit", "")),
                float(row.get("avg_toxicity", 0)),
                int(row.get("toxic_count", 0)),
                int(row.get("total_comments", 0)),
                float(row.get("toxic_rate", 0)),
            ))

        try:
            with self.conn.cursor() as cur:
                execute_values(cur, query, records)
            log.info(f"Inserted {len(records)} toxicity time-series records.")
        except Exception as e:
            log.error(f"insert_toxicity_timeseries failed: {e}")

    # ── Community health time-series ──────────────────────────
    def insert_health_timeseries(self, chm_results: list):
        """
        Insert community health scores over time.
        Input: list of CHM result dicts from meso layer.
        """
        if not self.is_connected() or not chm_results:
            return

        query = """
            INSERT INTO community_health_timeseries
                (time, subreddit, community_health_index,
                 toxicity_rate, polarization, churn_rate, misinfo_rate)
            VALUES %s
        """
        records = [
            (
                datetime.now(),
                str(r.get("subreddit", "")),
                float(r.get("community_health_index", 0)),
                float(r.get("toxicity_rate", 0)),
                float(r.get("polarization", 0)),
                float(r.get("churn_rate", 0)),
                float(r.get("misinfo_rate", 0)) if r.get("misinfo_rate") else 0.0,
            )
            for r in chm_results
        ]

        try:
            with self.conn.cursor() as cur:
                execute_values(cur, query, records)
            log.info(f"Inserted {len(records)} health time-series records.")
        except Exception as e:
            log.error(f"insert_health_timeseries failed: {e}")

    # ── Forecast time-series ──────────────────────────────────
    def insert_forecast_timeseries(self, forecast_df: pd.DataFrame):
        """
        Insert forecast results as time-series data.
        Input: forecast_results DataFrame from macro layer.
        """
        if not self.is_connected() or forecast_df.empty:
            return

        query = """
            INSERT INTO forecast_timeseries
                (time, subreddit, predicted_toxicity, risk_level, method)
            VALUES %s
            ON CONFLICT DO NOTHING
        """
        records = [
            (
                pd.to_datetime(row.get("date", datetime.now())),
                str(row.get("subreddit", "")),
                float(row.get("predicted_toxicity", 0)),
                str(row.get("risk_level", "UNKNOWN")),
                str(row.get("method", "LSTM")),
            )
            for _, row in forecast_df.iterrows()
        ]

        try:
            with self.conn.cursor() as cur:
                execute_values(cur, query, records)
            log.info(f"Inserted {len(records)} forecast time-series records.")
        except Exception as e:
            log.error(f"insert_forecast_timeseries failed: {e}")

    # ── Temporal queries ──────────────────────────────────────
    def get_toxicity_trend(self, subreddit: str,
                           days: int = 30) -> pd.DataFrame:
        """Get toxicity trend for a subreddit over the last N days."""
        if not self.is_connected():
            return pd.DataFrame()
        query = """
            SELECT time, avg_toxicity, toxic_rate
            FROM toxicity_timeseries
            WHERE subreddit = %s
              AND time > NOW() - INTERVAL '%s days'
            ORDER BY time ASC
        """
        try:
            return pd.read_sql(query, self.conn,
                               params=(subreddit, days))
        except Exception as e:
            log.error(f"get_toxicity_trend failed: {e}")
            return pd.DataFrame()

    def get_health_trend(self, subreddit: str,
                         days: int = 30) -> pd.DataFrame:
        """Get CHI trend for a subreddit over the last N days."""
        if not self.is_connected():
            return pd.DataFrame()
        query = """
            SELECT time, community_health_index,
                   toxicity_rate, polarization
            FROM community_health_timeseries
            WHERE subreddit = %s
              AND time > NOW() - INTERVAL '%s days'
            ORDER BY time ASC
        """
        try:
            return pd.read_sql(query, self.conn,
                               params=(subreddit, days))
        except Exception as e:
            log.error(f"get_health_trend failed: {e}")
            return pd.DataFrame()

    def close(self):
        if self.conn:
            self.conn.close()
            log.info("TimescaleDB connection closed.")