"""Freeing disk space without losing what a run found.

A course costs about 225 MB in the library and almost none of it is the
answer. Measured on Course 10: 172 MB of delivered narration, a 46 MB demuxed
wav, a 5.5 MB storyboard — and 0.8 MB of JSON that is the entire finding.

So the split is not "big files and small files". It is **what a machine can
make again** against **what a run discovered**:

    qa_work/audio/*.wav   derived from the delivered media, seconds to rebuild
    audio/, the script    customer material, downloadable again from SharePoint
    qa_work/*.json        what this run found. Nothing else can produce it.
    qa_out/               where the packet went

Everything in the first two groups can go. Nothing in the last two ever does.

**Why every qa_work JSON is kept, including the per-topic files.** The listen
list is rebuilt from `discrepancies_<topic>.json`, one per topic, every time
the Results tab is opened. Delete those and the page does not fail: it says
"Nothing on the listen list", which reads as a course with nothing to listen
to. That is a silent false clearance in the one place this tool exists to be
loud, and it would cost 0.8 MB to avoid. So the whole of qa_work's JSON stays,
and reclaiming a course still returns better than 99 percent of its size.

Two tiers, because they cost different things:

**Scratch** is the demuxed wav alone. Derived, rebuilt by the ingest stage in
seconds, and the course stays runnable. There is no reason not to.

**Media** is the delivered narration and the script document. The course stops
being runnable until it is ingested again, and everything a completed run
found stays readable. That is the trade, and it is stated before it is made.

Packets are never touched by either. They live outside the library on purpose
(D28) and the run history is the folder they sit in. They have their own
archive, in `archive_packets`.

Nothing here deletes without being asked, every path is checked to be inside
the folder it claims to be in before it is unlinked, and a course with a run
in progress is refused. See DECISIONS.md D31.
"""

from __future__ import annotations

import json
import re
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .library import library_root, list_courses, normalize, output_root
from .util import QAError

WORK = "qa_work"
OUT = "qa_out"
MEDIA = "audio"
SCRATCH = "audio"  # under qa_work
MARKER = "reclaimed.json"

# Documents at the course root that are the course's script. course.yaml is
# not one of them and is never removed: it is what makes the folder a course.
SCRIPT_SUFFIXES = (".pptx", ".docx", ".doc", ".txt", ".rtf")

SCRATCH_KEY = "scratch"
MEDIA_KEY = "media"

# What this tool writes into the packet folder, and therefore the only things
# the Storage tab may offer to archive or delete from it. The folder is chosen
# by a human and can be anything, including Documents; a survey that globbed
# every .md and .json there would list files this tool never wrote, and the
# delete path only checks that a file is inside the folder. See D35.
#
# A packet stem is <course_code>_<YYYY-MM-DD>_<HHMM>_<device>-<compute>, with
# an optional _<n> when two runs share a minute; see packet.packet_stem. An
# archive is packets_<YYYY-MM-DD>.zip with the same optional suffix.
PACKET_NAME = re.compile(
    r"^[a-z0-9]+(?:_[a-z0-9]+)*_\d{4}-\d{2}-\d{2}_\d{4}_(?:cpu|gpu)-[a-z0-9_]+"
    r"(?:_\d+)?\.(?:md|json)$",
    re.IGNORECASE,
)
ARCHIVE_NAME = re.compile(r"^packets_\d{4}-\d{2}-\d{2}(?:_\d+)?\.zip$", re.IGNORECASE)


def is_packet(path: Path) -> bool:
    """Whether a file is named the way this tool names packets."""
    return bool(PACKET_NAME.match(Path(path).name))


def is_archive(path: Path) -> bool:
    return bool(ARCHIVE_NAME.match(Path(path).name))


class CleanupError(QAError):
    pass


# ---------------------------------------------------------------------------
# Looking, which never changes anything
# ---------------------------------------------------------------------------

