"""Module 1: command line entry point.

    qa-run <course_dir>                 run every stage in order
    qa-run --stage script <course_dir>  rerun one stage
    qa-run --force <course_dir>         ignore existing outputs

Every stage runs every time. The cheap stages cost about six seconds together,
and transcribe skips per topic on each file's hash, so a re-run after a vendor
returns one corrected file re-transcribes that topic and nothing else.
--force additionally re-transcribes everything.

Failures stop the run and print one specific message rather than a traceback.

Later stages are registered here as they are built.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .util import QAError


@dataclass(frozen=True)
class Stage:
    """One pipeline stage: what it is called, where it writes, how to run it.

    `output` is no longer used to decide whether to skip; it names the file the
    stage produces so callers, including the web layer's progress view, can
    find a stage's result without knowing the pipeline's internals.
    """

    name: str
    output: str
    run: Callable[[Path, bool], dict]
    summary: Callable[[dict], str]


def _ingest(course_dir: Path, force: bool) -> dict:
    from .config import load_course_yaml
    from .ingest import run_ingest

    cfg = load_course_yaml(course_dir)
    return run_ingest(course_dir, cfg.project_type, force=force)


def _ingest_summary(result: dict) -> str:
    counts = result["counts"]
    parts = [f"{counts['total']} files"]
    if counts["passthrough"]:
        parts.append(f"{counts['passthrough']} passthrough")
    if counts["demuxed"]:
        parts.append(f"{counts['demuxed']} demuxed")
    if counts["reused"]:
        parts.append(f"{counts['reused']} reused")
    return ", ".join(parts)


def _config(course_dir: Path, force: bool) -> dict:
    from .config import run_config

    return run_config(course_dir, force=force)


def _config_summary(manifest: dict) -> str:
    minutes = manifest["total_duration_s"] / 60.0
    return f"{manifest['topic_count']} topics, {minutes:.1f} min of audio"


def _script(course_dir: Path, force: bool) -> dict:
    from .extract_script import run_extract_script

    return run_extract_script(course_dir, force=force)


def _script_summary(script: dict) -> str:
    words = sum(t["word_count"] for t in script["topics"])
    source = script["mapping"]["source"]
    # A storyboard has slides and a Word script has blocks. Say whichever this
    # course actually has rather than printing "None slides" for half of them.
    slides = script.get("slide_count")
    extent = (
        f"{slides} slides"
        if slides
        else f"{script['mapping'].get('blocks_found', len(script['topics']))} blocks"
    )
    return (
        f"{len(script['topics'])} topics mapped ({source}), "
        f"{words} script words, {extent}"
    )


def _transcribe(course_dir: Path, force: bool) -> dict:
    from .transcribe import run_transcribe

    return run_transcribe(
        course_dir, force=force, overrides=_ASR_OVERRIDES, only_topics=_ONLY_TOPICS
    )


def _transcribe_summary(index: dict) -> str:
    """What this run did, not what the transcripts on disk cost to make.

    The line used to sum every row's decode time, so a stage that finished in
    1.7 seconds reported "4.7 min decode" next to its own elapsed time on the
    same row. The reader is entitled to assume a stage summary describes the
    stage that just ran.
    """
    topics = index["topics"]
    words = sum(t["word_count"] for t in topics)
    anomalies = sum(t["anomaly_count"] for t in topics)
    fresh = [t for t in topics if t.get("status") == "transcribed"]
    decode = sum(t["decode_seconds"] for t in fresh)

    head = f"{len(topics)} topics, {words} words, {anomalies} anomalies, {index['model']}"
    if not fresh:
        return f"{head}, nothing decoded, {len(topics)} transcripts reused"
    tail = f"{len(fresh)} decoded in {decode / 60.0:.1f} min"
    if len(fresh) < len(topics):
        tail += f", {len(topics) - len(fresh)} reused"
    return f"{head}, {tail}"


def _align(course_dir: Path, force: bool) -> dict:
    from .align import run_align

    return run_align(course_dir, force=force)


def _align_summary(result: dict) -> str:
    scripted = [t for t in result["topics"] if t["aligned"]]
    clean = sum(1 for t in scripted if t["discrepancies"] == 0)
    coverage = (
        sum(t["coverage"] for t in scripted) / len(scripted) if scripted else 0.0
    )
    listen = sum(t["listen_items"] for t in result["topics"])
    return (
        f"{result['total_discrepancies']} discrepancies across {len(scripted)} "
        f"scripted topics ({clean} clean), {coverage * 100:.1f} percent coverage, "
        f"{listen} listen items"
    )


def _artifacts(course_dir: Path, force: bool) -> dict:
    from .artifacts import run_artifacts

    return run_artifacts(course_dir, force=force)


def _artifacts_summary(result: dict) -> str:
    high = sum(r["high"] for r in result["topics"])
    return (
        f"{result['total_findings']} audio findings across "
        f"{len(result['topics'])} files, {high} high severity"
    )


def _checks(course_dir: Path, force: bool) -> dict:
    from .checks import run_checks

    return run_checks(course_dir, force=force)


def _checks_summary(result: dict) -> str:
    s = result["summary"]
    flagged = s["flagged_topics"]
    return (
        f"{s['topic_count']} topics, {(s['mean_coverage'] or 0) * 100:.2f} percent "
        f"mean coverage, {len(flagged)} flagged"
        + (f" ({', '.join(flagged)})" if flagged else "")
    )


def _packet(course_dir: Path, force: bool) -> dict:
    from .packet import run_packet

    return run_packet(
        course_dir,
        force=force,
        run_date=_RUN_DATE,
        output_dir=_OUTPUT_DIR,
        started_at=_RUN_STARTED,
    )


def _packet_summary(result: dict) -> str:
    return (
        f"{Path(result['path']).name}, {result['words']} words, "
        f"about {result['estimated_pages']} pages, in {result['output_dir']}"
    )


STAGES: tuple[Stage, ...] = (
    Stage("ingest", "qa_work/ingest.json", _ingest, _ingest_summary),
    Stage("config", "qa_work/manifest.json", _config, _config_summary),
    Stage("script", "qa_work/script.json", _script, _script_summary),
    Stage("transcribe", "qa_work/transcripts.json", _transcribe, _transcribe_summary),
    Stage("align", "qa_work/discrepancies.json", _align, _align_summary),
    Stage("artifacts", "qa_work/artifacts.json", _artifacts, _artifacts_summary),
    Stage("checks", "qa_work/checks.json", _checks, _checks_summary),
    Stage("packet", "qa_out/packet_index.json", _packet, _packet_summary),
)

# Set from the command line before any stage runs.
_ASR_OVERRIDES: dict = {}
_ONLY_TOPICS: list[str] | None = None
_RUN_DATE: str | None = None
_OUTPUT_DIR: str | None = None
# Wall clock time this run began. The packet's filename is built from it, so
# that both halves of the name come from one clock and both describe the run
# rather than the moment the last stage happened to finish. See D28.
_RUN_STARTED: float | None = None

STAGE_NAMES = tuple(s.name for s in STAGES)


_SEEN_WARNINGS: set[str] = set()


def _print_warnings(result: dict) -> None:
    """Print each warning once per run.

    Later stages carry earlier stages' warnings forward in their own output,
    which is right for the JSON and wrong for the console: without this the
    ingest warning prints again under config.
    """
    for warning in result.get("warnings", []):
        if warning in _SEEN_WARNINGS:
            continue
        _SEEN_WARNINGS.add(warning)
        print(f"        WARNING  {warning}")


def run(course_dir: Path, only: str | None, force: bool) -> int:
    if not course_dir.is_dir():
        raise QAError(
            f"Course folder does not exist: {course_dir}\n"
            "  Expected a folder holding course.yaml, one .pptx and audio/."
        )

    global _RUN_STARTED
    _RUN_STARTED = _RUN_STARTED or time.time()

    selected = [s for s in STAGES if only is None or s.name == only]
    rows: list[tuple[str, str, float]] = []
    started_run = time.monotonic()

    # Every stage runs, every time. Skipping a stage because its output file
    # existed short circuited the per-file hashes underneath it: a corrected
    # mp3 was never re-hashed, so the manifest kept the old hash and
    # transcribe never saw a change. The cheap stages total about six seconds
    # on a full course, and transcribe skips per topic on its own hashes
    # without loading the model, so an unchanged course still costs seconds.
    # See DECISIONS.md D17.
    for stage in selected:
        started = time.monotonic()
        result = stage.run(course_dir, force)
        elapsed = time.monotonic() - started
        summary = stage.summary(result)
        print(f"  [ok]   {stage.name:<10} {summary}  ({elapsed:.1f}s)", flush=True)
        _print_warnings(result)
        rows.append((stage.name, summary, elapsed))

    total = time.monotonic() - started_run
    print()
    print(f"  {'stage':<11}{'time':>8}  detail")
    print("  " + "-" * 76)
    for name, detail, elapsed in rows:
        print(f"  {name:<11}{elapsed:>7.1f}s  {detail}")
    print("  " + "-" * 76)
    print(f"  {'total':<11}{total:>7.1f}s")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qa-run",
        description="Local synthetic-voice QA pipeline.",
        epilog=(
            "stages run in order: " + " -> ".join(STAGE_NAMES) + "\n"
            "intermediates land in <course_dir>/qa_work/, "
            "the packet in <course_dir>/qa_out/"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("course_dir", type=Path, help="course folder to process")
    parser.add_argument(
        "--stage",
        choices=STAGE_NAMES,
        help="run only this stage",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebuild outputs even when they already exist",
    )
    parser.add_argument(
        "--model",
        help="ASR model, overriding course.yaml (large-v3, medium, ...)",
    )
    parser.add_argument(
        "--device",
        choices=("cpu", "cuda", "auto"),
        help=(
            "where to decode (default: auto, the fastest device that works). "
            "Device affects speed; see DECISIONS.md D23 for what it does to "
            "results."
        ),
    )
    parser.add_argument(
        "--threads",
        type=int,
        help="CPU threads for the ASR decode, overriding course.yaml",
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help=(
            "the date the packet states about itself, overriding today; keeps "
            "golden tests reproducible. Does not name the file: that is built "
            "from when the run started"
        ),
    )
    parser.add_argument(
        "--topic",
        action="append",
        metavar="ID",
        help="restrict per topic work to this topic; repeatable",
    )
    parser.add_argument(
        "--output",
        type=Path,
        metavar="DIR",
        help=(
            "where to write the finished packet (default: the configured "
            "output folder, Documents/audio-qa). Working files always stay in "
            "the course folder."
        ),
    )
    args = parser.parse_args(argv)

    global _ASR_OVERRIDES, _ONLY_TOPICS, _RUN_DATE, _OUTPUT_DIR
    _ASR_OVERRIDES = {
        "model": args.model,
        "cpu_threads": args.threads,
        "device": args.device,
    }
    _ONLY_TOPICS = args.topic
    _RUN_DATE = args.date
    _OUTPUT_DIR = str(args.output) if args.output else None

    course_dir = args.course_dir.resolve()
    print(f"audio-qa: {course_dir}", flush=True)
    try:
        return run(course_dir, args.stage, args.force)
    except QAError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
