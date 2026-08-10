"""
APOLLO-M FastAPI Backend
Exposes pipeline results via REST API for frontend/dashboard consumption.

Endpoints:
    GET  /health                    — API health check
    GET  /communities               — All community health scores
    GET  /communities/{subreddit}   — Single community details
    GET  /alerts                    — All alerts
    GET  /alerts/{level}            — Alerts filtered by level
    GET  /forecast/{subreddit}      — 7-day forecast for a subreddit
    GET  /clusters                  — Community clusters
    GET  /summary                   — Dashboard summary stats
    POST /analyze                   — Trigger analysis on a subreddit
"""

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import psycopg2
from datetime import datetime
import os
import json
from pathlib import Path

from fastapi.security import OAuth2PasswordRequestForm
from api.auth import (authenticate_user, create_access_token,
                      get_current_user, require_role, Token, User,
                      ACCESS_TOKEN_EXPIRE_MINUTES)
from datetime import timedelta

# ── App setup ─────────────────────────────────────────────────
app = FastAPI(
    title="APOLLO-M API",
    description="AI Framework for Community Instability Forecasting",
    version="1.0.0"
)

# Which browser origins may call this API. Previously hardcoded to ["*"], which
# meant the CORS_ORIGINS setting the deployment passes in did nothing at all.
# Default stays "*" so local development and the demo keep working; set
# CORS_ORIGINS to a comma-separated list to restrict a deployed instance, e.g.
#   CORS_ORIGINS=https://apollo-m.streamlit.app,https://cerebro-sandy-beta.vercel.app
#
# allow_credentials stays off: this API authenticates with a Bearer token, not a
# cookie, so browsers have no ambient credential to leak. Enabling it alongside
# "*" is rejected by the CORS spec anyway.
_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Database connection ────────────────────────────────────────
def get_db():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME", "apollo_db"),
        user=os.getenv("DB_USER", "apollo"),
        password=os.getenv("DB_PASS", "apollo_pass"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432")
    )

def query_db(sql: str, params=None) -> list:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


# ── Root (friendly landing for the API) ───────────────────────
@app.get("/")
def root():
    return {
        "service": "APOLLO-M API",
        "status": "ok",
        "interactive_docs": "/docs",
        "endpoints": ["/health", "/summary", "/communities", "/communities/{subreddit}",
                      "/alerts", "/alerts/{level}", "/forecast/{subreddit}",
                      "/clusters", "/recommendations"],
        "frontend_dashboard": "http://localhost:8501",
    }


# ── Health check ───────────────────────────────────────────────
@app.get("/health")
def health():
    try:
        conn = get_db()
        conn.close()
        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now().isoformat(),
            "version": "1.0.0"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": str(e),
            "timestamp": datetime.now().isoformat()
        }
# ── Authentication endpoints ───────────────────────────────────

@app.post("/auth/token", response_model=Token)

async def login(form_data: OAuth2PasswordRequestForm = Depends()):

    """Login and get JWT token."""

    user = authenticate_user(form_data.username, form_data.password)

    if not user:

        raise HTTPException(

            status_code=401,

            detail="Incorrect username or password",

            headers={"WWW-Authenticate": "Bearer"},

        )

    token = create_access_token(

        data={"sub": user["username"], "role": user["role"]},

        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    )

    return Token(

        access_token=token,

        token_type="bearer",

        role=user["role"],

        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60

    )

@app.get("/auth/me", response_model=User)

async def get_me(current_user: User = Depends(get_current_user)):

    """Get current logged-in user info."""

    return current_user


# ── Communities ────────────────────────────────────────────────
@app.get("/communities")
def get_communities():
    """Get latest CHI scores for all communities."""
    rows = query_db("""
        SELECT DISTINCT ON (subreddit)
            subreddit, community_health_index, toxicity_rate,
            polarization, echo_chamber_index, churn_rate,
            total_comments, timestamp
        FROM community_health
        ORDER BY subreddit, timestamp DESC
    """)
    return {"communities": rows, "count": len(rows)}


