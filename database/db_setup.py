"""Stand up Apollo's database inside the SAME Postgres that runs CEREBRO.

This is the CEREBRO <-> Apollo connection at the infrastructure level: one
Postgres instance, `cerebro` database for the threat-intel app, `apollo_db` for
Apollo — created here, schema applied, and loaded with the real pipeline outputs
so the FastAPI backend serves genuine data (not CSV reads).

Run once locally (Postgres container must be up):
  python database/db_setup.py

Against a managed cloud database (Render, Neon, Supabase), pass its connection
string instead — the role/database creation steps are skipped, because a managed
instance provisions those for you and the supplied user usually lacks CREATE
ROLE/DATABASE rights:

  DATABASE_URL="postgresql://user:pass@host:5432/apollo_db" python database/db_setup.py

Use the EXTERNAL connection string when running this from your machine; Render's
internal URL only resolves inside its network. Never commit that string.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"

# When DATABASE_URL is set we are targeting a managed instance: connect straight
# to it and skip provisioning. Otherwise fall back to the local shared-Postgres
# layout, where CEREBRO's superuser creates Apollo's role and database.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
MANAGED = bool(DATABASE_URL)
ADMIN = dict(host="127.0.0.1", port=5433, user="cerebro", password="cerebro_dev_pw")


# Apollo's tables live in their own schema when sharing an instance with CEREBRO,
# so `alerts` here can never be confused with anything CEREBRO owns.
DB_SCHEMA = os.getenv("DB_SCHEMA", "apollo" if MANAGED else "public")


def connect_apollo():
    """One place that decides where Apollo's tables live."""
    opts = f"-c search_path={DB_SCHEMA},public"
    if MANAGED:
        # See api/main.py: 'prefer' negotiates TLS where the server offers it and
        # falls back on Render's plaintext internal network, instead of aborting.
        con = psycopg2.connect(DATABASE_URL, options=opts,
                               sslmode=os.getenv("PGSSLMODE", "prefer"))
    else:
        con = psycopg2.connect(dbname="apollo_db", options=opts, **ADMIN)
    con.autocommit = True
    return con


def band(chi: float) -> str:
    return ("LOW" if chi >= 85 else "MEDIUM" if chi >= 75
            else "HIGH" if chi >= 65 else "CRITICAL")


def ensure_db_and_role() -> None:
    con = psycopg2.connect(dbname="cerebro", **ADMIN); con.autocommit = True
    cur = con.cursor()
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname='apollo'")
    if not cur.fetchone():
        cur.execute("CREATE ROLE apollo LOGIN PASSWORD 'apollo_pass'")
    cur.execute("SELECT 1 FROM pg_database WHERE datname='apollo_db'")
    if not cur.fetchone():
        cur.execute("CREATE DATABASE apollo_db OWNER apollo")
    cur.close(); con.close()
    print("apollo_db + apollo role ready")


def apply_schema() -> None:
    sql = (ROOT / "database" / "schema.sql").read_text()
    con = connect_apollo()
    cur = con.cursor()
    if DB_SCHEMA != "public":
        # Created here rather than in schema.sql so the file stays portable, and
        # so search_path is already correct for the unqualified CREATE TABLEs.
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA}")
        cur.execute(f"SET search_path TO {DB_SCHEMA}, public")
        print(f"using schema: {DB_SCHEMA}")
    cur.execute(sql)
    cur.close(); con.close()
    print("schema applied to apollo_db")


def load_data() -> None:
    meso = pd.read_csv(OUT / "meso_report.csv")
    try:
        cl = pd.read_csv(OUT / "clusters_report.csv")[["subreddit", "cluster", "is_outlier"]]
        meso = meso.merge(cl, on="subreddit", how="left")
    except Exception:
        meso["cluster"] = None; meso["is_outlier"] = False
    meso["cluster"] = meso["cluster"].where(pd.notna(meso["cluster"]), None)

    con = connect_apollo()
    cur = con.cursor()
    for t in ("community_health", "alerts", "forecasts"):
        cur.execute(f"TRUNCATE {t} RESTART IDENTITY")

    ch_rows = [(r.subreddit, float(r.community_health_index), float(r.toxicity_rate),
                float(r.polarization), float(r.echo_chamber_index), float(r.churn_rate),
                int(r.total_comments),
                (int(r.cluster) if r.cluster is not None and pd.notna(r.cluster) else None),
                bool(getattr(r, "is_outlier", False)) if pd.notna(getattr(r, "is_outlier", False)) else False)
               for r in meso.itertuples()]
    execute_values(cur,
        "INSERT INTO community_health (subreddit, community_health_index, toxicity_rate, "
        "polarization, echo_chamber_index, churn_rate, total_comments, cluster, is_outlier) VALUES %s",
        ch_rows)

    al_rows = [(r.subreddit, band(r.community_health_index), float(r.community_health_index),
                f"[{band(r.community_health_index)}] {r.subreddit} CHI={r.community_health_index:.1f} "
                f"toxicity={r.toxicity_rate:.0%}",
                float(r.toxicity_rate), float(r.polarization), float(r.churn_rate))
               for r in meso.itertuples()]
    execute_values(cur,
        "INSERT INTO alerts (subreddit, alert_level, chi, message, toxicity, polarization, churn) "
        "VALUES %s", al_rows)

    try:
        fc = pd.read_csv(OUT / "forecast_results.csv")
        fc_rows = [(r.subreddit, str(r.date), float(r.p50), str(r.risk_level), "TFT")
                   for r in fc.itertuples()]
        execute_values(cur,
            "INSERT INTO forecasts (subreddit, forecast_date, predicted_toxicity, risk_level, method) "
            "VALUES %s", fc_rows)
    except Exception as exc:
        print("forecast load skipped:", exc)

    if not MANAGED:
        # Only meaningful in the local shared-Postgres layout, where CEREBRO's
        # superuser owns the objects and hands them to the apollo role. A managed
        # instance connects as its own owner, and that role does not exist there.
        cur.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO apollo")
        cur.execute("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO apollo")
    cur.execute("SELECT (SELECT count(*) FROM community_health), (SELECT count(*) FROM alerts), "
                "(SELECT count(*) FROM forecasts)")
    ch, al, fcn = cur.fetchone()
    cur.close(); con.close()
    print(f"loaded: community_health={ch}  alerts={al}  forecasts={fcn}")


if __name__ == "__main__":
    if MANAGED:
        # Show where we are writing, with the password stripped — running this
        # against the wrong database truncates three tables.
        safe = DATABASE_URL
        if "@" in safe:
            safe = safe.split("://", 1)[0] + "://***@" + safe.split("@", 1)[1]
        print(f"managed target: {safe}")
    else:
        ensure_db_and_role()
    apply_schema()
    load_data()
    print("apollo_db ready."
          if MANAGED else
          "apollo_db ready — one Postgres instance now serves both CEREBRO and Apollo.")
