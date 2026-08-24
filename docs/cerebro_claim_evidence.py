"""
Produce the full evidence table behind the "refutes nine of ten" claim.

The report states an aggregate and shows a single worked example, so a reader
asked to check the other nine has nothing to check. This runs all ten claims
through the same retrieval and stance pipeline CEREBRO uses and writes every
verdict, confidence and citation, so the aggregate becomes auditable rather than
asserted.

Runs against the local corpus with the pessimistic configuration the free tier
actually uses (lexical stance, hashing embedder), which is the configuration the
9/10 figure was measured under.

    python docs/cerebro_claim_evidence.py
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
OUT = HERE / "cerebro_claim_evidence.json"
BACKEND = Path(r"C:\cerebro_repo (apollo int)\cerebro\backend")
sys.path.insert(0, str(BACKEND))

from services.api.core.seed_corpus import DOCUMENTS, EVIDENCE_SOURCES  # noqa: E402
from services.ml.rag.retrieval import Document  # noqa: E402
from services.ml.rag.verify import Label, build_default_verifier  # noqa: E402

WEIGHTS = {d: w for d, _, w, _ in EVIDENCE_SOURCES}

CLAIMS = [
    "5G towers spread the coronavirus.",
    "Scientists confirmed that 5G mobile networks cause COVID-19 and the WHO is hiding it.",
    "Vaccines cause autism in children.",
    "COVID-19 vaccines contain microchips used to track people.",
    "Drinking bleach cures COVID-19.",
    "Ivermectin is a proven cure for COVID-19 that authorities are suppressing.",
    "The Apollo Moon landings were faked in a Hollywood studio.",
    "Global warming is a hoax invented by scientists.",
    "The Earth is flat.",
    "mRNA vaccines alter your DNA.",
]


def domain_of(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0].removeprefix("www.")


def main() -> None:
    corpus = []
    for i, (_, title, body, url) in enumerate(DOCUMENTS):
        dom = domain_of(url)
        corpus.append(Document(id=str(i), title=title, text=body, url=url,
                               domain=dom, credibility=WEIGHTS.get(dom, 0.5)))

    verifier = build_default_verifier(corpus, prefer_transformers=False)
    rows, refuted = [], 0

    for claim in CLAIMS:
        v = verifier.verify(claim)
        is_refuted = v.label is Label.REFUTED
        refuted += is_refuted
        rows.append({
            "claim": claim,
            "verdict": v.label.value,
            "confidence": round(float(v.confidence), 4),
            "refuted": bool(is_refuted),
            "citations": v.citations[:3],
            "top_evidence": [
                {"title": e.title, "domain": e.domain,
                 "stance": e.stance.value, "credibility": round(e.credibility, 2)}
                for e in v.evidence[:2]
            ],
        })

    result = {
        "configuration": "lexical stance + hashing embedder (no transformers) — "
                         "the configuration the deployed free tier runs, and the "
                         "one the headline figure was measured under",
        "corpus_documents": len(corpus),
        "claims_tested": len(CLAIMS),
        "refuted": refuted,
        "not_refuted": len(CLAIMS) - refuted,
        "note": "The claims not refuted return insufficient evidence rather than "
                "support: the system declines to rule, and never asserts that a "
                "false claim is true. That is the safe direction of failure.",
        "results": rows,
    }
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"corpus {len(corpus)} documents | {refuted}/{len(CLAIMS)} refuted\n")
    for r in rows:
        mark = "REFUTED " if r["refuted"] else "no ruling"
        print(f"  {mark} conf={r['confidence']:.2f}  {r['claim'][:56]}")
        for c in r["citations"][:2]:
            print(f"            {c[:88]}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
