"""Checks that need only the transcript, because some topics have no script.

A topic whose script state is `none` still had audio delivered, and it still
has to be checked. What it cannot have is word-level alignment, so everything
alignment normally catches has to come from somewhere else or not at all. These
two detectors are what a transcript alone can honestly support. Both produce
listen items and neither produces a defect: with no script there is nothing to
be wrong against, only something to go and hear.

Both were written because the first real demo run showed the gap. Course 10's
topic 09 is a demo whose narration reads a filename aloud, and the packet had
nowhere to say so.
"""

from __future__ import annotations

import re
from typing import Sequence

# Words that are the spoken name of a symbol or of a URL part. A synthetic
# voice reading `project_plan` literally says "project underscore plan", and
# the transcript then contains a perfectly ordinary word that is not a word.
#
# Never a defect. Narrators do say "underscore" on purpose, in a topic about
# naming conventions or when reading a path the learner has to type. What the
# report can say is where it happened, so one listen settles all of them.
SYMBOL_TERMS: frozenset[str] = frozenset(
    {
        "underscore",
        "hyphen",
        "dash",
        "slash",
        "backslash",
        "colon",
        "asterisk",
        "http",
        "https",
        "www",
    }
)

# "dot" is the one that cannot be flagged on its own: "dot" is a normal English
# word and "connect the dots" is not a URL. It counts only next to something
# domain shaped.
DOT_TERM = "dot"
DOT_NEIGHBOURS: frozenset[str] = frozenset(
    {
        "com", "net", "org", "io", "gov", "edu", "co", "uk", "ai", "dev",
        "www", "http", "https", "slash", "backslash", DOT_TERM,
    }
)

# How far either side of a "dot" to look for that neighbour.
DOT_WINDOW = 1

# Words of context carried with each site, so the packet can show
# "project underscore plan" rather than a bare "underscore".
CONTEXT_WORDS = 3

_BARE = re.compile(r"[^\w]+")


def _bare(token: str) -> str:
    return _BARE.sub("", token or "").lower()


def _context(words: Sequence[dict], index: int) -> str:
    first = max(0, index - CONTEXT_WORDS)
    last = min(len(words), index + CONTEXT_WORDS + 1)
    return " ".join(w["w"].strip() for w in words[first:last]).strip()


def voiced_symbols(words: Sequence[dict]) -> list[dict]:
    """Every site where the voice said the name of a symbol, grouped by term.

    Runs on scripted topics too. It costs nothing, and a voiced symbol that the
    script also contains is still worth a listen: the script saying
    "project_plan" does not tell anyone whether reading it out as "project
    underscore plan" was intended.
    """
    bare = [_bare(w.get("w", "")) for w in words]
    sites: dict[str, list[dict]] = {}

    for index, token in enumerate(bare):
        if not token:
            continue
        if token == DOT_TERM:
            neighbours = [
                bare[position]
                for position in range(
                    max(0, index - DOT_WINDOW), min(len(bare), index + DOT_WINDOW + 1)
                )
                if position != index
            ]
            if not any(n in DOT_NEIGHBOURS for n in neighbours):
                continue
        elif token not in SYMBOL_TERMS:
            continue

        word = words[index]
        sites.setdefault(token, []).append(
            {
                "start_s": word.get("start"),
                "confidence": word.get("p"),
                "heard": word.get("w", "").strip(),
                "context": _context(words, index),
            }
        )

    return [
        {
            "term": term,
            "occurrences": len(found),
            "sites": found,
            "first_s": found[0]["start_s"],
        }
        for term, found in sorted(sites.items())
    ]


def unverifiable_duplications(
    words: Sequence[dict], segments: Sequence[dict], low_confidence: float
) -> list[dict]:
    """Segment boundary duplications that no script can confirm.

    On a scripted topic these are suppressed outright, and that is safe only
    because alignment has already proved the script has one word there. With no
    script that proof does not exist, so the same candidates are listed instead
    of dropped, under their own heading, where one pass with headphones settles
    the lot. Dropping them silently would be the pipeline deciding a question it
    cannot answer; leaving them scattered through the low-confidence table
    would make a reader find them one at a time.

    Every candidate is listed, not only the ones whose second copy decoded
    badly, because the confidence of that second copy is a hint about which are
    artifacts and not evidence about what was said. It is reported per site so
    a reader can triage by it.
    """
    from .transcribe import boundary_duplicate_indices

    if not segments or not words:
        return []

    found: list[dict] = []
    for index in sorted(boundary_duplicate_indices(words, segments)):
        word = words[index]
        confidence = word.get("p")
        found.append(
            {
                "heard": word.get("w", "").strip(),
                "start_s": word.get("start"),
                "confidence": confidence,
                "low_confidence": confidence is not None and confidence < low_confidence,
                "context": _context(words, index),
            }
        )
    return found
