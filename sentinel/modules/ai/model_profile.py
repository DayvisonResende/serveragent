"""Ajustes por família de modelo (parâmetros recomendados, raciocínio, limpeza do texto)."""

from __future__ import annotations

import re
from typing import Any

# Parâmetros recomendados pelo fabricante, quando diferem do padrão.
MODEL_OPTIONS: dict[str, dict[str, Any]] = {
    "lfm3": {"temperature": 0.1, "top_k": 50, "repeat_penalty": 1.1},  # docs.liquid.ai/lfm/models/lfm3-1.7b
}


def options_for(model: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    low = model.lower()
    base = next((opts for key, opts in MODEL_OPTIONS.items() if key in low), {})
    return {**base, **(extra or {})}


def think_flag(model: str) -> bool | None:
    """Qwen3 e LFM3 "pensam" por padrão — lento em CPU; desligado dá respostas diretas."""
    low = model.lower()
    return False if ("qwen3" in low or "lfm3" in low) else None


def strip_thinking(text: str | None) -> str:
    """Remove <think>…</think> e a tag de fechamento solta relatada com o GGUF do LFM3."""
    cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>")[-1]
    return cleaned.strip()
