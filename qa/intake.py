"""Standardized intake: files from anywhere, into the library, verified.

The user hands the app a storyboard and a pile of media from wherever the
browser dropped them. This module derives everything the filenames carry,
copies the files into the library in the standard layout, verifies every copy
by hash, and writes course.yaml. Only then is the course ingested.

No UI code lives here. The web pages call this; so could anything else.

Three rules the design turns on:

Copy, never move. The delivery in Downloads is the only copy of customer
material until this succeeds. Removing it is a separate, explicit act.

Verify before declaring success. A truncated copy that nobody noticed would
surface much later as a transcription that disagrees with the storyboard, and
the hours between those two events are what make it expensive. Hashing every
copy costs seconds.

Derive, never ask twice. Everything the filenames carry is read with the
scaffolder's own parser, so intake and qa-new-course cannot drift apart. The
form asks only what a filename cannot answer.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .config import PROJECT_TYPES
from .ingest import MEDIA_SUFFIXES, sniff_container
from .library import course_path, is_ingested, library_root
from .new_course import Delivery, parse_delivery_name, render_course_yaml
from .util import QAError, sha256_file

STORYBOARD_SUFFIXES = {".pptx"}

# Where a browser drops things. Suggestions only; the app never acts on a guess.
DOWNLOAD_HINTS = ("Downloads", "Desktop", "OneDrive/Downloads")

# How recent a file has to be to be worth suggesting.
RECENT_DAYS = 14


class IntakeError(QAError):
    pass


# ---------------------------------------------------------------------------
# What a selection of files says about itself
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MediaFile:
    path: Path
    topic: str
    container: str
    is_video: bool

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class Selection:
    """A validated set of files that all belong to one course."""

    delivery: Delivery
    storyboard: Path | None
    media: tuple[MediaFile, ...]
    ignored: tuple[Path, ...] = ()

    @property
    def topics(self) -> list[str]:
        return sorted({m.topic for m in self.media})

    @property
    def video_topics(self) -> list[str]:
        return sorted({m.topic for m in self.media if m.is_video})

    @property
    def learning_path(self) -> str:
        return self.delivery.learning_path

    @property
    def course_number(self) -> str:
        return self.delivery.course_number

    @property
    def course_code(self) -> str:
        return self.delivery.course_code


def _classify(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in STORYBOARD_SUFFIXES:
        return "storyboard"
    if suffix in MEDIA_SUFFIXES:
        return "media"
    return "other"


def _is_video(path: Path) -> bool:
    """Sniff the header rather than trusting the extension, as ingest does."""
    try:
        container = sniff_container(path)
    except OSError:
        return False
    return container in {"mp4", "mov", "mkv", "webm", "avi"}


def read_selection(paths: list[Path] | list[str]) -> Selection:
    """Derive the course from a set of selected files.

    Uses the scaffolder's parser, so a filename this accepts is exactly a
    filename qa-new-course accepts. Files that are neither storyboard nor
    media are set aside rather than rejected, because a delivery folder
    routinely carries a stray PDF or thumbnail.
    """
    chosen = [Path(p) for p in paths]
    if not chosen:
        raise IntakeError("No files selected.")

    missing = [p for p in chosen if not p.is_file()]
    if missing:
        listed = "\n  ".join(str(p) for p in missing)
        raise IntakeError(f"These selected files do not exist:\n  {listed}")

    storyboards = [p for p in chosen if _classify(p) == "storyboard"]
    media_paths = [p for p in chosen if _classify(p) == "media"]
    ignored = tuple(p for p in chosen if _classify(p) == "other")

    if len(storyboards) > 1:
        listed = ", ".join(p.name for p in storyboards)
        raise IntakeError(
            f"More than one storyboard selected: {listed}.\n"
            "  A course has exactly one storyboard."
        )
    if not media_paths:
        raise IntakeError(
            "No narration files selected.\n"
            "  Select the mp3 or mp4 files delivered for this course."
        )

    parsed = [(p, parse_delivery_name(p.name)) for p in media_paths]
    courses = {(d.learning_path, d.course_code) for _, d in parsed}
    if len(courses) > 1:
        listed = ", ".join(sorted(code for _, code in courses))
        raise IntakeError(
            f"The selected files span more than one course: {listed}.\n"
            "  Submit one course at a time."
        )

    media = tuple(
        MediaFile(
            path=path,
            topic=delivery.topic,
            container=sniff_container(path),
            is_video=_is_video(path),
        )
        for path, delivery in sorted(parsed, key=lambda pair: pair[1].topic)
    )

    duplicates = sorted(
        {m.topic for m in media if [x.topic for x in media].count(m.topic) > 1}
    )
    if duplicates:
        raise IntakeError(
            "More than one file was selected for the same topic: "
            + ", ".join(duplicates)
            + "\n  Each topic has exactly one narration file."
        )

    return Selection(
        delivery=parsed[0][1],
        storyboard=storyboards[0] if storyboards else None,
        media=media,
        ignored=ignored,
    )


# ---------------------------------------------------------------------------
# The form's answers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IntakeForm:
    """What the filenames cannot answer, plus who is running it."""

    project_type: str
    unscripted_topics: tuple[str, ...] = ()
    device: str = "cpu"
    reviewed_by: str = ""
    notes: str = ""

    def validate(self, selection: Selection) -> None:
        if self.project_type.upper() not in PROJECT_TYPES:
            allowed = " or ".join(sorted(PROJECT_TYPES))
            raise IntakeError(
                f"project_type '{self.project_type}' is not recognized. Use {allowed}."
            )
        known = set(selection.topics)
        unknown = [t for t in self.unscripted_topics if t not in known]
        if unknown:
            raise IntakeError(
                "Outline-only topics that were not delivered: "
                + ", ".join(unknown)
                + "\n  Delivered topics are: "
                + ", ".join(selection.topics)
            )
        if not self.reviewed_by.strip():
            raise IntakeError(
                "Reviewed by is required, so the packet records who ran the course."
            )


# ---------------------------------------------------------------------------
# Copying into the library
# ---------------------------------------------------------------------------

@dataclass
class CopiedFile:
    source: Path
    destination: Path
    sha256: str
    verified: bool


@dataclass
class IntakeResult:
    course_dir: Path
    resubmission: bool
    copied: list[CopiedFile] = field(default_factory=list)
    changed_topics: list[str] = field(default_factory=list)
    unchanged_topics: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def sources(self) -> list[Path]:
        return [c.source for c in self.copied]


def _copy_verified(source: Path, destination: Path) -> CopiedFile:
    """Copy one file and prove the copy is byte identical.

    The hash is taken from the source before the copy and from the destination
    after it, rather than trusting shutil. A half written file on a full disk
    is the case this exists for.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected = sha256_file(source)
    temporary = destination.with_name(destination.name + ".part")
    try:
        shutil.copy2(source, temporary)
        actual = sha256_file(temporary)
        if actual != expected:
            raise IntakeError(
                f"Copy of {source.name} does not match the original.\n"
                f"  source      {expected}\n"
                f"  copy        {actual}\n"
                "  Nothing was ingested. Check the disk and the source file, "
                "then try again."
            )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return CopiedFile(
        source=source, destination=destination, sha256=expected, verified=True
    )


