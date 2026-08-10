"""Render APOLLO_Technical_Report.md -> a clean, styled PDF."""
import io
from pathlib import Path

import markdown
from xhtml2pdf import pisa

HERE = Path(__file__).resolve().parent
SRC = HERE / "APOLLO_Technical_Report.md"
OUT = HERE / "APOLLO_Technical_Report.pdf"

# PDF core fonts (Helvetica) can't draw these glyphs -> replace with ASCII.
SUB = {
    "→": "->", "×": "x", "≈": "~", "·": " - ", "—": " - ", "–": "-",
    "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...",
    "✅": "[DONE] ", "❌": "[PENDING] ", "⏳": "[PENDING] ",
    "🔴": "LIVE ", "🪐": "", "👍": "", "→": "->",
}


def sanitize(t: str) -> str:
    for k, v in SUB.items():
        t = t.replace(k, v)
    return t.encode("latin-1", "ignore").decode("latin-1")


CSS = """
@page { size: a4; margin: 1.7cm 1.6cm; }
body { font-family: Helvetica; font-size: 10pt; color: #222222; line-height: 1.4; }
h1 { font-size: 21pt; color: #4c1d95; margin: 0 0 3pt 0; }
h1 + p { color: #6d28d9; font-size: 11pt; }
h2 { font-size: 13.5pt; color: #5b21b6; border-bottom: 1.2px solid #ddd6fe;
     padding-bottom: 3pt; margin: 16pt 0 6pt 0; }
h3 { font-size: 11pt; color: #111111; margin: 10pt 0 3pt 0; }
p, li { font-size: 10pt; }
strong { color: #111111; }
table { width: 100%; border-collapse: collapse; margin: 6pt 0; }
th { background-color: #4c1d95; color: #ffffff; text-align: left; padding: 4pt 6pt; font-size: 9pt; }
td { border: 0.75px solid #e5e7eb; padding: 4pt 6pt; font-size: 9pt; }
blockquote { color: #5b21b6; font-style: italic; border-left: 3px solid #a78bfa;
             padding-left: 8pt; margin-left: 0; }
hr { border: 0; border-top: 1px solid #dddddd; margin: 10pt 0; }
code { background-color: #f3f4f6; font-family: Courier; font-size: 8.5pt; }
"""

md = sanitize(SRC.read_text(encoding="utf-8"))
body = markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists"])
html = f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"

with open(OUT, "wb") as f:
    result = pisa.CreatePDF(src=html, dest=f, encoding="utf-8")

print("PDF error" if result.err else f"OK -> {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
