"""
Temporal Fusion Transformer forecaster for APOLLO-M macro-layer forecasting.

Uses pytorch-forecasting's native TFT with QuantileLoss for prediction intervals.
Text embeddings from BERT/RoBERTa are injected as continuous time-varying covariates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import lightning.pytorch as pl
import numpy as np
import pandas as pd
import torch
from pytorch_forecasting import TemporalFusionTransformer, TimeSeriesDataSet
from pytorch_forecasting.data import NaNLabelEncoder
from pytorch_forecasting.metrics import QuantileLoss
from sklearn.decomposition import PCA

log = logging.getLogger("APOLLO-M")

FORECAST_QUANTILES = [0.1, 0.5, 0.9]


@dataclass
class TFTConfig:
    lookback_window: int = 14
    forecast_horizon: int = 5
    batch_size: int = 32
    learning_rate: float = 1e-3
    hidden_size: int = 32
    attention_head_size: int = 2
    dropout: float = 0.2
    hidden_continuous_size: int = 16
    max_epochs: int = 15
    embed_pca_components: int = 32
    model_dir: Path = field(default_factory=lambda: Path("models"))
    quantiles: list[float] = field(default_factory=lambda: FORECAST_QUANTILES.copy())


class TFTForecaster:
    """PyTorch Lightning training pipeline for Temporal Fusion Transformer."""

    def __init__(self, config: Optional[TFTConfig] = None):
        self.config = config or TFTConfig()
        self.model: Optional[TemporalFusionTransformer] = None
        self.training_dataset: Optional[TimeSeriesDataSet] = None
        self.pca: Optional[PCA] = None
        self.embedding_cols: list[str] = []
        self.raw_embedding_cols: list[str] = []

    def prepare_dataframe(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        """Normalize columns for TimeSeriesDataSet consumption."""
        df = daily_df.copy()
        df["subreddit"] = df["subreddit"].astype(str).apply(
            lambda x: x if x.startswith("r/") else f"r/{x}"
        )
        df["group_id"] = df["subreddit"]
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["subreddit", "date"]).reset_index(drop=True)
        df["time_idx"] = df.groupby("subreddit").cumcount()

        for col, default in [("avg_toxicity", 0.5), ("toxic_rate", 0.4)]:
            if col not in df.columns:
                df[col] = default
            df[col] = df[col].fillna(default).clip(0, 1)

        if "comment_count" not in df.columns:
            df["comment_count"] = 1
        df["comment_count"] = df["comment_count"].fillna(1).clip(lower=1)

        return df

    def _resolve_embedding_columns(self, df: pd.DataFrame) -> list[str]:
        return sorted(
            [col for col in df.columns if col.startswith("embed_")],
            key=lambda name: int(name.split("_", 1)[1]),
        )

    def fit_embedding_pca(self, df: pd.DataFrame) -> pd.DataFrame:
        """Reduce high-dimensional text embeddings for TFT covariate injection."""
        self.raw_embedding_cols = self._resolve_embedding_columns(df)
        if not self.raw_embedding_cols:
            self.embedding_cols = []
            return df

        matrix = df[self.raw_embedding_cols].fillna(0.0).values
        n_components = min(
            self.config.embed_pca_components,
            matrix.shape[0],
            matrix.shape[1],
        )
        if n_components < 1:
            self.embedding_cols = []
            return df

        self.pca = PCA(n_components=n_components, random_state=42)
        reduced = self.pca.fit_transform(matrix)
        self.embedding_cols = [f"emb_pca_{i}" for i in range(n_components)]
        for idx, col in enumerate(self.embedding_cols):
            df[col] = reduced[:, idx]

        explained = self.pca.explained_variance_ratio_.sum()
        log.info(
            "PCA reduced %d-dim embeddings → %d TFT covariates (%.1f%% variance)",
            len(self.raw_embedding_cols),
            n_components,
            explained * 100,
        )
        return df

    def transform_embeddings(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply fitted PCA to new data."""
        if self.pca is None or not self.raw_embedding_cols:
            return df

        available = [col for col in self.raw_embedding_cols if col in df.columns]
        if not available:
            return df

        matrix = df[available].fillna(0.0).values
        reduced = self.pca.transform(matrix)
        for idx, col in enumerate(self.embedding_cols):
            df[col] = reduced[:, idx]
        return df

    def _trained_subreddit_labels(self) -> set:
        """Subreddit labels known to the fitted TimeSeriesDataSet encoders."""
        encoders = getattr(self.training_dataset, "_categorical_encoders", {})
        for key in ("__group_id__subreddit", "subreddit"):
            encoder = encoders.get(key)
            if encoder is None or not hasattr(encoder, "classes_"):
                continue
            labels = set(encoder.classes_.keys())
            labels.discard("nan")
            labels.discard(np.nan)
            return labels
        return set()

    def _snapshot_training_state(self) -> dict:
        """Preserve TFT artifacts so holdout evaluation cannot clobber production state."""
        return {
            "model": self.model,
            "training_dataset": self.training_dataset,
            "pca": self.pca,
            "embedding_cols": list(self.embedding_cols),
            "raw_embedding_cols": list(self.raw_embedding_cols),
        }

    def _restore_training_state(self, snapshot: dict) -> None:
        self.model = snapshot["model"]
        self.training_dataset = snapshot["training_dataset"]
        self.pca = snapshot["pca"]
        self.embedding_cols = snapshot["embedding_cols"]
        self.raw_embedding_cols = snapshot["raw_embedding_cols"]

    def _forecast_subreddit_candidates(
        self, df: pd.DataFrame, trained_subs: set, preferred: str | None = None
    ) -> list[str]:
        min_required = self.config.lookback_window + self.config.forecast_horizon
        counts = df.groupby("subreddit").size()
        eligible = counts[counts >= min_required].sort_values(ascending=False)
        if trained_subs:
            eligible = eligible[eligible.index.isin(trained_subs)]

        candidates = eligible.index.astype(str).tolist()
        if preferred and preferred in candidates:
            return [preferred] + [s for s in candidates if s != preferred]
        return candidates

    def build_dataset(self, df: pd.DataFrame, for_training: bool = True) -> TimeSeriesDataSet:
        """Create a TimeSeriesDataSet with subreddit as the entity identifier."""
        max_pred = self.config.forecast_horizon
        max_encoder = self.config.lookback_window

        min_required = max_encoder + max_pred
        group_sizes = df.groupby("subreddit").size()
        valid_groups = group_sizes[group_sizes >= min_required].index.tolist()

        if not valid_groups:
            raise ValueError(
                f"No subreddit has >= {min_required} daily observations "
                f"(need {max_encoder} encoder + {max_pred} prediction steps)."
            )

        working = df[df["subreddit"].isin(valid_groups)].copy()
        if for_training:
            cutoff = working["time_idx"].max() - max_pred
            working = working[working["time_idx"] <= cutoff]

        time_varying_unknown = ["avg_toxicity", "toxic_rate", "comment_count"]
        time_varying_unknown.extend(self.embedding_cols)

        self.training_dataset = TimeSeriesDataSet(
            working,
            time_idx="time_idx",
            target="avg_toxicity",
            group_ids=["subreddit"],
            max_encoder_length=max_encoder,
            max_prediction_length=max_pred,
            time_varying_unknown_reals=time_varying_unknown,
            time_varying_known_reals=["time_idx"],
            static_categoricals=["subreddit"],
            categorical_encoders={"subreddit": NaNLabelEncoder(add_nan=True)},
            allow_missing_timesteps=True,
        )
        return self.training_dataset

    def train(self, daily_df: pd.DataFrame) -> None:
        """Train TFT via PyTorch Lightning."""
        df = self.prepare_dataframe(daily_df)
        df = self.fit_embedding_pca(df)
        dataset = self.build_dataset(df, for_training=True)

        train_loader = dataset.to_dataloader(
            train=True,
            batch_size=self.config.batch_size,
            num_workers=0,
        )

        quantile_loss = QuantileLoss(quantiles=self.config.quantiles)
        self.model = TemporalFusionTransformer.from_dataset(
            dataset,
            learning_rate=self.config.learning_rate,
            hidden_size=self.config.hidden_size,
            attention_head_size=self.config.attention_head_size,
            dropout=self.config.dropout,
            hidden_continuous_size=self.config.hidden_continuous_size,
            loss=quantile_loss,
            log_interval=10,
        )

        trainer = pl.Trainer(
            max_epochs=self.config.max_epochs,
            accelerator="auto",
            enable_progress_bar=True,
            enable_model_summary=False,
            logger=False,
        )
        trainer.fit(self.model, train_dataloaders=train_loader)

        self.config.model_dir.mkdir(parents=True, exist_ok=True)
        torch.save(self.model.state_dict(), self.config.model_dir / "tft_model.pt")
        log.info("TFT trained and saved → %s", self.config.model_dir / "tft_model.pt")

    def predict_quantiles(
        self, daily_df: pd.DataFrame, subreddit: str | None = None
    ) -> dict:
        """
        Generate multi-quantile forecasts.

        Returns dict with keys: quantiles, forecast (horizon x n_quantiles),
        p10, p50, p90 arrays of length forecast_horizon, and subreddit.
        """
        if self.model is None or self.training_dataset is None:
            raise RuntimeError("TFT model not trained. Call train() first.")

        df = self.prepare_dataframe(daily_df)
        df = self.transform_embeddings(df)

        trained_subs = self._trained_subreddit_labels()
        if trained_subs:
            df = df[df["subreddit"].isin(trained_subs)].copy()
        if df.empty:
            return {}

        candidates = self._forecast_subreddit_candidates(df, trained_subs, subreddit)
        for forecast_sub in candidates:
            sub_df = df[df["subreddit"] == forecast_sub].copy()
            try:
                pred_dataset = TimeSeriesDataSet.from_dataset(
                    self.training_dataset,
                    sub_df,
                    predict=True,
                    stop_randomization=True,
                )
            except AssertionError as exc:
                log.warning("TFT prediction window unavailable for %s: %s", forecast_sub, exc)
                continue

            pred_loader = pred_dataset.to_dataloader(
                train=False,
                batch_size=self.config.batch_size,
                num_workers=0,
            )

            # mode="quantiles" returns the full p10/p50/p90 spread — the whole
            # point of a TFT with QuantileLoss. mode="prediction" (the old call)
            # returned only the median, so the bands collapsed to a single value.
            raw_preds = self.model.predict(pred_loader, mode="quantiles", return_x=False)
            preds = raw_preds.detach().cpu().numpy()

            # Expected shape: [n_samples, horizon, n_quantiles]. We forecast one
            # group per call, so take the last sample; tolerate a squeezed 2-D
            # [horizon, n_quantiles] batch of one.
            if preds.ndim == 3:
                forecast = preds[-1]
            elif preds.ndim == 2:
                forecast = preds
            else:  # 1-D fallback — single-step, tile across quantiles
                forecast = preds.reshape(-1, 1).repeat(len(self.config.quantiles), axis=1)

            forecast = forecast[: self.config.forecast_horizon, :]
            forecast = np.clip(forecast, 0.0, 1.0)
            # Enforce p10 <= p50 <= p90 per day (quantile crossing guard).
            forecast = np.sort(forecast, axis=1)

            q_idx = {q: i for i, q in enumerate(self.config.quantiles)}
            log.info("TFT forecast generated for %s", forecast_sub)
            return {
                "quantiles": self.config.quantiles,
                "forecast": forecast,
                "p10": forecast[:, q_idx.get(0.1, 0)],
                "p50": forecast[:, q_idx.get(0.5, 1)],
                "p90": forecast[:, q_idx.get(0.9, 2)],
                "subreddit": forecast_sub,
            }

        return {}

    def evaluate(self, daily_df: pd.DataFrame, holdout_days: Optional[int] = None) -> dict:
        """Holdout evaluation using pinball loss on the median quantile."""
        if self.model is None or self.training_dataset is None:
            return {"mae": None, "pinball_loss": None, "n_holdout": 0}

        holdout = holdout_days or self.config.forecast_horizon
        min_len = self.config.lookback_window + holdout
        df = self.prepare_dataframe(daily_df)
        snapshot = self._snapshot_training_state()

        eligible = [
            (sub, group.sort_values("date"))
            for sub, group in df.groupby("subreddit")
            if len(group) >= min_len
        ]
        skipped = df["subreddit"].nunique() - len(eligible)
        if skipped:
            log.info(
                "Holdout eval: skipping %d subreddits with <%d daily points",
                skipped,
                min_len,
            )

        metrics = {"mae": None, "pinball_loss": None, "n_holdout": 0}
        try:
            for subreddit, group in eligible:
                train_part = group.iloc[:-holdout]
                test_part = group.iloc[-holdout:]

                try:
                    self.train(train_part)
                    result = self.predict_quantiles(group, subreddit=subreddit)
                    if not result:
                        continue
                    predicted = result["p50"][: len(test_part)]
                    actual = test_part["avg_toxicity"].values[: len(predicted)]

                    metrics["mae"] = float(np.mean(np.abs(predicted - actual)))
                    metrics["pinball_loss"] = float(
                        np.mean(
                            np.maximum(
                                0.5 * (actual - predicted),
                                0.5 * (predicted - actual),
                            )
                        )
                    )
                    metrics["n_holdout"] = len(actual)
                    metrics["subreddit"] = subreddit
                    log.info(
                        "TFT holdout eval [%s]: MAE=%.4f, pinball=%.4f",
                        subreddit,
                        metrics["mae"],
                        metrics["pinball_loss"],
                    )
                    break
                except (ValueError, RuntimeError, AssertionError, AttributeError) as exc:
                    log.warning("Holdout eval failed for %s: %s", subreddit, exc)
                    continue
        finally:
            self._restore_training_state(snapshot)

        return metrics

    def save_forecast_csv(
        self,
        forecast: dict,
        subreddit: str,
        start_date: pd.Timestamp,
        output_path: Path,
    ) -> pd.DataFrame:
        """Write multi-quantile forecast results to CSV."""
        horizon = len(forecast["p50"])
        dates = pd.date_range(start=start_date + pd.Timedelta(days=1), periods=horizon, freq="D")

        rows = []
        for day_idx in range(horizon):
            p50 = forecast["p50"][day_idx]
            rows.append(
                {
                    "day": day_idx + 1,
                    "date": dates[day_idx].strftime("%Y-%m-%d"),
                    "predicted_toxicity": round(float(p50), 4),
                    "p10": round(float(forecast["p10"][day_idx]), 4),
                    "p50": round(float(p50), 4),
                    "p90": round(float(forecast["p90"][day_idx]), 4),
                    "interval_width": round(
                        float(forecast["p90"][day_idx] - forecast["p10"][day_idx]), 4
                    ),
                    "risk_level": (
                        "CRITICAL"
                        if p50 > 0.8
                        else "HIGH"
                        if p50 > 0.6
                        else "MEDIUM"
                        if p50 > 0.4
                        else "LOW"
                    ),
                    "method": "TFT",
                    "subreddit": subreddit,
                }
            )

        result_df = pd.DataFrame(rows)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result_df.to_csv(output_path, index=False)
        log.info("Forecast saved (TFT quantiles) → %s", output_path)
        return result_df