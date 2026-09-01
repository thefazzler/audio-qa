"""Scaffold a new course folder from the delivered filenames.

    qa-new-course <delivery>            derive from a folder of delivered media
    qa-new-course <a_filename>          derive from one delivered filename

Delivered narration is named `<domain>_<learning_path>_<course>_<locale>_<topic>`,
so `it_spisccc26_11_enus_01.mp3` already carries everything this command needs
except one thing:

    learning path   spisccc26           second segment, the folder above the course
    course number   11                  third segment
    course_code     it_spisccc26_11_enus  prefix through the locale segment

The one question the filenames cannot answer is whether the course is VENDOR or
CGT, so that is the only prompt.

File formats are deliberately not asked about. Ingest sniffs each delivered
file's header and demuxes anything that is not already readable audio, per
DECISIONS.md D1, so a course.yaml has nothing to say about mp3 against mp4.

This command creates the folder, its audio/ subfolder and course.yaml. Copying
the delivered media and the storyboard into place stays a human step: the media
is Skillsoft source material and the command has no business moving it around.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import PROJECT_TYPES
from .ingest import MEDIA_SUFFIXES
from .util import ScaffoldError

# Where course folders live. This used to be the relative path Path("tests"),
# which resolved against the working directory rather than the repo root as
# its comment claimed, so running the scaffolder from anywhere else made a
# stray tests/ folder there. Courses now go to the library, which is an
# absolute path outside the repository. See DECISIONS.md D17.
def default_root() -> Path:
    from .library import library_root

    return library_root()

# <domain>_<learning_path>_<course>_<locale>_<topic ...>
DELIVERY_NAME = re.compile(
    r"^(?P<domain>[a-z0-9]+)"
    r"_(?P<path>[a-z0-9]+)"
    r"_(?P<course>\d+)"
    r"_(?P<locale>[a-z]{4})"
    r"_(?P<topic>\d+(?:_\d+)*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Delivery:
    """What one delivered filename says about the course it belongs to."""

    learning_path: str
    course_number: str
    course_code: str
    topic: str

    @property
    def course_folder(self) -> str:
        """Zero padded, so course01 sorts ahead of course10 in any listing."""
        return f"course{int(self.course_number):02d}"


def parse_delivery_name(name: str) -> Delivery:
    stem = Path(name).stem
    match = DELIVERY_NAME.match(stem)
    if not match:
        raise ScaffoldError(
            f"Cannot read a course out of the filename '{name}'.\n"
            "  Expected <domain>_<learning_path>_<course>_<locale>_<topic>, "
            "as in it_spisccc26_11_enus_01.mp3."
        )
    parts = match.groupdict()
    return Delivery(
        learning_path=parts["path"].lower(),
        course_number=parts["course"],
        course_code="_".join(
            (parts["domain"], parts["path"], parts["course"], parts["locale"])
        ).lower(),
        topic=parts["topic"],
    )


def read_delivery(target: Path) -> tuple[Delivery, list[str]]:
    """Derive the course from a delivery folder, or from a single filename.

    Returns the course facts plus the topic ids seen, so the operator can check
    the count against what was actually delivered before any audio is copied.
    A folder whose files disagree about the course is a hard stop: that is two
    courses in one delivery folder, and guessing which one is meant would only
    move the mistake downstream.
    """
    if target.is_dir():
        media = sorted(
            p for p in target.iterdir()
            if p.is_file() and p.suffix.lower() in MEDIA_SUFFIXES
        )
        if not media:
            raise ScaffoldError(
                f"No media files in {target}.\n"
                "  Point this at the delivery folder, or pass one delivered "
                "filename directly."
            )
        names = [p.name for p in media]
    else:
        names = [target.name]

    parsed = [parse_delivery_name(n) for n in names]
    courses = {(d.learning_path, d.course_code) for d in parsed}
    if len(courses) > 1:
        listed = ", ".join(sorted(code for _, code in courses))
        raise ScaffoldError(
            f"{target} holds more than one course: {listed}.\n"
            "  Scaffold one course at a time."
        )
    topics = sorted({d.topic for d in parsed})
    return parsed[0], topics


COURSE_YAML = """\
# Course {number} of the {path} learning path.
# Deliberately no slide_map: the auto-mapper infers the topic-to-slide map from
# the storyboard and is hard checked against the delivered file count. Add one
# here only if the mapper halts with PROBABLE MAPPING ERROR.
course_number: "{number}"
project_type: {project_type}
course_code: {code}

