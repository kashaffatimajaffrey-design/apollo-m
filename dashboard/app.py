"""APOLLO-M — community-instability console (Streamlit).

Login → sidebar navigation → per-page views, with a community drill-down, a
switchable LLM explanation (Ollama/Claude), a live real-time feed, and links to
the CEREBRO app + Grafana/Prometheus. Cosmic/galaxy theme.

Run:  streamlit run dashboard/app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
sys.path.insert(0, str(ROOT))

st.set_page_config(page_title="APOLLO-M", page_icon="🪐", layout="wide")


def _secrets_to_env() -> None:
    """
    Publish Streamlit secrets as environment variables.

    The LLM layer reads os.getenv("ANTHROPIC_API_KEY"), which works locally
    because llm/__init__.py loads the git-ignored .env. A Streamlit Cloud
    deployment has no .env, so the key was never visible and every explanation
    silently degraded to "[template fallback — no LLM reachable]" — the layer
    working exactly as designed, on a key that was never delivered to it.

    setdefault, not assignment: a real environment variable always wins, so this
    cannot override a deliberate local setting.
    """
    import os as _os
    try:
        for key in ("ANTHROPIC_API_KEY", "CLAUDE_MODEL", "LLM_PROVIDER",
                    "OLLAMA_HOST", "OLLAMA_MODEL", "APOLLO_API_URL"):
            if key in st.secrets:
                _os.environ.setdefault(key, str(st.secrets[key]))
    except Exception:
        # No secrets file at all is a normal local state, not an error.
        pass


_secrets_to_env()

st.markdown("""
<style>
.stApp { background:
    radial-gradient(1200px 600px at 15% -10%, rgba(139,92,246,.25), transparent 60%),
    radial-gradient(900px 500px at 90% 0%, rgba(34,211,238,.18), transparent 55%),
    #070714; color:#e5e7ff; }
.apollo-title{font-size:2.4rem;font-weight:800;
  background:linear-gradient(90deg,#8b5cf6,#22d3ee);-webkit-background-clip:text;
  -webkit-text-fill-color:transparent;}
h1,h2,h3{color:#fff !important;}
.kpi{background:rgba(255,255,255,.04);border:1px solid rgba(139,92,246,.35);
  border-radius:16px;padding:16px;box-shadow:0 0 24px rgba(139,92,246,.15)}
.kpi .v{font-size:1.9rem;font-weight:800;color:#fff}
.kpi .l{font-size:.75rem;color:#a5b4fc;text-transform:uppercase;letter-spacing:1px}
section[data-testid="stSidebar"]{background:#0b0b1e;border-right:1px solid rgba(139,92,246,.3)}
</style>
""", unsafe_allow_html=True)


def _read(name: str) -> pd.DataFrame:
    try:
        return pd.read_csv(OUTPUTS / name)
    except Exception:
        return pd.DataFrame()


def alert_of(chi: float) -> str:
    v = chi * 100 if chi <= 1.0 else chi
    return ("LOW" if v >= 85 else "MEDIUM" if v >= 75 else "HIGH" if v >= 65 else "CRITICAL")


ALERT_COLOR = {"CRITICAL": "#ef4444", "HIGH": "#f59e0b", "MEDIUM": "#eab308", "LOW": "#22c55e"}

# ── Authentication ──────────────────────────────────────────────────────────
USERS = {"admin": "apollo_admin", "analyst": "apollo_analyst", "viewer": "apollo_viewer"}


def _google_ready() -> bool:
    """
    Show the Google button only when sign-in can actually succeed.

    Two conditions, and both are needed. Checking only for the secrets rendered a
    button that raised StreamlitMissingAuthlibError the moment it was clicked,
    because st.login() requires Authlib and the deployed environment did not have
    it. A visible control that always fails is worse than no control — especially
    in a live demo, where it fails in front of an audience.
    """
    try:
        if "auth" not in st.secrets:
            return False
    except Exception:
        return False
    try:
        import authlib  # noqa: F401
    except Exception:
        return False
    return True


GOOGLE = _google_ready()
# Adopt a Google (OIDC) identity if the user signed in that way.
try:
    if GOOGLE and getattr(st, "user", None) is not None and st.user.is_logged_in:
        st.session_state.user = st.user.email
except Exception:
    pass

st.session_state.setdefault("user", None)

if not st.session_state.user:
    st.markdown("""<style>
    .stApp .block-container{padding-top:4vh}
    div[data-testid="stForm"]{background:rgba(20,18,45,.6);border:1px solid rgba(139,92,246,.4);
      border-radius:18px;padding:22px 22px 6px;box-shadow:0 0 60px rgba(139,92,246,.22);}
    </style>""", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.25, 1])
    with mid:
        st.markdown('<div class="apollo-title" style="text-align:center;font-size:2.8rem">'
                    '🪐 APOLLO-M</div>', unsafe_allow_html=True)
        st.markdown("<p style='text-align:center;color:#a5b4fc;margin-top:-6px'>"
                    "Community-Instability Forecasting Console</p>", unsafe_allow_html=True)
        if GOOGLE:
            if st.button("Continue with Google", use_container_width=True, type="primary"):
                st.login("google")
            st.markdown("<p style='text-align:center;color:#7c83b3'>— or sign in with an account —</p>",
                        unsafe_allow_html=True)
        with st.form("login"):
            u = st.text_input("Username", placeholder="admin")
            p = st.text_input("Password", type="password", placeholder="apollo_admin")
            ok = st.form_submit_button("Sign in", use_container_width=True,
                                       type=("secondary" if GOOGLE else "primary"))
            if ok:
                if USERS.get(u.strip().lower()) == p.strip():
                    st.session_state.user = u.strip().lower()
                    st.rerun()
                else:
                    st.error("Invalid credentials. Username is **admin**, password is **apollo_admin**.")
        if st.button("⚡ Sign in as demo (admin)", use_container_width=True):
            st.session_state.user = "admin"
            st.rerun()
        st.caption("Demo accounts — **admin / apollo_admin** · analyst / apollo_analyst · "
                   "viewer / apollo_viewer")
    st.stop()

# ── Data ────────────────────────────────────────────────────────────────────
meso = _read("meso_report.csv")
clusters = _read("clusters_report.csv")
forecast = _read("forecast_results.csv")
if not meso.empty:
    meso["alert"] = meso["community_health_index"].apply(alert_of)


def fc_p50(sub: str):
    if forecast.empty or "subreddit" not in forecast:
        return None
    row = forecast[forecast["subreddit"] == sub]
    return round(float(row["p50"].iloc[0]), 3) if not row.empty and "p50" in row else None


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="apollo-title" style="font-size:1.6rem">🪐 APOLLO-M</div>',
                unsafe_allow_html=True)
    st.caption(f"Signed in: **{st.session_state.user}**")
    page = st.radio("Navigate", ["Overview", "🎯 Actions", "Communities", "Forecast",
                                 "Clusters", "🔴 Live", "Monitoring"])
    provider = st.radio("LLM provider", ["claude", "ollama"], horizontal=True,
                        help="Claude = cloud API (works now). Ollama = local & free, "
                             "but needs `ollama serve` + a pulled model running.")
    st.divider()
    st.markdown("**Connected systems**")
    st.link_button("🛰️ Open CEREBRO", "https://cerebro-sandy-beta.vercel.app",
                   use_container_width=True)
    st.link_button("📊 Grafana", "http://localhost:3000", use_container_width=True)
    st.link_button("📈 Prometheus", "http://localhost:9090", use_container_width=True)
    st.link_button("🔌 API docs", "http://localhost:8010/docs", use_container_width=True)
    st.divider()
    # Explicit key so this can never collide with another identically-configured
    # button during a rerun (StreamlitDuplicateElementId). st.user is guarded
    # with getattr because it does not exist on older Streamlit versions.
    if st.button("Sign out", use_container_width=True, key="sidebar_signout"):
        st.session_state.user = None
        try:
            if GOOGLE and getattr(st, "user", None) is not None and st.user.is_logged_in:
                st.logout()
        except Exception:
            pass
        st.rerun()


def kpi_row():
    c = st.columns(4)
    n = len(meso) if not meso.empty else 0
    crit = int((meso["alert"] == "CRITICAL").sum()) if not meso.empty else 0
    tox = f"{meso['toxicity_rate'].mean():.1%}" if not meso.empty else "—"
    chi = f"{meso['community_health_index'].mean():.1f}" if not meso.empty else "—"
    for col, l, v in [(c[0], "Communities", n), (c[1], "Critical", crit),
                      (c[2], "Avg toxicity", tox), (c[3], "Avg CHI", chi)]:
        col.markdown(f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div></div>',
                     unsafe_allow_html=True)


@st.fragment(run_every="3s")
def live_panel():
    sp = OUTPUTS / "live_stats.json"
    if not sp.exists():
        # Says "local-only" rather than just "idle": on the hosted dashboard the
        # replay is not running and never will be, so a bare "idle" reads as a
        # fault instead of the documented design.
        st.info("**Live replay runs locally.** This page streams the real corpus "
                "through the pipeline in real time on the machine running "
                "`python ingest/live_replay.py`. The hosted dashboard serves "
                "precomputed results, so there is no live feed here.")
        return
    s = json.loads(sp.read_text())
    c = st.columns(4)
    c[0].metric("Processed", f"{s.get('processed', 0):,}")
    c[1].metric("Rolling toxic rate", f"{s.get('rolling_toxic_rate', 0):.0%}")
    c[2].metric("Rolling avg tox", f"{s.get('rolling_avg_toxicity', 0):.2f}")
    c[3].metric("Hottest", str(s.get("hottest_community") or "—"))
    try:
        for _, r in pd.read_csv(OUTPUTS / "live_feed.csv").tail(8).iloc[::-1].iterrows():
            col = "#ef4444" if r["is_toxic"] else "#22c55e"
            st.markdown(f"<span style='color:{col}'>●</span> <b>{r['subreddit']}</b> "
                        f"<span style='color:#7c83b3'>[{r['ts']}]</span> tox={float(r['toxicity']):.2f} — "
                        f"{str(r['body'])[:110]}", unsafe_allow_html=True)
    except Exception:
        pass
    st.caption(f"updated {s.get('updated', '')} · real corpus, real scores, live")


# ── Pages ────────────────────────────────────────────────────────────────────
st.markdown('<div class="apollo-title">🪐 APOLLO-M</div>', unsafe_allow_html=True)

if page == "Overview":
    st.subheader("Overview")
    kpi_row()
    st.write("")
    if meso.empty:
        st.info("No data — run `python main.py --mode full`.")
    else:
        show = meso[["subreddit", "community_health_index", "toxicity_rate",
                     "polarization", "alert"]].sort_values("community_health_index")
        st.dataframe(show.style.map(
            lambda a: f"color:{ALERT_COLOR.get(a, '#fff')};font-weight:700", subset=["alert"]),
            use_container_width=True, height=460)

elif page == "🎯 Actions":
    st.subheader("Proactive moderation actions")
    st.caption("This is the point of the system: a **standardised recommended action per "
               "community** so every moderator responds consistently — and the forecast lets "
               "them act **before** a community destabilises, not after.")
    if meso.empty:
        st.info("No data — run the pipeline.")
    else:
        REC = {"CRITICAL": "EMERGENCY_INTERVENTION", "HIGH": "INCREASE_MODERATION",
               "MEDIUM": "WARN", "LOW": "NO_ACTION"}
        d = meso.copy()
        d["recommended_action"] = d["alert"].map(REC)
        d["forecast_p50 (5d)"] = d["subreddit"].map(fc_p50)
        d = d.sort_values("community_health_index")
        act_counts = d["recommended_action"].value_counts().to_dict()
        cols = st.columns(len(act_counts) or 1)
        for col, (a, n) in zip(cols, act_counts.items()):
            col.metric(a.replace("_", " ").title(), n)
        st.write("")
        view = d[["subreddit", "community_health_index", "toxicity_rate", "alert",
                  "recommended_action", "forecast_p50 (5d)"]].rename(
            columns={"community_health_index": "CHI", "toxicity_rate": "toxicity"})
        st.dataframe(view.style.map(
            lambda a: f"color:{ALERT_COLOR.get(a, '#fff')};font-weight:700", subset=["alert"]),
            use_container_width=True, height=430)
        # This mapping is a deterministic rule, not a model. The caption used to
        # credit "the trained RandomForest recommender", which does not run in the
        # pipeline and has no saved weights — the table was always this dict.
        st.caption("Actions are a **deterministic mapping from the alert band** "
                   "(LOW→NO_ACTION … CRITICAL→EMERGENCY_INTERVENTION), not a model "
                   "prediction. The **forecast column "
                   "is the proactive signal** — a community forecast to rise into the critical "
                   "band is flagged for action before it gets there.")

elif page == "Communities":
    st.subheader("Community drill-down")
    if meso.empty:
        st.info("No community data yet.")
    else:
        subs = meso.sort_values("community_health_index")["subreddit"].tolist()
        sel = st.selectbox("Select a community", subs)
        r = meso[meso["subreddit"] == sel].iloc[0]
        chi = float(r["community_health_index"])          # already 0-100 — DO NOT *100
        c = st.columns(4)
        c[0].metric("CHI", f"{chi:.1f}")
        c[1].metric("Toxicity", f"{r['toxicity_rate']:.1%}")
        c[2].metric("Polarization", f"{r['polarization']:.1%}")
        c[3].metric("Alert", r["alert"])
        st.markdown(f"**Total comments analysed:** {int(r['total_comments'])}  ·  "
                    f"**Churn:** {r['churn_rate']:.2f}")
        if st.button(f"🧠 Explain with {provider}", type="primary"):
            with st.spinner(f"Asking {provider}…"):
                from llm.explain import explain_community
                txt = explain_community({
                    "subreddit": sel, "chi": round(chi, 1),      # FIXED — no *100
                    "toxicity": f"{r['toxicity_rate']:.0%}",
                    "polarization": f"{r['polarization']:.0%}",
                    "alert_level": r["alert"], "forecast_p50": fc_p50(sel),
                }, provider_name=provider)
            st.success(txt)
            if "template fallback" in txt and provider == "ollama":
                st.caption("Ollama isn't running — start it (`ollama serve` + `ollama pull llama3.1`) "
                           "or switch the LLM provider to **claude** in the sidebar.")

elif page == "Forecast":
    st.subheader("5-day toxicity forecast (TFT)")
    if forecast.empty or not {"p10", "p50", "p90", "subreddit"}.issubset(forecast.columns):
        st.info("No forecast — run `python gen_forecasts.py`.")
    else:
        fsel = st.selectbox("Community", sorted(forecast["subreddit"].unique()))
        fc = forecast[forecast["subreddit"] == fsel].reset_index(drop=True)
        x = list(fc["day"]) if "day" in fc else list(range(1, len(fc) + 1))
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x + x[::-1],
                      y=list(fc["p90"]) + list(fc["p10"])[::-1],
                      fill="toself", fillcolor="rgba(139,92,246,.25)",
                      line=dict(color="rgba(0,0,0,0)"), name="p10–p90"))
        fig.add_trace(go.Scatter(x=x, y=fc["p50"], mode="lines+markers",
                      line=dict(color="#22d3ee", width=3), name="p50 (median)"))
        fig.update_layout(template="plotly_dark", height=420, title=fsel, yaxis_title="toxicity",
                          xaxis_title="days ahead",
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
        trend = float(fc["p50"].iloc[-1] - fc["p50"].iloc[0])
        arrow = "▲ rising" if trend > 0.005 else "▼ falling" if trend < -0.005 else "→ stable"
        st.markdown(f"**5-day trend: {arrow}** ({trend:+.3f}) · mean 80% band width "
                    f"{(fc['p90'] - fc['p10']).mean():.3f}")
        st.caption("The **trend** is the proactive signal — a rising forecast flags a community "
                   "heading toward critical before it gets there. Widening bands = honest, "
                   "calibrated uncertainty (not compared to anything — it's the model's own confidence).")

elif page == "Clusters":
    st.subheader("Community clusters (unsupervised)")
    if clusters.empty or not {"pca_x", "pca_y"}.issubset(clusters.columns):
        st.info("No clusters — run `python main.py --mode unsupervised`.")
    else:
        fig = go.Figure(go.Scatter(
            x=clusters["pca_x"], y=clusters["pca_y"], mode="markers",
            marker=dict(size=10, color=clusters.get("cluster", 0), colorscale="Viridis",
                        line=dict(width=.5, color="#fff"), showscale=True),
            text=clusters["subreddit"], hovertemplate="%{text}<extra></extra>"))
        fig.update_layout(template="plotly_dark", height=460,
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Each point is a community grouped by its health profile; colour = cluster.")

elif page == "🔴 Live":
    st.subheader("Real-time comment processing")
    live_panel()

elif page == "Monitoring":
    st.subheader("Monitoring")
    st.markdown("Metrics flow: **exporter (:9100) → Prometheus (:9090) → Grafana (:3000)**.")
    c = st.columns(2)
    c[0].link_button("📊 Open Grafana dashboard", "http://localhost:3000", use_container_width=True)
    c[1].link_button("📈 Open Prometheus (PromQL)", "http://localhost:9090", use_container_width=True)
    st.info("**Grafana login:** username `admin`, password `admin` — Grafana has its own login "
            "(not your Google account). It'll ask you to set a new password on first sign-in.")
    st.markdown("**Don't know PromQL? Try these** — paste one into the Prometheus query box and press "
                "**Execute**:")
    for q, desc in {
        "apollo_avg_chi": "Average Community Health Index (0–100)",
        "apollo_critical_alerts": "How many communities are CRITICAL right now",
        "apollo_avg_toxicity": "Mean toxicity across communities",
        "apollo_communities_total": "Communities analysed",
        "apollo_toxicity_f1_micro": "Toxicity classifier F1 (micro)",
        "apollo_forecast_p50_day1": "Day-1 median toxicity forecast",
    }.items():
        st.markdown(f"- `{q}` — {desc}")
    st.caption("Grafana's APOLLO-M dashboard already charts all of these — no query typing needed there.")
    st.markdown("**Live exporter output** (what Prometheus scrapes):")
    try:
        import requests
        m = requests.get("http://localhost:9100/metrics", timeout=3).text
        rows = [l for l in m.splitlines() if l.startswith("apollo_") and not l.startswith("apollo_")==False]
        st.code("\n".join([l for l in m.splitlines() if l.startswith("apollo_")]) or "no apollo metrics",
                language="text")
    except Exception:
        st.info("**Monitoring runs locally.** Prometheus scrapes the exporter on "
                "`localhost:9100` and Grafana renders it on `localhost:3000`; "
                "neither is reachable from a hosted page. Start them with "
                "`python monitoring/exporter.py` to see this section populate.")
