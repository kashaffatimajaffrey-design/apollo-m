# Audit paper

*A Known-Answer Audit for Deployed Measurement Systems: Procedure and a Case Study.*

| File | Purpose |
|---|---|
| `paper.html` | Source of the paper. Edit this. |
| `paper.pdf` | Built output (A4, fonts embedded, page numbers, metadata set). |
| `bootstrap_ci.py` | Every number in Tables 1–4 and §5.6, from the committed outputs. Writes `results.json`. |
| `make_paper_figures.py` | Figures 2–10 at 300 dpi into `figures/`. Runs `bootstrap_ci.py` first if needed. |
| `build_pdf.py` | Renders `paper.html` to `paper.pdf` with headless Chromium. |
| `figures/fig01_architecture.png` | Reproduced from the project report; not generated. |
| `figures/fig07_trajectories_prebuilt.png` | Fallback for Figure 7 when `data/apollo_daily.csv` is absent. |

## Rebuild

```bash
pip install numpy scipy pandas matplotlib pymupdf playwright
playwright install chromium            # or set PAPER_CHROMIUM=/path/to/chrome
python docs/paper/bootstrap_ci.py      # ~25 s: 20,000 resamples, seed 20260903
python docs/paper/make_paper_figures.py
python docs/paper/build_pdf.py
```

`data/apollo_daily.csv` (written by `simulate_data.py`, committed) feeds Table 4's
OLS rows and Figure 7(a). If it is ever removed the scripts fall back to the
pre-built Figure 7, skip the OLS rows, and say so.