@app.get("/communities/{subreddit}")
def get_community(subreddit: str):
    """Get details for a specific subreddit."""
    # Handle r/ prefix
    if not subreddit.startswith("r/"):
        subreddit = f"r/{subreddit}"

    rows = query_db("""
        SELECT * FROM community_health
        WHERE subreddit = %s
        ORDER BY timestamp DESC
        LIMIT 1
    """, (subreddit,))

    if not rows:
        raise HTTPException(status_code=404,
                            detail=f"Community {subreddit} not found")
    return rows[0]


# ── Alerts ─────────────────────────────────────────────────────
@app.get("/alerts")
def get_alerts():
    """Get all alerts ordered by severity."""
    level_order = "CASE alert_level WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MEDIUM' THEN 3 ELSE 4 END"
    rows = query_db(f"""
        SELECT DISTINCT ON (subreddit)
            subreddit, alert_level, chi, message, timestamp
        FROM alerts
        ORDER BY subreddit, timestamp DESC
    """)
    # Sort by severity
    level_map = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    rows.sort(key=lambda x: level_map.get(x["alert_level"], 4))
    return {"alerts": rows, "count": len(rows)}


@app.get("/alerts/{level}")
def get_alerts_by_level(level: str):
    """Get alerts filtered by level (CRITICAL/HIGH/MEDIUM/LOW)."""
    level = level.upper()
    if level not in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        raise HTTPException(status_code=400,
                            detail="Level must be CRITICAL, HIGH, MEDIUM, or LOW")
    rows = query_db("""
        SELECT DISTINCT ON (subreddit)
            subreddit, alert_level, chi, message, timestamp
        FROM alerts
        WHERE alert_level = %s
        ORDER BY subreddit, timestamp DESC
    """, (level,))
    return {"alerts": rows, "count": len(rows), "level": level}


# ── Forecasts ──────────────────────────────────────────────────
@app.get("/forecast/{subreddit}")
def get_forecast(subreddit: str):
    """Get 7-day toxicity forecast for a subreddit."""
    if not subreddit.startswith("r/"):
        subreddit = f"r/{subreddit}"

    rows = query_db("""
        SELECT subreddit, forecast_date, predicted_toxicity,
               risk_level, method, created_at
        FROM forecasts
        WHERE subreddit = %s
        ORDER BY forecast_date ASC
    """, (subreddit,))

    if not rows:
        # Return forecast from CSV as fallback
        forecast_path = Path("outputs/forecast_results.csv")
        if forecast_path.exists():
            df = pd.read_csv(forecast_path)
            rows = df.to_dict(orient="records")

    return {
        "subreddit": subreddit,
        "forecast": rows,
        "days": len(rows)
    }


# ── Clusters ───────────────────────────────────────────────────
@app.get("/clusters")
def get_clusters():
    """Get community cluster assignments."""
    report_path = Path("outputs/community_health_report.csv")
    if not report_path.exists():
        raise HTTPException(status_code=404,
                            detail="Cluster data not available — run pipeline first")

    df = pd.read_csv(report_path)
    # The pipeline writes `cluster` (the KMeans id); `cluster_label` only exists
    # in the DB schema and was never produced, so this endpoint raised KeyError
    # on every call. Prefer the label when present, fall back to the id.
    col = "cluster_label" if "cluster_label" in df.columns else "cluster"
    if col not in df.columns:
        raise HTTPException(status_code=422,
                            detail="clusters_report.csv has no cluster column")
    clusters = {}
    for label in df[col].dropna().unique():
        subset = df[df[col] == label]
        label = str(label)
        clusters[label] = {
            "communities": subset["subreddit"].tolist(),
            "count": len(subset),
            "avg_chi": round(subset["community_health_index"].mean(), 2),
            "avg_toxicity": round(subset["toxicity_rate"].mean(), 4)
        }
    return {"clusters": clusters, "total_communities": len(df)}

