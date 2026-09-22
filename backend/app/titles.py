"""
Clip titles / hook lines.

Deterministic first: pick the most "hooky" sentence the creator actually
said (a question or exclamation, or a line with strong reaction language),
kept in the creator's own words and language -- Hinglish stays Hinglish.
If Ollama is reachable, it may suggest a punchier title, but the suggestion
must stay grounded in the transcript (it's asked not to invent events) and
it never replaces the deterministic title if it returns anything unusable.
"""
from __future__ import annotations

import json
import re

import requests

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("titles")

_SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+")
_HOOK_WORDS = (
    "no way", "what", "why", "how", "bhai", "kya", "omg", "wait", "insane", "never",
    "scary", "run", "help", "dead", "clutch", "seriously", "bro", "yaar", "arey",
)
MAX_TITLE_CHARS = 70


def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" -,;:")
    if s and s[0].isalpha() and s[0].islower():
        s = s[0].upper() + s[1:]
    return s


def heuristic_title(excerpt: str, category: str = "") -> str:
    text = (excerpt or "").strip()
    if not text:
        return (category or "Clip").replace("_", " ").title()
    sentences = [s.strip() for s in _SENT_SPLIT.split(text) if len(s.strip().split()) >= 2] or [text]

    def score(s: str) -> float:
        low = s.lower()
        sc = 0.0
        sc += 2.0 if "?" in s else 0.0
        sc += 1.5 * min(s.count("!"), 2)
        sc += sum(1.0 for w in _HOOK_WORDS if w in low)
        n = len(s.split())
        sc += 1.0 if 3 <= n <= 12 else (-1.0 if n > 20 else 0.0)
        return sc

    best = max(sentences[:12], key=score)
    best = _clean(best)
    if len(best) > MAX_TITLE_CHARS:
        cut = best[:MAX_TITLE_CHARS].rsplit(" ", 1)[0]
        best = cut.rstrip(",;:") + "..."
    return best


def llm_title(excerpt: str, content_type: str, fallback: str) -> str:
    """Ask the local LLM for a short title. Returns `fallback` on any failure."""
    prompt = (
        "You write titles for YouTube Shorts / Instagram Reels made from a creator's own video. "
        f"Video type: {content_type.replace('_', ' ')}. Write ONE short, punchy title (max 8 words) "
        "for the clip below. Rules: use only what actually happens in the transcript, don't invent "
        "events; if the creator speaks Hinglish, keep the title in Hinglish (Roman script); no hashtags, "
        'no quotes. Respond with ONLY JSON: {"title": "..."}\n\n'
        f'Transcript:\n"""{excerpt[:1500]}"""\n'
    )
    try:
        resp = requests.post(
            f"{settings.ollama_host}/api/generate",
            json={"model": settings.ollama_model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=25,
        )
        resp.raise_for_status()
        data = json.loads(resp.json().get("response", "") or "{}")
        title = _clean(str(data.get("title", "")).strip().strip('"'))
        if 2 <= len(title) <= 100:
            return title
    except Exception as exc:
        logger.info("LLM title skipped: %s", exc)
    return fallback
