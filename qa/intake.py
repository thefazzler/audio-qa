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
from .script_source import (
    DOCX_BUS,
    FREEFORM,
    NONE,
    OUTLINE,
    PPTX,
    SOURCE_LABEL,
    SOURCE_SUFFIX,
    TOPIC_STATES,
    VERBATIM,
    default_source,
)
from .util import QAError, sha256_file

STORYBOARD_SUFFIXES = {".pptx"}

# Documents that are not a storyboard: a CGT course's BUS script, and the
# occasional freeform script for one topic. Both arrive alongside the media and
# neither is media, so both used to be silently set aside as "other".
DOCUMENT_SUFFIXES = {".docx", ".txt"}

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
    documents: tuple[Path, ...] = ()

    def script_document(self, project_type: str) -> Path | None:
        """The document this project type's script source lives in, if present.

        Detected rather than asked: a VENDOR course's script is the pptx and a
        CGT course's is the docx, so once the project type is known the answer
        is already in the selection. Returns None when it is not, which the
        form turns into a stop rather than a guess.
        """
        source = default_source(project_type)
        if source == PPTX:
            return self.storyboard
        suffix = SOURCE_SUFFIX[source]
        found = [p for p in self.documents if p.suffix.lower() == suffix]
        return found[0] if len(found) == 1 else None

    def freeform_candidates(self, project_type: str) -> list[Path]:
        """Documents that could be one topic's own script, not the course's."""
        course_document = self.script_document(project_type)
        return [p for p in self.documents if p != course_document]

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
    if suffix in DOCUMENT_SUFFIXES:
        return "document"
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
    documents = tuple(sorted(p for p in chosen if _classify(p) == "document"))
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
        documents=documents,
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
    # Topic id to (state, document name). Only topics that are not verbatim
    # appear; outline-only topics may arrive here or in unscripted_topics.
    topic_scripts: dict[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def script_source(self) -> str:
        """Derived from the project type, never asked for. See D26."""
        return default_source(self.project_type)

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

        if selection.script_document(self.project_type) is None:
            source = self.script_source
            raise IntakeError(
                f"A {self.project_type.upper()} course's script is a "
                f"{SOURCE_SUFFIX[source]} ({SOURCE_LABEL[source]}), and exactly "
                "one was not found among the selected files.\n"
                "  Select it and submit again. This is not guessed at: reading "
                "the wrong document would align the whole course against text "
                "that is not its script."
            )

        for topic, (state, document) in sorted(self.topic_scripts.items()):
            if topic not in known:
                raise IntakeError(
                    f"A script state was set for topic {topic}, which was not "
                    "delivered.\n  Delivered topics are: "
                    + ", ".join(selection.topics)
                )
            if state not in TOPIC_STATES:
                allowed = ", ".join(sorted(TOPIC_STATES))
                raise IntakeError(
                    f"Topic {topic} has script state '{state}', which is not one "
                    f"of {allowed}."
                )
            if state == FREEFORM and not document:
                raise IntakeError(
                    f"Topic {topic} is freeform but no script document was "
                    "chosen for it."
                )
            if state == FREEFORM and document not in {
                p.name for p in selection.freeform_candidates(self.project_type)
            }:
                raise IntakeError(
                    f"Topic {topic}'s freeform script {document!r} is not among "
                    "the selected files. Select it and submit again."
                )

        if not self.reviewed_by.strip():
            raise IntakeError(
                "Reviewed by is required, so the packet records who ran the course."
            )

    def resolved_scripts(self) -> dict[str, tuple[str, str]]:
        """Every non-verbatim topic, with the two ways of saying so merged."""
        merged: dict[str, tuple[str, str]] = {
            topic: (OUTLINE, "") for topic in self.unscripted_topics
        }
        merged.update(
            {
                topic: (state, document)
                for topic, (state, document) in self.topic_scripts.items()
                if state != VERBATIM
            }
        )
        return merged


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

    audio_dir = course_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # The course's own script document, plus any freeform script a topic uses.
    # Everything else that was selected but is not media stays where it is.
    course_document = selection.script_document(form.project_type)
    freeform = {
        document
        for _, (state, document) in form.resolved_scripts().items()
        if state == FREEFORM and document
    }
    for document in [course_document] + [
        p for p in selection.freeform_candidates(form.project_type) if p.name in freeform
    ]:
        if document is None:
            continue
        result.copied.append(_copy_verified(document, course_dir / document.name))

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

    resolved = form.resolved_scripts()
    outline = sorted(t for t, (state, _) in resolved.items() if state == OUTLINE)
    if outline:
        listed = ", ".join(f'"{t}"' for t in outline)
        text = _replace_once(
            text,
            "# TODO: fill this in after reviewing the storyboard, using the topic ids from\n"
            "# the delivered filenames (for example [\"09\"]). Leave it empty if every topic\n"
            "# is scripted.\n"
            "unscripted_topics: []",
            "# Confirmed at intake.\n"
            f"unscripted_topics: [{listed}]",
        )

    others = {t: v for t, v in resolved.items() if v[0] != OUTLINE}
    if others:
        entries = ", ".join(
            f'"{topic}": {{script: {state}'
            + (f", file: {document}" if document else "")
            + "}"
            for topic, (state, document) in sorted(others.items())
        )
        text = _replace_once(text, "topics: {}", "# Confirmed at intake.\n"
                             f"topics: {{{entries}}}")

    trailer = ["", "# Recorded at intake."]
    if form.reviewed_by.strip():
        trailer.append(f"reviewed_by: {_yaml_scalar(form.reviewed_by.strip())}")
    if form.notes.strip():
        trailer.append(f"notes: {_yaml_scalar(form.notes.strip())}")
    return text.rstrip("\n") + "\n" + "\n".join(trailer) + "\n"


def _replace_once(text: str, old: str, new: str) -> str:
    """Replace, and refuse to pretend it happened when it did not.

    A string replace whose pattern does not match changes nothing and reports
    success. That silently dropped several edits during this build, and here it
    would produce a course.yaml missing exactly the states the operator had
    just typed in. See HANDOVER.md, "A no-op edit is not an error".
    """
    if old not in text:
        raise IntakeError(
            "Could not write the script states into course.yaml: the template "
            f"no longer contains the block starting {old.splitlines()[0]!r}.\n"
            "  qa/new_course.py's COURSE_YAML and qa/intake.py have drifted "
            "apart; they have to be changed together."
        )
    return text.replace(old, new, 1)


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
