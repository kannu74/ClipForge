"""
Thin client for local LLM reasoning via Ollama. Model is configurable
(app/config.py) -- never hard-coded. Every call is wrapped so a failure
(Ollama not running, model not pulled, timeout) degrades gracefully rather
than breaking the pipeline: moment detection works with deterministic
signals alone and simply skips LLM enrichment when this is unreachable.
"""
from __future__ import annotations

import json

import requests

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("llm")


class OllamaClient:
    def __init__(self, host: str | None = None, model: str | None = None):
        self.host = host or settings.ollama_host
        self.model = model or settings.ollama_model

    def is_reachable(self) -> bool:
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def enrich_moment(self, transcript_excerpt: str, content_type: str, category_guess: str) -> dict | None:
        """Ask the local model to sanity-check a candidate moment. Returns
        None on any failure (unreachable, bad JSON, timeout) -- callers must
        treat that as "no enrichment available", not an error."""
        prompt = (
            f"You are a short-form video editor evaluating a candidate clip from a "
            f"{content_type.replace('_', ' ')} video. A deterministic signal detector guessed the "
            f"category '{category_guess}'. Read the transcript excerpt and respond with ONLY compact "
            f"JSON, no other text: "
            f'{{"category": "one of funny|scare|rage|clutch|fail|surprise|reaction|story", '
            f'"score_adjustment": <integer from -2 to 2, how much to boost or lower this candidate>, '
            f'"reason": "<one short sentence explaining why this would or would not make a good clip>"}}\n\n'
            f'Transcript excerpt:\n"""{transcript_excerpt}"""\n'
        )
        try:
            resp = requests.post(
                f"{self.host}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
                timeout=30,
            )
            resp.raise_for_status()
            text = resp.json().get("response", "")
            data = json.loads(text)
            if "category" not in data or "reason" not in data:
                return None
            return data
        except Exception as exc:
            logger.info("Ollama enrichment skipped: %s", exc)
            return None
