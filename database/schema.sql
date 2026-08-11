-- APOLLO-M Database Schema
-- PostgreSQL + TimescaleDB ready structure

-- ── Communities table ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS communities (
    id              SERIAL PRIMARY KEY,
    subreddit       VARCHAR(100) UNIQUE NOT NULL,
    subscribers     INTEGER DEFAULT 0,
    posts_per_day   FLOAT DEFAULT 0,
    age_days        INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- ── Community Health Index scores ─────────────────────────
CREATE TABLE IF NOT EXISTS community_health (
    id                      SERIAL PRIMARY KEY,
    subreddit               VARCHAR(100) NOT NULL,
    community_health_index  FLOAT NOT NULL,
    toxicity_rate           FLOAT NOT NULL,
    polarization            FLOAT NOT NULL,
    echo_chamber_index      FLOAT NOT NULL,
    churn_rate              FLOAT NOT NULL,
    total_comments          INTEGER NOT NULL,
    cluster                 INTEGER,
    cluster_label           VARCHAR(50),
    is_outlier              BOOLEAN DEFAULT FALSE,
    instability_score       FLOAT,
    gnn_risk                FLOAT,
    recommended_action      VARCHAR(40),
    timestamp               TIMESTAMP DEFAULT NOW()
);

-- CREATE TABLE IF NOT EXISTS leaves an existing table untouched, so a database
-- created before these columns existed would silently keep the old shape and the
-- API would serve a pipeline output it cannot see. Added explicitly so the
-- schema file remains the single source of truth for both new and existing
-- deployments.
ALTER TABLE community_health ADD COLUMN IF NOT EXISTS instability_score  FLOAT;
ALTER TABLE community_health ADD COLUMN IF NOT EXISTS gnn_risk           FLOAT;
ALTER TABLE community_health ADD COLUMN IF NOT EXISTS recommended_action VARCHAR(40);

-- ── Toxicity scores per comment ────────────────────────────
CREATE TABLE IF NOT EXISTS toxicity_scores (
    id              SERIAL PRIMARY KEY,
    subreddit       VARCHAR(100) NOT NULL,
    comment_id      VARCHAR(100),
    body            TEXT,
    toxicity_score  FLOAT NOT NULL,
    is_toxic        BOOLEAN NOT NULL,
    created_utc     TIMESTAMP,
    inserted_at     TIMESTAMP DEFAULT NOW()
);

-- ── Misinformation scores ──────────────────────────────────
CREATE TABLE IF NOT EXISTS misinformation_scores (
    id                      SERIAL PRIMARY KEY,
    subreddit               VARCHAR(100) NOT NULL,
    comment_id              VARCHAR(100),
    misinformation_score    FLOAT NOT NULL,
    is_misinfo              BOOLEAN NOT NULL,
    misinfo_category        VARCHAR(50),
    coordinated_behaviour   BOOLEAN DEFAULT FALSE,
    inserted_at             TIMESTAMP DEFAULT NOW()
);

-- ── Forecasts ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS forecasts (
    id                      SERIAL PRIMARY KEY,
    subreddit               VARCHAR(100) NOT NULL,
    forecast_date           DATE NOT NULL,
    predicted_toxicity      FLOAT NOT NULL,
    risk_level              VARCHAR(20) NOT NULL,
    method                  VARCHAR(50),
    created_at              TIMESTAMP DEFAULT NOW()
);

-- ── Alerts ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alerts (
    id              SERIAL PRIMARY KEY,
    subreddit       VARCHAR(100) NOT NULL,
    alert_level     VARCHAR(20) NOT NULL,
    chi             FLOAT NOT NULL,
    message         TEXT,
    toxicity        FLOAT,
    polarization    FLOAT,
    churn           FLOAT,
    timestamp       TIMESTAMP DEFAULT NOW()
);

-- ── Indexes for fast queries ───────────────────────────────
CREATE INDEX IF NOT EXISTS idx_community_health_subreddit
    ON community_health(subreddit);
CREATE INDEX IF NOT EXISTS idx_community_health_timestamp
    ON community_health(timestamp);
CREATE INDEX IF NOT EXISTS idx_toxicity_subreddit
    ON toxicity_scores(subreddit);
CREATE INDEX IF NOT EXISTS idx_alerts_subreddit
    ON alerts(subreddit);
CREATE INDEX IF NOT EXISTS idx_alerts_level
    ON alerts(alert_level);
CREATE INDEX IF NOT EXISTS idx_forecasts_subreddit
    ON forecasts(subreddit);

-- ── Grant permissions ──────────────────────────────────────
-- Grants are applied by db_setup.py, not here, and only for the local layout
-- where CEREBRO's superuser creates the objects and hands them to the `apollo`
-- role. A managed provider issues its own owner role, so these hardcoded lines
-- aborted the whole schema with: role "apollo" does not exist. They also named
-- `public` explicitly, which is wrong once Apollo's tables live in their own
-- schema.