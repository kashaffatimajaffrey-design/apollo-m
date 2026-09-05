#!/usr/bin/env python3
"""
Render docs/paper/paper.html to docs/paper/paper.pdf with headless Chromium
(via Playwright), then stamp the PDF metadata.

    pip install playwright pymupdf && playwright install chromium
    python docs/paper/build_pdf.py

Chromium embeds every font it uses, so the output passes arXiv's
embedded-font check; page numbers come from the footer template.
"""
from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
SRC = HERE / "paper.html"
OUT = HERE / "paper.pdf"
TITLE = "A Known-Answer Audit for Deployed Measurement Systems: Procedure and a Case Study"
AUTHOR = "Kashaf Fatima"

FOOTER = (
    '<div style="width:100%;font-family:\'Liberation Serif\',serif;font-size:8.5pt;'
    'color:#444;text-align:center;">'
    '<span class="pageNumber"></span> / <span class="totalPages"></span></div>'
)

with sync_playwright() as p:
    exe = os.environ.get("PAPER_CHROMIUM")  # optional path to a Chromium binary
    browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    page = browser.new_page()
    page.goto(SRC.resolve().as_uri(), wait_until="networkidle")
    page.pdf(
        path=str(OUT),
        format="A4",
        print_background=True,
        display_header_footer=True,
        header_template="<div></div>",
        footer_template=FOOTER,
        margin={"top": "22mm", "bottom": "24mm", "left": "20mm", "right": "20mm"},
        prefer_css_page_size=False,
    )
    browser.close()

try:
    import pymupdf

    doc = pymupdf.open(OUT)
    doc.set_metadata({"title": TITLE, "author": AUTHOR, "subject": "Measurement audit of a community-health index",
                      "keywords": "measurement validity; algorithmic auditing; community health; toxicity",
                      "creator": "docs/paper/build_pdf.py", "producer": "Chromium (Playwright)"})
    doc.save(str(OUT), incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
    print(f"wrote {OUT.relative_to(HERE.parents[1])}: {doc.page_count} pages, metadata set")
except ImportError:
    print(f"wrote {OUT.relative_to(HERE.parents[1])} (install pymupdf to stamp metadata)")
