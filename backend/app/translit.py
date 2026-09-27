"""
Devanagari -> casual Roman Hinglish, for creators who want captions in the
way their audience actually types ("bhai ye kya ho raha hai"), even when
Whisper wrote the Hindi parts in Devanagari.

This is transliteration, never translation: the words stay Hindi, only the
script changes. Three layers, most-specific first:
  1. a dictionary of very common words with their conventional spellings
     (hai, hain, nahi, kya, mein, main, bhai, accha, theek, ...)
  2. rule-based letter mapping with Hindi schwa deletion (so "करना" becomes
     "karna", not "karanaa")
  3. anything that isn't Devanagari (English words, numbers, emoji) passes
     through untouched -- mixed Hinglish lines keep their English as-is.
"""
from __future__ import annotations

import re

COMMON = {
    "है": "hai", "हैं": "hain", "में": "mein", "मैं": "main", "नहीं": "nahi", "नही": "nahi",
    "क्या": "kya", "यह": "yeh", "वह": "woh", "ये": "ye", "वो": "wo", "भाई": "bhai",
    "हाँ": "haan", "हां": "haan", "तो": "toh", "भी": "bhi", "था": "tha", "थी": "thi",
    "थे": "the", "और": "aur", "कि": "ki", "की": "ki", "के": "ke", "का": "ka", "को": "ko",
    "से": "se", "पर": "par", "हम": "hum", "तुम": "tum", "आप": "aap", "मुझे": "mujhe",
    "तुझे": "tujhe", "यार": "yaar", "अरे": "arey", "अच्छा": "accha", "ठीक": "theek",
    "बहुत": "bahut", "कुछ": "kuch", "सब": "sab", "अब": "ab", "जब": "jab", "कब": "kab",
    "क्यों": "kyun", "क्यूँ": "kyun", "कैसे": "kaise", "कहाँ": "kahan", "कहां": "kahan",
    "चलो": "chalo", "देखो": "dekho", "रहा": "raha", "रही": "rahi", "रहे": "rahe",
    "गया": "gaya", "गई": "gayi", "गए": "gaye", "हो": "ho", "हूँ": "hoon", "हूं": "hoon",
    "एक": "ek", "दो": "do", "बस": "bas", "फिर": "phir", "मत": "mat", "ना": "na", "न": "na",
    "वाला": "wala", "वाली": "wali", "वाले": "wale", "लिए": "liye", "लिये": "liye",
    "मेरा": "mera", "मेरी": "meri", "मेरे": "mere", "तेरा": "tera", "तेरी": "teri",
    "उसने": "usne", "इसको": "isko", "उसको": "usko", "इधर": "idhar", "उधर": "udhar",
    "ऐसा": "aisa", "वैसा": "waisa", "कैसा": "kaisa", "जैसे": "jaise", "अभी": "abhi",
    "कभी": "kabhi", "सही": "sahi", "गलत": "galat", "पता": "pata", "चल": "chal",
    "मार": "maar", "मारो": "maaro", "भागो": "bhaago", "डर": "darr", "भूत": "bhoot",
    "पागल": "paagal", "बेटा": "beta", "ओए": "oye", "अबे": "abe", "साला": "saala",
    "लेकिन": "lekin", "मतलब": "matlab", "बिल्कुल": "bilkul", "सच": "sach", "मज़ा": "mazaa",
    "मजा": "mazaa", "दिमाग": "dimaag", "ज़्यादा": "zyada", "ज्यादा": "zyada",
}

CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "ळ": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "rh", "फ़": "f", "य़": "y",
}
NUKTA_FORMS = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "d", "ढ": "rh", "फ": "f", "य": "y"}
VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e",
}
MATRAS = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e",
}
VIRAMA = "्"
NUKTA = "़"
ANUSVARA = "ं"
CHANDRABINDU = "ँ"
VISARGA = "ः"
DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
DANDA = {"।": ".", "॥": "."}

DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
TOKEN_RE = re.compile(r"([ऀ-ॿ]+)")


def has_devanagari(text: str) -> bool:
    return bool(DEVANAGARI_RE.search(text or ""))


