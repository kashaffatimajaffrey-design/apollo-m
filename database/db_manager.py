"""
APOLLO-M Database Manager
Handles all PostgreSQL operations for the APOLLO-M pipeline.
Replaces CSV storage with persistent database.
"""

import logging
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime
from pathlib import Path

log = logging.getLogger("APOLLO-M.DB")


class DBManager:
    """
    Manages all database operations for APOLLO-M.
    Handles: communities, community_health, toxicity_scores,
             misinformation_scores, forecasts, alerts
    """

    def __init__(self, host="localhost", port="5432", dbname="apollo_db",
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
        """Establish database connection."""
        try:
            self.conn = psycopg2.connect(**self.conn_params)
            self.conn.autocommit = True
            log.info("PostgreSQL connected successfully.")
        except Exception as e:
            log.error(f"Database connection failed: {e}")
            self.conn = None

    def is_connected(self) -> bool:
        return self.conn is not None and not self.conn.closed

    def execute(self, query: str, params=None):
        """Execute a single query."""
        if not self.is_connected():
            log.error("No database connection.")
            return None
        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params)
                return cur
        except Exception as e:
            log.error(f"Query failed: {e}\nQuery: {query}")
            return None

    # ── Communities ───────────────────────────────────────────
    def upsert_communities(self, df: pd.DataFrame):
        """Insert or update community metadata."""
        if not self.is_connected():
            return
        query = """
            INSERT INTO communities (subreddit, subscribers, posts_per_day)
            VALUES %s
            ON CONFLICT (subreddit) DO UPDATE SET
                subscribers   = EXCLUDED.subscribers,
                posts_per_day = EXCLUDED.posts_per_day,
                updated_at    = NOW()
        """
        records = [
            (
                str(row.get("subreddit", "")),
                int(row.get("subscribers", 0)),
                float(row.get("posts_per_day", 0)),
            )
            for _, row in df.iterrows()
        ]
        try:
            with self.conn.cursor() as cur:
                execute_values(cur, query, records)
            log.info(f"Upserted {len(records)} communities.")
        except Exception as e:
            log.error(f"upsert_communities failed: {e}")

    # ── Community Health ──────────────────────────────────────
    def insert_community_health(self, chm_results: list):
        """Insert CHI scores from meso layer."""
        if not self.is_connected() or not chm_results:
            return
        query = """
            INSERT INTO community_health
                (subreddit, community_health_index, toxicity_rate,
                 polarization, echo_chamber_index, churn_rate,
                 total_comments, timestamp)
            VALUES %s
        """
        records = [
            (
                r.get("subreddit", ""),
                float(r.get("community_health_index", 0)),
                float(r.get("toxicity_rate", 0)),
                float(r.get("polarization", 0)),
                float(r.get("echo_chamber_index", 0)),
                float(r.get("churn_rate", 0)),
                int(r.get("total_comments", 0)),
                r.get("timestamp", datetime.now().isoformat()),
            )
            for r in chm_results
        ]
        try:
            with self.conn.cursor() as cur:
                execute_values(cur, query, records)
            log.info(f"Inserted {len(records)} community health records.")
        except Exception as e:
            log.error(f"insert_community_health failed: {e}")

    # ── Toxicity Scores ───────────────────────────────────────
    def insert_toxicity_scores(self, df: pd.DataFrame, batch_size=1000):
        """Insert comment-level toxicity scores in batches."""
        if not self.is_connected() or df.empty:
            return
        query = """
            INSERT INTO toxicity_scores
                (subreddit, comment_id, toxicity_score, is_toxic, created_utc)
            VALUES %s
            ON CONFLICT DO NOTHING
        """
        records = [
            (
                str(row.get("subreddit", "")),
                str(row.get("id", "")),
                float(row.get("toxicity_score", 0)),
                bool(row.get("is_toxic", False)),
                pd.to_datetime(row.get("created_utc"), errors="coerce"),
            )
            for _, row in df.iterrows()
        ]
        try:
            with self.conn.cursor() as cur:
                for i in range(0, len(records), batch_size):
                    execute_values(cur, query, records[i:i + batch_size])
            log.info(f"Inserted {len(records)} toxicity scores.")
        except Exception as e:
            log.error(f"insert_toxicity_scores failed: {e}")

    # ── Misinformation Scores ─────────────────────────────────
    def insert_misinfo_scores(self, df: pd.DataFrame):
        """Insert CEREBRO misinformation scores."""
        if not self.is_connected() or df.empty:
            return
        if "misinformation_score" not in df.columns:
            log.warning("No misinformation_score column found — skipping.")
            return
        query = """
            INSERT INTO misinformation_scores
                (subreddit, comment_id, misinformation_score,
                 is_misinfo, misinfo_category, coordinated_behaviour)
            VALUES %s
            ON CONFLICT DO NOTHING
        """
        records = [
            (
                str(row.get("subreddit", "")),
                str(row.get("id", "")),
                float(row.get("misinformation_score", 0)),
                bool(row.get("is_misinfo", False)),
                str(row.get("misinfo_category", "UNKNOWN")),
                bool(row.get("coordinated_behaviour", False)),
            )
            for _, row in df.iterrows()
        ]
        try:
            with self.conn.cursor() as cur:
                execute_values(cur, query, records)
            log.info(f"Inserted {len(records)} misinformation scores.")
        except Exception as e:
            log.error(f"insert_misinfo_scores failed: {e}")

    # ── Forecasts ─────────────────────────────────────────────
    def insert_forecasts(self, forecast_df: pd.DataFrame):
        """Insert LSTM/TFT forecast results."""
        if not self.is_connected() or forecast_df.empty:
            return
        query = """
            INSERT INTO forecasts
                (subreddit, forecast_date, predicted_toxicity,
                 risk_level, method)
            VALUES %s
            ON CONFLICT DO NOTHING
        """
        records = [
            (
                str(row.get("subreddit", "")),
                str(row.get("date", "")),
                float(row.get("predicted_toxicity", 0)),
                str(row.get("risk_level", "UNKNOWN")),
                str(row.get("method", "LSTM")),
            )
            for _, row in forecast_df.iterrows()
        ]
        try:
            with self.conn.cursor() as cur:
                execute_values(cur, query, records)
            log.info(f"Inserted {len(records)} forecast records.")
        except Exception as e:
            log.error(f"insert_forecasts failed: {e}")

    # ── Alerts ────────────────────────────────────────────────
    def insert_alerts(self, alerts: list):
        """Insert alert system outputs."""
        if not self.is_connected() or not alerts:
            return
        query = """
            INSERT INTO alerts
                (subreddit, alert_level, chi, message,
                 toxicity, polarization, churn, timestamp)
            VALUES %s
        """
        records = [
            (
                str(a.get("subreddit", "")),
                str(a.get("alert_level", "LOW")),
                float(a.get("chi", 0)),
                str(a.get("message", "")),
                float(a.get("toxicity", 0)) if a.get("toxicity") else None,
                float(a.get("polarization", 0)) if a.get("polarization") else None,
                float(a.get("churn", 0)) if a.get("churn") else None,
                a.get("timestamp", datetime.now().isoformat()),
            )
            for a in alerts
        ]
        try:
            with self.conn.cursor() as cur:
                execute_values(cur, query, records)
            log.info(f"Inserted {len(records)} alerts.")
        except Exception as e:
            log.error(f"insert_alerts failed: {e}")

    # ── Query helpers ─────────────────────────────────────────
    def get_communities(self) -> pd.DataFrame:
        """Fetch all communities."""
        return pd.read_sql(
            "SELECT * FROM community_health ORDER BY timestamp DESC",
            self.conn
        )

    def get_alerts(self, level: str = None) -> pd.DataFrame:
        """Fetch alerts, optionally filtered by level."""
        if level:
            return pd.read_sql(
                "SELECT * FROM alerts WHERE alert_level = %s ORDER BY timestamp DESC",
                self.conn, params=(level,)
            )
        return pd.read_sql(
            "SELECT * FROM alerts ORDER BY timestamp DESC",
            self.conn
        )

    def get_forecast(self, subreddit: str) -> pd.DataFrame:
        """Fetch forecast for a specific subreddit."""
        return pd.read_sql(
            "SELECT * FROM forecasts WHERE subreddit = %s ORDER BY forecast_date",
            self.conn, params=(subreddit,)
        )

    def close(self):
        if self.conn:
            self.conn.close()
            log.info("Database connection closed.")