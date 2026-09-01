"""Module 9: reconciliation packet.

Assembles everything the judgment step needs into one markdown file a person
drags into a Claude chat, plus the same data as JSON for phase 2.

The packet is evidence, not analysis. It states what the script says, what the
voice said, where in the audio, and how sure the instrument was. It reaches no
verdicts, because the verdicts are the prompt's job.

Length discipline applies to scripted topics only. An unscripted topic's
transcript runs its natural length, because for that file the transcript is
the only evidence a judge has.
"""

from __future__ import annotations

from datetime import date as date_type
from pathlib import Path

from .util import QAError, read_json, write_json

# Scripted topics beyond this many discrepancies list the worst and count the
# rest. A topic this noisy is usually a mapping problem, and dumping 200 rows
# buries the findings that matter in the ones that do not.
MAX_LISTED = 25


class PacketError(QAError):
    pass


def _fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    minutes, rest = divmod(float(seconds), 60.0)
    return f"{int(minutes):d}:{rest:05.2f}"


def _fmt_range(start: float | None, end: float | None) -> str:
    if start is None:
        return "n/a"
    if end is None or abs(end - start) < 0.01:
        return _fmt_time(start)
    return f"{_fmt_time(start)} to {_fmt_time(end)}"


def _count(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def _escape(text: str) -> str:
    """Keep pipes from breaking markdown tables."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _header(checks: dict, manifest: dict, transcripts: dict, run_date: str) -> list[str]:
    summary = checks["summary"]
    settings = transcripts["settings"]
    lines = [
        f"# Audio QA Reconciliation Packet: Course {summary['course_number']} "
        f"({summary['course_code']})",
        "",
        "| | |",
        "|---|---|",
        f"| Course | {summary['course_number']} ({summary['course_code']}) |",
        f"| Date | {run_date} |",
        f"| Project type | {summary['project_type']} |",
        f"| Storyboard | {manifest['storyboard']} |",
        f"| Topics | {summary['topic_count']} |",
        f"| ASR engine | {transcripts['engine']} {settings['model']}, "
        f"{settings['compute_type']}, beam {settings['beam_size']}, "
        f"VAD {'on' if settings['vad'] else 'off'} |",
        f"| Mean script coverage | {(summary['mean_coverage'] or 0) * 100:.2f} percent |",
        f"| Discrepancies | {summary['total_discrepancies']} |",
        f"| Listen items | {summary['total_listen_items']} |",
        "",
        "This packet was produced by a deterministic pipeline: ASR transcription,",
        "shared normalization of both sides, and token alignment against the",
        "storyboard script. There is no second transcriber to arbitrate, because",
        "there are no longer two instruments disagreeing. Word level differences",
        "below are alignment output, not judgments.",
        "",
    ]
    return lines


def _topic_map(checks: dict) -> list[str]:
    lines = ["## Topic to slide map", "", "| Topic | Slides | Duration | Scripted |", "|---|---|---|---|"]
    for row in checks["topics"]:
        first, last = row["slides"]
        span = f"{first}" if first == last else f"{first}-{last}"
        lines.append(
            f"| {row['topic']} | {span} | {_fmt_time(row['duration_s'])} | "
            f"{'yes' if row['scripted'] else 'no, demo outline only'} |"
        )
    lines.append("")
    return lines


def _conventions(artifacts_index: dict) -> list[str]:
    """State the measured house style, so absorbing it stays honest.

    Silences matching what the course does everywhere are treated as
    production convention rather than findings. That is only defensible if the
    convention itself is on the page, where a human can see that a course
    pads 3.00 s and decide whether 3.00 s is right.
    """
    c = artifacts_index.get("conventions") or {}
    lines = ["## Measured audio conventions", ""]
    lines += [
        f"Across {c.get('files', 0)} files this course opens with "
        f"{c.get('leading_pad_s')} s of silence, closes with "
        f"{c.get('trailing_pad_s')} s, and pauses about {c.get('slide_gap_s')} s "
        f"between slides ({c.get('slide_gap_count', 0)} such pauses measured).",
        "",
        f"{artifacts_index.get('conventional_gaps', 0)} pauses matched that house "
        "style and are reported here as convention rather than as findings. Only "
        "silences that deviate from it are listed per topic below. Any file with "
        "a rhythm of its own is judged against its own norm, which is stated in "
        "that topic's audio line.",
        "",
    ]
    return lines


def _checks_table(checks: dict) -> list[str]:
    lines = [
        "## Checks",
        "",
        "Pace is the transcript's rate against the rate this file's own script",
        "implies, so a slow or fast narrator does not register as a defect.",
        "Coverage is the share of script tokens matched in the transcript.",
        "",
        "| Topic | Coverage | Pace ratio | Tail matched | Script words | Voice words |"
        " Sentences (script/voice) | Low conf | Flags |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in checks["topics"]:
        coverage = f"{row['coverage'] * 100:.2f}%" if row["coverage"] is not None else "n/a"
        tail = {True: "yes", False: "NO", None: "n/a"}[row["tail_matched"]]
        pace = f"{row['pace_ratio']:.3f}" if row["pace_ratio"] is not None else "n/a"
        low = (
            f"{row['low_confidence_words']} ({(row['low_confidence_share'] or 0) * 100:.1f}%)"
            if row["low_confidence_words"] is not None
            else "n/a"
        )
        flags = ", ".join(row["flags"]) if row["flags"] else "none"
        script_words = (
            str(row["script_words"]) if row["scripted"] else "n/a (outline)"
        )
        script_sentences = str(row["script_sentences"]) if row["scripted"] else "n/a"
        lines.append(
            f"| {row['topic']} | {coverage} | {pace} | {tail} | {script_words} | "
            f"{row['transcript_words']} | {script_sentences}/"
            f"{row['transcript_sentences']} | {low} | {flags} |"
        )
    lines.append("")
    return lines


def _watchlist_section(checks: dict) -> list[str]:
    """The WATCHLIST table, or the one line that says there is no watchlist.

    The disclaimer in the header is not decoration. ASR emits orthography, so a
    MATCH here means the expected spelling appeared with reasonable confidence,
    not that the term was said correctly. Stating that on the page is what stops
    the judgment stage from reading a clean table as a pronunciation pass.
    """
    watchlist = checks.get("watchlist")
    if not watchlist:
        return []

    lines = ["## Watchlist", ""]
    if not watchlist.get("present"):
        lines += [watchlist.get("reason", "No watchlist for this learning path."), ""]
        return lines

    totals = watchlist["totals"]
    lines += [
        "Jargon and acronym terms checked explicitly at every site, independently",
        "of general alignment.",
        "",
        "This layer detects likely mispronunciation and routes it to a human; it "
        "never certifies pronunciation as correct or wrong.",
        "",
        "A matched term means the ASR wrote the expected spelling with reasonable",
        "confidence, which is not evidence about how it was voiced.",
        "",
        f"Watchlist: {watchlist['path']}, {_count(totals['terms'], 'term')}, "
        f"{_count(totals['occurrences'], 'occurrence')} across the course. "
        f"Confidence floor {watchlist['confidence_floor']}.",
        "",
        "| Term | Occurrences | Matched | Low confidence | Misheard | Worst site |"
        " Heard there |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in watchlist["terms"]:
        worst = row.get("worst")
        if worst and worst["status"] != "MATCH":
            where = f"{_fmt_time(worst['start_s'])} topic {worst['topic']}"
            confidence = (
                f" (p {worst['confidence']:.3f})"
                if worst["confidence"] is not None
                else ""
            )
            heard = f"{_escape(worst['heard']) or '(nothing)'}{confidence}"
        elif worst:
            where = "-"
            heard = "-"
        else:
            where = "not in this course"
            heard = "-"
        lines.append(
            f"| {_escape(row['term'])} | {row['occurrences']} | {row['matched']} | "
            f"{row['low_confidence']} | {row['misheard']} | {where} | {heard} |"
        )
    lines.append("")

    items = watchlist["listen_items"]
    if not items:
        lines += [
            "No watchlist term was misheard or decoded below the confidence floor.",
            "That is not a pronunciation pass; it means nothing on the list looks "
            "wrong on paper.",
            "",
        ]
        return lines

    lines += [
        f"**{_count(len(items), 'pronunciation candidate')}.** Each is a listen "
        "item, not a defect. Listen at the timestamp and decide.",
        "",
        "| Topic | Timestamp | Term | Heard | ASR confidence | Status |",
        "|---|---|---|---|---|---|",
    ]
    for item in items:
        confidence = (
            f"{item['confidence']:.3f}" if item["confidence"] is not None else "n/a"
        )
        lines.append(
            f"| {item['topic']} | {_fmt_time(item['start_s'])} | "
            f"{_escape(item['term'])} | {_escape(item['heard']) or '(nothing)'} | "
            f"{confidence} | {item['status']} |"
        )
    lines.append("")
    return lines


def _discrepancy_section(row: dict, discrepancies: dict) -> list[str]:
    items = discrepancies.get("discrepancies", [])
    lines: list[str] = []

    if not items:
        lines.append("No word level differences. The transcript matches the script.")
        lines.append("")
    else:
        listed = items[:MAX_LISTED]
        lines += [
            "| # | Type | Script says | Voice said | Timestamp | ASR confidence | Note |",
            "|---|---|---|---|---|---|---|",
        ]
        for number, item in enumerate(listed, 1):
            note = item["reason"] if item["listen_item"] else ""
            confidence = (
                f"{item['min_confidence']:.3f}"
                if item["min_confidence"] is not None
                else "n/a"
            )
            lines.append(
                f"| {number} | {item['type']} | {_escape(item['script_says']) or '(nothing)'} | "
                f"{_escape(item['voice_said']) or '(nothing)'} | "
                f"{_fmt_range(item['start_s'], item['end_s'])} | {confidence} | "
                f"{_escape(note)} |"
            )
        lines.append("")
        if len(items) > MAX_LISTED:
            lines += [
                f"{len(items) - MAX_LISTED} further differences are not listed. A topic "
                "this noisy usually indicates a topic to slide mapping error rather "
                "than a narration problem; check the mapping before treating these as "
                "defects.",
                "",
            ]
        for number, item in enumerate(listed, 1):
            sentence = item.get("script_sentence_text") or ""
            said = item["script_says"]
            if sentence and said and said in sentence:
                sentence = sentence.replace(said, f"**{said}**", 1)
            if not (sentence or item["context_before"] or item["context_after"]):
                continue
            parts = [
                p for p in (item["context_before"], sentence, item["context_after"]) if p
            ]
            lines.append(f"Context for {number}: ...{' '.join(parts)}...")
            lines.append("")

    suppressed = discrepancies.get("suppressed_asr_duplicates", [])
    if suppressed:
        words = ", ".join(f"\"{s['voice_said']}\" at {_fmt_time(s['start_s'])}" for s in suppressed)
        verb = "was" if len(suppressed) == 1 else "were"
        lines += [
            f"{_count(len(suppressed), 'ASR segment boundary duplication')} {verb} "
            f"suppressed as an engine artifact and is not narration: {words}."
            if len(suppressed) == 1
            else
            f"{_count(len(suppressed), 'ASR segment boundary duplication')} were "
            f"suppressed as engine artifacts and are not narration: {words}.",
            "",
        ]
    return lines


def _artifact_section(artifacts: dict) -> list[str]:
    findings = artifacts.get("findings", [])
    norm = artifacts.get("gap_norm_s")
    source = artifacts.get("gap_norm_source")
    gaps = artifacts.get("conventional_gaps", 0)
    pause = ""
    if norm is not None:
        pause = (
            f" Internal pauses: {gaps} at about {norm:.2f} s, matching this "
            f"{'file' if source == 'file' else 'course'}'s norm."
        )
    lines = [
        f"Audio: peak {artifacts['peak_dbfs']} dBFS, RMS {artifacts['rms_dbfs']} dBFS, "
        f"leading silence {artifacts['leading_silence_s']:.2f} s, trailing silence "
        f"{artifacts['trailing_silence_s']:.2f} s.{pause}",
        "",
    ]
    if not findings:
        lines += ["No audio artifacts detected.", ""]
        return lines
    lines += ["| Type | Timestamp | Severity | Detail |", "|---|---|---|---|"]
    for finding in findings:
        lines.append(
            f"| {finding['type']} | {_fmt_range(finding['start_s'], finding['end_s'])} | "
            f"{finding['severity']} | {_escape(finding['detail'])} |"
        )
    lines.append("")
    return lines


def _unscripted_section(script_entry: dict, transcript: dict, discrepancies: dict) -> list[str]:
    lines = [
        "This topic is a demonstration. The storyboard carries an outline, not",
        "verbatim narration, so no word level alignment is possible and none was",
        "attempted. The outline and the full transcript are both below so the",
        "narration can be judged against intent rather than against wording.",
        "",
        "**Storyboard outline**",
        "",
    ]
    for line in script_entry.get("outline", []):
        lines.append(f"> {line}")
        lines.append(">")
    lines += ["", "**Full transcript with timestamps**", ""]
    for segment in discrepancies.get("segments", []):
        lines.append(f"- `{_fmt_time(segment['start_s'])}` {segment['text']}")
    lines.append("")

    low = discrepancies.get("low_confidence_words", [])
    if low:
        lines += [
            f"**Low confidence words in this transcript ({len(low)})**. These are "
            "listen items, not defects, and for a demo they are the places where "
            "the transcript itself is least certain.",
            "",
            "| Word | Timestamp | Confidence |",
            "|---|---|---|",
        ]
        for word in low:
            lines.append(
                f"| {_escape(word['w'])} | {_fmt_time(word['start_s'])} | {word['p']:.3f} |"
            )
        lines.append("")
    return lines


def build_packet(
    checks: dict,
    manifest: dict,
    transcripts: dict,
    script: dict,
    per_topic: dict[str, dict],
    artifacts_index: dict,
    run_date: str,
) -> str:
    """Render the markdown packet. Pure: takes loaded data, returns text."""
    lines: list[str] = []
    lines += _header(checks, manifest, transcripts, run_date)
    lines += _topic_map(checks)
    lines += _conventions(artifacts_index)
    lines += _checks_table(checks)
    lines += _watchlist_section(checks)

    lines += ["## Per topic evidence", ""]
    for row in checks["topics"]:
        topic = row["topic"]
        first, last = row["slides"]
        span = f"{first}" if first == last else f"{first}-{last}"
        lines += [f"### Topic {topic} (slides {span})", ""]
        data = per_topic[topic]
        if row["scripted"]:
            lines += _discrepancy_section(row, data["discrepancies"])
        else:
            lines += _unscripted_section(
                data["script"], data["transcript"], data["discrepancies"]
            )
        lines += _artifact_section(data["artifacts"])

    lines += [
        "## Open items for the judgment step",
        "",
        f"- {_count(checks['summary']['total_listen_items'], 'site is', 'sites are')} "
        "marked as a listen item because ASR confidence was below 0.6 or the text "
        "is an identifier whose voicing cannot be judged on paper.",
        f"- {_count(checks['summary']['total_suppressed'], 'segment boundary duplication')} "
        "suppressed as engine artifacts. They are listed per topic above.",
    ]
    watchlist = checks.get("watchlist") or {}
    if watchlist.get("present"):
        candidates = len(watchlist["listen_items"])
        lines.append(
            f"- {_count(candidates, 'watchlist site is', 'watchlist sites are')} "
            "flagged as a pronunciation candidate. These are listen items only; "
            "the packet carries no evidence of how any term was voiced."
        )
    flagged = checks["summary"]["flagged_topics"]
    if flagged:
        lines.append(f"- Topics carrying check flags: {', '.join(flagged)}.")
    else:
        lines.append("- No topic carries a check flag.")
    lines.append("")
    return "\n".join(lines)


def run_packet(
    course_dir: Path, force: bool = False, run_date: str | None = None
) -> dict:
    """Stage entry point. run_date is injectable so golden tests reproduce."""
    from .config import load_course_yaml

    cfg = load_course_yaml(course_dir)
    work = cfg.qa_work

    def load(name: str) -> dict:
        path = work / name
        if not path.exists():
            raise PacketError(f"{path} not found. Run the earlier stages first.")
        return read_json(path)

    checks = load("checks.json")
    artifacts_index = load("artifacts.json")
    manifest = load("manifest.json")
    transcripts = load("transcripts.json")
    script = {t["topic"]: t for t in load("script.json")["topics"]}

    per_topic = {
        row["topic"]: {
            "script": script[row["topic"]],
            "transcript": load(f"transcript_{row['topic']}.json"),
            "discrepancies": load(f"discrepancies_{row['topic']}.json"),
            "artifacts": load(f"artifacts_{row['topic']}.json"),
        }
        for row in checks["topics"]
    }

    stamp = run_date or date_type.today().isoformat()
    text = build_packet(
        checks, manifest, transcripts, script, per_topic, artifacts_index, stamp
    )

    cfg.qa_out.mkdir(parents=True, exist_ok=True)
    name = f"reconciliation_packet_{manifest['course_code']}_{stamp}"
    md_path = cfg.qa_out / f"{name}.md"
    md_path.write_text(text + "\n", encoding="utf-8")

    payload = {
        "generated": stamp,
        "checks": checks,
        "manifest": manifest,
        "transcripts": transcripts,
        "topics": {
            topic: {
                "script": data["script"],
                "discrepancies": data["discrepancies"],
                "artifacts": data["artifacts"],
            }
            for topic, data in per_topic.items()
        },
    }
    write_json(cfg.qa_out / f"{name}.json", payload)

    words = len(text.split())
    result = {
        "path": str(md_path),
        "json_path": str(cfg.qa_out / f"{name}.json"),
        "words": words,
        "estimated_pages": round(words / 500.0, 1),
        "lines": len(text.splitlines()),
    }
    # Stable marker so the CLI can tell the stage has run; the packet itself
    # carries the run date in its filename and must not be overwritten by a
    # later run with a different date.
    write_json(cfg.qa_out / "packet_index.json", result)
    return result
