"""Module 2: course configuration and file manifest.

Two jobs, deliberately separable:

  load_course_yaml()  reads and validates course.yaml. Cheap, no media access,
                      and needed by the ingest stage that runs ahead of the
                      manifest.
  build_manifest()    consumes the ingest result, parses topic ids out of the
                      delivered filenames, measures each normalized audio file,
                      and writes qa_work/manifest.json.

The manifest is the pipeline's roster: every later stage iterates topics from
it, and its input hashes are what let a stage know its work is stale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import soundfile as sf
import yaml

from .util import ConfigError, read_json, rel, write_json

PROJECT_TYPES = {"VENDOR", "CGT"}

# Duration disagreement between ffprobe (at ingest) and soundfile (here) that
# is large enough to mean the demux went wrong rather than rounding.
DURATION_TOLERANCE_S = 1.0


@dataclass(frozen=True)
class CourseConfig:
    course_dir: Path
    course_number: str
    project_type: str
    course_code: str
    storyboard: Path
    slide_map: dict[str, list[int]] = field(default_factory=dict)
    unscripted_topics: tuple[str, ...] = ()
    asr: dict = field(default_factory=dict)

    @property
    def qa_work(self) -> Path:
        return self.course_dir / "qa_work"

    @property
    def qa_out(self) -> Path:
        return self.course_dir / "qa_out"


def _require(data: dict, key: str, path: Path) -> str:
    value = data.get(key)
    if value is None or str(value).strip() == "":
        raise ConfigError(f"{path}: required key '{key}' is missing or empty.")
    return str(value).strip()


def find_storyboard(course_dir: Path) -> Path:
    """Exactly one pptx at the course root. Zero or many is a hard stop."""
    decks = sorted(
        p for p in course_dir.glob("*.pptx") if not p.name.startswith("~$")
    )
    if not decks:
        raise ConfigError(
            f"No storyboard found: expected exactly one .pptx in {course_dir}."
        )
    if len(decks) > 1:
        names = ", ".join(p.name for p in decks)
        raise ConfigError(
            f"Found {len(decks)} .pptx files in {course_dir}: {names}.\n"
            "  Exactly one storyboard is required. Remove the extras or move "
            "them out of the course folder."
        )
    return decks[0]


def load_course_yaml(course_dir: Path) -> CourseConfig:
    """Read and validate course.yaml. No media is touched here."""
    course_dir = course_dir.resolve()
    if not course_dir.is_dir():
        raise ConfigError(f"Course folder does not exist: {course_dir}")

    path = course_dir / "course.yaml"
    if not path.exists():
        raise ConfigError(
            f"No course.yaml in {course_dir}.\n"
            "  Required keys: course_number, project_type, course_code."
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML:\n  {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping.")

    project_type = _require(data, "project_type", path).upper()
    if project_type not in PROJECT_TYPES:
        allowed = " or ".join(sorted(PROJECT_TYPES))
        raise ConfigError(
            f"{path}: project_type '{project_type}' is not recognized. Use {allowed}."
        )

    # A trailing underscore on course_code is a common convention in the
    # findings reports; accept it and normalize it away.
    course_code = _require(data, "course_code", path).rstrip("_")

    raw_map = data.get("slide_map") or {}
    if not isinstance(raw_map, dict):
        raise ConfigError(f"{path}: slide_map must be a mapping of topic to [first, last].")
    slide_map: dict[str, list[int]] = {}
    for topic, span in raw_map.items():
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            raise ConfigError(
                f"{path}: slide_map['{topic}'] must be [first_slide, last_slide]."
            )
        first, last = int(span[0]), int(span[1])
        if first > last:
            raise ConfigError(
                f"{path}: slide_map['{topic}'] has first_slide {first} after last_slide {last}."
            )
        slide_map[str(topic)] = [first, last]

    raw_unscripted = data.get("unscripted_topics") or []
    if not isinstance(raw_unscripted, (list, tuple)):
        raise ConfigError(f"{path}: unscripted_topics must be a list of topic ids.")

    asr = data.get("asr") or {}
    if not isinstance(asr, dict):
        raise ConfigError(f"{path}: asr must be a mapping of setting to value.")

    return CourseConfig(
        course_dir=course_dir,
        course_number=_require(data, "course_number", path),
        project_type=project_type,
        course_code=course_code,
        storyboard=find_storyboard(course_dir),
        slide_map=slide_map,
        unscripted_topics=tuple(str(t).strip() for t in raw_unscripted),
        asr=asr,
    )


# ---------------------------------------------------------------------------
# Topic ids
# ---------------------------------------------------------------------------

def parse_topic(filename: str, course_code: str) -> str | None:
    """Pull the topic id out of <course_code>_<topic>.<ext>.

    Topic ids are numeric groups joined by underscores, so both "01" and
    "09_01" parse. Returns None when the file does not belong to this course.
    """
    stem = Path(filename).stem
    prefix = course_code.rstrip("_") + "_"
    if not stem.lower().startswith(prefix.lower()):
        return None
    remainder = stem[len(prefix):]
    if not re.fullmatch(r"\d+(?:_\d+)*", remainder):
        return None
    return remainder


def topic_sort_key(topic: str) -> tuple[int, ...]:
    return tuple(int(part) for part in topic.split("_"))


def measure_audio(path: Path) -> dict:
    """Duration and format of a normalized audio file, via soundfile."""
    try:
        info = sf.info(str(path))
    except (RuntimeError, sf.LibsndfileError) as exc:
        raise ConfigError(
            f"soundfile could not read {path.name}:\n  {exc}\n"
            "  The ingest stage is supposed to leave every file in a readable "
            "format. Rerun ingest with --force."
        ) from exc
    return {
        "duration_s": round(float(info.frames) / info.samplerate, 3),
        "sample_rate": info.samplerate,
        "channels": info.channels,
        "format": f"{info.format}/{info.subtype}",
    }


def build_manifest(cfg: CourseConfig, ingest: dict) -> dict:
    """Roster of every topic in the course, with durations and input hashes."""
    entries: list[dict] = []
    warnings: list[str] = list(ingest.get("warnings", []))
    unmatched: list[str] = []

    for item in ingest["files"]:
        source = Path(item["source"])
        topic = parse_topic(source.name, cfg.course_code)
        if topic is None:
            unmatched.append(source.name)
            continue

        audio_path = cfg.course_dir / item["audio_path"]
        measured = measure_audio(audio_path)

        probe_duration = (item.get("streams") or {}).get("duration_s")
        if probe_duration and abs(probe_duration - measured["duration_s"]) > DURATION_TOLERANCE_S:
            warnings.append(
                f"{source.name}: ffprobe reported {probe_duration:.1f}s but the "
                f"normalized audio measures {measured['duration_s']:.1f}s. "
                "Suspect a bad demux."
            )

        entries.append(
            {
                "topic": topic,
                "source": item["source"],
                "audio_path": item["audio_path"],
                "action": item["action"],
                "container": item["container"],
                "kind": item["kind"],
                "source_sha256": item["source_sha256"],
                "scripted": topic not in cfg.unscripted_topics,
                **measured,
            }
        )

    if unmatched:
        raise ConfigError(
            "These files do not match the course_code naming convention "
            f"'{cfg.course_code}_<topic>':\n  " + "\n  ".join(sorted(unmatched))
            + "\n  Fix course.yaml's course_code, or rename the files."
        )
    if not entries:
        raise ConfigError(
            f"No audio files matched course_code '{cfg.course_code}'."
        )

    duplicates = sorted(
        {e["topic"] for e in entries if [x["topic"] for x in entries].count(e["topic"]) > 1}
    )
    if duplicates:
        raise ConfigError(
            "More than one file maps to the same topic id: "
            + ", ".join(duplicates)
            + "\n  Each topic must have exactly one narration file."
        )

    entries.sort(key=lambda e: topic_sort_key(e["topic"]))

    missing_unscripted = [
        t for t in cfg.unscripted_topics if t not in {e["topic"] for e in entries}
    ]
    if missing_unscripted:
        warnings.append(
            "course.yaml lists unscripted_topics that have no audio file: "
            + ", ".join(missing_unscripted)
        )

    manifest = {
        "course_number": cfg.course_number,
        "course_code": cfg.course_code,
        "project_type": cfg.project_type,
        "storyboard": rel(cfg.storyboard, cfg.course_dir),
        "storyboard_sha256": None,
        "topic_count": len(entries),
        "total_duration_s": round(sum(e["duration_s"] for e in entries), 3),
        "unscripted_topics": list(cfg.unscripted_topics),
        "warnings": warnings,
        "topics": entries,
    }
    return manifest


def run_config(course_dir: Path, force: bool = False) -> dict:
    """Stage entry point: read ingest.json, write manifest.json."""
    cfg = load_course_yaml(course_dir)
    ingest_path = cfg.qa_work / "ingest.json"
    if not ingest_path.exists():
        raise ConfigError(
            f"{ingest_path} not found. Run the ingest stage first."
        )
    from .util import sha256_file  # local import keeps the module surface small

    manifest = build_manifest(cfg, read_json(ingest_path))
    manifest["storyboard_sha256"] = sha256_file(cfg.storyboard)
    write_json(cfg.qa_work / "manifest.json", manifest)
    return manifest
