"""Module 8: per topic checks.

Deterministic replacements for the v4 transcriber's self-reported attestations.
The v4 prompt asked an instrument to certify its own completeness, which a
truncated instrument cannot honestly do. These are computed instead, from the
audio, the script and the transcript, so a failed file shows up on paper
whether or not anything chose to report it.

Every threshold that matters is named at the top of this file rather than
buried, because tuning them is a normal part of running this pipeline against
a new course.
"""

from __future__ import annotations

from pathlib import Path
from statistics import median

from .util import QAError, read_json, split_sentences, write_json
from .watchlist import (
    build_section,
    check_topic as check_watchlist_topic,
    find_watchlist,
)

# Pace. The spec and the v4 prompt both used an absolute floor of 120 words
# per minute, on the assumption that professional TTS runs 140 to 160. Course
# 10 runs about 115, so that floor flags nine of ten clean files. What actually
# matters is whether the transcript is paced like the script it was read from,
# which is a ratio and is immune to how fast a given voice talks.
PACE_RATIO_LOW = 0.85
PACE_RATIO_HIGH = 1.15

# Unscripted topics have no script to compare against, so they are checked
# against the pace of the rest of the course, with a wider band.
UNSCRIPTED_PACE_LOW = 0.70
UNSCRIPTED_PACE_HIGH = 1.40

# Script coverage. Below the first line is a real gap in what was spoken.
# Below the second, the topic to slide mapping is the more likely explanation
# than a narrator who skipped a third of the script.
COVERAGE_FLOOR = 0.97
MAPPING_ERROR_FLOOR = 0.85

# The decoder stopping well before the audio does. Paired with the artifact
# module's trailing silence measurement, this separates "narration stopped
# early", which is a defect, from "decoder stopped early", which is not.
TAIL_GAP_S = 40.0


class CheckError(QAError):
    pass


def _flag(condition: bool, label: str) -> list[str]:
    return [label] if condition else []


def check_topic(
    manifest_entry: dict,
    script_entry: dict,
    transcript: dict,
    discrepancies: dict,
    artifacts: dict,
    reference_wpm: float | None,
) -> dict:
    """One row of checks.json. Pure: takes the stage outputs, returns a row."""
    topic = manifest_entry["topic"]
    duration = manifest_entry["duration_s"]
    minutes = duration / 60.0 if duration else 0.0
    scripted = script_entry["scripted"]

    script_words = script_entry["word_count"]
    transcript_words = transcript["word_count"]
    script_wpm = round(script_words / minutes, 1) if minutes else 0.0
    transcript_wpm = round(transcript_words / minutes, 1) if minutes else 0.0

    flags: list[str] = []

    # Pace, as a ratio against the rate this file's own script implies.
    if scripted and script_wpm:
        pace_ratio = round(transcript_wpm / script_wpm, 3)
        pace_reference = "script"
        flags += _flag(pace_ratio < PACE_RATIO_LOW, "PACE BELOW SCRIPT")
        flags += _flag(pace_ratio > PACE_RATIO_HIGH, "PACE ABOVE SCRIPT")
    elif reference_wpm:
        pace_ratio = round(transcript_wpm / reference_wpm, 3)
        pace_reference = "course median"
        flags += _flag(pace_ratio < UNSCRIPTED_PACE_LOW, "PACE BELOW COURSE")
        flags += _flag(pace_ratio > UNSCRIPTED_PACE_HIGH, "PACE ABOVE COURSE")
    else:
        pace_ratio = None
        pace_reference = "none"

    # Coverage and the tail, the two real truncation detectors.
    coverage = discrepancies.get("coverage")
    tail_matched = discrepancies.get("tail_matched")
    if scripted:
        flags += _flag(
            coverage is not None and coverage < MAPPING_ERROR_FLOOR,
            "PROBABLE MAPPING ERROR",
        )
        if coverage is not None and MAPPING_ERROR_FLOOR <= coverage < COVERAGE_FLOOR:
            flags.append("LOW COVERAGE")
        flags += _flag(tail_matched is False, "TAIL SENTENCE NOT MATCHED")

    # Decoder tail gap, cross checked against measured trailing silence.
    last_word_end = transcript.get("last_word_end")
    trailing_silence = artifacts.get("trailing_silence_s", 0.0)
    tail_gap = round(duration - last_word_end, 2) if last_word_end is not None else None
    if tail_gap is not None and tail_gap > TAIL_GAP_S:
        if trailing_silence >= tail_gap - 1.0:
            flags.append("LONG TRAILING SILENCE")
        else:
            flags.append("DECODER STOPPED EARLY")

    # Whisper segments are decode windows, not sentences: one sentence often
    # spans two segments. Counting per segment nearly doubles the total and
    # would read as invented content next to the script count. Join first.
    joined = " ".join(segment["text"] for segment in transcript["segments"])
    transcript_sentences = len(split_sentences(joined))

    anomaly_types = sorted({a["type"] for a in transcript.get("anomalies", [])})
    artifact_types = sorted({f["type"] for f in artifacts.get("findings", [])})
    high_artifacts = [
        f for f in artifacts.get("findings", []) if f["severity"] == "high"
    ]
    flags += _flag(bool(high_artifacts), "AUDIO ARTIFACT")

    counts = discrepancies.get("counts") or {}
    return {
        "topic": topic,
        "slides": script_entry.get("slides"),
        "source_ref": script_entry.get("source_ref", ""),
        "script": script_entry.get("script")
        or ("verbatim" if scripted else "outline"),
        "scripted": scripted,
        "duration_s": duration,
        "script_words": script_words,
        "transcript_words": transcript_words,
        "script_wpm": script_wpm,
        "transcript_wpm": transcript_wpm,
        "pace_ratio": pace_ratio,
        "pace_reference": pace_reference,
        "coverage": coverage,
        "tail_matched": tail_matched,
        "tail_gap_s": tail_gap,
        "trailing_silence_s": trailing_silence,
        "script_sentences": len(script_entry["sentences"]),
        "transcript_sentences": transcript_sentences,
        "discrepancies": len(discrepancies.get("discrepancies", [])),
        "listen_items": discrepancies.get("listen_items", 0),
        "suppressed_asr_duplicates": len(
            discrepancies.get("suppressed_asr_duplicates", [])
        ),
        # Listen items in their own right, never defects. Counted here so the
        # summary can say how many there are without the packet being the only
        # place they exist.
        "voiced_symbols": sum(
            group["occurrences"] for group in discrepancies.get("voiced_symbols", [])
        ),
        "voiced_symbol_terms": [
            group["term"] for group in discrepancies.get("voiced_symbols", [])
        ],
        "unverifiable_duplications": len(
            discrepancies.get("unverifiable_duplications", [])
        ),
        "low_confidence_words": transcript.get("low_confidence_words"),
        "low_confidence_share": transcript.get("low_confidence_share"),
        "asr_anomalies": anomaly_types,
        "audio_findings": artifact_types,
        "flags": flags,
    }


