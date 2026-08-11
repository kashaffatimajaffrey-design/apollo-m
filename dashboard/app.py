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

# Where the deployed services live. The sidebar previously linked to
# http://localhost:3000 / :9090 / :8010 unconditionally, so on the hosted
# dashboard every one of those buttons led a visitor to a connection error on
# their own machine. Anything with a public URL now points at it; anything that
# genuinely only exists locally is shown only when a URL is supplied.
import os as _os

API_URL = _os.getenv("APOLLO_API_URL", "https://apollo-api-tllm.onrender.com").rstrip("/")
CEREBRO_URL = _os.getenv("CEREBRO_URL", "https://cerebro-sandy-beta.vercel.app").rstrip("/")
# Grafana and Prometheus default to the local ports because that is where they
# actually run: the demo is presented from the machine hosting them, and there
# the links open the real dashboards. They are shown with a note rather than
# hidden, since a viewer on another device would otherwise wonder where the
# monitoring layer went — "localhost" resolves to *their* machine, not ours.
GRAFANA_URL = _os.getenv("GRAFANA_URL", "http://localhost:3000").rstrip("/")
PROMETHEUS_URL = _os.getenv("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")

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


# Two datasets are kept deliberately rather than one replacing the other.
#
#   Benchmark  — 60 communities over 120 days with recorded ground truth. It is
#                the only source where the answer is known in advance, so it is
#                the only place recall can be measured, and it shows the system
#                at a scale real collection has not yet reached.
#   Real Reddit— genuine comments collected through Arctic Shift. Fewer
#                communities, but every number is computed from real activity.
#
# Both are produced by the same pipeline; only the ingestion adapter differs.
DATASETS = {
    "Benchmark (simulation)": OUTPUTS,
    "Real Reddit": OUTPUTS / "real",
}


def _read_from(base: Path, name: str) -> pd.DataFrame:
    try:
        return pd.read_csv(base / name)
    except Exception:
        return pd.DataFrame()


def _read(name: str) -> pd.DataFrame:
    """Read from the dataset the sidebar has selected, falling back to benchmark."""
    base = st.session_state.get("dataset_dir", OUTPUTS)
    df = _read_from(base, name)
    if df.empty and base != OUTPUTS:
        return _read_from(OUTPUTS, name)
    return df


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

# ── Dataset selection ───────────────────────────────────────────────────────
# Chosen before the data is read, since every page below depends on it.
_avail = {k: v for k, v in DATASETS.items()
          if (v / "meso_report.csv").exists() or k.startswith("Benchmark")}
with st.sidebar:
    _choice = st.radio("Dataset", list(_avail.keys()), index=0,
                       help="Benchmark = declared simulation with recorded ground "
                            "truth. Real Reddit = comments collected live through "
                            "Arctic Shift. Same pipeline, different ingestion.")
st.session_state["dataset_dir"] = _avail[_choice]
IS_REAL = _choice == "Real Reddit"

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
                                 "Clusters", "🔴 Live", "🌐 Real Reddit", "Monitoring"])
    provider = st.radio("LLM provider", ["claude", "ollama"], horizontal=True,
                        help="Claude = cloud API (works now). Ollama = local & free, "
                             "but needs `ollama serve` + a pulled model running.")
    st.divider()
    st.markdown("**Connected systems**")
    st.link_button("🛰️ Open CEREBRO", CEREBRO_URL,
                   use_container_width=True)
    st.link_button("📊 Grafana", GRAFANA_URL, use_container_width=True)
    st.link_button("📈 Prometheus", PROMETHEUS_URL, use_container_width=True)
    st.link_button("🔌 API docs", f"{API_URL}/docs", use_container_width=True)
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


def dataset_banner():
    """
    Say which corpus the numbers on screen come from.

    Without this the two datasets are indistinguishable once a chart is on
    screen, and a reader could take benchmark figures for measurements of real
    communities — the precise confusion the split exists to avoid.
    """
    if IS_REAL:
        st.success("**Real Reddit** — every figure below is computed from genuine "
                   "comments collected through Arctic Shift, scored by "
                   "`unitary/toxic-bert`.")
    else:
        st.info("**Benchmark (declared simulation)** — 60 communities over 120 days "
                "with recorded ground truth. Used to measure recall, because it is "
                "the only source where the answer is known in advance. Switch the "
                "dataset in the sidebar for real Reddit.")


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


