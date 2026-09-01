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

from .script_source import (
    COURSE_SOURCES,
    FREEFORM,
    OUTLINE,
    PPTX,
    SCRIPT_SOURCES,
    SOURCE_SUFFIX,
    TOPIC_STATES,
    TopicScript,
    VERBATIM,
    default_source,
)
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
    script_source: str
    script_document: Path
    slide_map: dict[str, list[int]] = field(default_factory=dict)
    unscripted_topics: tuple[str, ...] = ()
    topic_scripts: dict[str, TopicScript] = field(default_factory=dict)
    asr: dict = field(default_factory=dict)

    @property
    def storyboard(self) -> Path:
        """The old name for the script document, kept for readers of pptx courses."""
        return self.script_document

    def script_for(self, topic: str) -> TopicScript:
        """One topic's script state. Verbatim unless something said otherwise."""
        return self.topic_scripts.get(str(topic), TopicScript(state=VERBATIM))

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


# Titles the BUS template and the delivery tooling leave lying around next to
# a real script. Matching one is not a reason to halt; it is a reason not to
# count the file as a candidate script document.
IGNORED_DOCUMENTS = ("~$",)


def find_script_document(course_dir: Path, source: str) -> Path:
    """Exactly one document of the source's own type. Zero or many is a stop.

    Deliberately not "whichever document is there". A CGT course folder can
    easily acquire a stray Word file, and picking one by accident would align
    an entire course against the wrong text and read as a catastrophic
    narration failure rather than as the filing mistake it is.
    """
    suffix = SOURCE_SUFFIX.get(source)
    if suffix is None:
        raise ConfigError(
            f"{course_dir}: script_source '{source}' names no course-level "
            "document, so there is nothing to look for."
        )
    found = sorted(
        p
        for p in course_dir.glob(f"*{suffix}")
        if not any(p.name.startswith(prefix) for prefix in IGNORED_DOCUMENTS)
    )
    if not found:
        raise ConfigError(
            f"No script document found: script_source '{source}' expects exactly "
            f"one {suffix} in {course_dir}.\n"
            "  A VENDOR course carries its script in a PowerPoint storyboard; a "
            "CGT course carries it in a Word document in the BUS Writing "
            "Template. Put the right document in the course folder, or correct "
            "script_source in course.yaml."
        )
    if len(found) > 1:
        names = ", ".join(p.name for p in found)
        raise ConfigError(
            f"Found {len(found)} {suffix} files in {course_dir}: {names}.\n"
            "  Exactly one script document is required. Remove the extras or "
            "move them out of the course folder."
        )
    return found[0]


def find_storyboard(course_dir: Path) -> Path:
    """The pptx case, kept under its old name for callers that mean a deck."""
    return find_script_document(course_dir, PPTX)


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
    unscripted = tuple(str(t).strip() for t in raw_unscripted)

    script_source = str(data.get("script_source") or default_source(project_type)).strip()
    if script_source not in SCRIPT_SOURCES:
        allowed = ", ".join(sorted(SCRIPT_SOURCES))
        raise ConfigError(
            f"{path}: script_source '{script_source}' is not recognized. Use one of {allowed}."
        )
    if script_source not in COURSE_SOURCES:
        allowed = " or ".join(sorted(COURSE_SOURCES))
        raise ConfigError(
            f"{path}: script_source '{script_source}' describes one topic, not a "
            f"course. Set the course to {allowed} and put '{script_source}' on the "
            "topics that need it, under the topics key."
        )

    asr = data.get("asr") or {}
    if not isinstance(asr, dict):
        raise ConfigError(f"{path}: asr must be a mapping of setting to value.")

    return CourseConfig(
        course_dir=course_dir,
        course_number=_require(data, "course_number", path),
        project_type=project_type,
        course_code=course_code,
        script_source=script_source,
        script_document=find_script_document(course_dir, script_source),
        slide_map=slide_map,
        unscripted_topics=unscripted,
        topic_scripts=_topic_scripts(data, unscripted, path, course_dir),
        asr=asr,
    )