def run_checks(course_dir: Path, force: bool = False) -> dict:
    """Stage entry point: roll every stage output into one row per topic."""
    from .config import load_course_yaml

    cfg = load_course_yaml(course_dir)
    work = cfg.qa_work

    def load(name: str) -> dict:
        path = work / name
        if not path.exists():
            raise CheckError(f"{path} not found. Run the earlier stages first.")
        return read_json(path)

    manifest = load("manifest.json")
    script = {t["topic"]: t for t in load("script.json")["topics"]}

    # Pace reference for unscripted topics: the median of the scripted files,
    # so a demo is compared against the course it ships in.
    scripted_rates = []
    for entry in manifest["topics"]:
        if not script[entry["topic"]]["scripted"] or not entry["duration_s"]:
            continue
        transcript = load(f"transcript_{entry['topic']}.json")
        scripted_rates.append(
            transcript["word_count"] / (entry["duration_s"] / 60.0)
        )
    reference_wpm = round(median(scripted_rates), 1) if scripted_rates else None

    rows = [
        check_topic(
            manifest_entry=entry,
            script_entry=script[entry["topic"]],
            transcript=load(f"transcript_{entry['topic']}.json"),
            discrepancies=load(f"discrepancies_{entry['topic']}.json"),
            artifacts=load(f"artifacts_{entry['topic']}.json"),
            reference_wpm=reference_wpm,
        )
        for entry in manifest["topics"]
    ]

    scripted_rows = [r for r in rows if r["scripted"]]
    summary = {
        "course_code": manifest["course_code"],
        "course_number": manifest["course_number"],
        "project_type": manifest["project_type"],
        "topic_count": len(rows),
        "reference_wpm": reference_wpm,
        "mean_coverage": (
            round(
                sum(r["coverage"] or 0.0 for r in scripted_rows) / len(scripted_rows), 4
            )
            if scripted_rows
            else None
        ),
        "total_discrepancies": sum(r["discrepancies"] for r in rows),
        "total_listen_items": sum(r["listen_items"] for r in rows),
        "total_suppressed": sum(r["suppressed_asr_duplicates"] for r in rows),
        "total_voiced_symbols": sum(r["voiced_symbols"] for r in rows),
        "total_unverifiable_duplications": sum(
            r["unverifiable_duplications"] for r in rows
        ),
        "script_source": manifest.get("script_source", ""),
        "script_document": manifest.get("script_document")
        or manifest.get("storyboard")
        or "",
        "flagged_topics": [r["topic"] for r in rows if r["flags"]],
    }

    # Watchlist, as its own pass. Every listed term is examined at every site
    # in every scripted topic, whether or not alignment flagged it, because a
    # term can be voiced wrongly in a topic whose alignment is otherwise
    # silent. Nothing here is a defect and nothing here certifies pronunciation;
    # see qa/watchlist.py. Absence of a watchlist is not an error.
    path, terms = find_watchlist(cfg.course_dir)
    per_topic_sites: dict[str, list[dict]] = {}
    if terms:
        for entry in manifest["topics"]:
            topic = entry["topic"]
            if not script[topic]["scripted"]:
                continue
            per_topic_sites[topic] = check_watchlist_topic(
                script[topic]["sentences"],
                load(f"transcript_{topic}.json")["words"],
                terms,
            )
    watchlist = build_section(terms, path, per_topic_sites)

    checks = {"summary": summary, "topics": rows, "watchlist": watchlist}
    write_json(work / "checks.json", checks)
    return checks