# ── Moderation Recommendations ─────────────────────────────────
@app.get("/recommendations")
def get_recommendations():
    """Get moderation recommendations for all communities."""
    rec_path = Path("outputs/moderation_recommendations.csv")
    if not rec_path.exists():
        raise HTTPException(status_code=404,
                            detail="Recommendations not available — run pipeline first")
    df = pd.read_csv(rec_path)
    return {
        "recommendations": df.to_dict(orient="records"),
        "count": len(df)
    }

@app.get("/recommendations/{subreddit}")
def get_recommendation(subreddit: str):
    """Get moderation recommendation for a specific subreddit."""
    if not subreddit.startswith("r/"):
        subreddit = f"r/{subreddit}"
    rec_path = Path("outputs/moderation_recommendations.csv")
    if not rec_path.exists():
        raise HTTPException(status_code=404,
                            detail="Recommendations not available — run pipeline first")
    df = pd.read_csv(rec_path)
    row = df[df["subreddit"] == subreddit]
    if row.empty:
        raise HTTPException(status_code=404,
                            detail=f"{subreddit} not found")
    return row.iloc[0].to_dict()


# ── Summary ────────────────────────────────────────────────────
@app.get("/summary")
def get_summary():
    """Dashboard summary — key stats at a glance."""
    try:
        alerts = query_db("SELECT alert_level, COUNT(*) as count FROM alerts GROUP BY alert_level")
        alert_counts = {row["alert_level"]: row["count"] for row in alerts}

        health = query_db("""
            SELECT AVG(community_health_index) as avg_chi,
                   AVG(toxicity_rate) as avg_toxicity,
                   COUNT(DISTINCT subreddit) as total_communities
            FROM community_health
        """)

        toxicity = query_db("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN is_toxic THEN 1 ELSE 0 END) as toxic_count
            FROM toxicity_scores
        """)

        misinfo = query_db("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN is_misinfo THEN 1 ELSE 0 END) as misinfo_count
            FROM misinformation_scores
        """)

        return {
            "summary": {
                "total_communities": health[0]["total_communities"] if health else 0,
                "avg_chi": round(float(health[0]["avg_chi"] or 0), 2) if health else 0,
                "avg_toxicity": round(float(health[0]["avg_toxicity"] or 0), 4) if health else 0,
                "alert_distribution": alert_counts,
                "total_comments_analyzed": toxicity[0]["total"] if toxicity else 0,
                "toxic_comment_count": toxicity[0]["toxic_count"] if toxicity else 0,
                "misinfo_comment_count": misinfo[0]["misinfo_count"] if misinfo else 0,
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Analyze ────────────────────────────────────────────────────
@app.post("/analyze")
def analyze(payload: dict):
    """
    Trigger analysis on submitted text.
    Body: {"text": "comment text here"}
    Returns toxicity and misinfo scores.
    """
    text = payload.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text field required")

    try:
        from modules.cerebro_detector import CEREBRODetector
        cerebro = CEREBRODetector()
        misinfo_result = cerebro.analyze(text)
    except Exception:
        misinfo_result = {"misinformation_score": 0, "misinfo_category": "UNKNOWN"}

    # Simple toxicity keyword check for instant response
    toxic_words = ["hate", "kill", "stupid", "idiot", "garbage", "attack"]
    text_lower = text.lower()
    keyword_toxic = any(w in text_lower for w in toxic_words)

    return {
        "text": text[:100],
        "misinformation_score": misinfo_result.get("misinformation_score", 0),
        "misinfo_category": misinfo_result.get("misinfo_category", "UNKNOWN"),
        "coordinated_behaviour": misinfo_result.get("coordinated_behaviour", False),
        "keyword_toxicity_flag": keyword_toxic,
        "timestamp": datetime.now().isoformat()
    }