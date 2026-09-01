"""Where finished packets go, what they are called, and what never happens.

The rule that matters is that a packet is never overwritten. The output folder
is the run history: a before-fix packet and an after-fix packet, or a CPU
packet and a GPU packet of the same course, have to sit side by side or the
comparison cannot be made at all. See D28.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from qa.library import (
    OUTPUT_ENV_VAR,
    default_output,
    output_root,
    read_settings,
    resolve_output,
    set_output,
)
from qa.packet import DEVICE_NAMES, PacketError, _unclaimed, packet_stem


def manifest(code: str = "it_spisccc26_10_enus") -> dict:
    return {"course_code": code}


def transcripts(device: str = "cuda", compute: str = "float16") -> dict:
    return {"device_used": device, "settings": {"compute_type": compute}}


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

def test_a_packet_is_named_for_the_run_that_made_it():
    stem = packet_stem(manifest(), transcripts(), "2026-09-01", "1441")
    assert stem == "it_spisccc26_10_enus_2026-09-01_1441_gpu-float16"


def test_the_device_is_written_the_way_people_say_it():
    """"cuda" is the runtime's word. This name is read by people."""
    assert DEVICE_NAMES["cuda"] == "gpu"
    stem = packet_stem(manifest(), transcripts("cpu", "int8"), "2026-09-01", "0902")
    assert stem.endswith("_cpu-int8")


def test_two_runs_of_one_course_on_one_day_do_not_collide():
    """The case the old course-plus-date naming overwrote silently."""
    morning = packet_stem(manifest(), transcripts("cpu", "int8"), "2026-09-01", "0902")
    evening = packet_stem(manifest(), transcripts(), "2026-09-01", "1441")
    assert morning != evening


def test_a_packet_never_overwrites_one_that_is_already_there(tmp_path):
    stem = "it_spisccc26_10_enus_2026-09-01_1441_gpu-float16"
    assert _unclaimed(tmp_path, stem) == stem

    (tmp_path / f"{stem}.md").write_text("first", encoding="utf-8")
    assert _unclaimed(tmp_path, stem) == f"{stem}_2"

    (tmp_path / f"{stem}_2.md").write_text("second", encoding="utf-8")
    assert _unclaimed(tmp_path, stem) == f"{stem}_3"

    # And the first is still exactly what it was.
    assert (tmp_path / f"{stem}.md").read_text(encoding="utf-8") == "first"


def test_running_out_of_names_is_an_error_rather_than_a_silent_overwrite(tmp_path):
    stem = "course"
    (tmp_path / f"{stem}.md").write_text("x", encoding="utf-8")
    for suffix in range(2, 100):
        (tmp_path / f"{stem}_{suffix}.md").write_text("x", encoding="utf-8")
    with pytest.raises(PacketError, match="Ninety-nine"):
        _unclaimed(tmp_path, stem)


# ---------------------------------------------------------------------------
# Where it goes
# ---------------------------------------------------------------------------

def test_the_default_output_folder_is_documents_not_the_library():
    """Working files belong in AppData. A packet is a thing a person opens."""
    from qa.library import default_library

    assert default_output() != default_library()
    assert default_output().name == "audio-qa"


def test_an_environment_variable_wins_over_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv(OUTPUT_ENV_VAR, str(tmp_path / "packets"))
    resolution = resolve_output()
    assert resolution.path == tmp_path / "packets"
    assert resolution.source == "environment"


def test_an_explicit_path_wins_over_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(OUTPUT_ENV_VAR, str(tmp_path / "packets"))
    resolution = resolve_output(tmp_path / "chosen")
    assert resolution.path == tmp_path / "chosen"
    assert resolution.source == "argument"


def test_the_output_folder_is_created_only_when_asked(monkeypatch, tmp_path):
    target = tmp_path / "packets"
    monkeypatch.setenv(OUTPUT_ENV_VAR, str(target))
    assert output_root().exists() is False
    assert output_root(create=True).is_dir()