def _topic_scripts(
    data: dict, unscripted: tuple[str, ...], path: Path, course_dir: Path
) -> dict[str, TopicScript]:
    """Resolve every topic's script state from the two keys that can set it.

    `unscripted_topics` came first and means outline-only; it is still the
    shortest way to say the common VENDOR case and nothing here deprecates it.
    The `topics` mapping is the general form and wins where both speak, because
    a person who wrote out a state explicitly meant it.
    """
    resolved: dict[str, TopicScript] = {
        topic: TopicScript(state=OUTLINE) for topic in unscripted
    }

    raw = data.get("topics") or {}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{path}: topics must be a mapping of topic id to its settings, as in\n"
            '  topics: {"09": {script: none}}'
        )

    for key, value in raw.items():
        topic = str(key).strip()
        if not isinstance(value, dict):
            raise ConfigError(
                f"{path}: topics['{topic}'] must be a mapping, as in "
                "{script: none} or {script: freeform, file: demo_script.docx}."
            )
        state = str(value.get("script") or VERBATIM).strip()
        if state not in TOPIC_STATES:
            allowed = ", ".join(sorted(TOPIC_STATES))
            raise ConfigError(
                f"{path}: topics['{topic}'].script is '{state}', which is not a "
                f"script state. Use one of {allowed}."
            )
        document = str(value.get("file") or "").strip()
        if state == FREEFORM and not document:
            raise ConfigError(
                f"{path}: topics['{topic}'] is freeform but names no file. A "
                "freeform topic's narration is a document of its own, so it has "
                "to say which one:\n"
                f'  topics: {{"{topic}": {{script: freeform, file: demo_script.docx}}}}'
            )
        if document and state != FREEFORM:
            raise ConfigError(
                f"{path}: topics['{topic}'] names a file but its script state is "
                f"'{state}'. Only a freeform topic reads a document of its own."
            )
        if document and not (course_dir / document).exists():
            raise ConfigError(
                f"{path}: topics['{topic}'] names {document}, which is not in "
                f"{course_dir}.\n"
                "  Put the freeform script in the course folder, or correct the "
                "file name."
            )
        resolved[topic] = TopicScript(state=state, file=document)

    return resolved


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
                "script": cfg.script_for(topic).state,
                "script_file": cfg.script_for(topic).file,
                "scripted": cfg.script_for(topic).aligned,
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

    delivered = {e["topic"] for e in entries}
    missing_unscripted = [t for t in cfg.unscripted_topics if t not in delivered]
    if missing_unscripted:
        warnings.append(
            "course.yaml lists unscripted_topics that have no audio file: "
            + ", ".join(missing_unscripted)
        )
    missing_states = [t for t in sorted(cfg.topic_scripts) if t not in delivered]
    if missing_states:
        # Worth more than a shrug. A topic id that does not match a delivered
        # file means the state was not applied to anything, so a demo meant to
        # be outline-only is about to be aligned word for word against an
        # outline, which reads as a page of deletions. The usual cause is a
        # topic id written without its leading zero.
        warnings.append(
            "course.yaml sets a script state on topics that have no audio file: "
            + ", ".join(missing_states)
            + ". Those states were not applied to anything, and the topics they "
            "were meant for are being treated as verbatim. Delivered topic ids "
            "are: " + ", ".join(sorted(delivered))
        )

    manifest = {
        "course_number": cfg.course_number,
        "course_code": cfg.course_code,
        "project_type": cfg.project_type,
        "script_source": cfg.script_source,
        "script_document": rel(cfg.script_document, cfg.course_dir),
        "script_document_sha256": None,
        # The old names for the two keys above. Kept so a packet or a test
        # written against a pptx course still reads, and populated only when
        # the source really is a PowerPoint deck: a CGT course has no
        # storyboard, and saying it has one would be a lie in the data rather
        # than a convenience.
        "storyboard": (
            rel(cfg.script_document, cfg.course_dir)
            if cfg.script_source == PPTX
            else None
        ),
        "storyboard_sha256": None,
        "topic_count": len(entries),
        "total_duration_s": round(sum(e["duration_s"] for e in entries), 3),
        "unscripted_topics": list(cfg.unscripted_topics),
        "topic_scripts": {
            topic: {"script": script.state, "file": script.file}
            for topic, script in sorted(cfg.topic_scripts.items())
        },
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
    digest = sha256_file(cfg.script_document)
    manifest["script_document_sha256"] = digest
    if manifest["storyboard"] is not None:
        manifest["storyboard_sha256"] = digest
    write_json(cfg.qa_work / "manifest.json", manifest)
    return manifest
