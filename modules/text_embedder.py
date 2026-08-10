"""
BERT/RoBERTa text embedding engine for APOLLO-M.

Extracts sequence-level semantic embeddings from unstructured comment text
using the [CLS] token (or model-specific pooled output).
"""

from __future__ import annotations

from typing import Literal, Optional

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from tqdm import tqdm
from transformers import AutoModel, AutoTokenizer

ModelName = Literal["bert-base-uncased", "roberta-base"]


class TextEmbedder(nn.Module):
    """Switchable BERT/RoBERTa feature extractor using [CLS] representations."""

    SUPPORTED_MODELS = {
        "bert-base-uncased": "bert-base-uncased",
        "roberta-base": "roberta-base",
    }

    def __init__(
        self,
        model_name: ModelName = "bert-base-uncased",
        max_length: int = 256,
        device: Optional[str] = None,
        freeze: bool = True,
    ):
        super().__init__()
        if model_name not in self.SUPPORTED_MODELS:
            raise ValueError(
                f"Unsupported model '{model_name}'. "
                f"Choose from {list(self.SUPPORTED_MODELS)}"
            )

        self.model_name = model_name
        self.max_length = max_length
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        hf_name = self.SUPPORTED_MODELS[model_name]
        self.tokenizer = AutoTokenizer.from_pretrained(hf_name)
        self.encoder = AutoModel.from_pretrained(hf_name)

        if freeze:
            for param in self.encoder.parameters():
                param.requires_grad = False

        self.encoder.to(self.device)
        self.encoder.eval()
        self.hidden_size = self.encoder.config.hidden_size

    def _cls_embedding(
        self, input_ids: torch.Tensor, attention_mask: torch.Tensor
    ) -> torch.Tensor:
        outputs = self.encoder(input_ids=input_ids, attention_mask=attention_mask)

        if hasattr(outputs, "pooler_output") and outputs.pooler_output is not None:
            return outputs.pooler_output

        # RoBERTa and models without a pooler: use first token ([CLS] / <s>)
        return outputs.last_hidden_state[:, 0, :]

    @torch.no_grad()
    def forward(
        self, input_ids: torch.Tensor, attention_mask: torch.Tensor
    ) -> torch.Tensor:
        return self._cls_embedding(input_ids, attention_mask)

    @torch.no_grad()
    def embed_texts(
        self,
        texts: list[str],
        batch_size: int = 32,
        show_progress: bool = True,
    ) -> np.ndarray:
        """Return (N, hidden_size) CLS embeddings for a list of texts."""
        if not texts:
            return np.empty((0, self.hidden_size), dtype=np.float32)

        embeddings: list[np.ndarray] = []
        iterator = range(0, len(texts), batch_size)
        if show_progress:
            iterator = tqdm(iterator, desc=f"Embedding ({self.model_name})", unit="batch")

        for start in iterator:
            batch = texts[start : start + batch_size]
            encoded = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            batch_emb = self._cls_embedding(encoded["input_ids"], encoded["attention_mask"])
            embeddings.append(batch_emb.cpu().numpy())

        return np.vstack(embeddings).astype(np.float32)

    @torch.no_grad()
    def embed_dataframe(
        self,
        df: pd.DataFrame,
        text_col: str = "body",
        batch_size: int = 32,
        show_progress: bool = True,
    ) -> np.ndarray:
        """Extract embeddings from the text column of a DataFrame."""
        texts = df[text_col].fillna("").astype(str).tolist()
        return self.embed_texts(texts, batch_size=batch_size, show_progress=show_progress)

    def embedding_column_names(self) -> list[str]:
        return [f"embed_{i}" for i in range(self.hidden_size)]

    def attach_embeddings(
        self,
        df: pd.DataFrame,
        embeddings: np.ndarray,
        prefix: str = "embed_",
    ) -> pd.DataFrame:
        """Attach embedding vectors as columns to a DataFrame copy."""
        result = df.copy()
        for i in range(embeddings.shape[1]):
            result[f"{prefix}{i}"] = embeddings[:, i]
        return result