def test_the_library_and_the_output_folder_are_separate_settings(monkeypatch, tmp_path):
    """Changing where packets go must not move the course library."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv(OUTPUT_ENV_VAR, raising=False)
    monkeypatch.delenv("AUDIO_QA_LIBRARY", raising=False)

    set_output(tmp_path / "packets")
    settings = read_settings()
    assert settings["output"] == os.path.normpath(str(tmp_path / "packets"))
    assert "library" not in settings or settings["library"] != settings["output"]


# ---------------------------------------------------------------------------
# The whole stage, end to end
# ---------------------------------------------------------------------------

def test_run_packet_writes_to_the_output_folder_and_records_where(tmp_path):
    """The course folder keeps a marker; the packet itself lives elsewhere."""
    import json

    from qa.packet import run_packet
    from qa.results import find_packet

    course = _plant_course(tmp_path)
    destination = tmp_path / "packets"

    result = run_packet(course, run_date="2026-09-01", output_dir=destination)

    written = Path(result["path"])
    assert written.parent == destination
    assert written.name.startswith("it_spisccc26_10_enus_2026-09-01_")
    assert written.name.endswith("_cpu-int8.md")
    assert not list((course / "qa_out").glob("*.md"))

    marker = json.loads((course / "qa_out" / "packet_index.json").read_text("utf-8"))
    assert marker["path"] == str(written)
    assert marker["output_dir"] == str(destination)

    found, payload = find_packet(course)
    assert found == written
    assert payload is not None


def test_a_second_run_leaves_the_first_packet_alone(tmp_path):
    from qa.packet import run_packet
    from qa.results import packet_history

    course = _plant_course(tmp_path)
    destination = tmp_path / "packets"

    first = Path(run_packet(course, run_date="2026-09-01", output_dir=destination)["path"])
    second = Path(run_packet(course, run_date="2026-09-02", output_dir=destination)["path"])

    assert first != second
    assert first.exists() and second.exists()

    history = packet_history("it_spisccc26_10_enus", destination)
    assert set(history) == {first, second}
    assert history[0] == second, "newest first"


def _plant_course(tmp_path: Path) -> Path:
    """The minimum a course folder needs for the packet stage to run."""
    import json

    course = tmp_path / "course10"
    work = course / "qa_work"
    work.mkdir(parents=True)
    (course / "storyboard.pptx").write_bytes(b"")
    (course / "course.yaml").write_text(
        'course_number: "10"\nproject_type: VENDOR\n'
        "course_code: it_spisccc26_10_enus\nscript_source: pptx\n",
        encoding="utf-8",
    )

    row = {
        "topic": "01",
        "slides": [1, 2],
        "source_ref": "slides 1-2",
        "script": "verbatim",
        "scripted": True,
        "duration_s": 60.0,
        "script_words": 10,
        "transcript_words": 10,
        "script_wpm": 10.0,
        "transcript_wpm": 10.0,
        "pace_ratio": 1.0,
        "pace_reference": "script",
        "coverage": 1.0,
        "tail_matched": True,
        "tail_gap_s": 0.0,
        "trailing_silence_s": 0.0,
        "script_sentences": 1,
        "transcript_sentences": 1,
        "discrepancies": 0,
        "listen_items": 0,
        "suppressed_asr_duplicates": 0,
        "voiced_symbols": 0,
        "voiced_symbol_terms": [],
        "unverifiable_duplications": 0,
        "low_confidence_words": 0,
        "low_confidence_share": 0.0,
        "asr_anomalies": [],
        "audio_findings": [],
        "flags": [],
    }
    files = {
        "checks.json": {
            "summary": {
                "course_code": "it_spisccc26_10_enus",
                "course_number": "10",
                "project_type": "VENDOR",
                "topic_count": 1,
                "reference_wpm": 10.0,
                "mean_coverage": 1.0,
                "total_discrepancies": 0,
                "total_listen_items": 0,
                "total_suppressed": 0,
                "total_voiced_symbols": 0,
                "total_unverifiable_duplications": 0,
                "flagged_topics": [],
            },
            "topics": [row],
            "watchlist": {},
        },
        "artifacts.json": {"conventions": {}, "conventional_gaps": 0},
        "manifest.json": {
            "course_code": "it_spisccc26_10_enus",
            "script_source": "pptx",
            "script_document": "storyboard.pptx",
            "storyboard": "storyboard.pptx",
        },
        "transcripts.json": {
            "engine": "faster-whisper",
            "machine": "a laptop (Windows)",
            "settings": {
                "model": "large-v3",
                "compute_type": "int8",
                "beam_size": 5,
                "vad": True,
                "device": "cpu",
            },
            "device_used": "cpu",
            "requested_device": "cpu",
            "topics": [{"topic": "01", "duration_s": 60.0, "decode_seconds": 30.0}],
        },
        "script.json": {
            "script_source": "pptx",
            "topics": [
                {
                    "topic": "01",
                    "script": "verbatim",
                    "scripted": True,
                    "slides": [1, 2],
                    "source_ref": "slides 1-2",
                    "sentences": ["The kettle boils."],
                    "word_count": 3,
                    "non_narration": [],
                }
            ],
            "mapping": {"source": "auto", "markers": [], "excluded_slides": []},
        },
        "transcript_01.json": {
            "word_count": 3,
            "segments": [{"start": 0.0, "end": 1.0, "text": "The kettle boils."}],
            "words": [],
        },
        "discrepancies_01.json": {
            "aligned": True,
            "discrepancies": [],
            "voiced_symbols": [],
            "unverifiable_duplications": [],
        },
        "artifacts_01.json": {
            "peak_dbfs": -3.0,
            "rms_dbfs": -20.0,
            "leading_silence_s": 0.0,
            "trailing_silence_s": 0.0,
            "findings": [],
        },
    }
    for name, payload in files.items():
        (work / name).write_text(json.dumps(payload), encoding="utf-8")
    return course