def existing_hashes(course_dir: Path) -> dict[str, str]:
    """Topic to source hash, from the last run's manifest, if there is one.

    This is how a re-submission knows which files actually changed. The
    manifest already carries a hash per topic; nothing new is recorded here.
    """
    manifest = Path(course_dir) / "qa_work" / "manifest.json"
    if not manifest.exists():
        return {}
    try:
        import json

        data = json.loads(manifest.read_text(encoding="utf-8"))
        return {t["topic"]: t["source_sha256"] for t in data.get("topics", [])}
    except (OSError, ValueError, KeyError):
        return {}


def ingest_selection(
    selection: Selection,
    form: IntakeForm,
    library: Path | None = None,
    overwrite_yaml: bool = True,
) -> IntakeResult:
    """Copy a validated selection into the library and write course.yaml.

    Returns before any pipeline work happens. Nothing here transcribes.
    """
    form.validate(selection)

    root = library_root(library, create=True)
    course_dir = course_path(root, selection.learning_path, selection.course_number)
    resubmission = is_ingested(course_dir)
    before = existing_hashes(course_dir) if resubmission else {}

    result = IntakeResult(course_dir=course_dir, resubmission=resubmission)

    if selection.storyboard is None:
        result.warnings.append(
            "No storyboard was selected. The pipeline needs exactly one .pptx "
            "in the course folder before it can run."
        )

    audio_dir = course_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    if selection.storyboard is not None:
        result.copied.append(
            _copy_verified(
                selection.storyboard, course_dir / selection.storyboard.name
            )
        )

    for item in selection.media:
        copied = _copy_verified(item.path, audio_dir / item.name)
        result.copied.append(copied)
        previous = before.get(item.topic)
        if previous is None:
            result.changed_topics.append(item.topic)
        elif previous == copied.sha256:
            result.unchanged_topics.append(item.topic)
        else:
            result.changed_topics.append(item.topic)

    course_yaml = course_dir / "course.yaml"
    if overwrite_yaml or not course_yaml.exists():
        course_yaml.write_text(
            render_intake_yaml(selection, form), encoding="utf-8"
        )

    if resubmission and result.unchanged_topics:
        result.warnings.append(
            f"{len(result.unchanged_topics)} of {len(selection.media)} files are "
            "unchanged since the last run and will not be transcribed again."
        )
    return result