def _size(paths) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def _files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.rglob("*") if p.is_file())


@dataclass(frozen=True)
class Bucket:
    """One group of files, and what removing it would cost."""

    key: str
    label: str
    paths: tuple[Path, ...]
    bytes: int
    note: str = ""

    @property
    def count(self) -> int:
        return len(self.paths)

    @property
    def present(self) -> bool:
        return bool(self.paths)


@dataclass
class CourseSpace:
    """What one course is using, and what of it is reclaimable."""

    course_dir: Path
    label: str
    scratch: Bucket
    media: Bucket
    kept_bytes: int
    reclaimed_at: str = ""
    running: str = ""

    @property
    def total_bytes(self) -> int:
        return self.scratch.bytes + self.media.bytes + self.kept_bytes

    @property
    def reclaimable_bytes(self) -> int:
        return self.scratch.bytes + self.media.bytes

    @property
    def runnable(self) -> bool:
        """Whether a run could still start: the delivered media is still here."""
        return self.media.present

    def bucket(self, key: str) -> Bucket:
        return self.scratch if key == SCRATCH_KEY else self.media


def _script_documents(course_dir: Path) -> list[Path]:
    return sorted(
        p
        for p in course_dir.glob("*")
        if p.is_file() and p.suffix.lower() in SCRIPT_SUFFIXES
    )


def reclaimed_at(course_dir: Path) -> str:
    """When this course's media was last removed, or "" if it is still here."""
    marker = Path(course_dir) / WORK / MARKER
    if not marker.is_file():
        return ""
    try:
        return str(json.loads(marker.read_text(encoding="utf-8")).get("at", ""))
    except (OSError, ValueError):
        return ""


def survey(course_dir: Path, store=None) -> CourseSpace:
    """What this course is using. Reads only; deletes nothing."""
    course_dir = Path(course_dir)
    work = course_dir / WORK

    scratch_files = _files(work / SCRATCH)
    media_files = _files(course_dir / MEDIA) + _script_documents(course_dir)

    kept = [
        p
        for p in _files(work) + _files(course_dir / OUT)
        if (work / SCRATCH) not in p.parents
    ]
    kept += [p for p in [course_dir / "course.yaml"] if p.is_file()]

    return CourseSpace(
        course_dir=course_dir,
        label=f"{course_dir.parent.name} / {course_dir.name}",
        scratch=Bucket(
            SCRATCH_KEY,
            "Scratch audio",
            tuple(scratch_files),
            _size(scratch_files),
            "Demuxed from the delivered files. Rebuilt in seconds; the course "
            "stays runnable.",
        ),
        media=Bucket(
            MEDIA_KEY,
            "Delivered media and script",
            tuple(media_files),
            _size(media_files),
            "The narration and the script document. Download them again to "
            "run this course.",
        ),
        kept_bytes=_size(kept),
        reclaimed_at=reclaimed_at(course_dir),
        running=_running(course_dir, store),
    )


def library_survey(root: Path | None = None, store=None) -> list[CourseSpace]:
    """Every ingested course, largest reclaimable first."""
    courses = list_courses(Path(root) if root else library_root())
    spaces = [survey(course.path, store) for course in courses]
    return sorted(spaces, key=lambda s: s.reclaimable_bytes, reverse=True)


def _running(course_dir: Path, store=None) -> str:
    """The id of a run in progress for this course, or "".

    The same guard `qa.jobs.submit` uses, asked of the operating system rather
    than of the record, so a run whose process died does not lock a course out
    of being tidied up forever. See D29.
    """
    from .jobs import running_for

    job = running_for(course_dir, store)
    return job.id if job else ""


# ---------------------------------------------------------------------------
# Removing, which is asked for explicitly and says what it did
# ---------------------------------------------------------------------------

@dataclass
class Reclaimed:
    course_dir: Path
    removed: list[Path] = field(default_factory=list)
    freed_bytes: int = 0
    failed: list[tuple[Path, str]] = field(default_factory=list)
    buckets: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failed


