"""Assembling a finished run into something a person can read.

Composition only. Every number here already exists in the pipeline's outputs;
nothing is computed that checks.py, align.py or the watchlist did not already
decide. If a figure is not in a stage's output it does not belong here.

One thing this module deliberately does not do: assign verdicts. CLEAN, FIX
RECOMMENDED and SHOWSTOPPER belong to the judgment step, together with the
Class 1 to 4 taxonomy, and putting them here would quietly move judgment out of
the reconciliation prompt and into an app that has no basis for it. What a
topic gets instead is a factual state: how many differences were found, how
many sites want a listen. That is a measurement, not a verdict, and the results
view says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .util import QAError, read_json

# What a topic's row says, in plain measured terms.
NO_DIFFERENCES = "no differences"
DIFFERENCES = "differences found"
LISTEN = "listen items"
FLAGGED = "check flag"
UNSCRIPTED = "outline only"


class ResultsError(QAError):
    pass


@dataclass
class ListenItem:
    """One place a human has to use their ears. The pipeline cannot settle it."""

    topic: str
    kind: str
    start_s: float | None
    what: str
    detail: str
    confidence: float | None = None
    # Another detector flagged the same spot. Alignment and the watchlist are
    # independent of each other, so agreement between them is a reason to
    # listen there first rather than a duplicate row to tidy away.
    corroborated: bool = False

    @property
    def timestamp(self) -> str:
        if self.start_s is None:
            return "n/a"
        minutes, rest = divmod(float(self.start_s), 60.0)
        return f"{int(minutes)}:{rest:05.2f}"


@dataclass
class TopicResult:
    topic: str
    slides: list[int]
    scripted: bool
    state: str
    coverage: float | None
    differences: int
    listen_items: int
    flags: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    audio_findings: list[str] = field(default_factory=list)
    suppressed: int = 0
    duration_s: float = 0.0


@dataclass
class Stats:
    """Telemetry, for the panel that is off by default.

    Everything is either recorded by a stage or measured about this machine.
    Nothing here is invented for the display.
    """

    engine: str = ""
    model: str = ""
    compute_type: str = ""
    device: str = ""
    device_requested: str = ""
    fallback_reason: str = ""
    cpu_threads: int | None = None
    beam_size: int | None = None
    vad: bool | None = None
    decode_seconds: float = 0.0
    audio_seconds: float = 0.0
    rate_realtime: float | None = None
    per_topic: list[dict] = field(default_factory=list)
    mean_coverage: float | None = None
    low_confidence_share: float | None = None
    suppressed_duplicates: int = 0
    anomalies: list[str] = field(default_factory=list)
    audio_conventions: dict = field(default_factory=dict)
    conventional_gaps: int = 0
    memory: dict = field(default_factory=dict)
    eta_basis: str = ""


@dataclass
class CourseResults:
    course_dir: Path
    course_code: str
    course_number: str
    project_type: str
    topic_count: int
    mean_coverage: float | None
    total_differences: int
    total_listen_items: int
    flagged_topics: list[str]
    topics: list[TopicResult] = field(default_factory=list)
    listen: list[ListenItem] = field(default_factory=list)
    watchlist: dict = field(default_factory=dict)
    packet_md: Path | None = None
    packet_json: Path | None = None
    stats: Stats = field(default_factory=Stats)

    @property
    def clean_topics(self) -> int:
        return sum(1 for t in self.topics if t.state == NO_DIFFERENCES)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _load(work: Path, name: str) -> dict | None:
    path = work / name
    if not path.exists():
        return None
    try:
        return read_json(path)
    except (ValueError, OSError):
        return None


def _topic_state(row: dict) -> str:
    if not row.get("scripted", True):
        return UNSCRIPTED
    if row.get("flags"):
        return FLAGGED
    if row.get("discrepancies"):
        return DIFFERENCES
    if row.get("listen_items"):
        return LISTEN
    return NO_DIFFERENCES


def collect_listen_items(work: Path, checks: dict) -> list[ListenItem]:
    """Every site the pipeline says a person must listen to.

    Two sources, deliberately merged into one list. A reviewer should not have
    to remember that alignment produces some listen items and the watchlist
    produces others; what they want is the list of places to put their ears.
    """
    items: list[ListenItem] = []

    for row in checks.get("topics", []):
        topic = row["topic"]
        data = _load(work, f"discrepancies_{topic}.json") or {}
        for site in data.get("discrepancies", []):
            if not site.get("listen_item"):
                continue
            items.append(
                ListenItem(
                    topic=topic,
                    kind="alignment",
                    start_s=site.get("start_s"),
                    what=(
                        f"script says {site.get('script_says') or '(nothing)'}, "
                        f"voice said {site.get('voice_said') or '(nothing)'}"
                    ),
                    detail=site.get("reason", ""),
                    confidence=site.get("min_confidence"),
                )
            )
        # An unscripted topic cannot be arbitrated on paper at all.
        if not row.get("scripted", True):
            items.append(
                ListenItem(
                    topic=topic,
                    kind="unscripted topic",
                    start_s=0.0,
                    what="the whole file",
                    detail=(
                        "the storyboard carries an outline rather than a script, "
                        "so no word level check is possible"
                    ),
                )
            )

    watchlist = checks.get("watchlist") or {}
    for site in watchlist.get("listen_items", []):
        items.append(
            ListenItem(
                topic=site.get("topic", ""),
                kind="pronunciation candidate",
                start_s=site.get("start_s"),
                what=f"{site.get('term')} heard as {site.get('heard')!r}",
                detail=(
                    f"{site.get('status')}. A match here would only mean the "
                    "expected spelling appeared, which is orthography, not "
                    "pronunciation."
                ),
                confidence=site.get("confidence"),
            )
        )

    items.sort(key=lambda i: (i.topic, i.start_s if i.start_s is not None else 0))

    # Mark sites two independent detectors both landed on.
    seen: dict[tuple[str, int], list[ListenItem]] = {}
    for item in items:
        if item.start_s is None:
            continue
        seen.setdefault((item.topic, round(item.start_s, 1)), []).append(item)
    for group in seen.values():
        if len({i.kind for i in group}) > 1:
            for item in group:
                item.corroborated = True
    return items


def build_stats(work: Path, checks: dict) -> Stats:
    """Telemetry the stages already recorded, plus what this machine is."""
    from .device import memory

    stats = Stats(memory=memory(), eta_basis="")

    transcripts = _load(work, "transcripts.json") or {}
    settings = transcripts.get("settings") or {}
    stats.engine = transcripts.get("engine", "")
    stats.model = transcripts.get("model") or settings.get("model", "")
    stats.compute_type = settings.get("compute_type", "")
    stats.device = transcripts.get("device_used") or settings.get("device", "")
    stats.device_requested = (
        transcripts.get("requested_device") or settings.get("requested_device") or ""
    )
    stats.fallback_reason = transcripts.get("fallback_reason") or ""
    stats.cpu_threads = settings.get("cpu_threads")
    stats.beam_size = settings.get("beam_size")
    stats.vad = settings.get("vad")

    for row in transcripts.get("topics", []):
        stats.per_topic.append(
            {
                "topic": row.get("topic"),
                "audio_s": row.get("duration_s"),
                "decode_s": row.get("decode_seconds"),
                "realtime": (
                    round(row["duration_s"] / row["decode_seconds"], 2)
                    if row.get("duration_s") and row.get("decode_seconds")
                    else None
                ),
                "words": row.get("word_count"),
                "anomalies": row.get("anomaly_count"),
            }
        )
        stats.decode_seconds += row.get("decode_seconds") or 0.0
        stats.audio_seconds += row.get("duration_s") or 0.0
    if stats.decode_seconds:
        stats.rate_realtime = round(stats.audio_seconds / stats.decode_seconds, 2)
        stats.eta_basis = (
            f"{stats.audio_seconds / 60:.1f} min of audio decoded in "
            f"{stats.decode_seconds / 60:.1f} min, measured on this machine"
        )

    summary = checks.get("summary", {})
    stats.mean_coverage = summary.get("mean_coverage")
    stats.suppressed_duplicates = summary.get("total_suppressed", 0)

    rows = checks.get("topics", [])
    shares = [r.get("low_confidence_share") for r in rows if r.get("low_confidence_share")]
    stats.low_confidence_share = round(sum(shares) / len(shares), 4) if shares else None
    stats.anomalies = sorted({a for r in rows for a in r.get("asr_anomalies", [])})

    artifacts = _load(work, "artifacts.json") or {}
    stats.audio_conventions = artifacts.get("conventions") or {}
    stats.conventional_gaps = artifacts.get("conventional_gaps", 0)
    return stats


def find_packet(course_dir: Path) -> tuple[Path | None, Path | None]:
    """The most recent packet, and its JSON twin."""
    out = Path(course_dir) / "qa_out"
    if not out.is_dir():
        return None, None
    packets = sorted(out.glob("reconciliation_packet_*.md"))
    if not packets:
        return None, None
    markdown = packets[-1]
    payload = markdown.with_suffix(".json")
    return markdown, (payload if payload.exists() else None)


def load_results(course_dir: Path) -> CourseResults:
    """Everything a finished run has to say, composed for reading."""
    course_dir = Path(course_dir)
    work = course_dir / "qa_work"
    checks = _load(work, "checks.json")
    if checks is None:
        raise ResultsError(
            f"No results for {course_dir.name} yet.\n"
            "  Run the course first; results appear when the checks stage has run."
        )

    summary = checks.get("summary", {})
    topics = [
        TopicResult(
            topic=row["topic"],
            slides=row.get("slides", []),
            scripted=row.get("scripted", True),
            state=_topic_state(row),
            coverage=row.get("coverage"),
            differences=row.get("discrepancies", 0),
            listen_items=row.get("listen_items", 0),
            flags=row.get("flags", []),
            anomalies=row.get("asr_anomalies", []),
            audio_findings=row.get("audio_findings", []),
            suppressed=row.get("suppressed_asr_duplicates", 0),
            duration_s=row.get("duration_s", 0.0),
        )
        for row in checks.get("topics", [])
    ]

    markdown, payload = find_packet(course_dir)
    return CourseResults(
        course_dir=course_dir,
        course_code=summary.get("course_code", ""),
        course_number=summary.get("course_number", ""),
        project_type=summary.get("project_type", ""),
        topic_count=summary.get("topic_count", len(topics)),
        mean_coverage=summary.get("mean_coverage"),
        total_differences=summary.get("total_discrepancies", 0),
        total_listen_items=summary.get("total_listen_items", 0),
        flagged_topics=summary.get("flagged_topics", []),
        topics=topics,
        listen=collect_listen_items(work, checks),
        watchlist=checks.get("watchlist") or {},
        packet_md=markdown,
        packet_json=payload,
        stats=build_stats(work, checks),
    )
