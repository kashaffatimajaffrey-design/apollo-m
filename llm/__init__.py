"""Apollo-M LLM layer — provider-switchable text generation.

The rest of the pipeline (toxicity, misinfo, CHI, GNN, TFT) is deterministic and
does NOT depend on an LLM. This layer is the *explanation* surface only: it turns
already-computed numbers (a forecast, a CHI score, an alert) into plain-English
narration. Same rule as CEREBRO: models decide, the LLM only explains.

Two providers, one interface, switch via the LLM_PROVIDER env var:
  * ollama  — local, free, what the team develops against (default)
  * claude  — Anthropic API, for the panel demo (key added later)
"""

import os as _os
from pathlib import Path as _Path


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from the project .env into the environment (once),
    without overriding anything already set. Keeps secrets out of code."""
    env = _Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            _os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

from .provider import LLMProvider, OllamaProvider, ClaudeProvider, get_provider

__all__ = ["LLMProvider", "OllamaProvider", "ClaudeProvider", "get_provider"]