def _inside(path: Path, root: Path) -> bool:
    """Whether `path` really sits under `root`, links not followed.

    The guard that makes a bug here a refusal rather than an incident. Nothing
    is unlinked without passing it, so a survey that somehow collected a path
    from elsewhere deletes nothing.
    """
    try:
        normalize(path).relative_to(normalize(root))
    except ValueError:
        return False
    return True


def _protected(path: Path, course_dir: Path) -> bool:
    """Files that are never removed, whatever a caller asks for.

    Every finding a run produced, plus the file that makes the folder a
    course. Belt and braces: no bucket collects these in the first place.
    """
    if path.name == "course.yaml" and path.parent == course_dir:
        return True
    if (course_dir / OUT) in path.parents:
        return True
    work = course_dir / WORK
    return work in path.parents and (work / SCRATCH) not in path.parents


def reclaim(
    course_dir: Path,
    media: bool = False,
    store=None,
) -> Reclaimed:
    """Remove this course's scratch audio, and its delivered media when asked.

    Always keeps every finding. Refuses outright while a run is in progress:
    deleting the wav a running transcribe is reading would fail the run
    halfway through and leave a course nobody could explain.
    """
    course_dir = Path(course_dir)
    if not (course_dir / "course.yaml").is_file():
        raise CleanupError(
            f"{course_dir} is not an ingested course, so there is nothing here "
            "to reclaim safely."
        )

    space = survey(course_dir, store)
    if space.running:
        raise CleanupError(
            f"A run for this course is in progress ({space.running}).\n"
            "  Wait for it to finish. Removing files underneath a running "
            "transcribe would fail it halfway through."
        )

    buckets = [space.scratch] + ([space.media] if media else [])
    result = Reclaimed(course_dir=course_dir, buckets=tuple(b.key for b in buckets))

    for bucket in buckets:
        for path in bucket.paths:
            if not _inside(path, course_dir) or _protected(path, course_dir):
                result.failed.append((path, "refused: outside the course or protected"))
                continue
            try:
                size = path.stat().st_size
                path.unlink()
            except OSError as exc:
                result.failed.append((path, str(exc)))
                continue
            result.removed.append(path)
            result.freed_bytes += size

    _prune_empty(course_dir / WORK / SCRATCH, course_dir)
    if media:
        _prune_empty(course_dir / MEDIA, course_dir)
        _write_marker(course_dir, result)
    return result


def _prune_empty(directory: Path, course_dir: Path) -> None:
    """An emptied folder goes too, but only ever an empty one inside the course."""
    if not directory.is_dir() or not _inside(directory, course_dir):
        return
    if any(directory.iterdir()):
        return
    try:
        directory.rmdir()
    except OSError:
        pass


