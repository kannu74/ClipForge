"""
Caption + hashtag suggestions for posting a clip (Reels / Shorts / TikTok).

Deterministic first, grounded in what the creator actually said: caption
drafts reuse the clip's own hook line, and topical hashtags come from the
words spoken in the clip plus its category and the video's content type.
If Ollama is reachable the caller may ask for an AI-written set as well; it
is told not to invent events, and any unusable answer falls back to the
deterministic set. Nothing here leaves the machine.

Hashtags are suggestions, not a promise of reach: Instagram itself
recommends only a handful of relevant tags, so the list is ranked and the UI
pre-selects the first few.
"""
from __future__ import annotations

import json
import re
from collections import Counter

import requests

from app.config import settings
from app.logging_config import get_logger
from app.titles import heuristic_title

logger = get_logger("social")

BROAD_TAGS = ["reels", "shorts", "viral", "fyp", "trending"]

CONTENT_TAGS = {
    "gaming": ["gaming", "gamer", "gameplay", "gamingclips"],
    "funny_gaming": ["funnygaming", "gamingmemes", "gamingfails", "gaming"],
    "horror_gaming": ["horrorgaming", "horrorgame", "jumpscare", "scary", "gaming"],
    "reaction": ["reaction", "reactionvideo", "reacts"],
    "comedy": ["comedy", "funny", "funnyvideos", "memes"],
    "commentary": ["commentary", "opinion", "hottake"],
    "review": ["review", "gamereview", "seriesreview", "worthit"],
    "storytelling": ["storytime", "story", "storytelling"],
    "general_creator": ["creator", "contentcreator"],
}
CATEGORY_TAGS = {
    "funny": ["funny", "lol", "comedy"],
    "scare": ["scary", "jumpscare", "horror"],
    "rage": ["rage", "ragequit", "angry"],
    "clutch": ["clutch", "insane", "gamingmoments"],
    "fail": ["fail", "epicfail", "funnyfails"],
    "surprise": ["unexpected", "shocking", "omg"],
    "reaction": ["reaction", "reacts"],
    "story": ["storytime", "story"],
    "verdict": ["review", "verdict", "worthit"],
    "insight": ["explained", "didyouknow", "facts"],
}
# Hinglish markers: if a clip's speech has several of these, tag it for the
# Hindi-speaking audience.
HINGLISH_MARKERS = {
    "bhai", "yaar", "kya", "hai", "nahi", "nahin", "toh", "ye", "yeh", "abhi", "matlab",
    "bahut", "accha", "arey", "kyun", "mera", "tera", "hain", "raha", "gaya", "chal",
}
STOPWORDS = set(
    """a an the and or but if so to of in on at for with from by is are was were be been am i you he she it we they
    me my your his her our their this that these those there here what when where who why how do does did done not no
    yes just like really very can could will would should have has had get got going gonna out up down over then than
    too also as into about all some any one two more most much many well oh okay ok yeah hey um uh
    hai hain ho tha thi the ka ki ke ko se me mein main par pe aur ya ye yeh wo woh toh bhi hi na nahi nahin kya kyun
    tum aap hum mera tera meri teri mere tere ek do isko usko abhi ab jab tab phir fir raha rahi rahe gaya gayi gaye
    kar kiya karo karna wala wali wale liye lekin bas bohot bahut sab kuch yaar bhai""".split()
)


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z']{2,}", text.lower())