def _word(word: str) -> str:
    if word in COMMON:
        return COMMON[word]
    # tokens: [consonant_roman, vowel_roman, vowel_is_inherent]
    toks: list[list] = []
    i = 0
    n = len(word)
    while i < n:
        ch = word[i]
        nxt = word[i + 1] if i + 1 < n else ""
        if ch in CONS:
            cons = CONS[ch]
            if nxt == NUKTA:
                cons = NUKTA_FORMS.get(ch, cons)
                i += 1
                nxt = word[i + 1] if i + 1 < n else ""
            if nxt == VIRAMA:
                toks.append([cons, "", False])
                i += 2
                continue
            if nxt in MATRAS:
                toks.append([cons, MATRAS[nxt], False])
                i += 2
                continue
            toks.append([cons, "a", True])
            i += 1
            continue
        if ch in VOWELS:
            toks.append(["", VOWELS[ch], False])
            i += 1
            continue
        if ch in (ANUSVARA, CHANDRABINDU):
            if toks:
                # nasal before a labial sounds like m (संभव -> sambhav)
                after = word[i + 1] if i + 1 < n else ""
                toks[-1][1] += "m" if after in ("प", "फ", "ब", "भ", "म") else "n"
            i += 1
            continue
        if ch == VISARGA:
            if toks:
                toks[-1][1] += "h"
            i += 1
            continue
        if ch in DIGITS:
            toks.append([DIGITS[ch], "", False])
            i += 1
            continue
        if ch in DANDA:
            toks.append([DANDA[ch], "", False])
            i += 1
            continue
        i += 1  # unknown sign: drop

    m = len(toks)
    # Schwa deletion. Word-final inherent 'a' is silent in Hindi (kam, not kama)...
    if m > 1 and toks[-1][2] and toks[-1][1] == "a":
        toks[-1][1] = ""
    # ...and so is a medial one between two vowel-bearing syllables
    # (samajhna, not samajhana). Scan right-to-left, never deleting two in a row.
    j = m - 2
    while j >= 1:
        cur, prev, nxt = toks[j], toks[j - 1], toks[j + 1]
        if cur[2] and cur[1] == "a" and prev[1] and nxt[1] and nxt[0]:
            cur[1] = ""
            j -= 2
            continue
        j -= 1

    out = []
    for k, (c, v, _inh) in enumerate(toks):
        closed = k + 1 < m and toks[k + 1][1] == "" and toks[k + 1][0] != ""
        final = k == m - 1
        if not c:
            # independent vowel (आ, ई ...): keep its full length -- "aaya", "aa"
            out.append(v)
            continue
        if v.startswith("aa") and (final or not closed):
            v = "a" + v[2:]
        elif v.startswith("ee") and (final or not closed):
            v = "i" + v[2:]
        elif v.startswith("oo") and final:
            v = "u" + v[2:]
        out.append(c + v)
    return "".join(out)


def to_roman(text: str) -> str:
    """Transliterate every Devanagari run in `text`; leave everything else."""
    if not has_devanagari(text):
        return text
    return TOKEN_RE.sub(lambda m: _word(m.group(1)), text)


# --- Roman Hinglish spelling clean-up -------------------------------------
# Whisper spells Roman Hinglish inconsistently ("nahin", "nhi", "kyaa"). This
# maps the common variants onto one casual spelling so captions look uniform.
# Still the same words -- only the spelling is unified, never translated.
SPELLING_VARIANTS = {
    "nahin": "nahi", "nhi": "nahi", "nahi": "nahi",
    "kyaa": "kya", "kyon": "kyun", "kyu": "kyun", "kyoon": "kyun",
    "yeh": "ye", "ya": "ye", "woh": "wo", "vo": "wo",
    "acha": "accha", "achha": "accha", "achcha": "accha", "acchha": "accha",
    "thik": "theek", "theek": "theek", "bhaii": "bhai", "bhaiya": "bhaiya",
    "yar": "yaar", "yaaar": "yaar", "haan": "haan", "han": "haan", "ha": "haan",
    "mai": "main", "mein": "mein", "me": "mein",
    "bohot": "bahut", "bahot": "bahut", "bhut": "bahut", "boht": "bahut",
    "jyada": "zyada", "jyaada": "zyada", "zyaada": "zyada",
    "matlb": "matlab", "mtlb": "matlab", "bilkl": "bilkul",
    "abhi": "abhi", "abi": "abhi", "kabhi": "kabhi", "kbhi": "kabhi",
    "phir": "phir", "fir": "phir", "phr": "phir",
    "lekin": "lekin", "lakin": "lekin", "par": "par", "pe": "pe",
    "chalo": "chalo", "chlo": "chalo", "dekho": "dekho", "dkho": "dekho",
    "sahi": "sahi", "shi": "sahi", "mazza": "mazaa", "maza": "mazaa", "majaa": "mazaa",
    "paagal": "pagal", "pagal": "pagal", "bhoot": "bhoot",
}
# "ha"/"ya"/"me"/"bhut" collide with English or other words, so they are only
# rewritten when explicitly listed as safe below.
_UNSAFE = {"ha", "ya", "me", "pe", "han", "fir", "mai"}
_SAFE_VARIANTS = {k: v for k, v in SPELLING_VARIANTS.items() if k not in _UNSAFE and k != v}
_WORD_RE = re.compile(r"^([^\w']*)([\w']+)([^\w']*)$", re.UNICODE)


def normalize_spelling(word: str) -> str:
    """Unify a Roman Hinglish word's spelling, keeping punctuation and case."""
    m = _WORD_RE.match(word)
    if not m:
        return word
    pre, core, post = m.groups()
    target = _SAFE_VARIANTS.get(core.lower())
    if not target:
        return word
    if core.isupper() and len(core) > 1:
        target = target.upper()
    elif core[0].isupper():
        target = target[0].upper() + target[1:]
    return pre + target + post


# Words to mask in captions for platform-friendliness (Reels reach, ads).
# Only the vowel/inner letters are starred so the word is still readable.
PROFANITY = {
    "fuck", "fucking", "fucked", "shit", "bitch", "asshole", "bastard", "dick", "pussy",
    "chutiya", "chutiye", "madarchod", "bhenchod", "behenchod", "bhosdike", "bhosdi",
    "gaand", "gand", "lund", "randi", "harami", "haramkhor", "kutta", "kamina", "kamine",
}


def mask_profanity(word: str) -> str:
    m = _WORD_RE.match(word)
    if not m:
        return word
    pre, core, post = m.groups()
    if core.lower() not in PROFANITY or len(core) < 3:
        return word
    return pre + core[0] + "*" * (len(core) - 2) + core[-1] + post
