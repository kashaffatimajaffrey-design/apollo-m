"""Verify the Claude API key works — minimal call, prints no secrets."""
import os
from pathlib import Path

import anthropic

# Load ANTHROPIC_API_KEY / CLAUDE_MODEL from .env if not already in the environment.
env = Path(__file__).resolve().parents[1] / ".env"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

model = os.getenv("CLAUDE_MODEL", "claude-opus-5")
client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
msg = client.messages.create(
    model=model, max_tokens=16,
    messages=[{"role": "user", "content": "Reply with only the word: online"}],
)
reply = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
print(f"CLAUDE OK — model={model} — reply={reply!r} — tokens_out={msg.usage.output_tokens}")