def render_intake_yaml(selection: Selection, form: IntakeForm) -> str:
    """course.yaml as qa-new-course writes it, with the answers filled in.

    The scaffolder's template is the source of truth for the comments and the
    key order; this fills in the two things the form knows and the scaffolder
    leaves as a TODO.
    """
    text = render_course_yaml(selection.delivery, form.project_type.upper())

    if form.unscripted_topics:
        listed = ", ".join(f'"{t}"' for t in sorted(form.unscripted_topics))
        text = text.replace(
            "# TODO: fill this in after reviewing the storyboard, using the topic ids from\n"
            "# the delivered filenames (for example [\"09\"]). Leave it empty if every topic\n"
            "# is scripted.\n"
            "unscripted_topics: []",
            "# Confirmed at intake.\n"
            f"unscripted_topics: [{listed}]",
        )

    trailer = ["", "# Recorded at intake."]
    if form.reviewed_by.strip():
        trailer.append(f"reviewed_by: {_yaml_scalar(form.reviewed_by.strip())}")
    if form.notes.strip():
        trailer.append(f"notes: {_yaml_scalar(form.notes.strip())}")
    return text.rstrip("\n") + "\n" + "\n".join(trailer) + "\n"


def _yaml_scalar(value: str) -> str:
    """Quote a free text value so a colon or a hash cannot break the file."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = " ".join(escaped.split())
    return f'"{escaped}"'


# ---------------------------------------------------------------------------
# Optional helpers
# ---------------------------------------------------------------------------

def remove_originals(result: IntakeResult) -> list[Path]:
    """Delete the source files, only when a human asks for it.

    Never called automatically and never called before the copies have been
    verified, which ingest_selection has already done for every file it
    reports.
    """
    removed: list[Path] = []
    for copied in result.copied:
        if not copied.verified:
            continue
        if not copied.destination.exists():
            continue
        if sha256_file(copied.destination) != copied.sha256:
            continue
        try:
            copied.source.unlink()
            removed.append(copied.source)
        except OSError:
            continue
    return removed


def find_recent_deliveries(
    search_dirs: list[Path] | None = None, days: int = RECENT_DAYS
) -> list[Selection]:
    """Look where browsers drop things and suggest what looks like a course.

    A suggestion the user confirms, never an action. Anything that does not
    parse as a delivery filename is simply not suggested.
    """
    import time

    if search_dirs is None:
        home = Path.home()
        search_dirs = [home / hint for hint in DOWNLOAD_HINTS]

    cutoff = time.time() - days * 86400
    candidates: dict[tuple[str, str], list[Path]] = {}

    for directory in search_dirs:
        directory = Path(directory)
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if not path.is_file() or path.suffix.lower() not in MEDIA_SUFFIXES:
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            try:
                delivery = parse_delivery_name(path.name)
            except QAError:
                continue
            candidates.setdefault(
                (delivery.learning_path, delivery.course_code), []
            ).append(path)

    suggestions: list[Selection] = []
    for paths in candidates.values():
        try:
            suggestions.append(read_selection(paths))
        except QAError:
            continue
    return sorted(
        suggestions, key=lambda s: (s.learning_path, int(s.course_number))
    )