# Topics whose slides carry an outline rather than verbatim narration, such as
# screen-capture demos. They are excluded from word-level alignment and their
# transcripts run at full length in the packet.
# TODO: fill this in after reviewing the storyboard, using the topic ids from
# the delivered filenames (for example ["09"]). Leave it empty if every topic
# is scripted.
unscripted_topics: []
"""


def render_course_yaml(delivery: Delivery, project_type: str) -> str:
    return COURSE_YAML.format(
        number=delivery.course_number,
        path=delivery.learning_path,
        project_type=project_type,
        code=delivery.course_code,
    )


def ask_project_type(stream=None) -> str:
    """The one thing the filenames cannot tell us.

    Takes the stream rather than calling input() so a test can drive it, and so
    a piped answer behaves the same as a typed one. The terminal supplies the
    newline after a typed answer; a pipe does not, hence the isatty check.
    """
    stream = stream or sys.stdin
    echoes = getattr(stream, "isatty", lambda: False)()
    while True:
        print("  project_type [VENDOR/CGT]: ", end="", flush=True)
        line = stream.readline()
        if not line:
            raise ScaffoldError(
                "No answer given for project_type.\n"
                "  Run this interactively, or pass --project-type VENDOR|CGT."
            )
        answer = line.strip().upper()
        if answer in PROJECT_TYPES:
            if not echoes:
                print(answer)
            return answer
        if not echoes:
            print(answer or "(blank)")
        print(f"    '{line.strip()}' is not VENDOR or CGT. Try again.")


def scaffold(
    delivery: Delivery, root: Path, project_type: str, force: bool = False
) -> Path:
    course_dir = root / delivery.learning_path / delivery.course_folder
    course_yaml = course_dir / "course.yaml"
    if course_yaml.exists() and not force:
        raise ScaffoldError(
            f"{course_yaml} already exists.\n"
            "  This course is already scaffolded. Pass --force to overwrite "
            "its course.yaml, or edit it by hand."
        )

    (course_dir / "audio").mkdir(parents=True, exist_ok=True)
    course_yaml.write_text(render_course_yaml(delivery, project_type), encoding="utf-8")
    return course_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qa-new-course",
        description=(
            "Scaffold tests/<learning_path>/<course>/ and its course.yaml from "
            "the delivered audio filenames."
        ),
        epilog=(
            "the learning path, course number and course_code are read out of "
            "the filenames;\nproject_type is the only prompt. Copying the media "
            "and the storyboard in stays\na human step."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "delivery",
        type=Path,
        help="delivery folder, or one delivered filename to read the course from",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="where learning paths live (default: the course library)",
    )
    parser.add_argument(
        "--project-type",
        choices=sorted(PROJECT_TYPES),
        help="answer the project_type prompt up front, for scripted use",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing course.yaml",
    )
    args = parser.parse_args(argv)

    try:
        delivery, topics = read_delivery(args.delivery)
        print(f"audio-qa: scaffolding from {args.delivery}")
        print()
        print(f"  learning path   {delivery.learning_path}")
        print(f"  course number   {delivery.course_number}")
        print(f"  course_code     {delivery.course_code}")
        print(f"  topics seen     {len(topics)}  ({', '.join(topics)})")
        print()

        project_type = args.project_type or ask_project_type()
        course_dir = scaffold(
            delivery, args.root or default_root(), project_type, args.force
        )
    except ScaffoldError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130

    print()
    print(f"  created {course_dir.as_posix()}/")
    print("          course.yaml")
    print("          audio/")
    print()
    print("  next, by hand:")
    print(f"    1. copy the {len(topics)} delivered files into "
          f"{(course_dir / 'audio').as_posix()}/")
    print(f"    2. drop the storyboard .pptx into {course_dir.as_posix()}/")
    print("    3. review the storyboard and list any outline-only topics under")
    print("       unscripted_topics in course.yaml")
    print(f"    4. qa-run {course_dir.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
