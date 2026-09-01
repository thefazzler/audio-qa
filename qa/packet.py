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

from datetime import date as date_type, datetime
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
        f"| Script source | {_script_source_line(manifest)} |",
        f"| Topics | {summary['topic_count']} |",
        f"| ASR engine | {transcripts['engine']} {settings['model']}, "
        f"{settings['compute_type']}, beam {settings['beam_size']}, "
        f"VAD {'on' if settings['vad'] else 'off'} |",
        f"| Device | {_device_line(transcripts)} |",
        f"| Decode | {_decode_line(transcripts)} |",
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


def _script_source_line(manifest: dict) -> str:
    """Which document the script came from, and what kind of document it is.

    This replaced a row that said "Storyboard" and named a pptx. A CGT course
    has no storyboard at all, so that row was about to start printing a Word
    filename under a heading that said PowerPoint.
    """
    from .script_source import describe_source

    document = manifest.get("script_document") or manifest.get("storyboard")
    source = manifest.get("script_source") or ""
    if not source:
        return document or "not recorded"
    return describe_source(source, document)


def _decode_line(transcripts: dict) -> str:
    """Wall time, realtime factor and the machine, on the durable record.

    These were only ever on a stats panel in the web interface, which is not
    where anyone reads a finished run six months later. "23 minutes to 4" was
    written down nowhere.
    """
    rows = transcripts.get("topics") or []
    decode = sum(row.get("decode_seconds") or 0.0 for row in rows)
    audio = sum(row.get("duration_s") or 0.0 for row in rows)
    machine = transcripts.get("machine") or "not recorded"
    if not decode:
        return f"no decode this run, transcripts reused; on {machine}"
    rate = f"{audio / decode:.2f}x realtime" if audio else "rate not measurable"
    return (
        f"{decode / 60.0:.1f} min to decode {audio / 60.0:.1f} min of audio "
        f"({rate}), on {machine}"
    )


def _device_line(transcripts: dict) -> str:
    """What was asked for, what ran, and why they differ.

    A run that fell back to CPU part way through must say so on the packet
    itself. Anyone reading the findings later is entitled to know what
    produced them.
    """
    requested = transcripts.get("requested_device") or "auto"
    used = transcripts.get("device_used") or (
        (transcripts.get("settings") or {}).get("device") or "cpu"
    )
    reason = transcripts.get("fallback_reason")
    if not reason:
        return f"requested {requested}, decoded on {used}"
    after = transcripts.get("fallback_after_topic")
    where = f" from topic {after}" if after else ""
    return (
        f"requested {requested}, decoded on {used}{where} after: {reason}"
    )


def _source_span(row: dict) -> str:
    """Where in the script document this topic came from.

    Slides for a storyboard, the block heading for a BUS document, the file
    name for a freeform script. One column, because the reader's question is
    the same in all three cases: where do I go and look?
    """
    slides = row.get("slides")
    if slides and len(slides) == 2:
        first, last = slides
        return f"slides {first}" if first == last else f"slides {first}-{last}"
    return row.get("source_ref") or "n/a"


def _topic_map(checks: dict, script: dict | None = None) -> list[str]:
    from .script_source import STATE_NOTE

    lines = [
        "## Topic map",
        "",
        "| Topic | Script source | Script | Duration |",
        "|---|---|---|---|",
    ]
    for row in checks["topics"]:
        state = row.get("script") or ("verbatim" if row["scripted"] else "outline")
        lines.append(
            f"| {row['topic']} | {_escape(_source_span(row))} | "
            f"{STATE_NOTE.get(state, state)} | {_fmt_time(row['duration_s'])} |"
        )
    lines.append("")
    lines += _author_estimates(script or {})
    lines += _dropped_blocks(script or {})
    return lines


def _author_estimates(script: dict) -> list[str]:
    """What the script's own author expected each topic to run to.

    A source-side pacing reference and deliberately not a threshold. The
    pipeline's own pace check compares the transcript against the script it was
    read from, which is a ratio and is immune to how fast a given voice talks
    (D6). This is a different thing: the number a human wrote down before
    anyone recorded anything. Worth having on the page when a topic reads long
    or short, and worth nobody turning into a limit.
    """
    rows = [t for t in script.get("topics", []) if t.get("author_word_count")]
    if not rows:
        return []
    lines = [
        "The script document states a word count and an estimated duration per "
        "topic, written by its author. They are reported here as a pacing "
        "reference from the source side. Nothing in the pipeline compares "
        "against them and nothing should: a threshold built from them would be "
        "a threshold built from an estimate.",
        "",
        "| Topic | Author's word count | Extracted | Author's estimate |",
        "|---|---|---|---|",
    ]
    for row in rows:
        extracted = row.get("word_count")
        stated = row.get("author_word_count")
        note = "" if extracted == stated else f" ({extracted - stated:+d})"
        lines.append(
            f"| {row['topic']} | {stated} | {extracted}{note} | "
            f"{_escape(row.get('author_estimate') or 'n/a')} |"
        )
    lines.append("")
    return lines


