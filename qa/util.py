"""Shared helpers: error types, JSON IO, hashing, text splitting.

Everything here is small and pure enough to be reused by any stage without
pulling in that stage's dependencies.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


class QAError(Exception):
    """Base for every failure the CLI should report as a clean message.

    Raising this (rather than letting a traceback escape) is how a stage says
    "stop the run and tell the operator exactly what is wrong".
    """


class IngestError(QAError):
    pass


class ConfigError(QAError):
    pass


class ScriptError(QAError):
    pass


class ScaffoldError(QAError):
    pass


# --------------------------------------------------------------------------
# JSON IO. Every intermediate is human readable by design.
# --------------------------------------------------------------------------

def write_json(path: Path, obj: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def rel(path: Path, root: Path) -> str:
    """Course-relative POSIX path, so intermediates stay portable."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


# --------------------------------------------------------------------------
# Sentence splitting.
# --------------------------------------------------------------------------

# Tokens that end in a period without ending a sentence. Kept explicit and in
# one place so the list can grow as real storyboards demand.
ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "e.g.", "i.e.", "etc.", "vs.", "cf.", "approx.", "est.",
        "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.",
        "inc.", "ltd.", "llc.", "corp.", "co.", "dept.", "univ.",
        "u.s.", "u.k.", "u.s.a.", "e.u.",
        "fig.", "no.", "vol.", "sec.", "min.", "max.", "avg.",
        "jan.", "feb.", "mar.", "apr.", "jun.", "jul.", "aug.",
        "sep.", "sept.", "oct.", "nov.", "dec.",
    }
)

# End of sentence: terminal punctuation, optional closing quote or bracket,
# whitespace, then something that can start a sentence.
_SENTENCE_BOUNDARY = re.compile(
    r"(?<=[.!?])([\"'\u2019\u201d)\]]*)\s+(?=[\"'\u2018\u201c(\[]*[A-Z0-9])"
)

_LAST_TOKEN = re.compile(r"(\S+)\s*$")


def _blocks_split(left: str) -> bool:
    """True when the period ending `left` is not a sentence end."""
    m = _LAST_TOKEN.search(left)
    if not m:
        return True
    token = m.group(1).lower()
    if token in ABBREVIATIONS:
        return True
    # Single initial such as "J." or a spelled acronym such as "A.C.I.S."
    if re.fullmatch(r"(?:[a-z]\.)+", token):
        return True
    # Decimal or version number: "3.11." is rare, "3.11" never ends a sentence
    if re.search(r"\d\.\d*$", token):
        return True
    return False


def split_sentences(text: str) -> list[str]:
    """Split into sentences, preserving the original characters exactly.

    Paragraph breaks (newline, and the vertical tab PowerPoint uses for a
    soft return) end a sentence even without terminal punctuation, because
    storyboard notes routinely use bulleted paragraphs with no final period.
    """
    sentences: list[str] = []
    for para in re.split(r"[\n\x0b\r]+", text):
        para = para.strip()
        if not para:
            continue
        start = 0
        for m in _SENTENCE_BOUNDARY.finditer(para):
            end = m.end(1)
            candidate = para[start:end]
            if _blocks_split(candidate):
                continue
            piece = candidate.strip()
            if piece:
                sentences.append(piece)
            start = m.end()
        tail = para[start:].strip()
        if tail:
            sentences.append(tail)
    return sentences


def summarize(items: Iterable[str], limit: int = 4) -> str:
    """Compact join for status lines: a, b, c and 7 more."""
    items = list(items)
    if len(items) <= limit:
        return ", ".join(items)
    return ", ".join(items[:limit]) + f" and {len(items) - limit} more"
