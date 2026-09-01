"""Module 3: storyboard script extraction and topic mapping.

Pulls speaker notes out of the storyboard, decides which slide belongs to which
topic, and splits each topic's narration into sentences with the original text
preserved exactly.

The topic mapper is the highest-risk component in the pipeline: one slide
assigned to the wrong topic produces a block of false deletions in one topic
and false insertions in the next, which reads exactly like a serious narration
defect. So it does two things beyond mapping. It emits its evidence, naming the
marker phrase that fired on every boundary slide, and it hard-checks its result
against the audio file count from the manifest. A mapper that cannot produce
one topic per delivered audio file stops the run rather than guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pptx import Presentation

from .util import ScriptError, read_json, split_sentences, write_json

# Marker phrases that open a new topic in Skillsoft storyboard notes. Ordered
# most specific first; the first match wins and is recorded as the evidence.
TOPIC_MARKERS: tuple[tuple[str, str], ...] = (
    ("demo_intro", r"^(?:in this (?:demonstration|demo)\b|demonstrate\b)"),
    ("video_intro", r"^in this (?:video|topic)\b"),
    ("summary_intro", r"^in this course,\s*we\b"),
)

_COMPILED_MARKERS = tuple(
    (name, re.compile(pattern, re.IGNORECASE)) for name, pattern in TOPIC_MARKERS
)

# Notes that are template boilerplate rather than narration.
TEMPLATE_HINTS = (
    "general directions",
    "directions for using this template",
    "delete this slide",
    "do not delete",
    "instructions for the",
    "template instructions",
)


@dataclass(frozen=True)
class Slide:
    number: int
    title: str
    notes: str


@dataclass(frozen=True)
class Marker:
    slide: int
    kind: str
    quote: str


def _shape_title(slide) -> str:
    for shape in slide.shapes:
        if shape.has_text_frame and shape.text_frame.text.strip():
            return " / ".join(
                line.strip()
                for line in shape.text_frame.text.splitlines()
                if line.strip()
            )
    return ""


def read_slides(storyboard: Path) -> list[Slide]:
    """Every slide in deck order, with its speaker notes verbatim."""
    try:
        deck = Presentation(str(storyboard))
    except Exception as exc:  # python-pptx raises a variety of package errors
        raise ScriptError(f"Could not open storyboard {storyboard.name}:\n  {exc}") from exc

    slides: list[Slide] = []
    for number, slide in enumerate(deck.slides, start=1):
        notes = ""
        if slide.has_notes_slide:
            frame = slide.notes_slide.notes_text_frame
            if frame is not None:
                notes = frame.text or ""
        slides.append(
            Slide(number=number, title=_shape_title(slide), notes=notes)
        )
    if not slides:
        raise ScriptError(f"{storyboard.name} contains no slides.")
    return slides


def exclusion_reason(slide: Slide) -> str | None:
    """Why this slide carries no narration, or None if it does."""
    stripped = slide.notes.strip()
    if not stripped:
        return "empty notes"
    lowered = stripped.lower()
    if any(hint in lowered for hint in TEMPLATE_HINTS):
        return "template instructions"
    return None


def detect_marker(notes: str) -> Marker | None:
    """First narration-continuity marker in a slide's notes, if any."""
    head = notes.strip()
    if not head:
        return None
    # Compare against the opening sentence only: "In this video" three
    # paragraphs down is a back reference, not a topic boundary.
    opening = split_sentences(head)
    probe = opening[0] if opening else head
    for kind, pattern in _COMPILED_MARKERS:
        if pattern.search(probe.strip()):
            return Marker(slide=0, kind=kind, quote=probe.strip()[:120])
    return None


def auto_map(
    slides: list[Slide], topics: list[str]
) -> tuple[dict[str, list[int]], list[Marker], list[dict]]:
    """Map slides to topics by narration continuity.

    Returns (slide_map, markers, excluded). Raises when the number of topics
    the markers imply does not match the number of delivered audio files.
    """
    excluded: list[dict] = []
    narrated: list[Slide] = []
    for slide in slides:
        reason = exclusion_reason(slide)
        if reason:
            excluded.append(
                {"slide": slide.number, "reason": reason, "title": slide.title[:80]}
            )
        else:
            narrated.append(slide)

    if not narrated:
        raise ScriptError("No slide in the storyboard carries speaker notes.")

    markers: list[Marker] = []
    for slide in narrated:
        found = detect_marker(slide.notes)
        if found is not None:
            markers.append(
                Marker(slide=slide.number, kind=found.kind, quote=found.quote)
            )

    # The first narrated block, before any marker, is the course overview and
    # belongs to the first topic.
    boundaries = [m.slide for m in markers]
    lead_in = [s.number for s in narrated if not boundaries or s.number < boundaries[0]]

    starts: list[int] = []
    if lead_in:
        starts.append(lead_in[0])
    starts.extend(boundaries)

    if len(starts) != len(topics):
        raise ScriptError(_mapping_error(starts, markers, topics, lead_in, excluded))

    slide_map: dict[str, list[int]] = {}
    numbers = [s.number for s in narrated]
    for index, topic in enumerate(topics):
        first = starts[index]
        next_start = starts[index + 1] if index + 1 < len(starts) else None
        span = [
            n for n in numbers
            if n >= first and (next_start is None or n < next_start)
        ]
        slide_map[topic] = [span[0], span[-1]]
    return slide_map, markers, excluded


