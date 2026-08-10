"""Explanation layer — the one place Apollo-M uses an LLM.

Deterministic models produce every number; this layer only *narrates* them. It is
provider-aware so the switch is meaningful:

  * ollama  — concise 2-3 sentence explanation (local, free, everyday)
  * claude  — a deeper analyst-grade briefing (drivers, forecast implication,
              recommended action), for the panel demo

If no LLM is reachable it falls back to a deterministic template, so the pipeline
never depends on the LLM being up.
"""

from __future__ import annotations

from typing import Any

from .provider import LLMUnavailable, get_provider

# Ollama: short and factual.
SYSTEM_OLLAMA = (
    "You are an analyst assistant for a Reddit community-health monitor. "
    "Explain the provided metrics in 2-3 plain sentences for a moderator. "
    "Do not invent numbers; only interpret what you are given."
)

# Claude: richer, structured analyst briefing (still explanation-only).
SYSTEM_CLAUDE = (
    "You are a senior analyst for Apollo-M, a system that forecasts instability in "
    "online communities. You are given metrics that were computed by deterministic "
    "models — never change or invent numbers, only interpret them. Write a concise "
    "but insightful briefing (4-6 sentences) for a moderator that: (1) states the "
    "community's current health, (2) identifies which measured factor is driving it, "
    "(3) reads the 5-day forecast and what it implies, and (4) recommends a "
    "proportionate moderation action. Be precise and calm; avoid hype."
)


def explain_community(metrics: dict[str, Any], provider_name: str | None = None) -> str:
    """Narrate one community's health metrics. Depth adapts to the provider."""
    prompt = (
        f"Community: {metrics.get('subreddit', '?')}\n"
        f"Community Health Index (0-100, higher = healthier): {metrics.get('chi')}\n"
        f"Toxicity: {metrics.get('toxicity')}\n"
        f"Polarization: {metrics.get('polarization')}\n"
        f"Alert level: {metrics.get('alert_level')}\n"
        f"5-day forecast (median toxicity, 0-1): {metrics.get('forecast_p50')}\n"
        "Explain what this means and whether moderators should act."
    )
    # Try the chosen provider, then the other one, then the template — so a real
    # briefing appears whenever ANY LLM is reachable (Ollama needs a local server;
    # Claude works via the API key).
    prefer = provider_name or "claude"
    order = [prefer] + [p for p in ("claude", "ollama") if p != prefer]
    for name in order:
        try:
            provider = get_provider(name)
            if provider.name == "claude":
                txt = provider.complete(prompt, system=SYSTEM_CLAUDE, max_tokens=800)
            else:
                txt = provider.complete(prompt, system=SYSTEM_OLLAMA, max_tokens=300)
            if name != prefer:
                txt += f"\n\n_(via {name} — {prefer} was unavailable)_"
            return txt
        except (LLMUnavailable, ValueError):
            continue
    return _template(metrics)


def _template(m: dict[str, Any]) -> str:
    """Deterministic fallback — no LLM required."""
    lvl = str(m.get("alert_level", "UNKNOWN")).upper()
    verb = {"CRITICAL": "requires immediate moderator intervention",
            "HIGH": "warrants close monitoring",
            "MEDIUM": "is worth watching",
            "LOW": "appears healthy"}.get(lvl, "has an undetermined status")
    return (f"{m.get('subreddit', 'This community')} {verb} "
            f"(CHI {m.get('chi', 'n/a')}, alert {lvl}). "
            f"[template fallback — no LLM reachable]")
