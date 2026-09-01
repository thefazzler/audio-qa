"""Propose pronunciation watchlist candidates from a course's storyboard.

    qa-terms <course_dir>            candidates from one course
    qa-terms <learning_path_dir>     union across every course in the path

Nobody should have to type a watchlist from scratch. This reads the script
stage's output, pulls out the tokens that look like jargon, counts where they
occur, and writes tests/<learning_path>/watchlist.candidates.yaml.

It never writes watchlist.yaml. Promotion is a human act: which terms actually
matter to a course, and how each one should be said, are judgments this command
has no way to make. The say field is written as TODO for exactly that reason.

Two shapes are proposed:

    all caps, two or more letters       SIEM, NIST, SOC, CISO
    mixed case with an inner capital    IaaS, PaaS, DevSecOps

and, with --neighbors, any token sharing a sentence with a term already on the
watchlist. That catches the jargon that travels with an acronym but is not
shaped like one, such as a product name next to SIEM.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .util import QAError, read_json
from .watchlist import (
    CANDIDATES_NAME,
    WATCHLIST_NAME,
    WatchlistError,
    load_watchlist,
    normalize_phrase,
)

# Two or more letters, all capital. Digits are allowed after the letters so
# SOC2 and MFA2 survive, but a bare number does not qualify.
ALL_CAPS = re.compile(r"^[A-Z]{2,}[0-9]*$")

# An inner capital is what distinguishes IaaS and DevSecOps from an ordinary
# capitalized sentence opener.
INNER_CAPS = re.compile(r"^[A-Za-z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*$")

# Tokens shaped like jargon that are not jargon. Kept deliberately short: this
# is a proposal, and over filtering hides terms a human would have wanted.
STOPWORDS = {"A", "I", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "IF", "IN",
             "IS", "IT", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "WE"}

_STRIP = re.compile(r"^[^\w]+|[^\w]+$")


class TermsError(QAError):
    pass


def extract_tokens(text: str) -> list[str]:
    """Jargon shaped tokens in one string, in the notation they were written."""
    found: list[str] = []
    for raw in text.split():
        token = _STRIP.sub("", raw)
        # A possessive or plural s on an acronym is notation, not a new term.
        if len(token) > 2 and token.endswith("'s"):
            token = token[:-2]
        if len(token) > 2 and token.endswith("s") and token[:-1].isupper():
            token = token[:-1]
        if not token or token.upper() in STOPWORDS:
            continue
        if ALL_CAPS.match(token) or (INNER_CAPS.match(token) and not token.isupper()):
            found.append(token)
    return found


def _sentences(script: dict) -> list[tuple[str, str]]:
    """(topic, sentence) for every sentence in a script.json, outlines included."""
    out: list[tuple[str, str]] = []
    for entry in script["topics"]:
        for sentence in entry.get("sentences") or []:
            out.append((entry["topic"], sentence))
        for line in entry.get("outline") or []:
            out.append((entry["topic"], line))
    return out


def course_dirs(target: Path) -> list[Path]:
    """One course, or every course under a learning path folder."""
    target = target.resolve()
    if not target.is_dir():
        raise TermsError(f"Not a folder: {target}")
    if (target / "course.yaml").exists():
        return [target]
    courses = sorted(
        p for p in target.iterdir() if p.is_dir() and (p / "course.yaml").exists()
    )
    if not courses:
        raise TermsError(
            f"No courses under {target}.\n"
            "  Point qa-terms at a course folder (one holding course.yaml) or at "
            "a learning path folder holding several."
        )
    return courses


def collect(
    courses: list[Path], neighbors: bool = False
) -> tuple[dict[str, Counter], dict[str, set[str]], dict[str, dict]]:
    """Count candidate tokens across courses, remembering where each was seen.

    Also returns the terms the script author already wrote down. A BUS document
    carries a Pronunciation Guide, and a term in it comes with the stated
    pronunciation attached, which is the one thing this command otherwise
    cannot know. Those are merged with the token-shaped proposals rather than
    listed twice.
    """
    counts: dict[str, Counter] = defaultdict(Counter)
    seen_in: dict[str, set[str]] = defaultdict(set)
    stated: dict[str, dict] = {}

    watch_keys: set[tuple[str, ...]] = set()
    if neighbors:
        for course in courses:
            path = course.parent / WATCHLIST_NAME
            if path.exists():
                watch_keys |= {w.key for w in load_watchlist(path)}

    for course in courses:
        script_path = course / "qa_work" / "script.json"
        if not script_path.exists():
            raise TermsError(
                f"{script_path} not found.\n"
                f"  Run the script stage first: qa-run {course.as_posix()} "
                "--stage script"
            )
        script = read_json(script_path)
        for row in script.get("pronunciation_guide") or []:
            term = (row.get("term") or "").strip()
            if not term:
                continue
            entry = stated.setdefault(
                term, {"say": "", "source": "", "seen_in": set()}
            )
            entry["say"] = entry["say"] or (row.get("say") or "").strip()
            entry["source"] = entry["source"] or (row.get("source") or "").strip()
            where = (row.get("topic") or "").strip()
            entry["seen_in"].add(
                f"{course.name}:{where}" if where else f"{course.name}"
            )

        for topic, sentence in _sentences(script):
            tokens = extract_tokens(sentence)
            if neighbors and watch_keys:
                near = {normalize_phrase(t) for t in sentence.split()}
                if watch_keys & near:
                    tokens += [
                        _STRIP.sub("", w)
                        for w in sentence.split()
                        if len(_STRIP.sub("", w)) > 2
                        and _STRIP.sub("", w).upper() not in STOPWORDS
                    ]
            for token in tokens:
                counts[token][f"{course.name}:{topic}"] += 1
                seen_in[token].add(f"{course.name}:{topic}")
    return counts, seen_in, stated


def render_candidates(
    counts: dict[str, Counter],
    seen_in: dict[str, set[str]],
    learning_path: str,
    already: set[str],
    stated: dict[str, dict] | None = None,
) -> str:
    """The candidates file. Same shape as watchlist.yaml, so promotion is a copy."""
    stated = stated or {}

    totals: dict[str, int] = {
        term: sum(c.values())
        for term, c in counts.items()
        if term.lower() not in already
    }
    # A term the author put in a Pronunciation Guide belongs here whether or not
    # it is shaped like an acronym, and it merges with the counted occurrences
    # rather than appearing beside them as a second row for the same word.
    for term in stated:
        if term.lower() in already:
            continue
        totals.setdefault(term, sum(counts.get(term, Counter()).values()))

    rows = sorted(totals.items(), key=lambda r: (-r[1], r[0].lower()))
    lines = [
        f"# Watchlist candidates for the {learning_path} learning path.",
        "# Proposed by qa-terms from the course scripts. This file is never",
        "# read by the pipeline. Promote a term by copying its block into",
        f"# {WATCHLIST_NAME} and filling in say; delete the rest.",
        "#",
        "# say is left as TODO on purpose. How a term should be pronounced is not",
        "# derivable from a script and is not guessed here. The one exception is",
        "# a term the author put in the script document's Pronunciation Guide:",
        "# there the stated pronunciation is carried through, because a human",
        "# wrote it down.",
        "",
    ]
    if not rows:
        lines += ["# No new candidates: every proposed term is already listed.", "[]"]
        return "\n".join(lines) + "\n"

    for term, total in rows:
        guide = stated.get(term, {})
        where = ", ".join(
            sorted(set(seen_in.get(term, set())) | set(guide.get("seen_in", ())))
        )
        say = (guide.get("say") or "").strip()
        lines += [
            f'- term: "{term}"',
            f'  expect: "{term}"',
            f'  say: "{say}"' if say else "  say: TODO",
        ]
        if guide:
            lines.append("  # listed in the script document's Pronunciation Guide")
            if guide.get("source"):
                lines.append(f'  source: "{guide["source"]}"')
        lines += [
            f"  occurrences: {total}",
            f'  seen_in: "{where}"',
            "",
        ]
    return "\n".join(lines) + "\n"


def run_terms(target: Path, neighbors: bool = False) -> dict:
    """Write the candidates file for a course or a learning path."""
    courses = course_dirs(target)
    path_dir = courses[0].parent
    counts, seen_in, stated = collect(courses, neighbors=neighbors)

    watchlist = path_dir / WATCHLIST_NAME
    already: set[str] = set()
    if watchlist.exists():
        already = {w.term.lower() for w in load_watchlist(watchlist)}

    out_path = path_dir / CANDIDATES_NAME
    text = render_candidates(counts, seen_in, path_dir.name, already, stated)
    out_path.write_text(text, encoding="utf-8")

    proposed = [
        t
        for t in dict.fromkeys(list(counts) + list(stated))
        if t.lower() not in already
    ]
    return {
        "path": out_path.as_posix(),
        "learning_path": path_dir.name,
        "courses": [c.name for c in courses],
        "candidates": len(proposed),
        "already_listed": len(already & {t.lower() for t in counts}),
        "from_pronunciation_guide": sorted(
            t for t in stated if t.lower() not in already
        ),
        "top": sorted(
            ((t, sum(counts.get(t, Counter()).values())) for t in proposed),
            key=lambda r: (-r[1], r[0].lower()),
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qa-terms",
        description=(
            "Propose pronunciation watchlist candidates from a course's "
            "storyboard script."
        ),
        epilog=(
            "writes <learning_path>/" + CANDIDATES_NAME + " and never touches "
            + WATCHLIST_NAME + ".\npromoting a candidate, and saying how it "
            "should be pronounced, stays a human step."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "target",
        type=Path,
        help="a course folder, or a learning path folder to union across",
    )
    parser.add_argument(
        "--neighbors",
        action="store_true",
        help="also propose tokens sharing a sentence with a listed term",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=25,
        metavar="N",
        help="how many candidates to print (default 25); all are written",
    )
    args = parser.parse_args(argv)

    try:
        result = run_terms(args.target, neighbors=args.neighbors)
    except (TermsError, WatchlistError) as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 2

    print(f"audio-qa: watchlist candidates for {result['learning_path']}")
    print(f"  courses    {', '.join(result['courses'])}")
    print(f"  candidates {result['candidates']} proposed, "
          f"{result['already_listed']} already on the watchlist")
    print()
    shown = result["top"][: args.top]
    if shown:
        width = max(len(t) for t, _ in shown)
        for term, total in shown:
            print(f"    {term:<{width}}  {total}")
        if len(result["top"]) > len(shown):
            print(f"    ... {len(result['top']) - len(shown)} more in the file")
    print()
    print(f"  written to {result['path']}")
    print("  promote the ones that matter into "
          f"{Path(result['path']).parent.as_posix()}/{WATCHLIST_NAME}, "
          "filling in say.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