def _write_marker(course_dir: Path, result: Reclaimed) -> None:
    """A course says so itself when its media has gone.

    Read by the Results tab and the run picker, so a course that cannot be run
    says why rather than failing at the ingest stage with a missing file.
    """
    work = course_dir / WORK
    work.mkdir(parents=True, exist_ok=True)
    (work / MARKER).write_text(
        json.dumps(
            {
                "at": time.strftime("%Y-%m-%d %H:%M"),
                "freed_bytes": result.freed_bytes,
                "files": len(result.removed),
                "note": (
                    "Delivered media removed to free disk space. Findings and "
                    "packets are untouched. Ingest the course again to run it."
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Packets: their own space, their own archive
# ---------------------------------------------------------------------------

@dataclass
class PacketSpace:
    directory: Path
    markdown: tuple[Path, ...] = ()
    payloads: tuple[Path, ...] = ()
    archives: tuple[Path, ...] = ()
    bytes: int = 0
    archived_bytes: int = 0

    @property
    def count(self) -> int:
        return len(self.markdown) + len(self.payloads)


def packet_space(output_dir: Path | None = None) -> PacketSpace:
    directory = Path(output_dir) if output_dir else output_root()
    if not directory.is_dir():
        return PacketSpace(directory=directory)
    markdown = sorted(p for p in directory.glob("*.md") if is_packet(p))
    payloads = sorted(p for p in directory.glob("*.json") if is_packet(p))
    archives = sorted(p for p in directory.glob("*.zip") if is_archive(p))
    return PacketSpace(
        directory=directory,
        markdown=tuple(markdown),
        payloads=tuple(payloads),
        archives=tuple(archives),
        bytes=_size(markdown + payloads),
        archived_bytes=_size(archives),
    )


@dataclass
class Archived:
    archive: Path | None = None
    packed: list[Path] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)
    bytes_before: int = 0
    bytes_after: int = 0
    failed: list[tuple[Path, str]] = field(default_factory=list)


def archive_packets(
    output_dir: Path | None = None,
    paths: list[Path] | None = None,
    delete: bool = False,
) -> Archived:
    """Zip packets into the folder they already live in, and optionally remove them.

    One zip beside them rather than somewhere else: the packet folder is the
    run history, and a history that is half here and half on a drive somebody
    remembers is not one. Deletion happens only after the archive is written
    and verified to contain every member, because the failure worth designing
    against is an archive that was not written and originals that were.
    """
    space = packet_space(output_dir)
    directory = space.directory
    chosen = [Path(p) for p in paths] if paths is not None else list(
        space.markdown + space.payloads
    )
    result = Archived(bytes_before=_size(chosen))
    if not chosen:
        return result

    for path in chosen:
        if not _inside(path, directory):
            raise CleanupError(
                f"{path} is not in the packet folder. Refusing to archive it."
            )
        if not is_packet(path):
            raise CleanupError(
                f"{path.name} is not a packet this tool wrote. Refusing to archive it."
            )

    directory.mkdir(parents=True, exist_ok=True)
    archive = _unused(directory / f"packets_{time.strftime('%Y-%m-%d')}.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in chosen:
            try:
                bundle.write(path, arcname=path.name)
            except OSError as exc:
                result.failed.append((path, str(exc)))
                continue
            result.packed.append(path)

    result.archive = archive
    result.bytes_after = _size([archive])

    if not delete:
        return result

    # Only what the archive can be seen to hold, read back from the file
    # rather than from the list that was just written to it.
    with zipfile.ZipFile(archive) as bundle:
        inside = set(bundle.namelist())
    for path in result.packed:
        if path.name not in inside:
            result.failed.append((path, "not found in the archive; kept"))
            continue
        try:
            path.unlink()
        except OSError as exc:
            result.failed.append((path, str(exc)))
            continue
        result.deleted.append(path)
    return result


def delete_packets(paths: list[Path], output_dir: Path | None = None) -> Archived:
    """Remove packets outright. Nothing to undo, which is why the UI asks twice."""
    directory = Path(output_dir) if output_dir else output_root()
    result = Archived(bytes_before=_size([Path(p) for p in paths]))
    for path in [Path(p) for p in paths]:
        if not _inside(path, directory):
            raise CleanupError(
                f"{path} is not in the packet folder. Refusing to delete it."
            )
        if not is_packet(path):
            raise CleanupError(
                f"{path.name} is not a packet this tool wrote. Refusing to delete it."
            )
        try:
            path.unlink()
        except OSError as exc:
            result.failed.append((path, str(exc)))
            continue
        result.deleted.append(path)
    return result


def _unused(path: Path) -> Path:
    """A name nothing has taken, so an archive never overwrites an archive."""
    if not path.exists():
        return path
    for n in range(2, 500):
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise CleanupError(f"Too many archives named like {path.name}.")


# ---------------------------------------------------------------------------

def human(size: float) -> str:
    """Bytes as somebody would say them."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
