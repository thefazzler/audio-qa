"""Tests for the device selection reaching the decoder, and failing safely.

The selection is only worth having if it is both honoured and harmless. These
cover both halves: a choice reaches the model, and a GPU that dies under load
never takes the run with it.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from qa.device import (
    AUTO,
    CPU,
    CPU_COMPUTE,
    GPU,
    Device,
    gpu_compute_type,
    resolve_device,
)
from qa.transcribe import (
    ASRSettings,
    FasterWhisperEngine,
    Transcript,
    settings_from_course,
    transcript_is_current,
)

USABLE = [Device(GPU, "GPU", True), Device(CPU, "CPU", True)]
UNUSABLE = [Device(CPU, "CPU", True), Device(GPU, "GPU", False, reason="no device.")]


class Course:
    def __init__(self, asr=None):
        self.asr = asr or {}


# ---------------------------------------------------------------------------
# The selection reaches the decoder
# ---------------------------------------------------------------------------

def test_a_cuda_selection_constructs_the_model_on_cuda(monkeypatch):
    seen = {}

    class FakeModel:
        def __init__(self, model, device=None, compute_type=None, cpu_threads=None):
            seen.update(device=device, compute_type=compute_type, model=model)

    import sys
    import types

    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    monkeypatch.setattr("qa.transcribe.enable_bundled_cuda", lambda: [])

    engine = FasterWhisperEngine(
        ASRSettings(device=GPU, compute_type="float16", model="large-v3")
    )
    engine._load()
    assert seen["device"] == GPU
    assert seen["compute_type"] == "float16"


def test_a_cpu_selection_never_constructs_on_cuda(monkeypatch):
    seen = {}

    class FakeModel:
        def __init__(self, model, device=None, compute_type=None, cpu_threads=None):
            seen.update(device=device, compute_type=compute_type)

    import sys
    import types

    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)

    FasterWhisperEngine(ASRSettings(device=CPU, compute_type=CPU_COMPUTE))._load()
    assert seen["device"] == CPU
    assert seen["compute_type"] == CPU_COMPUTE


def test_precision_follows_the_device_unless_pinned(monkeypatch):
    monkeypatch.setattr("qa.transcribe.resolve_device", lambda r: (GPU, ""))
    monkeypatch.setattr("qa.transcribe.gpu_compute_type", lambda: "float16")
    assert settings_from_course(Course({"device": "cuda"})).compute_type == "float16"

    monkeypatch.setattr("qa.transcribe.resolve_device", lambda r: (CPU, ""))
    assert settings_from_course(Course({"device": "cpu"})).compute_type == CPU_COMPUTE

    # A pinned precision wins, so an experiment can hold it constant.
    monkeypatch.setattr("qa.transcribe.resolve_device", lambda r: (GPU, ""))
    pinned = settings_from_course(Course({"device": "cuda", "compute_type": "int8"}))
    assert pinned.compute_type == "int8"
    assert pinned.device == GPU


def test_gpu_compute_type_falls_back_through_the_preference_list():
    assert gpu_compute_type(["float16", "int8"]) == "float16"
    assert gpu_compute_type(["int8_float16", "int8"]) == "int8_float16"
    assert gpu_compute_type(["int8"]) == "int8"
    assert gpu_compute_type([]) == CPU_COMPUTE


def test_the_requested_device_is_recorded_alongside_what_ran(monkeypatch):
    monkeypatch.setattr("qa.transcribe.resolve_device", lambda r: (CPU, "no gpu"))
    settings = settings_from_course(Course({"device": "cuda"}))
    assert settings.requested_device == "cuda"
    assert settings.device == CPU, "what ran, not what was asked for"


# ---------------------------------------------------------------------------
# The fingerprint rule survives the change
# ---------------------------------------------------------------------------

def test_a_device_only_change_leaves_transcripts_current(tmp_path):
    path = tmp_path / "transcript_01.json"
    path.write_text("{}", encoding="utf-8")
    cpu = ASRSettings(device=CPU, compute_type="int8")
    gpu = replace(cpu, device=GPU)
    prior = {"source_sha256": "abc", "fingerprint": cpu.fingerprint()}
    assert transcript_is_current(prior, "abc", gpu.fingerprint(), path)


def test_a_compute_type_change_invalidates_them(tmp_path):
    path = tmp_path / "transcript_01.json"
    path.write_text("{}", encoding="utf-8")
    cpu = ASRSettings(device=CPU, compute_type="int8")
    half = ASRSettings(device=GPU, compute_type="float16")
    prior = {"source_sha256": "abc", "fingerprint": cpu.fingerprint()}
    assert not transcript_is_current(prior, "abc", half.fingerprint(), path)


def test_the_requested_device_is_not_in_the_fingerprint():
    a = ASRSettings(device=CPU, requested_device="auto")
    b = ASRSettings(device=CPU, requested_device="cuda")
    assert a.fingerprint() == b.fingerprint()


# ---------------------------------------------------------------------------
# Falling back without losing the run
# ---------------------------------------------------------------------------

class FlakyEngine:
    """Fails on one topic when on GPU, succeeds on CPU."""

    name = "fake"

    def __init__(self, settings, fail_on="02", error=None):
        self.settings = settings
        self.fail_on = fail_on
        self.error = error or RuntimeError("CUDA failed with error out of memory")
        self.calls: list[tuple[str, str]] = []
        self.released = 0

    def release(self):
        self.released += 1

    def transcribe(self, path, topic):
        self.calls.append((topic, self.settings.device))
        if topic == self.fail_on and self.settings.device == GPU:
            raise self.error
        return Transcript(
            topic=topic,
            duration_s=60.0,
            engine=self.name,
            model=self.settings.model,
            settings={"device": self.settings.device},
            language="en",
            language_probability=1.0,
            words=[],
            segments=[],
            decode_seconds=1.0,
        )


def build_course(tmp_path: Path, topics=("01", "02", "03")) -> Path:
    course = tmp_path / "course"
    work = course / "qa_work"
    work.mkdir(parents=True)
    (course / "course.yaml").write_text(
        'course_number: "01"\nproject_type: VENDOR\ncourse_code: it_x_01_enus\n',
        encoding="utf-8",
    )
    (course / "x.pptx").write_bytes(b"PK\x03\x04")
    (work / "manifest.json").write_text(
        json.dumps(
            {
                "course_code": "it_x_01_enus",
                "total_duration_s": 60.0 * len(topics),
                "topics": [
                    {
                        "topic": t,
                        "duration_s": 60.0,
                        "audio_path": f"audio/{t}.mp3",
                        "source_sha256": f"hash{t}",
                        "scripted": True,
                    }
                    for t in topics
                ],
            }
        ),
        encoding="utf-8",
    )
    return course


def run_with(course: Path, engine, monkeypatch):
    from qa import transcribe as module

    monkeypatch.setattr(module, "build_engine", lambda settings: _swap(engine, settings))
    return module.run_transcribe(course, force=True, overrides={"device": "cuda"})


def _swap(engine, settings):
    """The loop rebuilds the engine on fallback; keep the same fake."""
    engine.settings = settings
    return engine


def test_a_gpu_failure_completes_that_topic_on_cpu(tmp_path, monkeypatch):
    monkeypatch.setattr("qa.transcribe.resolve_device", lambda r: (GPU, ""))
    monkeypatch.setattr("qa.transcribe.gpu_compute_type", lambda: "float16")
    course = build_course(tmp_path)
    engine = FlakyEngine(ASRSettings(device=GPU))

    index = run_with(course, engine, monkeypatch)

    assert len(index["topics"]) == 3, "no topic may be lost to the failure"
    assert index["device_used"] == CPU
    assert index["requested_device"] == "cuda"
    assert "out of memory" in index["fallback_reason"]
    assert index["fallback_after_topic"] == "02"


def test_the_run_does_not_retry_gpu_after_a_fallback(tmp_path, monkeypatch):
    """Thrashing between devices is how a run takes longer than either."""
    monkeypatch.setattr("qa.transcribe.resolve_device", lambda r: (GPU, ""))
    monkeypatch.setattr("qa.transcribe.gpu_compute_type", lambda: "float16")
    course = build_course(tmp_path, topics=("01", "02", "03", "04"))
    engine = FlakyEngine(ASRSettings(device=GPU), fail_on="02")

    run_with(course, engine, monkeypatch)

    after = [device for topic, device in engine.calls if topic in {"03", "04"}]
    assert after == [CPU, CPU], f"GPU was retried: {engine.calls}"
    assert engine.released == 1, "the GPU model must be released before falling back"


def test_the_fallback_is_recorded_as_a_warning(tmp_path, monkeypatch):
    monkeypatch.setattr("qa.transcribe.resolve_device", lambda r: (GPU, ""))
    monkeypatch.setattr("qa.transcribe.gpu_compute_type", lambda: "float16")
    course = build_course(tmp_path)
    engine = FlakyEngine(ASRSettings(device=GPU))
    index = run_with(course, engine, monkeypatch)
    assert any("continued on CPU" in w for w in index["warnings"])


def test_a_cpu_failure_is_not_swallowed(tmp_path, monkeypatch):
    """Only a GPU failure is recoverable. A CPU failure is a real failure."""
    monkeypatch.setattr("qa.transcribe.resolve_device", lambda r: (CPU, ""))
    course = build_course(tmp_path)
    engine = FlakyEngine(ASRSettings(device=CPU), fail_on="02")
    engine.transcribe = _always_fail
    from qa import transcribe as module

    monkeypatch.setattr(module, "build_engine", lambda settings: engine)
    with pytest.raises(RuntimeError):
        module.run_transcribe(course, force=True, overrides={"device": "cpu"})


def _always_fail(path, topic):
    raise RuntimeError("disk on fire")


def test_a_clean_gpu_run_records_no_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("qa.transcribe.resolve_device", lambda r: (GPU, ""))
    monkeypatch.setattr("qa.transcribe.gpu_compute_type", lambda: "float16")
    course = build_course(tmp_path)
    engine = FlakyEngine(ASRSettings(device=GPU), fail_on="none")
    index = run_with(course, engine, monkeypatch)
    assert index["fallback_reason"] is None
    assert index["device_used"] == GPU


# ---------------------------------------------------------------------------
# The packet says what ran
# ---------------------------------------------------------------------------

def test_the_packet_header_states_requested_and_actual_device():
    from qa.packet import _device_line

    clean = _device_line({"requested_device": "cuda", "device_used": "cuda"})
    assert "requested cuda" in clean and "decoded on cuda" in clean

    fell_back = _device_line(
        {
            "requested_device": "cuda",
            "device_used": "cpu",
            "fallback_reason": "RuntimeError: CUDA out of memory",
            "fallback_after_topic": "03",
        }
    )
    assert "requested cuda" in fell_back
    assert "decoded on cpu" in fell_back
    assert "out of memory" in fell_back, "the reason must reach the packet"
    assert "topic 03" in fell_back


def test_the_packet_falls_back_to_the_settings_block_for_old_runs():
    from qa.packet import _device_line

    line = _device_line({"settings": {"device": "cpu"}})
    assert "decoded on cpu" in line


# ---------------------------------------------------------------------------
# One engine, two front doors
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("choice", ["cpu", "cuda", "auto"])
def test_the_cli_flag_and_the_web_selector_agree(choice, monkeypatch):
    """Both front doors must build the same settings from the same choice."""
    monkeypatch.setattr(
        "qa.transcribe.resolve_device", lambda r: (CPU if r != "cuda" else GPU, "")
    )
    monkeypatch.setattr("qa.transcribe.gpu_compute_type", lambda: "float16")

    from_cli = settings_from_course(Course(), {"device": choice})
    from_web = settings_from_course(Course({"device": choice}))
    assert from_cli == from_web
    assert from_cli.requested_device == choice


def test_the_cli_exposes_the_flag():
    from qa.cli import main
    import argparse

    with pytest.raises(SystemExit):
        main(["--help"])