def _slug(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def _is_hinglish(words: list[str]) -> bool:
    return sum(1 for w in words if w in HINGLISH_MARKERS) >= 3


def hashtags(excerpt: str, title: str, category: str, content_type: str, limit: int = 12) -> list[dict]:
    """Ranked hashtags: [{"tag": "#horrorgaming", "kind": "niche|topic|language|broad"}]."""
    words = _words(f"{title} {excerpt}")
    out: list[dict] = []
    seen: set[str] = set()

    def add(tag: str, kind: str) -> None:
        t = _slug(tag)
        if len(t) < 3 or t in seen:
            return
        seen.add(t)
        out.append({"tag": "#" + t, "kind": kind})

    for t in CONTENT_TAGS.get(content_type, []):
        add(t, "niche")
    for t in CATEGORY_TAGS.get(category, []):
        add(t, "niche")
    # Topical: the most-repeated meaningful words the creator actually said.
    counts = Counter(w for w in words if w not in STOPWORDS and len(w) >= 4)
    for w, n in counts.most_common(6):
        if n >= 2 or len(counts) <= 6:
            add(w, "topic")
    if _is_hinglish(words):
        add("hinglish", "language")
        add("indiangamer" if "gaming" in content_type else "desi", "language")
    for t in BROAD_TAGS:
        add(t, "broad")
    return out[:limit]


def caption_drafts(excerpt: str, title: str, category: str) -> list[dict]:
    """A few caption options in the creator's own words."""
    hook = (title or "").strip() or heuristic_title(excerpt, category)
    bare = hook.rstrip(".!? ")
    first = re.split(r"(?<=[.!?।])\s+", excerpt.strip())[0] if excerpt and excerpt.strip() else ""
    drafts = [{"style": "Hook", "text": hook}]
    if first and first.lower().strip(" .!?") != bare.lower():
        short = first if len(first) <= 90 else first[:90].rsplit(" ", 1)[0] + "..."
        drafts.append({"style": "Opening line", "text": short})
    drafts.append({"style": "Question", "text": f"{bare}? Comment what you would have done 👇"})
    drafts.append({"style": "Short", "text": f"{bare} 👀"})
    return drafts


def suggest(excerpt: str, title: str, category: str, content_type: str) -> dict:
    return {
        "source": "local-rules",
        "captions": caption_drafts(excerpt, title, category),
        "hashtags": hashtags(excerpt, title, category, content_type),
    }


def suggest_with_llm(excerpt: str, title: str, category: str, content_type: str) -> dict:
    """Same shape as `suggest`, written by the local model. Falls back to the
    deterministic set when Ollama is unreachable or answers with junk."""
    base = suggest(excerpt, title, category, content_type)
    prompt = (
        "You write Instagram Reels captions for a creator's own clip. "
        f"Video type: {content_type.replace('_', ' ')}. Category: {category}. "
        "Write 3 different captions (each max 140 characters, a scroll-stopping first line, "
        "at most one emoji) and 8 relevant hashtags (lowercase, no spaces). Rules: use only what "
        "actually happens in the transcript, don't invent events; if the creator speaks Hinglish, "
        "write in Hinglish (Roman script), never translate it to English. "
        'Respond with ONLY JSON: {"captions": ["..."], "hashtags": ["..."]}\n\n'
        f'Clip title: {title}\nTranscript:\n"""{excerpt[:1500]}"""\n'
    )
    try:
        resp = requests.post(
            f"{settings.ollama_host}/api/generate",
            json={"model": settings.ollama_model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=40,
        )
        resp.raise_for_status()
        data = json.loads(resp.json().get("response", "") or "{}")
        caps = [str(c).strip() for c in data.get("captions", []) if 5 <= len(str(c).strip()) <= 300][:3]
        if not caps:
            return {**base, "note": "The local AI didn't return usable captions, so these are rule-based."}
        tags: list[dict] = []
        for t in data.get("hashtags", []):
            slug = "#" + _slug(str(t))
            if len(slug) > 3 and slug not in {x["tag"] for x in tags}:
                tags.append({"tag": slug, "kind": "ai"})
        tag_names = {x["tag"] for x in tags[:8]}
        broad = [h for h in base["hashtags"] if h["kind"] == "broad" and h["tag"] not in tag_names]
        return {
            "source": f"ollama:{settings.ollama_model}",
            "captions": [{"style": "AI", "text": c} for c in caps] + base["captions"][:1],
            "hashtags": (tags[:8] + broad)[:12] or base["hashtags"],
        }
    except Exception as exc:
        logger.info("LLM caption suggestions skipped: %s", exc)
        return {
            **base,
            "note": "Couldn't reach the local AI (is Ollama running?), so these are rule-based suggestions.",
        }