def _mapping_error(
    starts: list[int],
    markers: list[Marker],
    topics: list[str],
    lead_in: list[int],
    excluded: list[dict],
) -> str:
    lines = [
        "PROBABLE MAPPING ERROR: the storyboard implies "
        f"{len(starts)} topics but the course delivered {len(topics)} audio files.",
        "",
        "  Marker evidence:",
    ]
    if lead_in:
        lines.append(
            f"    slide {lead_in[0]:>3}  lead-in       (no marker; opens the first topic)"
        )
    for marker in markers:
        lines.append(f"    slide {marker.slide:>3}  {marker.kind:<13} {marker.quote!r}")
    if not markers:
        lines.append("    (no marker phrase matched any slide)")
    lines += [
        "",
        f"  Audio topics: {', '.join(topics)}",
        f"  Excluded slides: {len(excluded)}",
        "",
        "  Fix one of these:",
        "    - add slide_map to course.yaml to state the mapping explicitly",
        "    - extend TOPIC_MARKERS in qa/extract_script.py if this storyboard",
        "      opens topics with wording the mapper does not know",
        "    - check that every narration file was delivered",
    ]
    return "\n".join(lines)


def _validate_slide_map(
    slide_map: dict[str, list[int]], topics: list[str], slide_count: int
) -> None:
    missing = [t for t in topics if t not in slide_map]
    if missing:
        raise ScriptError(
            "course.yaml slide_map is missing topics: " + ", ".join(missing)
        )
    for topic, (first, last) in slide_map.items():
        if first < 1 or last > slide_count:
            raise ScriptError(
                f"slide_map['{topic}'] = [{first}, {last}] falls outside the "
                f"storyboard, which has {slide_count} slides."
            )


def build_script(
    storyboard: Path,
    topics: list[str],
    unscripted: set[str],
    slide_map: dict[str, list[int]] | None = None,
) -> dict:
    """Extract per-topic narration from the storyboard."""
    slides = read_slides(storyboard)
    by_number = {s.number: s for s in slides}

    if slide_map:
        _validate_slide_map(slide_map, topics, len(slides))
        excluded = [
            {"slide": s.number, "reason": r, "title": s.title[:80]}
            for s in slides
            if (r := exclusion_reason(s))
        ]
        markers = [
            Marker(slide=s.number, kind=m.kind, quote=m.quote)
            for s in slides
            if not exclusion_reason(s) and (m := detect_marker(s.notes))
        ]
        mapping_source = "course.yaml"
        resolved = {t: list(slide_map[t]) for t in topics}
    else:
        resolved, markers, excluded = auto_map(slides, topics)
        mapping_source = "auto"

    excluded_numbers = {e["slide"] for e in excluded}
    topic_entries: list[dict] = []

    for topic in topics:
        first, last = resolved[topic]
        members = [
            by_number[n]
            for n in range(first, last + 1)
            if n in by_number and n not in excluded_numbers
        ]
        sentences: list[str] = []
        sentence_slides: list[int] = []
        for slide in members:
            for sentence in split_sentences(slide.notes):
                sentences.append(sentence)
                sentence_slides.append(slide.number)

        scripted = topic not in unscripted
        entry: dict = {
            "topic": topic,
            "slides": [first, last],
            "scripted": scripted,
            "slide_numbers": [s.number for s in members],
            "sentences": sentences,
            "sentence_slides": sentence_slides,
            "word_count": sum(len(s.split()) for s in sentences),
        }
        if not scripted:
            # Demo outlines are not verbatim narration. Keep the raw text so the
            # packet can show a human what the demo was supposed to cover.
            entry["outline"] = [
                line.strip()
                for slide in members
                for line in re.split(r"[\n\x0b\r]+", slide.notes)
                if line.strip()
            ]
        topic_entries.append(entry)

    return {
        "storyboard": storyboard.name,
        "slide_count": len(slides),
        "mapping": {
            "source": mapping_source,
            "markers": [
                {"slide": m.slide, "kind": m.kind, "quote": m.quote} for m in markers
            ],
            "excluded_slides": excluded,
        },
        "topics": topic_entries,
    }


def run_extract_script(course_dir: Path, force: bool = False) -> dict:
    """Stage entry point: read manifest.json, write script.json."""
    from .config import load_course_yaml

    cfg = load_course_yaml(course_dir)
    manifest_path = cfg.qa_work / "manifest.json"
    if not manifest_path.exists():
        raise ScriptError(f"{manifest_path} not found. Run the config stage first.")

    manifest = read_json(manifest_path)
    topics = [t["topic"] for t in manifest["topics"]]

    # Record the storyboard the extraction was made from, and say so when it
    # has changed since the last run. The stage runs every time now, so this
    # cannot go stale silently; it is here to make the dependency explicit and
    # to tell the operator that the script they are aligning against is not
    # the one they aligned against yesterday. See DECISIONS.md D17.
    storyboard_sha256 = manifest.get("storyboard_sha256")
    previous_path = cfg.qa_work / "script.json"
    changed = False
    if previous_path.exists() and storyboard_sha256:
        try:
            previous = read_json(previous_path).get("storyboard_sha256")
            changed = bool(previous) and previous != storyboard_sha256
        except (OSError, ValueError):
            changed = False

    script = build_script(
        storyboard=cfg.course_dir / manifest["storyboard"],
        topics=topics,
        unscripted=set(cfg.unscripted_topics),
        slide_map=cfg.slide_map or None,
    )
    script["storyboard_sha256"] = storyboard_sha256
    script["warnings"] = (
        [
            "The storyboard has changed since the last run. Every topic is "
            "aligned against the new script."
        ]
        if changed
        else []
    )
    write_json(cfg.qa_work / "script.json", script)
    return script
