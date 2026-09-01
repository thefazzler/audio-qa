"""Module 6: shared token normalization.

Both sides of the comparison, script and transcript, pass through exactly the
same functions here. That symmetry is the whole point: a difference that
survives normalization is a difference in what was said, not a difference in
how two systems chose to write it down.

Everything is pure. Originals are carried alongside the normalized forms so
that reports always quote what was actually written or actually heard.

The equivalence table is the one place where conventions are taught to the
pipeline, and it is meant to grow. Adding a row is the correct response to a
notation difference showing up as a false discrepancy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from num2words import num2words

# Symbols that are spoken as words. Expanded before punctuation is stripped,
# because "50%" and "50 percent" have to land in the same place.
SYMBOL_WORDS = {
    "%": " percent ",
    "&": " and ",
    "+": " plus ",
    "=": " equals ",
    "@": " at ",
}

# Characters that separate two spoken words inside one written token. Whisper's
# word timestamps split hyphenated compounds already ("cloud" then "-based"),
# so splitting both sides on the hyphen makes the two agree.
SPLIT_CHARS = re.compile(r"[-‐‑‒–—/\\_ \s]+")

# Curly punctuation folded to ASCII so quoting styles never register as a diff.
UNICODE_FOLD = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "…": " ",
}

_ORDINAL = re.compile(r"^(\d+)(st|nd|rd|th)$")
_CARDINAL = re.compile(r"^\d+$")
_DECIMAL = re.compile(r"^\d+\.\d+$")

# Multi-token phrases that collapse to one canonical token. Written as the
# normalized pieces they arrive as, after splitting and punctuation stripping.
EQUIVALENCES: dict[tuple[str, ...], str] = {
    # Compounds Skillsoft storyboards and ASR spell differently
    ("health", "care"): "healthcare",
    ("life", "cycle"): "lifecycle",
    ("life", "cycles"): "lifecycles",
    ("data", "set"): "dataset",
    ("data", "sets"): "datasets",
    ("data", "base"): "database",
    ("data", "bases"): "databases",
    ("web", "site"): "website",
    ("web", "sites"): "websites",
    ("e", "mail"): "email",
    ("on", "premise"): "onpremises",
    ("on", "premises"): "onpremises",
    ("onpremise",): "onpremises",
    ("real", "time"): "realtime",
    ("multi", "cloud"): "multicloud",
    ("multi", "factor"): "multifactor",
    ("end", "user"): "enduser",
    ("end", "users"): "endusers",
    ("log", "in"): "login",
    ("set", "up"): "setup",
    ("back", "up"): "backup",
    ("back", "ups"): "backups",
    # Acronyms that arrive spelled out letter by letter
    ("a", "i"): "ai",
    ("i", "t"): "it",
    ("a", "p", "i"): "api",
    ("s", "l", "a"): "sla",
    ("v", "m"): "vm",
    ("i", "a", "a", "s"): "iaas",
    ("p", "a", "a", "s"): "paas",
    ("s", "a", "a", "s"): "saas",
    ("u", "r", "l"): "url",
    ("h", "t", "t", "p", "s"): "https",
    ("h", "t", "t", "p"): "http",
}

MAX_PHRASE = max(len(k) for k in EQUIVALENCES)

# Single tokens with a canonical spelling.
CANONICAL: dict[str, str] = {
    "onpremise": "onpremises",
    "on-premise": "onpremises",
    "okay": "ok",
    "versus": "vs",
}

# Written forms that are pronounced as an identifier rather than as words.
# These are reported as listen items rather than forced into agreement, because
# no normalization can tell how a URL was actually voiced.
IDENTIFIER = re.compile(
    r"(https?://|www\.|\S+\.(com|net|org|io|gov|edu)\b|\S+@\S+\.\S+)", re.IGNORECASE
)


@dataclass(frozen=True)
class NormToken:
    """One normalized token and the source tokens it came from."""

    norm: str
    src: tuple[int, ...]


@dataclass(frozen=True)
class SourceToken:
    """One token exactly as it was written or heard, with its provenance."""

    original: str
    index: int
    sentence: int | None = None
    start: float | None = None
    end: float | None = None
    p: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def fold_unicode(text: str) -> str:
    for bad, good in UNICODE_FOLD.items():
        text = text.replace(bad, good)
    return text


def _spell_number(piece: str) -> str:
    """Digits to words, so "24" and "twenty four" meet in the middle."""
    ordinal = _ORDINAL.match(piece)
    if ordinal:
        return num2words(int(ordinal.group(1)), to="ordinal")
    if _CARDINAL.match(piece):
        value = int(piece)
        # Four digit numbers in narration are usually years.
        if 1000 <= value <= 2999:
            return num2words(value, to="year")
        return num2words(value)
    if _DECIMAL.match(piece):
        return num2words(float(piece))
    return piece


def normalize_token(raw: str) -> list[str]:
    """One written token to zero or more normalized spoken tokens. Pure."""
    text = fold_unicode(raw).lower()
    for symbol, word in SYMBOL_WORDS.items():
        text = text.replace(symbol, word)

    pieces: list[str] = []
    for piece in SPLIT_CHARS.split(text):
        if not piece:
            continue
        # Strip everything that is not a letter, digit or internal apostrophe.
        piece = re.sub(r"[^\w']+", "", piece, flags=re.UNICODE).strip("'")
        if not piece:
            continue
        if any(ch.isdigit() for ch in piece):
            spelled = _spell_number(piece)
            if spelled != piece:
                pieces.extend(p for p in SPLIT_CHARS.split(spelled.lower()) if p)
                continue
        pieces.append(CANONICAL.get(piece, piece))
    return pieces


def build_sequence(sources: Sequence[SourceToken]) -> list[NormToken]:
    """Normalize a token sequence and apply the phrase equivalence table."""
    flat: list[tuple[str, int]] = []
    for token in sources:
        for piece in normalize_token(token.original):
            flat.append((piece, token.index))

    out: list[NormToken] = []
    i = 0
    while i < len(flat):
        merged = False
        for length in range(min(MAX_PHRASE, len(flat) - i), 0, -1):
            key = tuple(piece for piece, _ in flat[i : i + length])
            replacement = EQUIVALENCES.get(key)
            if replacement is None:
                continue
            src = tuple(dict.fromkeys(idx for _, idx in flat[i : i + length]))
            out.append(NormToken(norm=replacement, src=src))
            i += length
            merged = True
            break
        if not merged:
            piece, idx = flat[i]
            out.append(NormToken(norm=piece, src=(idx,)))
            i += 1
    return out


# ---------------------------------------------------------------------------
# Side specific adapters
# ---------------------------------------------------------------------------

_WORD_SPLIT = re.compile(r"\S+")


def script_tokens(sentences: Sequence[str]) -> list[SourceToken]:
    """Flatten script sentences into tokens that remember their sentence."""
    tokens: list[SourceToken] = []
    for sentence_index, sentence in enumerate(sentences):
        for match in _WORD_SPLIT.finditer(sentence):
            tokens.append(
                SourceToken(
                    original=match.group(0),
                    index=len(tokens),
                    sentence=sentence_index,
                )
            )
    return tokens


def transcript_tokens(words: Sequence[dict]) -> list[SourceToken]:
    """Transcript words as tokens that remember their timestamp and confidence."""
    tokens: list[SourceToken] = []
    for word in words:
        tokens.append(
            SourceToken(
                original=word["w"],
                index=len(tokens),
                start=word.get("start"),
                end=word.get("end"),
                p=word.get("p"),
            )
        )
    return tokens


def is_identifier(text: str) -> bool:
    """True for URLs, addresses and the like, which are listen items."""
    return bool(IDENTIFIER.search(text))


def join_originals(tokens: Sequence[SourceToken], first: int, last: int) -> str:
    """Original text for a token range, quoted exactly as it was written."""
    if first > last:
        return ""
    return " ".join(t.original for t in tokens[first : last + 1])
