"""Module 11: pronunciation watchlist, level 1.

The cheap level of pronunciation checking. It does not grade how a term was
voiced. It guarantees that every jargon term and acronym a course depends on is
examined explicitly, at every site, and routed to a human when anything looks
off.

The reason it exists: a mispronounced acronym does not arrive as silence. It
arrives as a low confidence mishearing at exactly that term. In Course 11 the
ASR failed to write SIEM at three of its sites, at p 0.474, 0.533 and 0.282,
producing two different wrong tokens instead. General alignment
did surface those, incidentally, mixed in with 29 other differences. This layer
finds them deliberately and exhaustively, and would still find them on a course
whose alignment was otherwise silent.

What this layer must never do is certify. A MATCH here means the ASR wrote the
expected orthography with reasonable confidence. It does not mean the term was
pronounced correctly, because ASR emits orthography only: it writes "IaaS"
whether the voice said "eye-as" or "ee-ay-ay-ess". So nothing here is a defect,
and nothing here clears a term. It detects likely mispronunciation and routes
to a human.

One watchlist per learning path, at tests/<learning_path>/watchlist.yaml, because
acronyms are shared across a certification journey rather than owned by one
course. Absence is not an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Sequence

import yaml

from .align import LOW_CONFIDENCE
from .normalize import (
    NormToken,
    SourceToken,
    build_sequence,
    join_originals,
    script_tokens,
    transcript_tokens,
)
from .util import QAError

WATCHLIST_NAME = "watchlist.yaml"
CANDIDATES_NAME = "watchlist.candidates.yaml"

# Occurrence classifications. Deliberately not named "pass" or "fail": this
# layer routes, it does not judge.
MATCH = "MATCH"
LOW = "LOW CONFIDENCE"
MISHEARD = "MISHEARD"

LISTEN_TAG = "pronunciation candidate"

# Keys a watchlist entry may carry. occurrences and seen_in are written by
# qa-terms into the candidates file and ignored here, so a human can promote a
# candidate by copying the whole block without having to strip it first. Any
# other key is a typo and is worth stopping for.
ENTRY_KEYS = {"term", "expect", "say"}
CANDIDATE_KEYS = {"occurrences", "seen_in"}


class WatchlistError(QAError):
    pass


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WatchTerm:
    """One watched term, with every rendering that counts as expected."""

    term: str
    expect: tuple[str, ...]
    say: str | None
    # Normalized through the same machinery both sides of the comparison use,
    # so "IaaS", "iaas" and a spelled out "I a a S" are the same key here.
    key: tuple[str, ...]
    expect_keys: tuple[tuple[str, ...], ...]


def normalize_phrase(text: str) -> tuple[str, ...]:
    """Normalize a written phrase exactly as the aligner normalizes a script.

    This is the whole reason the watchlist can be written in storyboard
    notation: matching goes through normalize.py, so case, hyphenation and
    spelled out letters are not misses.
    """
    return tuple(token.norm for token in build_sequence(script_tokens([text])))


def _as_text(value: object, field: str, where: Path | str) -> str:
    # YAML turns an unquoted NO, ON or Y into a bool, which would silently
    # rename a term. Say so rather than carrying a False around.
    if isinstance(value, bool):
        raise WatchlistError(
            f"{where}: '{field}' read as the boolean {value}. YAML treats bare "
            "NO, ON, YES and OFF as booleans; quote it, as term: \"NO\"."
        )
    if value is None or str(value).strip() == "":
        raise WatchlistError(f"{where}: '{field}' is missing or empty.")
    return str(value).strip()


def parse_watchlist(data: object, where: Path | str) -> list[WatchTerm]:
    """Parse watchlist YAML that has already been loaded. Pure."""
    if data is None:
        return []
    if not isinstance(data, list):
        raise WatchlistError(
            f"{where}: expected a list of terms, got {type(data).__name__}.\n"
            "  Each entry is '- term: SIEM' with optional expect and say."
        )

    terms: list[WatchTerm] = []
    seen: set[str] = set()
    for index, raw in enumerate(data, 1):
        if not isinstance(raw, dict):
            raise WatchlistError(f"{where}: entry {index} is not a mapping.")
        unknown = set(raw) - ENTRY_KEYS - CANDIDATE_KEYS
        if unknown:
            raise WatchlistError(
                f"{where}: entry {index} has unrecognized "
                f"{'keys' if len(unknown) > 1 else 'key'} "
                f"{', '.join(sorted(unknown))}. Allowed: term, expect, say."
            )

        term = _as_text(raw.get("term"), "term", where)
        if term.lower() in seen:
            raise WatchlistError(f"{where}: '{term}' is listed more than once.")
        seen.add(term.lower())

        raw_expect = raw.get("expect")
        if raw_expect is None:
            expect = (term,)
        elif isinstance(raw_expect, (list, tuple)):
            if not raw_expect:
                raise WatchlistError(
                    f"{where}: '{term}' has an empty expect list. Omit the key "
                    "to default to the term itself."
                )
            expect = tuple(
                _as_text(item, f"expect for '{term}'", where) for item in raw_expect
            )
        else:
            expect = (_as_text(raw_expect, f"expect for '{term}'", where),)

        say = raw.get("say")
        say = None if say is None or str(say).strip() == "" else str(say).strip()

        key = normalize_phrase(term)
        if not key:
            raise WatchlistError(
                f"{where}: '{term}' normalizes to nothing, so it can never match."
            )
        expect_keys = tuple(dict.fromkeys(normalize_phrase(e) for e in expect if e))
        expect_keys = tuple(k for k in expect_keys if k)
        if not expect_keys:
            raise WatchlistError(
                f"{where}: every expect form for '{term}' normalizes to nothing."
            )

        terms.append(
            WatchTerm(
                term=term,
                expect=expect,
                say=say,
                key=key,
                expect_keys=expect_keys,
            )
        )
    return terms


def load_watchlist(path: Path) -> list[WatchTerm]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WatchlistError(f"{path} is not valid YAML:\n  {exc}") from exc
    return parse_watchlist(data, path)


def watchlist_path(course_dir: Path) -> Path:
    """tests/<learning_path>/watchlist.yaml, one level above the course."""
    return course_dir.resolve().parent / WATCHLIST_NAME


def find_watchlist(course_dir: Path) -> tuple[Path, list[WatchTerm]] | tuple[Path, None]:
    """Return the expected path, and its terms if the file is there."""
    path = watchlist_path(course_dir)
    if not path.exists():
        return path, None
    return path, load_watchlist(path)


# ---------------------------------------------------------------------------
# Locating a term in one topic
# ---------------------------------------------------------------------------

def _find_occurrences(sequence: Sequence[str], key: Sequence[str]) -> list[tuple[int, int]]:
    """Every contiguous [start, end) in sequence matching key."""
    n, k = len(sequence), len(key)
    if not k or k > n:
        return []
    target = tuple(key)
    return [
        (i, i + k) for i in range(n - k + 1) if tuple(sequence[i : i + k]) == target
    ]


def _project(opcodes: Sequence[tuple], i1: int, i2: int) -> tuple[int, int]:
    """Map a script normalized range onto the transcript normalized range.

    Uses the same opcodes the aligner uses, so the span this reports is the
    span alignment actually put opposite the term. An equal block maps
    position for position; a replace, insert or delete block maps to the whole
    of its transcript side, because inside such a block there is no finer
    correspondence to be had.
    """
    lo: int | None = None
    hi: int | None = None
    for tag, a1, a2, b1, b2 in opcodes:
        if a2 <= i1 or a1 >= i2:
            continue
        if tag == "equal":
            start = b1 + (max(a1, i1) - a1)
            end = b1 + (min(a2, i2) - a1)
        else:
            start, end = b1, b2
        lo = start if lo is None else min(lo, start)
        hi = end if hi is None else max(hi, end)
    if lo is None or hi is None:
        return 0, 0
    return lo, hi


def _src_span(seq: Sequence[NormToken], lo: int, hi: int) -> tuple[int, int] | None:
    indices = [i for token in seq[lo:hi] for i in token.src]
    if not indices:
        return None
    return min(indices), max(indices)


def _span_evidence(
    tokens: Sequence[SourceToken], seq: Sequence[NormToken], lo: int, hi: int
) -> dict:
    """What the transcript has at a normalized span, quoted as it was heard."""
    span = _src_span(seq, lo, hi)
    if span is None:
        return {"heard": "", "start_s": None, "end_s": None, "confidence": None}
    first, last = span
    starts = [t.start for t in tokens[first : last + 1] if t.start is not None]
    ends = [t.end for t in tokens[first : last + 1] if t.end is not None]
    ps = [t.p for t in tokens[first : last + 1] if t.p is not None]
    return {
        "heard": join_originals(tokens, first, last),
        "start_s": round(min(starts), 2) if starts else None,
        "end_s": round(max(ends), 2) if ends else None,
        "confidence": round(min(ps), 3) if ps else None,
    }


def _narrow_to_expected(
    t_norm: Sequence[str], lo: int, hi: int, expect_keys: Sequence[Sequence[str]]
) -> tuple[int, int] | None:
    """If an expected rendering sits inside a wide span, report just that.

    A replace block can be wider than the term when neighbouring words also
    differ. Narrowing keeps the reported confidence and timestamp attached to
    the term itself rather than to its neighbours.
    """
    window = list(t_norm[lo:hi])
    for key in expect_keys:
        k = len(key)
        for offset in range(0, max(len(window) - k, 0) + 1):
            if tuple(window[offset : offset + k]) == tuple(key):
                return lo + offset, lo + offset + k
    return None


def check_topic(
    sentences: Sequence[str],
    words: Sequence[dict],
    terms: Sequence[WatchTerm],
    floor: float = LOW_CONFIDENCE,
) -> list[dict]:
    """Every watched term at every site in one scripted topic. Pure.

    Takes the same two inputs the aligner takes and normalizes them the same
    way, so a site located here is the site alignment would have located.
    """
    s_tokens = script_tokens(sentences)
    t_tokens = transcript_tokens(words)
    s_seq = build_sequence(s_tokens)
    t_seq = build_sequence(t_tokens)
    s_norm = [t.norm for t in s_seq]
    t_norm = [t.norm for t in t_seq]

    opcodes = SequenceMatcher(a=s_norm, b=t_norm, autojunk=False).get_opcodes()

    sites: list[dict] = []
    for watched in terms:
        for i1, i2 in _find_occurrences(s_norm, watched.key):
            lo, hi = _project(opcodes, i1, i2)

            narrowed = _narrow_to_expected(t_norm, lo, hi, watched.expect_keys)
            if narrowed is not None:
                lo, hi = narrowed
                expected_present = True
            else:
                expected_present = tuple(t_norm[lo:hi]) in set(watched.expect_keys)

            evidence = _span_evidence(t_tokens, t_seq, lo, hi)
            confidence = evidence["confidence"]

            if not expected_present:
                status = MISHEARD
            elif confidence is not None and confidence < floor:
                status = LOW
            else:
                status = MATCH

            s_span = _src_span(s_seq, i1, i2)
            sentence_index = s_tokens[s_span[0]].sentence if s_span else None
            sites.append(
                {
                    "term": watched.term,
                    "status": status,
                    "script_says": join_originals(s_tokens, *s_span) if s_span else watched.term,
                    "heard": evidence["heard"],
                    "start_s": evidence["start_s"],
                    "end_s": evidence["end_s"],
                    "confidence": confidence,
                    "script_sentence": sentence_index,
                    "script_sentence_text": (
                        sentences[sentence_index] if sentence_index is not None else ""
                    ),
                }
            )
    return sites


# ---------------------------------------------------------------------------
# Course roll up
# ---------------------------------------------------------------------------

_WORST_ORDER = {MISHEARD: 0, LOW: 1, MATCH: 2}


def _worst(sites: Sequence[dict]) -> dict | None:
    """The site a human should listen to first: misheard, then least certain."""
    if not sites:
        return None
    return sorted(
        sites,
        key=lambda s: (
            _WORST_ORDER[s["status"]],
            s["confidence"] if s["confidence"] is not None else 1.0,
        ),
    )[0]


def build_section(
    terms: Sequence[WatchTerm] | None,
    path: Path,
    per_topic_sites: dict[str, list[dict]],
    floor: float = LOW_CONFIDENCE,
) -> dict:
    """Roll per topic sites into the watchlist section of checks.json."""
    if terms is None:
        return {
            "present": False,
            "path": path.name,
            "reason": "no watchlist for this learning path; run qa-terms to seed one",
            "confidence_floor": floor,
            "terms": [],
            "listen_items": [],
            "totals": {
                "terms": 0,
                "occurrences": 0,
                "matched": 0,
                "low_confidence": 0,
                "misheard": 0,
            },
        }

    by_term: dict[str, list[dict]] = {w.term: [] for w in terms}
    listen_items: list[dict] = []
    for topic in sorted(per_topic_sites):
        for site in per_topic_sites[topic]:
            row = dict(site, topic=topic)
            by_term.setdefault(site["term"], []).append(row)
            if site["status"] in (LOW, MISHEARD):
                listen_items.append(
                    {
                        "tag": LISTEN_TAG,
                        "topic": topic,
                        "term": site["term"],
                        "status": site["status"],
                        "heard": site["heard"],
                        "start_s": site["start_s"],
                        "confidence": site["confidence"],
                    }
                )

    rows: list[dict] = []
    for watched in terms:
        sites = by_term.get(watched.term, [])
        counts = {MATCH: 0, LOW: 0, MISHEARD: 0}
        for site in sites:
            counts[site["status"]] += 1
        rows.append(
            {
                "term": watched.term,
                "expect": list(watched.expect),
                "say": watched.say,
                "occurrences": len(sites),
                "matched": counts[MATCH],
                "low_confidence": counts[LOW],
                "misheard": counts[MISHEARD],
                "worst": _worst(sites),
                "sites": sites,
            }
        )

    listen_items.sort(key=lambda i: (i["topic"], i["start_s"] if i["start_s"] is not None else 0.0))
    return {
        "present": True,
        "path": path.name,
        "reason": None,
        "confidence_floor": floor,
        "terms": rows,
        "listen_items": listen_items,
        "totals": {
            "terms": len(rows),
            "occurrences": sum(r["occurrences"] for r in rows),
            "matched": sum(r["matched"] for r in rows),
            "low_confidence": sum(r["low_confidence"] for r in rows),
            "misheard": sum(r["misheard"] for r in rows),
        },
    }
