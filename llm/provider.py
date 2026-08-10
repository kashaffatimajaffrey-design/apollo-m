"""Provider-switchable LLM access for Apollo-M.

`get_provider()` reads `LLM_PROVIDER` (ollama | claude) and returns a provider
exposing one method, `complete(prompt, system=...) -> str`. Nothing else in the
codebase needs to know which backend is live — swap the env var and every caller
follows. Both providers degrade gracefully: if the backend isn't reachable they
raise `LLMUnavailable` with a clear message rather than crashing the pipeline.

  LLM_PROVIDER=ollama   OLLAMA_MODEL=llama3.1   OLLAMA_HOST=http://localhost:11434
  LLM_PROVIDER=claude   ANTHROPIC_API_KEY=sk-... CLAUDE_MODEL=claude-opus-5
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class LLMUnavailable(RuntimeError):
    """The configured LLM backend could not be reached or is not installed."""


class LLMProvider(ABC):
    """One method: turn a prompt into text. Deterministic callers stay unaware
    of which concrete provider is behind this."""

    name: str = "base"

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None,
                 max_tokens: int = 512) -> str:
        ...

    def available(self) -> bool:
        """Best-effort reachability check; never raises."""
        try:
            self.complete("ping", max_tokens=1)
            return True
        except Exception:
            return False


class OllamaProvider(LLMProvider):
    """Local Ollama over HTTP (http://localhost:11434). Free, offline, the
    team's day-to-day backend. No SDK — just the REST API via requests."""

    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.1")
        self.host = (host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")

    def complete(self, prompt: str, system: str | None = None,
                 max_tokens: int = 512) -> str:
        import requests

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if system:
            payload["system"] = system
        try:
            resp = requests.post(f"{self.host}/api/generate", json=payload, timeout=120)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise LLMUnavailable(
                f"Ollama not reachable at {self.host} ({exc.__class__.__name__}). "
                "Is `ollama serve` running and the model pulled?"
            ) from exc
        return resp.json().get("response", "").strip()


class ClaudeProvider(LLMProvider):
    """Anthropic Claude via the official SDK — the panel-demo backend.

    Imported lazily so the module loads even before `anthropic` is installed or a
    key is set (key arrives later). Default model: claude-opus-5.
    """

    name = "claude"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or os.getenv("CLAUDE_MODEL", "claude-opus-5")
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

    def complete(self, prompt: str, system: str | None = None,
                 max_tokens: int = 512) -> str:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - env dependent
            raise LLMUnavailable(
                "Claude provider needs the `anthropic` package: pip install anthropic"
            ) from exc
        if not self.api_key:
            raise LLMUnavailable(
                "ANTHROPIC_API_KEY is not set — add it to switch to the Claude provider."
            )
        client = anthropic.Anthropic(api_key=self.api_key)
        try:
            msg = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system or "You explain threat-intelligence results plainly.",
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # noqa: BLE001 - surface any API error uniformly
            raise LLMUnavailable(f"Claude API call failed: {exc}") from exc
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()


def get_provider(name: str | None = None) -> LLMProvider:
    """Return the configured provider. `name` overrides `LLM_PROVIDER` (default ollama)."""
    choice = (name or os.getenv("LLM_PROVIDER", "ollama")).lower()
    if choice == "ollama":
        return OllamaProvider()
    if choice == "claude":
        return ClaudeProvider()
    raise ValueError(f"unknown LLM_PROVIDER {choice!r} (use 'ollama' or 'claude')")
