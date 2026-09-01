"""Tests for the library, the device probe and standardized intake.

Nothing here touches the real library or the real home directory: every test
is given a tmp_path and the resolution layers are driven explicitly, so a
developer's own settings can never change the result.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from qa.config import load_course_yaml
from qa.device import CPU, GPU, default_device, effective_device, probe_cpu, probe_gpu
from qa.intake import (
    IntakeError,
    IntakeForm,
    existing_hashes,
    find_recent_deliveries,
    ingest_selection,
    read_selection,
    remove_originals,
    render_intake_yaml,
)
from qa.library import (
    ENV_VAR,
    course_path,
    default_library,
    is_ingested,
    library_root,
    list_courses,
    resolve_library,
    set_library,
)
from qa.new_course import parse_delivery_name
from qa.util import sha256_file

CODE = "it_spisccc26_11_enus"

# A real mp3 header, so sniff_container classifies these as audio rather than
# rejecting them. The bytes after it are irrelevant; nothing decodes here.
MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
MP4 = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 64
PPTX = b"PK\x03\x04" + b"\x00" * 64


def delivery(tmp_path: Path, topics=("01", "02"), video=(), storyboard=True) -> list[Path]:
    """A folder of delivered files, as a browser would have left it."""
    source = tmp_path / "Downloads"
    source.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for topic in topics:
        if topic in video:
            path = source / f"{CODE}_{topic}.mp4"
            path.write_bytes(MP4 + topic.encode())
        else:
            path = source / f"{CODE}_{topic}.mp3"
            path.write_bytes(MP3 + topic.encode())
        made.append(path)
    if storyboard:
        deck = source / "it_spisccc26_11_storyboard.pptx"
        deck.write_bytes(PPTX)
        made.append(deck)
    return made


# ---------------------------------------------------------------------------
# Library resolution
# ---------------------------------------------------------------------------

def test_library_defaults_outside_the_repository():
    """Courses must never live where an ignore rule could publish them."""
    root = default_library()
    assert root.is_absolute()
    assert "audio-qa" in root.as_posix()
    assert Path.cwd() not in root.parents


def test_resolution_order_argument_beats_everything(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "from-env"))
    assert resolve_library(tmp_path / "explicit").source == "argument"
    assert resolve_library(tmp_path / "explicit").path == tmp_path / "explicit"


def test_environment_beats_settings_and_default(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "from-env"))
    resolved = resolve_library()
    assert resolved.source == "environment"
    assert resolved.path == tmp_path / "from-env"


def test_settings_file_is_used_when_no_environment(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr("qa.library.user_config_dir", lambda: tmp_path / "config")
    saved = set_library(tmp_path / "chosen")
    resolved = resolve_library()
    assert resolved.source == "settings"
    assert resolved.path == saved


def test_falls_back_to_the_platform_default(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr("qa.library.user_config_dir", lambda: tmp_path / "empty")
    assert resolve_library().source == "default"


def test_a_corrupt_settings_file_does_not_stop_the_app(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("qa.library.user_config_dir", lambda: config)
    assert resolve_library().source == "default"


def test_library_path_is_stable_whether_or_not_it_exists(tmp_path, monkeypatch):
    """The location shown before the first course must match the one after.

    Path.resolve() follows junctions and reparse points and answers
    differently once a directory exists, so on Windows the displayed library
    moved into a packaged app's private cache after the first ingest. The
    location a person configured is the one they get told about.
    """
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "lib"))
    before = resolve_library().path
    (tmp_path / "lib").mkdir()
    after = resolve_library().path
    assert before == after == (tmp_path / "lib")


def test_normalization_does_not_follow_a_symlink(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this platform or account cannot create symlinks")
    monkeypatch.setenv(ENV_VAR, str(link))
    assert resolve_library().path == link


def test_course_paths_are_zero_padded(tmp_path):
    assert course_path(tmp_path, "spisccc26", "9").name == "course09"
    assert course_path(tmp_path, "spisccc26", "11").name == "course11"


def test_listing_ignores_folders_that_are_not_ingested(tmp_path):
    (tmp_path / "spisccc26" / "course01").mkdir(parents=True)
    ingested = tmp_path / "spisccc26" / "course02"
    ingested.mkdir(parents=True)
    (ingested / "course.yaml").write_text("course_number: '2'\n", encoding="utf-8")
    found = list_courses(tmp_path)
    assert [c.course_number for c in found] == ["02"]
    assert is_ingested(ingested)


# ---------------------------------------------------------------------------
# Device probe
# ---------------------------------------------------------------------------

def test_cpu_is_always_available():
    device = probe_cpu()
    assert device.available and device.key == CPU
    assert "processors" in device.detail


def test_gpu_reports_a_reason_when_the_runtime_is_absent(monkeypatch):
    """A content contributor gets a sentence, never a traceback."""
    import builtins

    real_import = builtins.__import__

    def no_ctranslate2(name, *args, **kwargs):
        if name == "ctranslate2":
            raise ImportError("no module named ctranslate2")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_ctranslate2)
    device = probe_gpu()
    assert not device.available
    assert "asr extra" in device.reason


def test_gpu_reports_a_reason_when_no_cuda_device_exists(monkeypatch):
    pytest.importorskip("ctranslate2")
    monkeypatch.setattr("ctranslate2.get_cuda_device_count", lambda: 0)
    device = probe_gpu()
    assert not device.available
    assert "no CUDA capable device" in device.reason


def test_gpu_reports_a_reason_when_the_driver_mismatches(monkeypatch):
    pytest.importorskip("ctranslate2")
    monkeypatch.setattr("ctranslate2.get_cuda_device_count", lambda: 1)
    monkeypatch.setattr(
        "ctranslate2.get_supported_compute_types",
        lambda _: (_ for _ in ()).throw(RuntimeError("CUDA driver version is insufficient")),
    )
    device = probe_gpu()
    assert not device.available
    assert "driver" in device.reason


def test_default_device_is_the_fastest_working_one():
    from qa.device import Device

    gpu_ok = [Device(GPU, "GPU", True), Device(CPU, "CPU", True)]
    gpu_bad = [Device(CPU, "CPU", True), Device(GPU, "GPU", False, "no device")]
    assert default_device(gpu_ok) == GPU
    assert default_device(gpu_bad) == CPU


def test_choosing_gpu_falls_back_to_cpu_and_says_so():
    """Device affects speed, not results, and the note must say that."""
    used, note = effective_device(GPU)
    assert used == CPU
    assert "identical" in note
    assert effective_device(CPU) == (CPU, "")


# ---------------------------------------------------------------------------
# Reading a selection
# ---------------------------------------------------------------------------

def test_derivation_matches_the_scaffolders_parser(tmp_path):
    files = delivery(tmp_path, topics=("01", "02", "03"))
    selection = read_selection(files)
    expected = parse_delivery_name(f"{CODE}_01.mp3")
    assert selection.learning_path == expected.learning_path
    assert selection.course_number == expected.course_number
    assert selection.course_code == expected.course_code
    assert selection.topics == ["01", "02", "03"]
    assert selection.storyboard is not None


def test_two_courses_in_one_selection_is_refused(tmp_path):
    files = delivery(tmp_path, topics=("01",))
    other = tmp_path / "Downloads" / "it_spisccc26_12_enus_01.mp3"
    other.write_bytes(MP3)
    with pytest.raises(IntakeError, match="more than one course"):
        read_selection(files + [other])


def test_two_storyboards_is_refused(tmp_path):
    files = delivery(tmp_path)
    second = tmp_path / "Downloads" / "another_storyboard.pptx"
    second.write_bytes(PPTX)
    with pytest.raises(IntakeError, match="More than one storyboard"):
        read_selection(files + [second])


def test_two_files_for_one_topic_is_refused(tmp_path):
    files = delivery(tmp_path, topics=("01",))
    duplicate = tmp_path / "Downloads" / f"{CODE}_01.mp4"
    duplicate.write_bytes(MP4)
    with pytest.raises(IntakeError, match="same topic"):
        read_selection(files + [duplicate])


def test_no_media_is_refused(tmp_path):
    files = delivery(tmp_path, topics=(), storyboard=True)
    with pytest.raises(IntakeError, match="No narration files"):
        read_selection(files)


def test_unrelated_files_are_set_aside_not_rejected(tmp_path):
    files = delivery(tmp_path)
    stray = tmp_path / "Downloads" / "notes.pdf"
    stray.write_bytes(b"%PDF-1.4")
    selection = read_selection(files + [stray])
    assert [p.name for p in selection.ignored] == ["notes.pdf"]


def test_video_topics_are_detected_by_header_not_extension(tmp_path):
    files = delivery(tmp_path, topics=("01", "12"), video=("12",))
    selection = read_selection(files)
    assert selection.video_topics == ["12"]


def test_a_missing_storyboard_is_allowed_but_reported(tmp_path):
    files = delivery(tmp_path, storyboard=False)
    selection = read_selection(files)
    assert selection.storyboard is None


# ---------------------------------------------------------------------------
# The form
# ---------------------------------------------------------------------------

def test_reviewed_by_is_required(tmp_path):
    selection = read_selection(delivery(tmp_path))
    with pytest.raises(IntakeError, match="Reviewed by"):
        IntakeForm(project_type="VENDOR", reviewed_by="  ").validate(selection)


def test_project_type_must_be_known(tmp_path):
    selection = read_selection(delivery(tmp_path))
    with pytest.raises(IntakeError, match="not recognized"):
        IntakeForm(project_type="OTHER", reviewed_by="Ryan").validate(selection)


def test_outline_topics_must_have_been_delivered(tmp_path):
    selection = read_selection(delivery(tmp_path, topics=("01", "02")))
    form = IntakeForm(
        project_type="VENDOR", unscripted_topics=("09",), reviewed_by="Ryan"
    )
    with pytest.raises(IntakeError, match="not delivered"):
        form.validate(selection)


# ---------------------------------------------------------------------------
# Ingesting
# ---------------------------------------------------------------------------

def ingest(tmp_path, topics=("01", "02"), video=(), unscripted=(), **kwargs):
    selection = read_selection(delivery(tmp_path, topics=topics, video=video))
    form = IntakeForm(
        project_type=kwargs.pop("project_type", "VENDOR"),
        unscripted_topics=unscripted,
        reviewed_by=kwargs.pop("reviewed_by", "Ryan"),
        notes=kwargs.pop("notes", ""),
    )
    return selection, ingest_selection(selection, form, library=tmp_path / "library")


def test_files_land_in_the_standard_layout(tmp_path):
    selection, result = ingest(tmp_path)
    assert result.course_dir == tmp_path / "library" / "spisccc26" / "course11"
    assert (result.course_dir / "course.yaml").exists()
    assert (result.course_dir / "it_spisccc26_11_storyboard.pptx").exists()
    assert sorted(p.name for p in (result.course_dir / "audio").iterdir()) == [
        f"{CODE}_01.mp3",
        f"{CODE}_02.mp3",
    ]


def test_originals_are_copied_never_moved(tmp_path):
    selection, result = ingest(tmp_path)
    for copied in result.copied:
        assert copied.source.exists(), "the delivery must be left alone"
        assert copied.destination.exists()


def test_every_copy_is_verified_by_hash(tmp_path):
    selection, result = ingest(tmp_path)
    for copied in result.copied:
        assert copied.verified
        assert sha256_file(copied.destination) == copied.sha256
        assert sha256_file(copied.source) == copied.sha256


def test_a_corrupted_copy_is_caught_and_nothing_is_declared_ingested(tmp_path, monkeypatch):
    """The failure this check exists for: a short write nobody noticed."""
    real_copy = shutil.copy2

    def truncating_copy(src, dst, *args, **kwargs):
        real_copy(src, dst, *args, **kwargs)
        Path(dst).write_bytes(b"truncated")

    monkeypatch.setattr("qa.intake.shutil.copy2", truncating_copy)
    with pytest.raises(IntakeError, match="does not match the original"):
        ingest(tmp_path)


def test_course_yaml_round_trips_through_the_real_loader(tmp_path):
    selection, result = ingest(tmp_path, topics=("01", "12"), video=("12",), unscripted=("12",))
    cfg = load_course_yaml(result.course_dir)
    assert cfg.course_number == "11"
    assert cfg.project_type == "VENDOR"
    assert cfg.course_code == CODE
    assert cfg.unscripted_topics == ("12",)


def test_reviewed_by_and_notes_are_recorded(tmp_path):
    selection, result = ingest(tmp_path, reviewed_by="Ryan Mount", notes="second pass: fixed 03")
    data = yaml.safe_load((result.course_dir / "course.yaml").read_text(encoding="utf-8"))
    assert data["reviewed_by"] == "Ryan Mount"
    assert data["notes"] == "second pass: fixed 03"


def test_free_text_with_yaml_punctuation_does_not_break_the_file(tmp_path):
    selection, result = ingest(tmp_path, notes='re-run: vendor sent "new" audio # again')
    data = yaml.safe_load((result.course_dir / "course.yaml").read_text(encoding="utf-8"))
    assert "vendor sent" in data["notes"]


def test_no_outline_topics_leaves_the_scaffolders_empty_list(tmp_path):
    selection, result = ingest(tmp_path)
    cfg = load_course_yaml(result.course_dir)
    assert cfg.unscripted_topics == ()


# ---------------------------------------------------------------------------
# Re-submission
# ---------------------------------------------------------------------------

def write_manifest(course_dir: Path, hashes: dict[str, str]) -> None:
    """A manifest as the config stage would have left it after a run."""
    work = course_dir / "qa_work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "manifest.json").write_text(
        json.dumps(
            {"topics": [{"topic": t, "source_sha256": h} for t, h in hashes.items()]}
        ),
        encoding="utf-8",
    )


def test_first_submission_marks_every_topic_changed(tmp_path):
    selection, result = ingest(tmp_path, topics=("01", "02", "03"))
    assert not result.resubmission
    assert sorted(result.changed_topics) == ["01", "02", "03"]
    assert result.unchanged_topics == []


def test_resubmission_detects_only_the_changed_file(tmp_path):
    """The point of the exercise: one corrected file, one topic to re-decode."""
    library = tmp_path / "library"
    selection, first = ingest(tmp_path, topics=("01", "02", "03"))

    # Stand in for a completed run: the manifest carries a hash per topic.
    by_topic = {
        m.topic: sha256_file(m.path) for m in selection.media
    }
    write_manifest(first.course_dir, by_topic)

    # The vendor returns a corrected file for topic 02 only. Same name, same
    # place, different bytes, which is exactly how a re-delivery arrives.
    (tmp_path / "Downloads" / f"{CODE}_02.mp3").write_bytes(MP3 + b"corrected")

    resubmitted = read_selection(
        [m.path for m in selection.media] + [selection.storyboard]
    )
    second = ingest_selection(
        resubmitted,
        IntakeForm(project_type="VENDOR", reviewed_by="Ryan"),
        library=library,
    )

    assert second.resubmission
    assert second.changed_topics == ["02"]
    assert sorted(second.unchanged_topics) == ["01", "03"]


def test_resubmission_with_no_changes_marks_everything_unchanged(tmp_path):
    library = tmp_path / "library"
    selection, first = ingest(tmp_path, topics=("01", "02"))
    write_manifest(
        first.course_dir, {m.topic: sha256_file(m.path) for m in selection.media}
    )
    second = ingest_selection(
        selection, IntakeForm(project_type="VENDOR", reviewed_by="Ryan"), library=library
    )
    assert second.changed_topics == []
    assert sorted(second.unchanged_topics) == ["01", "02"]
    assert any("unchanged" in w for w in second.warnings)


def test_existing_hashes_survives_a_missing_or_broken_manifest(tmp_path):
    assert existing_hashes(tmp_path / "nothing") == {}
    broken = tmp_path / "course"
    (broken / "qa_work").mkdir(parents=True)
    (broken / "qa_work" / "manifest.json").write_text("{oops", encoding="utf-8")
    assert existing_hashes(broken) == {}


# ---------------------------------------------------------------------------
# Cleanup and suggestions
# ---------------------------------------------------------------------------

def test_originals_are_only_removed_when_asked(tmp_path):
    selection, result = ingest(tmp_path)
    assert all(c.source.exists() for c in result.copied)
    removed = remove_originals(result)
    assert len(removed) == len(result.copied)
    assert all(not c.source.exists() for c in result.copied)
    assert all(c.destination.exists() for c in result.copied)


def test_removal_refuses_when_the_copy_no_longer_matches(tmp_path):
    """Never delete an original on the strength of a stale verification."""
    selection, result = ingest(tmp_path)
    for copied in result.copied:
        copied.destination.write_bytes(b"something else")
    assert remove_originals(result) == []
    assert all(c.source.exists() for c in result.copied)


def test_recent_deliveries_are_suggested_not_acted_on(tmp_path):
    delivery(tmp_path, topics=("01", "02"))
    found = find_recent_deliveries([tmp_path / "Downloads"])
    assert len(found) == 1
    assert found[0].course_code == CODE
    assert found[0].topics == ["01", "02"]
    # A suggestion copies nothing.
    assert not (tmp_path / "library").exists()


def test_unparseable_files_are_simply_not_suggested(tmp_path):
    source = tmp_path / "Downloads"
    source.mkdir()
    (source / "holiday-photo.mp3").write_bytes(MP3)
    assert find_recent_deliveries([source]) == []


def test_old_files_are_not_suggested(tmp_path):
    import os
    import time

    files = delivery(tmp_path, topics=("01",))
    old = time.time() - 90 * 86400
    for path in files:
        os.utime(path, (old, old))
    assert find_recent_deliveries([tmp_path / "Downloads"]) == []


# ---------------------------------------------------------------------------
# course.yaml rendering
# ---------------------------------------------------------------------------

def test_rendered_yaml_keeps_the_scaffolders_guidance(tmp_path):
    selection = read_selection(delivery(tmp_path))
    text = render_intake_yaml(
        selection, IntakeForm(project_type="CGT", reviewed_by="Ryan")
    )
    assert "PROBABLE MAPPING ERROR" in text, "the mapper hint must survive"
    assert "project_type: CGT" in text
    assert yaml.safe_load(text)["course_code"] == CODE


def test_confirmed_outline_topics_replace_the_todo(tmp_path):
    selection = read_selection(delivery(tmp_path, topics=("01", "12"), video=("12",)))
    text = render_intake_yaml(
        selection,
        IntakeForm(project_type="VENDOR", unscripted_topics=("12",), reviewed_by="Ryan"),
    )
    assert "TODO" not in text.split("unscripted_topics")[0].split("# Topics whose")[-1]
    assert yaml.safe_load(text)["unscripted_topics"] == ["12"]
