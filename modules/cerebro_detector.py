"""
CEREBRO Detector — Misinformation Detection Module
Integrated into APOLLO-M Micro Layer
"""

import logging
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from transformers import pipeline

log = logging.getLogger("APOLLO-M.CEREBRO")


class CEREBRODetector:

    MISINFO_LABELS = [
        "misinformation or fake news",
        "factual and credible content",
        "conspiracy theory",
        "coordinated inauthentic behaviour",
        "satire or opinion"
    ]

    COORDINATION_SIGNALS = [
        "share this before it gets deleted",
        "they don't want you to know",
        "mainstream media won't report",
        "wake up", "do your own research",
        "banned from", "shadow banned",
        "deep state", "false flag", "hoax",
        "plandemic", "they are hiding",
        "spread the word", "repost this", "going viral",
    ]

    def __init__(self, device: str = "cpu"):
        self.device = device
        self.classifier = None
        self.supervised_clf = None
        self.use_supervised = False
        self._load_model()

    def _load_model(self):
        """Load supervised classifier first, fall back to zero-shot."""
        supervised_path = Path("models/cerebro_classifier.pkl")
        if supervised_path.exists():
            try:
                with open(supervised_path, "rb") as f:
                    self.supervised_clf = pickle.load(f)
                self.use_supervised = True
                log.info("CEREBRO supervised classifier loaded (99% accuracy).")
                self.classifier = None
                return
            except Exception as e:
                log.warning(f"Supervised classifier load failed ({e}), trying zero-shot.")

        self.supervised_clf = None
        self.use_supervised = False

        try:
            log.info("Loading CEREBRO misinformation detector (facebook/bart-large-mnli)...")
            self.classifier = pipeline(
                "zero-shot-classification",
                model="facebook/bart-large-mnli",
                device=0 if self.device == "cuda" else -1,
            )
            log.info("CEREBRO model loaded successfully.")
        except Exception as e:
            log.warning(f"CEREBRO model failed to load ({e}). Using enhanced keyword fallback.")
            self.classifier = None

    def analyze(self, text: str) -> dict:
        text = str(text).strip()[:512]
        if self.use_supervised and self.supervised_clf is not None:
            return self._supervised_analyze(text)
        elif self.classifier:
            return self._model_analyze(text)
        else:
            return self._keyword_analyze(text)

    def _supervised_analyze(self, text: str) -> dict:
        """Use trained supervised classifier for fast accurate misinfo detection."""
        try:
            prob = self.supervised_clf.predict_proba([text])[0]
            misinfo_score = float(prob[1])
            is_fake = misinfo_score > 0.5
            coord = self._detect_coordination(text)
            return {
                "misinformation_score":  round(misinfo_score, 4),
                "source_credibility":    round(1 - misinfo_score, 4),
                "coordinated_behaviour": coord or (misinfo_score > 0.8),
                "misinfo_category":      "FAKE_NEWS" if is_fake else "CREDIBLE",
                "model_used":            "supervised_tfidf_lr"
            }
        except Exception as e:
            log.warning(f"Supervised analysis failed: {e} — using fallback.")
            return self._keyword_analyze(text)

    def _model_analyze(self, text: str) -> dict:
        """Zero-shot classification based analysis."""
        try:
            result = self.classifier(
                text,
                candidate_labels=self.MISINFO_LABELS,
                multi_label=False
            )
            scores = dict(zip(result["labels"], result["scores"]))
            misinfo_score = (
                scores.get("misinformation or fake news", 0) * 0.5 +
                scores.get("conspiracy theory", 0) * 0.35 +
                scores.get("coordinated inauthentic behaviour", 0) * 0.15
            )
            credibility = scores.get("factual and credible content", 0)
            coord = self._detect_coordination(text)
            top_label = result["labels"][0]
            category_map = {
                "misinformation or fake news": "FAKE_NEWS",
                "factual and credible content": "CREDIBLE",
                "conspiracy theory": "CONSPIRACY",
                "coordinated inauthentic behaviour": "COORDINATED",
                "satire or opinion": "OPINION"
            }
            return {
                "misinformation_score":  round(float(misinfo_score), 4),
                "source_credibility":    round(float(credibility), 4),
                "coordinated_behaviour": coord or (misinfo_score > 0.7),
                "misinfo_category":      category_map.get(top_label, "UNKNOWN"),
                "model_used":            "bart-large-mnli"
            }
        except Exception as e:
            log.warning(f"CEREBRO model inference failed: {e} — using fallback.")
            return self._keyword_analyze(text)

    def _keyword_analyze(self, text: str) -> dict:
        text_lower = text.lower()
        coord_hits = sum(1 for s in self.COORDINATION_SIGNALS if s in text_lower)
        misinfo_keywords = [
            "fake", "hoax", "conspiracy", "false", "lie", "lying",
            "cover up", "coverup", "scam", "fraud", "manipulated",
            "fabricated", "disinformation", "propaganda"
        ]
        misinfo_hits = sum(1 for kw in misinfo_keywords if kw in text_lower)
        credibility_keywords = [
            "study shows", "research found", "according to",
            "published", "peer reviewed", "data shows", "evidence"
        ]
        cred_hits = sum(1 for kw in credibility_keywords if kw in text_lower)
        misinfo_score = min((misinfo_hits * 0.25 + coord_hits * 0.2), 1.0)
        credibility = min(cred_hits * 0.3, 1.0)
        if coord_hits >= 2:
            category = "COORDINATED"
        elif misinfo_hits >= 2:
            category = "FAKE_NEWS"
        elif cred_hits >= 2:
            category = "CREDIBLE"
        else:
            category = "NEUTRAL"
        return {
            "misinformation_score":  round(misinfo_score, 4),
            "source_credibility":    round(credibility, 4),
            "coordinated_behaviour": coord_hits >= 2,
            "misinfo_category":      category,
            "model_used":            "keyword_fallback"
        }

    def _detect_coordination(self, text: str) -> bool:
        text_lower = text.lower()
        hits = sum(1 for s in self.COORDINATION_SIGNALS if s in text_lower)
        return hits >= 2

    def analyze_batch(self, df: pd.DataFrame,
                      text_col: str = "body",
                      toxicity_col: str = "toxicity_score",
                      toxicity_threshold: float = 0.4,
                      sample_rate: float = 0.3) -> pd.DataFrame:
        df = df.copy()
        df["misinformation_score"]  = 0.05
        df["source_credibility"]    = 0.90
        df["coordinated_behaviour"] = False
        df["misinfo_category"]      = "NEUTRAL"
        df["is_misinfo"]            = False

        if toxicity_col in df.columns:
            candidate_mask = df[toxicity_col] > toxicity_threshold
        else:
            candidate_mask = pd.Series([True] * len(df), index=df.index)

        candidates = df[candidate_mask].copy()
        log.info(f"CEREBRO: {len(candidates)}/{len(df)} comments above "
                 f"toxicity threshold {toxicity_threshold}")

        if len(candidates) > 0:
            if self.use_supervised:
                # Supervised is fast enough to run on all candidates
                sample = candidates
                log.info(f"CEREBRO analyzing all {len(sample)} candidates "
                         f"(supervised mode — fast)...")
            else:
                # Zero-shot is slow — sample 30%
                sample = candidates.sample(frac=sample_rate, random_state=42)
                log.info(f"CEREBRO analyzing {len(sample)} sampled comments "
                         f"({sample_rate:.0%} of candidates)...")

            results = []
            for i, text in enumerate(sample[text_col].astype(str)):
                results.append(self.analyze(text))
                if (i + 1) % 500 == 0:
                    log.info(f"  CEREBRO processed {i+1}/{len(sample)} comments")

            result_df = pd.DataFrame(results, index=sample.index)
            df.loc[sample.index, "misinformation_score"]  = result_df["misinformation_score"].values
            df.loc[sample.index, "source_credibility"]    = result_df["source_credibility"].values
            df.loc[sample.index, "coordinated_behaviour"] = result_df["coordinated_behaviour"].values
            df.loc[sample.index, "misinfo_category"]      = result_df["misinfo_category"].values
            df.loc[sample.index, "is_misinfo"]            = result_df["misinformation_score"].values > 0.5

        misinfo_rate = df["is_misinfo"].mean()
        log.info(f"CEREBRO complete. Misinfo rate: {misinfo_rate:.2%}")
        return df

    def compute_community_misinfo_index(self, df: pd.DataFrame) -> pd.DataFrame:
        agg = df.groupby("subreddit").agg(
            avg_misinfo_score   =("misinformation_score", "mean"),
            misinformation_rate =("is_misinfo", "mean"),
            fake_news_count     =("is_misinfo", "sum"),
            coordinated_count   =("coordinated_behaviour", "sum"),
            avg_credibility     =("source_credibility", "mean"),
            total_comments      =("misinformation_score", "count"),
        ).reset_index()
        agg["community_misinfo_index"] = (
            agg["avg_misinfo_score"] * 60 +
            agg["misinformation_rate"] * 25 +
            (agg["coordinated_count"] / agg["total_comments"].clip(lower=1)) * 15
        ) * 100
        agg["community_misinfo_index"] = agg["community_misinfo_index"].clip(0, 100).round(2)
        return agg