@st.cache_data
def _live_seed() -> pd.DataFrame:
    try:
        return pd.read_csv(OUTPUTS / "live_seed.csv")
    except Exception:
        return pd.DataFrame()


def _hosted_stream():
    """
    Drive the live feed from the wall clock instead of a background process.

    The page used to require `ingest/live_replay.py` running on the same machine,
    so on the hosted dashboard it showed nothing — the one page whose whole point
    is motion was the one page that could not move for anyone but the operator.

    Position is derived from the current time, so every visitor sees the stream
    advancing on their own device with no server-side state, no websocket and no
    background worker. The comments and their toxicity scores are the real,
    already-scored corpus rows; only the arrival timing is synthetic, which is
    exactly what "replay" means and what the caption says.
    """
    import time as _time
    seed = _live_seed()
    if seed.empty:
        return None, None
    step = 2                                    # seconds per new comment
    pos = int(_time.time() // step) % len(seed)
    window = seed.iloc[max(0, pos - 250):pos + 1]        # rolling stats window
    if window.empty:
        window = seed.iloc[:1]
    recent = window.tail(8).iloc[::-1].copy()
    recent["ts"] = [
        _time.strftime("%H:%M:%S", _time.localtime(_time.time() - i * step))
        for i in range(len(recent))
    ]
    stats = {
        "processed": pos + 1,
        "rolling_toxic_rate": float(window["is_toxic"].mean()),
        "rolling_avg_toxicity": float(window["toxicity"].mean()),
        "hottest_community": (window.groupby("subreddit")["toxicity"].mean()
                              .idxmax() if len(window) else "—"),
        "updated": _time.strftime("%H:%M:%S"),
    }
    return stats, recent


@st.fragment(run_every="2s")
def live_panel():
    sp = OUTPUTS / "live_stats.json"
    hosted = False
    if sp.exists():
        s = json.loads(sp.read_text())
        feed = None
    else:
        # No local replay running: stream the committed corpus slice instead, so
        # the page works for every viewer rather than only for the operator.
        s, feed = _hosted_stream()
        hosted = True
        if s is None:
            st.info("Live feed unavailable — outputs/live_seed.csv is missing.")
            return
    c = st.columns(4)
    c[0].metric("Processed", f"{s.get('processed', 0):,}")
    c[1].metric("Rolling toxic rate", f"{s.get('rolling_toxic_rate', 0):.0%}")
    c[2].metric("Rolling avg tox", f"{s.get('rolling_avg_toxicity', 0):.2f}")
    c[3].metric("Hottest", str(s.get("hottest_community") or "—"))
    try:
        rows = feed if feed is not None else \
            pd.read_csv(OUTPUTS / "live_feed.csv").tail(8).iloc[::-1]
        for _, r in rows.iterrows():
            col = "#ef4444" if r["is_toxic"] else "#22c55e"
            sub = str(r["subreddit"])
            sub = sub if sub.startswith("r/") else f"r/{sub}"
            st.markdown(f"<span style='color:{col}'>●</span> <b>{sub}</b> "
                        f"<span style='color:#7c83b3'>[{r['ts']}]</span> tox={float(r['toxicity']):.2f} — "
                        f"{str(r['body'])[:110]}", unsafe_allow_html=True)
    except Exception:
        pass
    if hosted:
        st.caption(f"updated {s.get('updated', '')} · replaying the scored corpus — "
                   "comments and toxicity scores are real, arrival timing is simulated")
    else:
        st.caption(f"updated {s.get('updated', '')} · real corpus, real scores, live")


# ── Pages ────────────────────────────────────────────────────────────────────
st.markdown('<div class="apollo-title">🪐 APOLLO-M</div>', unsafe_allow_html=True)

if page == "Overview":
    st.subheader("Overview")
    dataset_banner()
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
    dataset_banner()
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
    dataset_banner()
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
    dataset_banner()
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
    dataset_banner()
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

elif page == "🌐 Real Reddit":
    st.subheader("Real Reddit ingestion")

    # A live call, made when the button is pressed. Everything else on this page
    # is a stored corpus; this proves the ingestion path is genuinely open right
    # now rather than something that worked once on a developer's machine. It
    # needs no credentials, which is the whole reason Arctic Shift was chosen
    # over Reddit's own API.
    st.markdown("**Fetch live from Reddit — right now**")
    fc = st.columns([2, 1, 1])
    sub_live = fc[0].text_input("Subreddit", value="politics",
                                label_visibility="collapsed",
                                placeholder="subreddit, e.g. politics")
    n_live = fc[1].selectbox("How many", [10, 25, 50], index=0,
                             label_visibility="collapsed")
    go_live = fc[2].button("⚡ Fetch now", use_container_width=True, type="primary")

    if go_live:
        import datetime as _dt
        import requests as _rq
        with st.spinner(f"calling Arctic Shift for r/{sub_live}…"):
            try:
                now = int(_dt.datetime.now(_dt.timezone.utc).timestamp())
                r = _rq.get("https://arctic-shift.photon-reddit.com/api/comments/search",
                            params={"subreddit": sub_live.strip().lstrip("r/"),
                                    "before": now, "limit": int(n_live)}, timeout=25)
                if r.status_code != 200:
                    st.error(f"Arctic Shift returned HTTP {r.status_code}")
                else:
                    rows = [c for c in (r.json().get("data") or [])
                            if (c.get("body") or "").strip()
                            not in ("", "[deleted]", "[removed]")]
                    if not rows:
                        st.warning("No comments returned for that subreddit/window.")
                    else:
                        newest = max(c["created_utc"] for c in rows)
                        age = (now - newest) / 60
                        st.success(f"Fetched {len(rows)} comments from r/{sub_live} — "
                                   f"newest posted {age:.0f} minutes ago.")
                        st.caption("Live HTTP call, no credentials, made when you "
                                   "pressed the button. Toxicity scoring runs in the "
                                   "pipeline, which loads the transformer locally.")
                        for c in rows[:12]:
                            ts = _dt.datetime.fromtimestamp(
                                c["created_utc"], _dt.timezone.utc).strftime("%H:%M UTC")
                            st.markdown(
                                f"<span style='color:#22d3ee'>●</span> "
                                f"<b>r/{c.get('subreddit', sub_live)}</b> "
                                f"<span style='color:#7c83b3'>u/{c.get('author','?')} "
                                f"· {ts}</span> — {str(c.get('body',''))[:170]}",
                                unsafe_allow_html=True)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Live fetch failed: {exc}")
    st.divider()
    # Reads from outputs/ rather than data/, because data/*.csv is gitignored and
    # would therefore be absent on the hosted dashboard — the page would look
    # broken everywhere except the machine that collected the corpus.
    summary_p = OUTPUTS / "real_reddit_summary.json"
    daily_p = OUTPUTS / "real_reddit_daily.csv"
    recent_p = OUTPUTS / "real_reddit_recent.csv"

    if not summary_p.exists():
        st.info("**No real-Reddit corpus yet.** Collect one with\n\n"
                "`python ingest/arctic_shift.py --days 40 --per-sub 2400`\n\n"
                "then score it with `python score_real_reddit.py`.")
    else:
        s = json.loads(summary_p.read_text(encoding="utf-8"))
        st.caption(f"Source: **{s.get('source','Arctic Shift')}** · scored by "
                   f"`{s.get('model','unitary/toxic-bert')}` — the same micro layer "
                   "the rest of the pipeline uses.")

        k = st.columns(5)
        k[0].metric("Comments", f"{s.get('comments_scored', 0):,}")
        k[1].metric("Communities", s.get("subreddits", 0))
        k[2].metric("Authors", f"{s.get('authors', 0):,}")
        k[3].metric("Days covered", s.get("days_covered", 0))
        k[4].metric("Mean toxicity", f"{s.get('mean_toxicity_overall', 0):.3f}")
        rng = s.get("date_range") or []
        if len(rng) == 2:
            st.caption(f"Window: {rng[0]} → {rng[1]}  ·  overall toxic rate "
                       f"{s.get('toxic_rate_overall', 0):.1%}")

        per = s.get("per_community") or {}
        if per:
            st.markdown("**Toxicity by community — measured on real comments**")
            pc = (pd.DataFrame(per).T.reset_index()
                    .rename(columns={"index": "subreddit"})
                    .sort_values("mean_toxicity", ascending=False))
            fig = go.Figure(go.Bar(
                x=pc["subreddit"].apply(lambda v: f"r/{v}"),
                y=pc["mean_toxicity"],
                marker=dict(color=pc["mean_toxicity"], colorscale="Plasma"),
                hovertemplate="%{x}<br>mean toxicity %{y:.3f}<extra></extra>"))
            fig.update_layout(height=330, margin=dict(l=10, r=10, t=10, b=10),
                              paper_bgcolor="rgba(0,0,0,0)",
                              plot_bgcolor="rgba(0,0,0,0)",
                              font_color="#e5e7ff", yaxis_title="mean toxicity")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(pc, use_container_width=True, hide_index=True)

        if daily_p.exists():
            st.markdown("**Daily toxicity — the series the forecaster consumes**")
            dd = pd.read_csv(daily_p, parse_dates=["date"])
            picks = st.multiselect("Communities", sorted(dd["subreddit"].unique()),
                                   default=sorted(dd["subreddit"].unique())[:4])
            f2 = go.Figure()
            for sub in picks:
                g = dd[dd["subreddit"] == sub].sort_values("date")
                f2.add_trace(go.Scatter(x=g["date"], y=g["avg_toxicity"],
                                        mode="lines+markers", name=f"r/{sub}"))
            f2.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10),
                             paper_bgcolor="rgba(0,0,0,0)",
                             plot_bgcolor="rgba(0,0,0,0)", font_color="#e5e7ff",
                             yaxis_title="daily mean toxicity")
            st.plotly_chart(f2, use_container_width=True)

        if recent_p.exists():
            st.markdown("**Recent real comments** (scored)")
            rc = pd.read_csv(recent_p)
            for _, r in rc.head(12).iterrows():
                tox = float(r.get("toxicity_score", 0))
                col = "#ef4444" if tox >= 0.5 else "#f59e0b" if tox >= 0.2 else "#22c55e"
                st.markdown(
                    f"<span style='color:{col}'>●</span> <b>r/{r['subreddit']}</b> "
                    f"<span style='color:#7c83b3'>u/{r.get('author','?')}</span> "
                    f"tox={tox:.2f} — {str(r['body'])[:150]}",
                    unsafe_allow_html=True)

        st.info(s.get("note", ""))