def _dropped_blocks(script: dict) -> list[str]:
    """Blocks the extractor did not treat as topics, and why.

    A dropped block is a silent decision about how many topics a course has,
    and it moves every later block's file assignment by one if it is wrong. So
    it is stated on the page rather than left in a log.
    """
    dropped = (script.get("mapping") or {}).get("dropped_blocks") or []
    if not dropped:
        return []
    lines = [
        f"{_count(len(dropped), 'block')} in the script document "
        f"{'was' if len(dropped) == 1 else 'were'} not treated as a topic, "
        "because nothing is delivered for them and so nothing can be checked. "
        "They are listed here because dropping one that is really a topic would "
        "shift every topic after it onto the wrong audio file.",
        "",
        "| Block | Title | Words | Why it was dropped |",
        "|---|---|---|---|",
    ]
    for item in dropped:
        lines.append(
            f"| {item.get('block')} | {_escape(item.get('title', ''))} | "
            f"{item.get('word_count')} | {_escape(item.get('reason', ''))} |"
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


def _voiced_symbol_section(discrepancies: dict) -> list[str]:
    """Where the voice said the name of a symbol out loud.

    Listen items, never defects, and grouped by term rather than by site: the
    question "was reading `project_plan` as 'project underscore plan' meant?"
    is answered once for all twelve occurrences, not twelve times.
    """
    groups = discrepancies.get("voiced_symbols") or []
    if not groups:
        return []
    total = sum(g["occurrences"] for g in groups)
    lines = [
        f"**Voiced symbols: {_count(total, 'site')} across "
        f"{_count(len(groups), 'term')}.** The voice spoke the name of a symbol "
        "or a URL part, which is what a synthetic voice does when it reads an "
        "identifier such as `project_plan` literally. These are listen items, "
        "not defects: a narrator does sometimes say \"underscore\" on purpose.",
        "",
        "| Term | Sites | Timestamps | Heard in context |",
        "|---|---|---|---|",
    ]
    for group in groups:
        stamps = ", ".join(_fmt_time(s["start_s"]) for s in group["sites"])
        example = group["sites"][0].get("context", "")
        lines.append(
            f"| {_escape(group['term'])} | {group['occurrences']} | "
            f"{_escape(stamps)} | {_escape(example)} |"
        )
    lines.append("")
    return lines


def _unverifiable_duplication_section(discrepancies: dict) -> list[str]:
    """Boundary duplications that no script is available to settle."""
    found = discrepancies.get("unverifiable_duplications") or []
    if not found:
        return []
    lines = [
        f"**Possible segment boundary duplication, unverifiable without a "
        f"script: {_count(len(found), 'site')}.** On a scripted topic these are "
        "suppressed as engine artifacts, which is safe only because alignment "
        "has already proved the script has one word there. Here that proof does "
        "not exist, so they are listed rather than dropped. One pass with "
        "headphones settles all of them.",
        "",
        "| Heard | Timestamp | ASR confidence | Context |",
        "|---|---|---|---|",
    ]
    for item in found:
        confidence = (
            f"{item['confidence']:.3f}" if item["confidence"] is not None else "n/a"
        )
        if item.get("low_confidence"):
            confidence += " (low)"
        lines.append(
            f"| {_escape(item['heard'])} | {_fmt_time(item['start_s'])} | "
            f"{confidence} | {_escape(item.get('context', ''))} |"
        )
    lines.append("")
    return lines


def _unscripted_section(script_entry: dict, transcript: dict, discrepancies: dict) -> list[str]:
    state = script_entry.get("script") or "outline"
    if state == "none":
        lines = [
            "This topic has no script. Nothing in the delivery says what the",
            "voice was supposed to say, so no word level alignment is possible",
            "and none was attempted. The full transcript is below and is the",
            "whole of the evidence; the two checks that need no script follow",
            "it.",
            "",
        ]
    else:
        lines = [
            "This topic is a demonstration. The script document carries an",
            "outline, not verbatim narration, so no word level alignment is",
            "possible and none was attempted. The outline and the full",
            "transcript are both below so the narration can be judged against",
            "intent rather than against wording.",
            "",
            "**Script outline**",
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
    """Render the markdown packet. Pure: takes loaded data, returns text.

    `script` is the whole of script.json, because the packet reports what the
    extractor decided as well as what it extracted: which blocks it dropped,
    and which part of the document each topic came from.
    """
    lines: list[str] = []
    lines += _header(checks, manifest, transcripts, run_date)
    lines += _topic_map(checks, script)
    lines += _conventions(artifacts_index)
    lines += _checks_table(checks)
    lines += _watchlist_section(checks)

    lines += ["## Per topic evidence", ""]
    for row in checks["topics"]:
        topic = row["topic"]
        lines += [f"### Topic {topic} ({_source_span(row)})", ""]
        data = per_topic[topic]
        if row["scripted"]:
            lines += _discrepancy_section(row, data["discrepancies"])
        else:
            lines += _unscripted_section(
                data["script"], data["transcript"], data["discrepancies"]
            )
        lines += _unverifiable_duplication_section(data["discrepancies"])
        lines += _voiced_symbol_section(data["discrepancies"])
        lines += _artifact_section(data["artifacts"])

    summary = checks["summary"]
    lines += [
        "## Open items for the judgment step",
        "",
        f"- {_count(summary['total_listen_items'], 'site is', 'sites are')} "
        "marked as a listen item because ASR confidence was below 0.6 or the text "
        "is an identifier whose voicing cannot be judged on paper.",
        f"- {_count(summary['total_suppressed'], 'segment boundary duplication')} "
        "suppressed as engine artifacts. They are listed per topic above.",
    ]
    if summary.get("total_voiced_symbols"):
        lines.append(
            f"- {_count(summary['total_voiced_symbols'], 'site is', 'sites are')} "
            "a voiced symbol or URL part. Listen items, not defects."
        )
    if summary.get("total_unverifiable_duplications"):
        lines.append(
            f"- {_count(summary['total_unverifiable_duplications'], 'site is', 'sites are')} "
            "a possible segment boundary duplication that no script is available "
            "to confirm. Listen items, not defects."
        )
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


# How a device is written in a packet's filename. "cuda" is the runtime's word
# for it; "gpu" is everyone else's, and this name is read by people.
DEVICE_NAMES = {"cuda": "gpu", "cpu": "cpu"}


def packet_stem(manifest: dict, transcripts: dict, stamp: str, clock: str) -> str:
    """Course, timestamp and device, so a packet names the run that made it.

    The old name was course plus date, so a second run on the same day
    overwrote the first silently. That is precisely the case where comparing
    the two matters most: before a fix and after it, or CPU against GPU. See
    D28.
    """
    settings = transcripts.get("settings") or {}
    device = transcripts.get("device_used") or settings.get("device") or "cpu"
    compute = settings.get("compute_type") or "unknown"
    label = DEVICE_NAMES.get(device, device)
    return f"{manifest['course_code']}_{stamp}_{clock}_{label}-{compute}"


def _unclaimed(directory: Path, stem: str) -> str:
    """A stem nothing has taken, so no packet is ever overwritten.

    The timestamp usually settles it. This is for the case it does not: two
    runs of the same course on the same device inside the same minute, which
    happens when a re-run is scripted.
    """
    if not (directory / f"{stem}.md").exists():
        return stem
    for suffix in range(2, 100):
        candidate = f"{stem}_{suffix}"
        if not (directory / f"{candidate}.md").exists():
            return candidate
    raise PacketError(
        f"Ninety-nine packets already exist for {stem} in {directory}. "
        "Move some out of the way."
    )


def run_packet(
    course_dir: Path,
    force: bool = False,
    run_date: str | None = None,
    output_dir: Path | str | None = None,
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
    script = load("script.json")
    by_topic = {t["topic"]: t for t in script["topics"]}

    per_topic = {
        row["topic"]: {
            "script": by_topic[row["topic"]],
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

    from .library import output_root

    destination = output_root(output_dir, create=True)
    name = _unclaimed(
        destination,
        packet_stem(manifest, transcripts, stamp, datetime.now().strftime("%H%M")),
    )
    md_path = destination / f"{name}.md"
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
    write_json(destination / f"{name}.json", payload)

    words = len(text.split())
    result = {
        "path": str(md_path),
        "json_path": str(destination / f"{name}.json"),
        "output_dir": str(destination),
        "words": words,
        "estimated_pages": round(words / 500.0, 1),
        "lines": len(text.splitlines()),
    }
    # Stable marker in the course folder so the CLI can tell the stage has run
    # and anything downstream can find the packet without knowing where the
    # output folder is. The packet itself lives in the output folder, is named
    # for the run that made it, and is never overwritten.
    cfg.qa_out.mkdir(parents=True, exist_ok=True)
    write_json(cfg.qa_out / "packet_index.json", result)
    return result
