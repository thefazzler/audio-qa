"""Module 7: script to transcript alignment.

Aligns normalized script tokens against normalized transcript tokens and emits
every surviving difference with its type, the original text on both sides, and
the audio timestamp range where it happened.

This module reports, it does not judge. Nothing here decides whether a
difference is a defect. That is the reconciliation prompt's job, and keeping
the line clean is what makes the packet auditable.

Topics with no verbatim script are not aligned at all. An outline cannot
arbitrate word level fidelity and a topic with no script has nothing to
arbitrate against, so the packet carries the transcript itself instead. Two
checks in `qa/transcript_checks.py` run on the transcript alone and are
attached here, so that a topic without a script is still examined rather than
merely transcribed.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Sequence

from .normalize import (
    NormToken,
    SourceToken,
    build_sequence,
    is_identifier,
    join_originals,
    script_tokens,
    transcript_tokens,
)
from .util import QAError, read_json, write_json

# Word confidence below which a transcript word is evidence of an uncertain
# decode rather than of a narration defect.
LOW_CONFIDENCE = 0.6

# Discrepancies per topic beyond which the packet lists the worst and counts
# the rest. A topic this noisy is usually a mapping error, not a bad recording.
DIFF_LIMIT = 40


class AlignError(QAError):
    pass


@dataclass(frozen=True)
class Discrepancy:
    type: str
    script_text: str
    transcript_text: str
    start_s: float | None
    end_s: float | None
    script_sentence: int | None
    script_sentence_text: str
    context_before: str
    context_after: str
    min_confidence: float | None
    listen_item: bool
    reason: str

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "script_says": self.script_text,
            "voice_said": self.transcript_text,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "script_sentence": self.script_sentence,
            "script_sentence_text": self.script_sentence_text,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "min_confidence": self.min_confidence,
            "listen_item": self.listen_item,
            "reason": self.reason,
        }


def _src_span(seq: Sequence[NormToken], lo: int, hi: int) -> tuple[int, int] | None:
    """Source token range covered by normalized tokens [lo, hi)."""
    indices = [i for token in seq[lo:hi] for i in token.src]
    if not indices:
        return None
    return min(indices), max(indices)


def _timestamps(
    tokens: Sequence[SourceToken], span: tuple[int, int] | None, fallback: int | None
) -> tuple[float | None, float | None]:
    """Audio range for a transcript span, or the seam where nothing was said."""
    if span is not None:
        first, last = span
        starts = [t.start for t in tokens[first : last + 1] if t.start is not None]
        ends = [t.end for t in tokens[first : last + 1] if t.end is not None]
        if starts and ends:
            return round(min(starts), 2), round(max(ends), 2)
    # A deletion has no transcript tokens. Point at the seam between the words
    # that surround where the missing content should have been.
    if fallback is not None and tokens:
        before = tokens[fallback - 1] if fallback > 0 else None
        after = tokens[fallback] if fallback < len(tokens) else None
        at = (before.end if before else None) or (after.start if after else None)
        if at is not None:
            return round(at, 2), round(at, 2)
    return None, None


def _confidence(
    tokens: Sequence[SourceToken], span: tuple[int, int] | None
) -> float | None:
    if span is None:
        return None
    first, last = span
    values = [t.p for t in tokens[first : last + 1] if t.p is not None]
    return round(min(values), 3) if values else None


def _context(sentences: Sequence[str], sentence_index: int | None) -> tuple[str, str]:
    if sentence_index is None:
        return "", ""
    before = sentences[sentence_index - 1] if sentence_index > 0 else ""
    after = (
        sentences[sentence_index + 1]
        if sentence_index + 1 < len(sentences)
        else ""
    )
    return before, after


def _suppress_asr_duplicates(
    pairs: list[tuple[Discrepancy, tuple[int, int] | None]],
    words: Sequence[dict],
    segments: Sequence[dict],
) -> tuple[list[Discrepancy], list[dict]]:
    """Drop single word insertions that are segment boundary duplication.

    Only insertions are eligible, which is what makes this safe. The token was
    already unmatched against the script, so removing it cannot turn into a
    false deletion. A word that is a suffix of its predecessor but does match
    the script, such as "demand," followed by "and", never reaches this code.
    """
    from .transcribe import boundary_duplicate_indices

    if not segments:
        return [d for d, _ in pairs], []

    flagged = boundary_duplicate_indices(words, segments)
    kept: list[Discrepancy] = []
    suppressed: list[dict] = []

    for discrepancy, span in pairs:
        single = span is not None and span[0] == span[1]
        index = span[0] if span is not None else None
        # Either this token is the duplicate, or the token after it is the
        # duplicate of this one. SequenceMatcher may flag either of the pair.
        artifact = (
            discrepancy.type == "insertion"
            and single
            and index is not None
            and (index in flagged or (index + 1) in flagged)
        )
        if artifact:
            suppressed.append(
                {
                    "voice_said": discrepancy.transcript_text,
                    "start_s": discrepancy.start_s,
                    "confidence": discrepancy.min_confidence,
                    "reason": "faster-whisper segment boundary duplication",
                }
            )
        else:
            kept.append(discrepancy)
    return kept, suppressed


def align_topic(
    sentences: Sequence[str],
    words: Sequence[dict],
    segments: Sequence[dict] | None = None,
) -> dict:
    """Align one scripted topic. Pure: takes data, returns data."""
    s_tokens = script_tokens(sentences)
    t_tokens = transcript_tokens(words)
    s_seq = build_sequence(s_tokens)
    t_seq = build_sequence(t_tokens)

    s_norm = [t.norm for t in s_seq]
    t_norm = [t.norm for t in t_seq]

    matcher = SequenceMatcher(a=s_norm, b=t_norm, autojunk=False)
    opcodes = matcher.get_opcodes()

    matched = sum(size for _, _, size in matcher.get_matching_blocks())
    coverage = matched / len(s_norm) if s_norm else 0.0

    # Tail check: did the last sentence of the script actually get spoken?
    # This is the deterministic replacement for the transcriber attestation
    # that quoted its FINAL SENTENCE, and unlike that attestation it cannot
    # be produced by an instrument that never reached the end of the audio.
    matched_script = set()
    for block in matcher.get_matching_blocks():
        matched_script.update(range(block.a, block.a + block.size))
    last_sentence = len(sentences) - 1 if sentences else None
    tail_matched = None
    if last_sentence is not None:
        tail_norm = [
            k for k, token in enumerate(s_seq)
            if any(s_tokens[i].sentence == last_sentence for i in token.src)
        ]
        tail_matched = bool(tail_norm) and all(k in matched_script for k in tail_norm)

    pairs: list[tuple[Discrepancy, tuple[int, int] | None]] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue

        s_span = _src_span(s_seq, i1, i2)
        t_span = _src_span(t_seq, j1, j2)

        script_text = join_originals(s_tokens, *s_span) if s_span else ""
        voice_text = join_originals(t_tokens, *t_span) if t_span else ""

        # A deletion points at the transcript position where content is absent.
        seam = None
        if t_span is None:
            seam_tokens = [i for token in t_seq[max(j1 - 1, 0) : j1 + 1] for i in token.src]
            seam = (max(seam_tokens) + 1) if seam_tokens else 0
        start_s, end_s = _timestamps(t_tokens, t_span, seam)

        sentence_index = (
            s_tokens[s_span[0]].sentence if s_span is not None else None
        )
        before, after = _context(sentences, sentence_index)
        confidence = _confidence(t_tokens, t_span)

        listen = False
        reason = ""
        if confidence is not None and confidence < LOW_CONFIDENCE:
            listen = True
            reason = f"ASR confidence {confidence} below {LOW_CONFIDENCE}"
        elif is_identifier(script_text) or is_identifier(voice_text):
            listen = True
            reason = "identifier or URL, voicing cannot be judged on paper"

        kind = {"replace": "substitution", "delete": "deletion", "insert": "insertion"}[tag]
        pairs.append(
            (
                Discrepancy(
                    type=kind,
                    script_text=script_text,
                    transcript_text=voice_text,
                    start_s=start_s,
                    end_s=end_s,
                    script_sentence=sentence_index,
                    script_sentence_text=(
                        sentences[sentence_index] if sentence_index is not None else ""
                    ),
                    context_before=before,
                    context_after=after,
                    min_confidence=confidence,
                    listen_item=listen,
                    reason=reason,
                ),
                t_span,
            )
        )

    discrepancies, suppressed = _suppress_asr_duplicates(
        pairs, words, segments or []
    )

    counts = {"substitution": 0, "deletion": 0, "insertion": 0}
    for item in discrepancies:
        counts[item.type] += 1

    return {
        "aligned": True,
        "script_tokens": len(s_norm),
        "transcript_tokens": len(t_norm),
        "matched_tokens": matched,
        "coverage": round(coverage, 4),
        "tail_matched": tail_matched,
        "final_script_sentence": sentences[-1] if sentences else "",
        "counts": counts,
        "listen_items": sum(1 for d in discrepancies if d.listen_item),
        "suppressed_asr_duplicates": suppressed,
        "over_diff_limit": len(discrepancies) > DIFF_LIMIT,
        "discrepancies": [d.to_dict() for d in discrepancies],
    }


# What the packet says about a topic that was not aligned, per script state.
UNALIGNED_REASON = {
    "outline": (
        "topic has no verbatim script; the script document carries an outline only"
    ),
    "none": (
        "topic has no script at all, so there is nothing to align against and "
        "the transcript is the whole of the evidence"
    ),
}


def unscripted_topic(
    words: Sequence[dict], segments: Sequence[dict], state: str = "outline"
) -> dict:
    """No alignment. Carry the transcript with timestamps for a human to read."""
    return {
        "aligned": False,
        "script": state,
        "reason": UNALIGNED_REASON.get(state, UNALIGNED_REASON["outline"]),
        "transcript_tokens": len(words),
        "segments": [
            {"start_s": s["start"], "end_s": s["end"], "text": s["text"]}
            for s in segments
        ],
        "low_confidence_words": [
            {"w": w["w"], "start_s": w["start"], "p": w["p"]}
            for w in words
            if w.get("p") is not None and w["p"] < LOW_CONFIDENCE
        ],
    }


def _add_transcript_checks(result: dict, transcript: dict, aligned: bool) -> None:
    """The two checks that need no script, attached to every topic's evidence.

    Voiced symbols run everywhere, because a script containing `project_plan`
    says nothing about whether reading it out as "project underscore plan" was
    meant. Unverifiable duplications run only where alignment did not, because
    where it did the same candidates are already suppressed with proof.
    """
    from .transcript_checks import unverifiable_duplications, voiced_symbols

    words = transcript.get("words") or []
    segments = transcript.get("segments") or []

    result["voiced_symbols"] = voiced_symbols(words)
    result["unverifiable_duplications"] = (
        [] if aligned else unverifiable_duplications(words, segments, LOW_CONFIDENCE)
    )


def run_align(course_dir: Path, force: bool = False) -> dict:
    """Stage entry point: script.json plus transcripts, out to discrepancies."""
    from .config import load_course_yaml

    cfg = load_course_yaml(course_dir)
    script_path = cfg.qa_work / "script.json"
    if not script_path.exists():
        raise AlignError(f"{script_path} not found. Run the script stage first.")
    script = read_json(script_path)
    by_topic = {t["topic"]: t for t in script["topics"]}

    rows: list[dict] = []
    for topic_id, entry in by_topic.items():
        transcript_path = cfg.qa_work / f"transcript_{topic_id}.json"
        if not transcript_path.exists():
            raise AlignError(
                f"{transcript_path} not found. Run the transcribe stage first."
            )
        transcript = read_json(transcript_path)

        state = entry.get("script") or ("verbatim" if entry["scripted"] else "outline")
        if entry["scripted"]:
            result = align_topic(
                entry["sentences"], transcript["words"], transcript["segments"]
            )
            result["script"] = state
        else:
            result = unscripted_topic(
                transcript["words"], transcript["segments"], state
            )

        _add_transcript_checks(result, transcript, aligned=entry["scripted"])

        result["topic"] = topic_id
        result["slides"] = entry.get("slides")
        result["source_ref"] = entry.get("source_ref", "")
        write_json(cfg.qa_work / f"discrepancies_{topic_id}.json", result)
        rows.append(
            {
                "topic": topic_id,
                "aligned": result["aligned"],
                "script": state,
                "coverage": result.get("coverage"),
                "counts": result.get("counts"),
                "discrepancies": len(result.get("discrepancies", [])),
                "listen_items": result.get("listen_items", 0),
                "suppressed": len(result.get("suppressed_asr_duplicates", [])),
                "voiced_symbols": sum(
                    g["occurrences"] for g in result.get("voiced_symbols", [])
                ),
                "unverifiable_duplications": len(
                    result.get("unverifiable_duplications", [])
                ),
            }
        )

    total = sum(r["discrepancies"] for r in rows)
    index = {"total_discrepancies": total, "topics": rows}
    write_json(cfg.qa_work / "discrepancies.json", index)
    return index