elif page == "Monitoring":
    st.subheader("Monitoring")
    # The metrics are rendered here directly rather than only linked to. The page
    # used to consist of buttons to localhost:3000 and localhost:9090, which on a
    # hosted dashboard sent every visitor to a connection error on their own
    # machine -- the monitoring section was invisible to everyone but the operator.
    # These are the same series the Prometheus exporter publishes, read from the
    # pipeline outputs, so the page is meaningful wherever it is served.
    st.markdown("These are the metrics APOLLO-M publishes. The same series are "
                "exported to Prometheus and charted in Grafana for operations; "
                "they are rendered here so the dashboard is self-contained.")

    mrow = st.columns(4)
    n_comm = len(meso) if not meso.empty else 0
    crit = int((meso["alert"] == "CRITICAL").sum()) if not meso.empty else 0
    mrow[0].metric("apollo_communities_total", n_comm)
    mrow[1].metric("apollo_critical_alerts", crit)
    mrow[2].metric("apollo_avg_chi",
                   f"{meso['community_health_index'].mean():.1f}" if not meso.empty else "-")
    mrow[3].metric("apollo_avg_toxicity",
                   f"{meso['toxicity_rate'].mean():.3f}" if not meso.empty else "-")

    try:
        _m = json.loads((OUTPUTS / "metrics.json").read_text())
        tox = _m.get("Toxicity (TF-IDF+LR, Jigsaw)", {})
        r2 = st.columns(4)
        r2[0].metric("toxicity accuracy", tox.get("accuracy", "-"))
        r2[1].metric("apollo_toxicity_f1_micro", tox.get("F1 micro", "-"))
        r2[2].metric("apollo_toxicity_f1_macro", tox.get("F1 macro", "-"))
        fp = float(forecast["p50"].iloc[0]) if not forecast.empty and "p50" in forecast else None
        r2[3].metric("apollo_forecast_p50_day1", f"{fp:.3f}" if fp is not None else "-")
    except Exception:
        pass

    st.markdown("**Model status** — modules are marked unevaluated rather than "
                "given a number they never earned:")
    try:
        _m = json.loads((OUTPUTS / "metrics.json").read_text())
        st.json({k: v for k, v in _m.items()}, expanded=False)
    except Exception:
        st.caption("outputs/metrics.json not found.")

    try:
        _v = json.loads((OUTPUTS / "validation.json").read_text())
        st.markdown("**Validation against planted ground truth** "
                    "(`outputs/validation.json`):")
        vcol = st.columns(3)
        vcol[0].metric("instability score ROC-AUC",
                       _v["detection"]["instability_score_roc_auc"])
        vcol[1].metric("CHI ROC-AUC", _v["detection"]["chi_roc_auc"])
        vcol[2].metric("TFT slope ROC-AUC", _v["forecast_tft"]["slope_roc_auc"])
        st.caption(_v.get("caveat", ""))
    except Exception:
        pass

    st.divider()
    st.markdown("**Operations stack**")
    oc = st.columns(3)
    oc[0].link_button("📊 Open Grafana dashboard", GRAFANA_URL, use_container_width=True)
    oc[1].link_button("📈 Open Prometheus (PromQL)", PROMETHEUS_URL, use_container_width=True)
    oc[2].link_button("🔎 Live /metrics endpoint", f"{API_URL}/metrics",
                      use_container_width=True)
    st.caption(
        "Grafana and Prometheus run next to the pipeline on the machine that hosts it, "
        "so the first two links open the real dashboards **on that machine**. The third "
        "is public: the deployed API serves the same series in Prometheus exposition "
        "format, so any Prometheus — including Grafana Cloud — can scrape it from "
        "anywhere. Set GRAFANA_URL / PROMETHEUS_URL to point at a hosted instance.")
    st.info("**Grafana login:** username `admin` — Grafana keeps its own account, "
            "separate from this dashboard and from Google.")

    # Show the exposition text inline as well, so the scrape target is visible
    # without leaving the page.
    try:
        import requests as _rq
        _txt = _rq.get(f"{API_URL}/metrics", timeout=8).text
        with st.expander("Live scrape output (Prometheus exposition format)", expanded=False):
            st.code(_txt, language="text")
    except Exception:
        st.caption("Scrape endpoint unreachable right now — the API may be waking "
                   "from sleep on the free tier.")

    st.caption(
        "Prometheus stores the history of these series and Grafana charts them with "
        "alerting; both run as an operations stack next to the pipeline rather than "
        "as a public page, which is how monitoring is normally deployed. The scrape "
        "endpoint above is public, so any Prometheus — including Grafana Cloud — can "
        "read it. Set GRAFANA_URL or PROMETHEUS_URL to link a hosted instance here.")
    with st.expander("PromQL queries used by the Grafana dashboard"):
        for q, desc in {
            "apollo_avg_chi": "Average Community Health Index (0-100)",
            "apollo_critical_alerts": "Communities currently CRITICAL",
            "apollo_avg_toxicity": "Mean toxicity across communities",
            "apollo_communities_total": "Communities analysed",
            "apollo_toxicity_f1_micro": "Toxicity classifier F1 (micro)",
            "apollo_forecast_p50_day1": "Day-1 median toxicity forecast",
            "apollo_rising_communities": "Communities whose recent toxicity exceeds baseline",
        }.items():
            st.markdown(f"- `{q}` — {desc}")
