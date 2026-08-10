# Apollo-M — Deployment Checklist

Goal: put the **backend** (FastAPI) + **database** (PostgreSQL) on **Render**, and
the **frontend** (Streamlit) on **Streamlit Community Cloud** — all connected by
environment variables. Monitoring (Prometheus/Grafana) stays **local** for the demo
(hardest to host; not graded).

> Everything is env-var driven, so deploying is configuration, not code changes.

---

## 0. Before you start
- Push the `apollo-m/` code to GitHub (a repo the deploy platforms can read).
- Confirm `.env` is git-ignored (it is) — **secrets go in each platform's dashboard, never in the repo.**
- Use the **serve-only** deps: `requirements-serve.txt` (no torch/transformers → small builds).

## 1. Database (Render PostgreSQL)
1. Render → New → PostgreSQL (free). Note its **Internal/External `DATABASE_URL`**.
2. Apply the schema + load data once:
   - `psql "<DATABASE_URL>" -f database/schema.sql`
   - Load `outputs/*.csv` (adapt `database/db_setup.py`'s loaders to point at `DATABASE_URL`).
   - *(Or reuse CEREBRO's Render Postgres and create an `apollo` schema there — that's the shared-DB integration from the report.)*

## 2. Backend (Render Web Service)
- **Build:** `pip install -r requirements-serve.txt`
- **Start:** `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
- **Env vars (Render dashboard → Environment):**
  - `DATABASE_URL` (or `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASS`)
  - `ANTHROPIC_API_KEY` = the Claude key (secret)
  - `LLM_PROVIDER` = `claude` (or `ollama` — but Ollama isn't reachable from the cloud, so use `claude` in prod)
  - `CEREBRO_API_URL` = `https://cerebro-api-nmah.onrender.com` (optional cross-system calls)
- Verify: open `https://<backend>.onrender.com/health` → `database: connected`.

## 3. Frontend (Streamlit Community Cloud)
- streamlit.io → New app → point at the GitHub repo, main file `dashboard/app.py`.
- **Secrets (Streamlit → App settings → Secrets):**
  - `APOLLO_API_URL` = `https://<backend>.onrender.com`
  - `ANTHROPIC_API_KEY`, `LLM_PROVIDER=claude`
- Data: ship `outputs/*.csv` in the repo (simplest — the dashboard reads them), **or** point the dashboard at `APOLLO_API_URL` for live data.
- Result: public URL like `https://apollo-m.streamlit.app`.

> **Not Vercel/Netlify** — Streamlit is a Python server; those hosts run static/serverless only.

## 4. Monitoring (local for the demo)
- Run on your laptop: exporter (`:9100`) → Prometheus (`:9090`) → Grafana (`:3000`).
- Optional public: **Grafana Cloud** free tier can scrape a publicly-exposed exporter.

## 5. Connection map (once deployed)
```
Streamlit Cloud (frontend)  --HTTPS-->  Render (FastAPI backend)
                                              |-- DATABASE_URL --> Render Postgres
                                              |-- CEREBRO_API_URL --> CEREBRO (Render)
                                              '-- ANTHROPIC_API_KEY --> Claude
```

## 6. Smoke test after deploy
- `GET https://<backend>/health` → healthy
- `GET https://<backend>/summary` → real numbers
- Open the Streamlit URL → dashboard renders; Claude "explain" works (key set in secrets)

---

**Reminder:** for Wednesday, the *safe* demo is **local from your laptop** (everything already runs). The cloud deploy is the "and it's also live at this URL" bonus.
