"""
Generate the report figures for APOLLO-M.

These replace three earlier diagrams that showed modules as active pipeline
stages when they are implemented but never invoked (GraphSAGE, the
misinformation classifier, the RandomForest recommender), claimed storage the
project does not use (TimescaleDB), and described an intelligence exchange
between CEREBRO and Apollo that does not exist. A figure that contradicts §11 of
the technical report is worse than no figure.

Every status marker here is derived from the code as it stands:
  RUNS     — invoked by the pipeline on every run
  NOT WIRED— implemented in the repo, never called, no saved weights
  PLANNED  — designed, not built

Writes SVG (crisp, for the web) and PNG (for the PDF, which xhtml2pdf rasterises)
into docs/figures/.

    python docs/make_figures.py
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent / "figures"
OUT.mkdir(exist_ok=True)

# Palette kept close to the existing CEREBRO figures so the set looks coherent.
INK = "#12142b"
MUTED = "#5b6178"
LINE = "#c9cee0"
BLUE, GREEN, ORANGE, PURPLE, GREY = "#1e5fbf", "#12805c", "#c2610a", "#5b3fbf", "#6b7280"
BLUE_BG, GREEN_BG, ORANGE_BG, PURPLE_BG, GREY_BG = (
    "#eaf1fd", "#e6f5ef", "#fdf1e3", "#f0ebfd", "#f3f4f6")
AMBER, AMBER_BG = "#8a6d00", "#fdf6d8"


class SVG:
    def __init__(self, w: int, h: int, title: str, sub: str = ""):
        self.w, self.h = w, h
        self.p: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" font-family="Helvetica,Arial,sans-serif">',
            f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        ]
        self.text(36, 52, title, 27, INK, weight="bold")
        if sub:
            self.text(36, 78, sub, 14, MUTED)

    def text(self, x, y, s, size=13, fill=INK, weight="normal", anchor="start",
             italic=False):
        s = (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        style = ' font-style="italic"' if italic else ""
        self.p.append(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
            f'font-weight="{weight}" text-anchor="{anchor}"{style}>{s}</text>')

    def box(self, x, y, w, h, fill="#fff", stroke=LINE, rx=8, dash=None, sw=1.4):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.p.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def band(self, x, y, w, h, tag, colour, bg):
        """A pipeline stage: coloured spine on the left, label inside it."""
        self.box(x, y, w, h, bg, colour)
        self.p.append(f'<rect x="{x}" y="{y}" width="9" height="{h}" rx="4" fill="{colour}"/>')
        self.text(x + 24, y + 25, tag, 12.5, colour, weight="bold")

    def chip(self, x, y, w, h, label, status=None, colour=BLUE):
        """A module box. `status` renders a small pill: RUNS / NOT WIRED / PLANNED."""
        pill = {"RUNS": (GREEN, "#dcf2e8"), "NOT WIRED": (AMBER, AMBER_BG),
                "PLANNED": (GREY, "#e9eaee")}.get(status or "", None)
        self.box(x, y, w, h, "#ffffff", colour if not pill else pill[0], rx=7,
                 dash=None if status != "NOT WIRED" else "5,4", sw=1.2)
        lines = label.split("|")
        ty = y + (h - (len(lines) - 1) * 15) / 2 + 5
        for i, ln in enumerate(lines):
            self.text(x + w / 2, ty + i * 15, ln.strip(), 12.5, INK,
                      weight="bold" if i == 0 else "normal", anchor="middle")
        if pill:
            pw = 74 if status != "RUNS" else 50
            self.box(x + w - pw - 8, y + 7, pw, 17, pill[1], pill[0], rx=8, sw=1)
            self.text(x + w - pw / 2 - 8, y + 19.5, status, 9.5, pill[0],
                      weight="bold", anchor="middle")

    def arrow(self, x1, y1, x2, y2, colour=MUTED, dash=None, width=1.8):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.p.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{colour}" '
            f'stroke-width="{width}"{d} marker-end="url(#a)"/>')

    def save(self, name: str):
        self.p.insert(1, (
            '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{MUTED}"/></marker></defs>'))
        self.p.append("</svg>")
        svg = OUT / f"{name}.svg"
        svg.write_text("\n".join(self.p), encoding="utf-8")
        _png(svg)
        print(f"  {svg.name}")


def _png(svg_path: Path) -> None:
    """PNG alongside the SVG: xhtml2pdf rasterises, so the PDF needs one."""
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        drawing = svg2rlg(str(svg_path))
        renderPM.drawToFile(drawing, str(svg_path.with_suffix(".png")),
                            fmt="PNG", dpi=200)
    except Exception as exc:  # noqa: BLE001
        print(f"    (PNG skipped for {svg_path.name}: {exc})")


# ---------------------------------------------------------------------------
# 1. APOLLO-M pipeline
# ---------------------------------------------------------------------------

def fig_apollo_architecture() -> None:
    s = SVG(1180, 1080, "APOLLO-M — System Architecture",
            "Layered pipeline. Status markers reflect what the code actually runs.")

    # Legend. Both statuses get their own pill drawn exactly as the chips draw
    # them, so the key cannot drift from what the diagram actually shows.
    s.box(736, 26, 408, 62, "#fbfbfd", LINE)
    s.box(750, 38, 74, 20, "#dcf2e8", GREEN, rx=9, sw=1)
    s.text(787, 52, "RUNS", 10.5, GREEN, weight="bold", anchor="middle")
    s.text(834, 52, "invoked on every pipeline run", 11.5, MUTED)
    s.box(750, 62, 74, 20, AMBER_BG, AMBER, rx=9, sw=1)
    s.text(787, 76, "NOT WIRED", 9, AMBER, weight="bold", anchor="middle")
    s.text(834, 76, "in the repo, never called by the pipeline", 11.5, MUTED)

    x, w = 36, 1108
    y = 104

    # data sources
    s.band(x, y, w, 96, "DATA", GREY, GREY_BG)
    s.chip(x + 120, y + 12, 470, 70,
           "Reddit community structure|SNAP hyperlink graph — 35,776 nodes / 137,821 edges|"
           "subreddit names, authors, volumes", None, BLUE)
    s.chip(x + 606, y + 12, 470, 70,
           "Davidson / Jigsaw toxicity corpus|24,783 labelled texts (Twitter)|"
           "scored by unitary/toxic-bert", None, BLUE)
    y += 108
    s.box(x + 120, y, 956, 30, AMBER_BG, AMBER, rx=7, sw=1.2)
    s.text(x + 598, y + 20,
           "Declared simulation with recorded ground truth — 60 communities × 120 days, "
           "15 given a rising trend (§7.1)", 12, AMBER, weight="bold", anchor="middle")
    y += 46
    s.arrow(x + 598, y, x + 598, y + 18)
    y += 24

    # micro
    s.band(x, y, w, 92, "MICRO", BLUE, BLUE_BG)
    s.chip(x + 120, y + 14, 300, 64, "Toxicity|unitary/toxic-bert", "RUNS", BLUE)
    s.chip(x + 434, y + 14, 300, 64, "Text embeddings|BERT / RoBERTa → PCA", "RUNS", BLUE)
    s.chip(x + 748, y + 14, 328, 64, "Misinformation|TF-IDF + Logistic Regression",
           "NOT WIRED", BLUE)
    y += 104
    s.arrow(x + 598, y, x + 598, y + 18)
    y += 24

    # meso
    s.band(x, y, w, 158, "MESO", GREEN, GREEN_BG)
    s.chip(x + 120, y + 14, 300, 64, "Community Health Index|toxicity, polarisation,|"
                                     "echo-chamber, churn", "RUNS", GREEN)
    s.chip(x + 434, y + 14, 300, 64, "Instability score|recent vs baseline toxicity|"
                                     "(trend-aware)", "RUNS", GREEN)
    s.chip(x + 748, y + 14, 328, 64, "GraphSAGE GNN|community structure", "NOT WIRED", GREEN)
    s.chip(x + 120, y + 86, 614, 58, "Unsupervised — K-Means + DBSCAN over community "
                                     "features|5 clusters, outlier flags", "RUNS", GREEN)
    s.chip(x + 748, y + 86, 328, 58, "Transformer autoencoder|trained on random noise",
           "NOT WIRED", GREEN)
    y += 170
    s.arrow(x + 598, y, x + 598, y + 18)
    y += 24

    # macro
    s.band(x, y, w, 84, "MACRO", ORANGE, ORANGE_BG)
    s.chip(x + 120, y + 12, 956, 60,
           "Temporal Fusion Transformer — 5-day quantile forecast|"
           "p10 / p50 / p90 from a 14-day lookback, per community", "RUNS", ORANGE)
    y += 96
    s.arrow(x + 598, y, x + 598, y + 18)
    y += 24

    # act
    s.band(x, y, w, 84, "ACT", PURPLE, PURPLE_BG)
    s.chip(x + 120, y + 12, 460, 60,
           "Alert bands|CRITICAL / HIGH / MEDIUM / LOW from CHI", "RUNS", PURPLE)
    s.chip(x + 594, y + 12, 482, 60,
           "Recommended action|deterministic mapping from alert band|"
           "(RandomForest recommender not wired)", "RUNS", PURPLE)
    y += 96
    s.arrow(x + 598, y, x + 598, y + 18)
    y += 24

    # validation — the part the earlier figures omitted entirely
    s.box(x, y, w, 62, "#eef7f2", GREEN, rx=9, sw=1.6)
    s.text(x + 20, y + 26, "VALIDATION", 12.5, GREEN, weight="bold")
    s.text(x + 130, y + 25,
           "Against planted ground truth the pipeline never sees:  TFT predicts a rising trend for "
           "15 / 15 destabilising communities", 12.5, INK)
    s.text(x + 130, y + 44,
           "(slope ROC-AUC 0.732).  Ranking by instability score 1.000 · by CHI 0.575 · "
           "by raw toxicity 0.649.", 12.5, INK)
    y += 76

    # serving row
    for i, (tag, label, col, bg) in enumerate([
        ("STORE", "PostgreSQL — apollo schema, shared instance with CEREBRO", BLUE, BLUE_BG),
        ("SERVE", "FastAPI + JWT — reads precomputed results", GREEN, GREEN_BG),
        ("SHOW", "Streamlit + Plotly dashboard", PURPLE, PURPLE_BG),
        ("OBSERVE", "Prometheus → Grafana", ORANGE, ORANGE_BG),
    ]):
        yy = y + i * 42
        s.box(x, yy, w, 34, bg, col, rx=7, sw=1.2)
        s.text(x + 16, yy + 22, tag, 11.5, col, weight="bold")
        s.text(x + 116, yy + 22, label, 12.5, INK)

    s.save("apollo_architecture")


# ---------------------------------------------------------------------------
# 2. Request flow
# ---------------------------------------------------------------------------

def fig_apollo_request_flow() -> None:
    s = SVG(1180, 620, "APOLLO-M — Request Processing",
            "How a request is served, and where the modelling actually happens.")

    steps = [
        ("1. REQUEST", "Dashboard or client|calls the REST API", BLUE, BLUE_BG),
        ("2. AUTH", "FastAPI validates|the JWT and role", GREEN, GREEN_BG),
        ("3. ROUTE", "Dispatch to the|matching endpoint", PURPLE, PURPLE_BG),
        ("4. READ", "SELECT from PostgreSQL|(apollo schema)|no model runs here", ORANGE, ORANGE_BG),
        ("5. RESPOND", "JSON with values,|model versions|and provenance", BLUE, BLUE_BG),
    ]
    bw, gap, x0, y0 = 200, 24, 36, 110
    for i, (tag, body, col, bg) in enumerate(steps):
        x = x0 + i * (bw + gap)
        s.box(x, y0, bw, 150, bg, col, rx=10, sw=1.5)
        s.text(x + bw / 2, y0 + 28, tag, 13, col, weight="bold", anchor="middle")
        for j, ln in enumerate(body.split("|")):
            s.text(x + bw / 2, y0 + 58 + j * 19, ln, 12, INK, anchor="middle")
        if i < len(steps) - 1:
            s.arrow(x + bw + 3, y0 + 75, x + bw + gap - 3, y0 + 75)

    s.box(36, 288, 1108, 56, AMBER_BG, AMBER, rx=8, sw=1.4)
    s.text(56, 312,
           "The API performs no inference. Every score, forecast and alert is computed "
           "offline by the pipeline below and read back as a stored value,", 12.5, INK)
    s.text(56, 331,
           "so a request costs a database read rather than a model load — which is why the "
           "deployed service needs no PyTorch.", 12.5, INK)

    s.text(36, 380, "OFFLINE PIPELINE — run separately, then loaded into PostgreSQL",
           13.5, INK, weight="bold")
    chain = ["simulate_data.py", "micro — toxic-bert", "meso — CHI + instability",
             "TFT forecast", "outputs/*.csv", "db_setup.py → PostgreSQL"]
    cw, cgap, cx, cy = 172, 15, 36, 396
    for i, label in enumerate(chain):
        x = cx + i * (cw + cgap)
        s.box(x, cy, cw, 48, "#ffffff", GREY, rx=7, sw=1.2)
        s.text(x + cw / 2, cy + 29, label, 11.5, INK, anchor="middle")
        if i < len(chain) - 1:
            s.arrow(x + cw + 2, cy + 24, x + cw + cgap - 2, cy + 24)

    s.box(36, 476, 1108, 92, "#f7f8fb", LINE, rx=9)
    s.text(56, 504, "Two things this diagram deliberately does not claim:", 12.5, INK,
           weight="bold")
    s.text(56, 528,
           "•  No WebSocket. The Streamlit dashboard polls files and the database; "
           "Apollo has no push channel (CEREBRO does).", 12, MUTED)
    s.text(56, 550,
           "•  No live Reddit feed. Reddit's API is closed to the project, so the Live page "
           "replays the scored corpus client-side.", 12, MUTED)

    s.save("apollo_request_flow")


# ---------------------------------------------------------------------------
# 3. Integration
# ---------------------------------------------------------------------------

def fig_integration() -> None:
    s = SVG(1180, 760, "CEREBRO + APOLLO-M — Integration",
            "What is deployed today, and what is designed but not yet built.")

    # CEREBRO
    s.box(36, 104, 400, 400, BLUE_BG, BLUE, rx=12, sw=1.8)
    s.text(236, 136, "CEREBRO", 19, BLUE, weight="bold", anchor="middle")
    s.text(236, 158, "per-item verdicts, on demand", 12, MUTED, anchor="middle")
    for i, m in enumerate(["Email forensics", "News / claim verification (RAG)",
                           "Network anomaly detection", "URL & source reputation",
                           "Published fact-check lookup", "LLM explanation (Claude)"]):
        s.box(56, 176 + i * 48, 360, 38, "#ffffff", BLUE, rx=7, sw=1.1)
        s.text(236, 200 + i * 48, m, 12.5, INK, anchor="middle")

    # APOLLO
    s.box(744, 104, 400, 400, GREEN_BG, GREEN, rx=12, sw=1.8)
    s.text(944, 136, "APOLLO-M", 19, GREEN, weight="bold", anchor="middle")
    s.text(944, 158, "per-community forecasts, over time", 12, MUTED, anchor="middle")
    for i, m in enumerate(["Toxicity scoring (toxic-bert)", "Community Health Index",
                           "Instability score (trend)", "Clustering & outliers",
                           "TFT 5-day forecast", "Alerts & recommended actions"]):
        s.box(764, 176 + i * 48, 360, 38, "#ffffff", GREEN, rx=7, sw=1.1)
        s.text(944, 200 + i * 48, m, 12.5, INK, anchor="middle")

    # shared database — what actually connects them
    s.box(462, 150, 256, 190, "#ffffff", PURPLE, rx=12, sw=1.8)
    s.text(590, 178, "SHARED", 12.5, PURPLE, weight="bold", anchor="middle")
    s.text(590, 196, "PostgreSQL instance", 12.5, PURPLE, weight="bold", anchor="middle")
    s.text(590, 214, "one Render database", 11.5, MUTED, anchor="middle")
    s.box(482, 230, 216, 44, BLUE_BG, BLUE, rx=7, sw=1.1)
    s.text(590, 248, "cerebro schema", 12.5, INK, weight="bold", anchor="middle")
    s.text(590, 265, "20 tables", 11, MUTED, anchor="middle")
    s.box(482, 282, 216, 44, GREEN_BG, GREEN, rx=7, sw=1.1)
    s.text(590, 300, "apollo schema", 12.5, INK, weight="bold", anchor="middle")
    s.text(590, 317, "6 tables", 11, MUTED, anchor="middle")
    s.arrow(438, 240, 460, 240)
    s.arrow(742, 240, 720, 240)

    # planned exchange
    s.box(462, 362, 256, 142, "#ffffff", GREY, rx=12, dash="6,5", sw=1.6)
    s.box(546, 372, 88, 19, "#e9eaee", GREY, rx=9, sw=1)
    s.text(590, 385.5, "PLANNED", 10, GREY, weight="bold", anchor="middle")
    s.text(590, 412, "Intelligence exchange", 12.5, INK, weight="bold", anchor="middle")
    for i, ln in enumerate(["CEREBRO misinformation", "detections aggregated daily",
                            "→ TFT covariate for Apollo"]):
        s.text(590, 434 + i * 18, ln, 11.5, MUTED, anchor="middle")
    s.arrow(438, 430, 460, 430, GREY, dash="5,4")
    s.arrow(742, 430, 720, 430, GREY, dash="5,4")

    # status strip
    s.box(36, 528, 1108, 64, "#eef7f2", GREEN, rx=9, sw=1.5)
    s.text(56, 554, "DEPLOYED TODAY", 12, GREEN, weight="bold")
    s.text(196, 553,
           "One PostgreSQL instance serves both systems, schema-isolated and verified: "
           "Apollo's 6 tables loaded (60 communities,", 12.5, INK)
    s.text(196, 573,
           "60 alerts, 300 forecasts) alongside CEREBRO's 20, with CEREBRO's data untouched. "
           "Both APIs deployed on Render.", 12.5, INK)

    s.box(36, 606, 1108, 64, "#f7f8fb", GREY, rx=9, dash="6,5", sw=1.5)
    s.text(56, 632, "NOT YET BUILT", 12, GREY, weight="bold")
    s.text(196, 631,
           "Apollo does not read CEREBRO's detections and CEREBRO does not call Apollo. "
           "Sharing an instance is infrastructure integration,", 12.5, INK)
    s.text(196, 651,
           "not intelligence exchange. The next step is the covariate above: each CEREBRO "
           "verdict becomes a daily misinformation-pressure signal.", 12.5, INK)

    s.text(36, 700,
           "Design rationale: CEREBRO answers \"is this claim true?\" for one item on demand; "
           "APOLLO-M answers \"is this community", 12, MUTED)
    s.text(36, 718,
           "destabilising?\" for many communities over time. CEREBRO produces events; Apollo "
           "consumes time series. That is the join.", 12, MUTED)

    s.save("integration")


if __name__ == "__main__":
    print("writing figures to docs/figures/")
    fig_apollo_architecture()
    fig_apollo_request_flow()
    fig_integration()
    print("done")
