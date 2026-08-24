# APOLLO-M — Forecasting Instability in Digital Communities

A multi-layer pipeline that scores Reddit comments for toxicity, aggregates them
into a per-community health index and a trend-aware instability score, clusters
communities without labels, and forecasts each community's toxicity five days
ahead with quantile confidence bands using a Temporal Fusion Transformer.

Final Year Project — Bahria University Karachi.
Kashaf Fatima · Rizwan Saleem · Aaqib Mehmood. Supervisor: Mr. Saghir Ahmed.

Companion project: [CEREBRO](https://github.com/kashaffatimajaffrey-design/CEREBRO)
— threat and misinformation intelligence, deployed separately.

---

## Read this first: what the numbers mean

**The community-level corpus is a declared simulation with recorded ground truth,
not real Reddit activity.** No public labelled dataset of genuinely destabilising
communities exists, so the pipeline is validated by its ability to recover
instability that was deliberately planted. `simulate_data.py` assigns 15 of 60
communities a rising toxicity trend and records it in `data/ground_truth.json`,
which the pipeline never reads; `validate_simulation.py` then measures recovery.

Toxicity itself is real: 12,000 Davidson/Jigsaw texts are scored once by
`unitary/toxic-bert`, and every generated comment carries the genuine score for
the exact text it contains.

Measured results (`outputs/validation.json`):

| | Result |
|---|---|
| TFT predicts rising trend for planted destabilising communities | **15/15**, slope ROC-AUC **0.732** |
| Ranking by trend-aware instability score | ROC-AUC **1.000** |
| Ranking by Community Health Index | ROC-AUC 0.575 |
| Ranking by raw toxicity | ROC-AUC 0.649 |
| Toxicity classifier, held-out real labels | acc **0.901**, F1-macro 0.702 |

The 1.000 is a **wiring check, not accuracy**: the instability score looks for a
recent-vs-baseline change and the simulation plants a monotonic ramp, so it is
searching for the shape it was given. The TFT's 0.732 is the independent result —
the forecaster never sees the ground-truth file.

That ordering is the project's central finding: **an index built from
present-tense health cannot rank communities by how fast they are changing**,
which is what forecasting instability actually asks for. CHI scoring below one of
its own inputs is what prompted the instability score.

Modules named in the architecture that are **implemented but not yet invoked** by
the pipeline: the in-Apollo misinformation classifier, the GraphSAGE GNN, and the
moderation recommender. `outputs/metrics.json` marks each as unevaluated rather
than assigning it a number. See §11 of the technical report.

---

## Quick start

```bash
pip install -r requirements-train.txt   # full pipeline (torch, transformers, TFT)
python simulate_data.py        # build the benchmark (~15 min; scores texts with toxic-bert)
python regen_meso.py           # micro + meso + clustering -> outputs/
python gen_forecasts.py        # train the TFT -> outputs/forecast_results.csv
python validate_simulation.py  # measure recovery -> outputs/validation.json
```

Serving (no torch required — reads precomputed results):

```bash
pip install -r requirements.txt
uvicorn api.main:app --port 8010     # backend
streamlit run dashboard/app.py       # dashboard
```

| File | Installs | Used by |
|---|---|---|
| `requirements.txt` | dashboard + API, no ML | **Streamlit Cloud** (fixed filename) |
| `requirements-api.txt` | API only | Render |
| `requirements-train.txt` | full pipeline incl. torch | local training |

Large corpora are not in the repository (~526 MB; see `.gitignore`). The SNAP
Reddit hyperlink graph must be downloaded separately to recompute polarisation.

## Layout

| Path | What |
|---|---|
| `main.py` | Pipeline layers: micro, meso, unsupervised, macro, alerts |
| `simulate_data.py` / `validate_simulation.py` | Benchmark generation and ground-truth validation |
| `models/tft_forecaster.py` | Temporal Fusion Transformer, p10/p50/p90 |
| `api/` · `dashboard/` | FastAPI backend · Streamlit analyst dashboard |
| `web/` | Public web surface — Next.js App Router on Supabase ([README](web/README.md)) |
| `monitoring/` | Prometheus exporter + provisioned Grafana dashboard |
| `llm/` | Explanation layer (Ollama / Claude, template fallback) |
| `docs/APOLLO_Technical_Report.md` | Full report — §7.1 data provenance, §11 status |

## Three surfaces, one database

The pipeline writes community health scores to Postgres once. Everything that
reads them reads the same rows — there is no export, no copy and nothing to fall
out of sync.

| Surface | Stack | For |
|---|---|---|
| [Analyst dashboard](https://apollo-m.streamlit.app) | Streamlit + Plotly | Dense, stateful, behind a login |
| [REST API](https://apollo-api-tllm.onrender.com/docs) | FastAPI + JWT | Programmatic access, three roles |
| [Public web view](https://apollo-m.vercel.app) | Next.js 16 App Router, React 19, Supabase | Server-rendered, no login needed to read ([source](web/README.md)) |
| [Monitoring](monitoring/) | Prometheus + Grafana | Operational metrics |

`web/` is the one to read for frontend work: React Server Components, streaming
SSR across two independent Suspense boundaries, auth as Server Actions that work
without JavaScript, and row-level security as the actual authorisation boundary
rather than an app-layer check. Its own CI runs type safety, Prettier, ESLint,
build and a Playwright suite with no secrets in the runner.

## Deployment

`render.yaml` deploys the backend plus a managed PostgreSQL. No secrets are in it:
`JWT_SECRET`, `ANTHROPIC_API_KEY` and `CORS_ORIGINS` are `sync:false` and set in
Render's Environment tab. See `docs/DEPLOYMENT.md`.
