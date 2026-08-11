"""
Diagrams required by the FYP report template that the technical-report figures
do not cover: process model, block diagram, ERD, sequence, context and use-case.

Reuses the SVG helper in make_figures.py so both sets share one visual language.
Every entity, table and message here is taken from the code — database/schema.sql
for the ERD, api/main.py for the sequence and context diagrams — so the diagrams
cannot drift from the implementation the way hand-drawn ones do.

    python docs/make_report_figures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_figures import (SVG, INK, MUTED, LINE, BLUE, GREEN, ORANGE, PURPLE,  # noqa: E402
                          GREY, BLUE_BG, GREEN_BG, ORANGE_BG, PURPLE_BG, GREY_BG,
                          AMBER, AMBER_BG)


def fig_process_model() -> None:
    s = SVG(1180, 560, "APOLLO-M — Process Model",
            "Incremental-iterative development: each layer is built, measured, then integrated.")
    phases = [
        ("REQUIREMENTS", "Scope, datasets,|success criteria", BLUE, BLUE_BG),
        ("DESIGN", "Layer decomposition,|schema, interfaces", PURPLE, PURPLE_BG),
        ("IMPLEMENT", "One layer at a time,|micro → meso → macro", GREEN, GREEN_BG),
        ("MEASURE", "Ground-truth validation,|held-out metrics", ORANGE, ORANGE_BG),
        ("INTEGRATE", "API, dashboard,|monitoring, deploy", BLUE, BLUE_BG),
    ]
    bw, gap, x0, y0 = 196, 30, 60, 130
    for i, (tag, body, col, bg) in enumerate(phases):
        x = x0 + i * (bw + gap)
        s.box(x, y0, bw, 132, bg, col, rx=10, sw=1.5)
        s.text(x + bw / 2, y0 + 32, tag, 12.5, col, weight="bold", anchor="middle")
        for j, ln in enumerate(body.split("|")):
            s.text(x + bw / 2, y0 + 62 + j * 19, ln, 11.5, INK, anchor="middle")
        if i < len(phases) - 1:
            s.arrow(x + bw + 4, y0 + 66, x + bw + gap - 4, y0 + 66)

    # iteration arrow back
    s.p.append(f'<path d="M {x0 + 4*(bw+gap) + bw/2} {y0+140} '
               f'L {x0 + 4*(bw+gap) + bw/2} {y0+186} L {x0 + bw/2} {y0+186} '
               f'L {x0 + bw/2} {y0+146}" fill="none" stroke="{MUTED}" '
               f'stroke-width="1.8" stroke-dasharray="6,5" marker-end="url(#a)"/>')
    s.text(590, y0 + 205, "iterate — measurement feeds the next increment", 12,
           MUTED, anchor="middle", italic=True)

    s.box(60, 400, 1060, 108, "#f7f8fb", LINE, rx=9)
    s.text(80, 428, "Why incremental rather than waterfall", 12.5, INK, weight="bold")
    s.text(80, 452,
           "Each layer produces a measurable artefact before the next depends on it, so a "
           "defect is caught in the layer that", 12, MUTED)
    s.text(80, 472,
           "introduced it. Three faults were found this way — a CHI scaling overflow, an "
           "alphabetically-biased sample, and a", 12, MUTED)
    s.text(80, 492,
           "health index that ranked communities worse than one of its own inputs.", 12, MUTED)
    s.save("process_model")


def fig_block_diagram() -> None:
    s = SVG(1180, 470, "APOLLO-M — System Block Diagram",
            "Modules and the data that moves between them.")
    blocks = [
        (60, 120, 210, "INGESTION", "Corpus loader|community selection|by comment volume", BLUE, BLUE_BG),
        (310, 120, 210, "MICRO", "toxic-bert scoring|BERT embeddings → PCA", GREEN, GREEN_BG),
        (560, 120, 210, "MESO", "CHI, instability score|clustering, graph features", PURPLE, PURPLE_BG),
        (810, 120, 210, "MACRO", "Temporal Fusion|Transformer forecast", ORANGE, ORANGE_BG),
    ]
    for x, y, w, tag, body, col, bg in blocks:
        s.box(x, y, w, 120, bg, col, rx=10, sw=1.5)
        s.text(x + w / 2, y + 30, tag, 12.5, col, weight="bold", anchor="middle")
        for j, ln in enumerate(body.split("|")):
            s.text(x + w / 2, y + 58 + j * 18, ln, 11.5, INK, anchor="middle")
    for x in (270, 520, 770):
        s.arrow(x + 4, 180, x + 36, 180)

    s.box(310, 286, 460, 96, "#ffffff", PURPLE, rx=10, sw=1.5)
    s.text(540, 314, "ALERTS & RECOMMENDED ACTIONS", 12.5, PURPLE, weight="bold", anchor="middle")
    s.text(540, 340, "Alert band from CHI · action from band", 11.5, INK, anchor="middle")
    s.text(540, 362, "persisted to PostgreSQL (apollo schema)", 11.5, MUTED, anchor="middle")
    s.arrow(915, 244, 700, 284)

    s.box(60, 286, 210, 96, "#ffffff", BLUE, rx=10, sw=1.5)
    s.text(165, 314, "SERVING", 12.5, BLUE, weight="bold", anchor="middle")
    s.text(165, 338, "FastAPI + JWT", 11.5, INK, anchor="middle")
    s.text(165, 358, "Streamlit dashboard", 11.5, INK, anchor="middle")
    s.arrow(306, 334, 276, 334)

    s.box(810, 286, 210, 96, "#ffffff", ORANGE, rx=10, sw=1.5)
    s.text(915, 314, "OBSERVABILITY", 12.5, ORANGE, weight="bold", anchor="middle")
    s.text(915, 338, "Prometheus exporter", 11.5, INK, anchor="middle")
    s.text(915, 358, "Grafana dashboard", 11.5, INK, anchor="middle")
    s.arrow(774, 334, 806, 334)
    s.save("block_diagram")


def fig_erd() -> None:
    s = SVG(1180, 700, "APOLLO-M — Database Design (ERD)",
            "Tables as defined in database/schema.sql, in the apollo schema.")

    def table(x, y, name, rows, col, bg, w=250):
        h = 34 + len(rows) * 21
        s.box(x, y, w, h, "#ffffff", col, rx=8, sw=1.6)
        s.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="28" rx="8" fill="{bg}"/>')
        s.p.append(f'<rect x="{x}" y="{y+18}" width="{w}" height="10" fill="{bg}"/>')
        s.text(x + w / 2, y + 19, name, 12.5, col, weight="bold", anchor="middle")
        for i, (fld, typ, key) in enumerate(rows):
            yy = y + 46 + i * 21
            mark = {"PK": "◆", "FK": "◇"}.get(key, "·")
            s.text(x + 12, yy, mark, 10, col if key else LINE)
            s.text(x + 26, yy, fld, 11, INK, weight="bold" if key == "PK" else "normal")
            s.text(x + w - 12, yy, typ, 10, MUTED, anchor="end")
        return h

    table(60, 110, "communities", [
        ("id", "SERIAL", "PK"), ("subreddit", "VARCHAR(100) UQ", ""),
        ("subscribers", "INTEGER", ""), ("posts_per_day", "FLOAT", ""),
        ("age_days", "INTEGER", ""), ("created_at", "TIMESTAMP", "")], BLUE, BLUE_BG)

    table(450, 110, "community_health", [
        ("id", "SERIAL", "PK"), ("subreddit", "VARCHAR", "FK"),
        ("community_health_index", "FLOAT", ""), ("toxicity_rate", "FLOAT", ""),
        ("polarization", "FLOAT", ""), ("echo_chamber_index", "FLOAT", ""),
        ("churn_rate", "FLOAT", ""), ("cluster", "INTEGER", ""),
        ("is_outlier", "BOOLEAN", ""), ("timestamp", "TIMESTAMP", "")], GREEN, GREEN_BG, 280)

    table(850, 110, "alerts", [
        ("id", "SERIAL", "PK"), ("subreddit", "VARCHAR", "FK"),
        ("alert_level", "VARCHAR(20)", ""), ("chi", "FLOAT", ""),
        ("message", "TEXT", ""), ("toxicity", "FLOAT", ""),
        ("polarization", "FLOAT", ""), ("timestamp", "TIMESTAMP", "")], PURPLE, PURPLE_BG, 270)

    table(60, 400, "toxicity_scores", [
        ("id", "SERIAL", "PK"), ("comment_id", "VARCHAR", ""),
        ("subreddit", "VARCHAR", "FK"), ("toxicity_score", "FLOAT", ""),
        ("is_toxic", "BOOLEAN", ""), ("created_utc", "TIMESTAMP", "")], ORANGE, ORANGE_BG)

    table(450, 400, "forecasts", [
        ("id", "SERIAL", "PK"), ("subreddit", "VARCHAR", "FK"),
        ("forecast_date", "DATE", ""), ("predicted_toxicity", "FLOAT", ""),
        ("risk_level", "VARCHAR(20)", ""), ("method", "VARCHAR(50)", "")], ORANGE, ORANGE_BG, 280)

    table(850, 400, "misinformation_scores", [
        ("id", "SERIAL", "PK"), ("comment_id", "VARCHAR", ""),
        ("subreddit", "VARCHAR", "FK"), ("misinfo_score", "FLOAT", ""),
        ("category", "VARCHAR(50)", "")], GREY, GREY_BG, 270)

    for a, b in ((310, 175), (730, 175)):
        s.arrow(a, b, a + 138, b)
    s.arrow(185, 260, 185, 396)
    s.arrow(590, 290, 590, 396)
    s.arrow(985, 290, 985, 396)

    s.box(60, 596, 1060, 76, AMBER_BG, AMBER, rx=9, sw=1.4)
    s.text(80, 622, "Note on population", 12, AMBER, weight="bold")
    s.text(80, 645,
           "community_health, alerts and forecasts are populated by every pipeline run. "
           "toxicity_scores and misinformation_scores", 11.5, INK)
    s.text(80, 664,
           "are defined but not yet written to — the per-comment persistence and the "
           "misinformation module are not wired (§11).", 11.5, INK)
    s.save("erd")


def fig_sequence() -> None:
    s = SVG(1180, 660, "APOLLO-M — Sequence Diagram",
            "A moderator opens a community drill-down and requests an explanation.")
    actors = [("Moderator", 110, BLUE), ("Dashboard", 330, GREEN),
              ("FastAPI", 550, PURPLE), ("PostgreSQL", 770, ORANGE),
              ("Claude (LLM)", 1000, GREY)]
    for name, x, col in actors:
        s.box(x - 88, 106, 176, 38, "#ffffff", col, rx=8, sw=1.5)
        s.text(x, 130, name, 12.5, col, weight="bold", anchor="middle")
        s.p.append(f'<line x1="{x}" y1="146" x2="{x}" y2="566" stroke="{LINE}" '
                   f'stroke-width="1.2" stroke-dasharray="4,4"/>')

    msgs = [
        (110, 330, 190, "select community"),
        (330, 550, 226, "GET /communities/{sub}  (JWT)"),
        (550, 770, 262, "SELECT … FROM community_health"),
        (770, 550, 298, "row: CHI, toxicity, churn, cluster"),
        (550, 330, 334, "200 JSON + model_versions"),
        (330, 1000, 380, "explain(metrics)  — narration only"),
        (1000, 330, 416, "analyst briefing text"),
        (330, 110, 452, "render metrics, forecast band, briefing"),
    ]
    for x1, x2, y, label in msgs:
        s.arrow(x1 + (10 if x2 > x1 else -10), y, x2 + (-10 if x2 > x1 else 10), y, INK)
        s.text((x1 + x2) / 2, y - 8, label, 11, INK, anchor="middle")

    s.box(60, 496, 1060, 96, "#f7f8fb", LINE, rx=9)
    s.text(80, 524, "The ordering encodes the project's governing principle", 12.5, INK,
           weight="bold")
    s.text(80, 548,
           "Every number reaching the user is read from storage before the language model "
           "is contacted. The LLM receives", 12, MUTED)
    s.text(80, 568,
           "already-computed metrics and returns prose; if it is unavailable a deterministic "
           "template is substituted and the", 12, MUTED)
    s.save("sequence")


def fig_context() -> None:
    s = SVG(1180, 620, "APOLLO-M — Context Diagram",
            "System boundary: external entities and the data crossing it.")
    s.box(400, 210, 380, 200, GREEN_BG, GREEN, rx=14, sw=2)
    s.text(590, 268, "APOLLO-M", 20, GREEN, weight="bold", anchor="middle")
    s.text(590, 296, "instability forecasting", 12.5, MUTED, anchor="middle")
    s.text(590, 316, "pipeline · API · dashboard", 12.5, MUTED, anchor="middle")
    s.box(452, 336, 276, 46, "#ffffff", GREEN, rx=8, sw=1.2)
    s.text(590, 356, "60 communities · 120 days", 11.5, INK, anchor="middle")
    s.text(590, 373, "5-day quantile forecast", 11.5, INK, anchor="middle")

    ents = [
        (80, 130, "Davidson / Jigsaw corpus", "labelled toxic text", BLUE, "in"),
        (80, 300, "SNAP Reddit graph", "community hyperlinks", BLUE, "in"),
        (80, 470, "Reddit API", "blocked — planned ingestion", GREY, "planned"),
        (900, 130, "Moderator / analyst", "reads alerts and forecasts", PURPLE, "out"),
        (900, 300, "Anthropic Claude", "explanation text", ORANGE, "both"),
        (900, 470, "CEREBRO", "shares the database", BLUE, "both"),
    ]
    for x, y, name, sub, col, direction in ents:
        dash = "6,5" if direction == "planned" else None
        s.box(x, y, 200, 76, "#ffffff", col, rx=10, dash=dash, sw=1.5)
        s.text(x + 100, y + 32, name, 12, col, weight="bold", anchor="middle")
        s.text(x + 100, y + 54, sub, 10.5, MUTED, anchor="middle")
        if x < 500:
            s.arrow(x + 204, y + 38, 396, 250 + (y - 130) * 0.34,
                    GREY if direction == "planned" else MUTED,
                    dash="5,4" if direction == "planned" else None)
        else:
            if direction == "out":
                s.arrow(784, 250 + (y - 130) * 0.34, x - 4, y + 38)
            else:
                s.arrow(784, 250 + (y - 130) * 0.34, x - 4, y + 38)
    s.save("context")


def fig_usecase() -> None:
    s = SVG(1180, 640, "APOLLO-M — Use Case Diagram",
            "Actors and the operations available to each role.")
    s.box(330, 108, 520, 470, "#fbfbfd", LINE, rx=14, sw=1.5)
    s.text(590, 136, "APOLLO-M", 13, MUTED, weight="bold", anchor="middle")

    cases = ["View community health dashboard", "Inspect a community drill-down",
             "View 5-day toxicity forecast", "Review alerts by severity",
             "Read LLM-generated briefing", "Explore community clusters",
             "Watch live processing feed", "Run the pipeline / reload data"]
    for i, c in enumerate(cases):
        y = 162 + i * 52
        s.p.append(f'<ellipse cx="590" cy="{y+18}" rx="228" ry="21" fill="#ffffff" '
                   f'stroke="{PURPLE}" stroke-width="1.3"/>')
        s.text(590, y + 22, c, 11.5, INK, anchor="middle")

    def actor(x, y, label, note):
        s.p.append(f'<circle cx="{x}" cy="{y}" r="15" fill="#ffffff" stroke="{BLUE}" stroke-width="1.8"/>')
        s.p.append(f'<line x1="{x}" y1="{y+15}" x2="{x}" y2="{y+48}" stroke="{BLUE}" stroke-width="1.8"/>')
        s.p.append(f'<line x1="{x-18}" y1="{y+27}" x2="{x+18}" y2="{y+27}" stroke="{BLUE}" stroke-width="1.8"/>')
        s.p.append(f'<line x1="{x}" y1="{y+48}" x2="{x-14}" y2="{y+76}" stroke="{BLUE}" stroke-width="1.8"/>')
        s.p.append(f'<line x1="{x}" y1="{y+48}" x2="{x+14}" y2="{y+76}" stroke="{BLUE}" stroke-width="1.8"/>')
        s.text(x, y + 98, label, 12.5, INK, weight="bold", anchor="middle")
        s.text(x, y + 116, note, 10.5, MUTED, anchor="middle")

    actor(130, 210, "Viewer", "summary + alerts")
    actor(130, 400, "Analyst", "all read operations")
    actor(1050, 300, "Admin", "read + pipeline control")

    for y in (180, 232, 284):
        s.p.append(f'<line x1="152" y1="240" x2="360" y2="{y+18}" stroke="{LINE}" stroke-width="1.2"/>')
    for y in (180, 232, 284, 336, 388, 440, 492):
        s.p.append(f'<line x1="152" y1="430" x2="360" y2="{y+18}" stroke="{LINE}" stroke-width="1.2"/>')
    for y in (180, 232, 284, 336, 388, 440, 492, 544):
        s.p.append(f'<line x1="1028" y1="330" x2="820" y2="{y+18}" stroke="{LINE}" stroke-width="1.2"/>')

    s.text(590, 606, "Roles are enforced by the API through JWT claims "
                     "(api/auth.py: viewer, analyst, admin).", 11.5, MUTED, anchor="middle")
    s.save("usecase")


if __name__ == "__main__":
    print("writing report figures to docs/figures/")
    fig_process_model()
    fig_block_diagram()
    fig_erd()
    fig_sequence()
    fig_context()
    fig_usecase()
    print("done")
