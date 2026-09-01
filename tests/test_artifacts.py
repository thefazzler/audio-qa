"""Tests for acoustic artifact detection.

Course 10 produces zero artifact findings, which is the correct answer for
that course but proves nothing on its own. These tests build signals with
known defects and assert the detector still fires.
"""

from __future__ import annotations

import numpy as np
import pytest

from qa.artifacts import (
    CONVENTION_MIN_SAMPLES,
    apply_conventions,
    find_abrupt_end,
    find_clipping,
    find_silences,
    frame_rms,
    measure_conventions,
)

RATE = 24000


def speech(seconds: float, level: float = 0.3) -> np.ndarray:
    """A tone at speech level. Content does not matter, energy does."""
    t = np.arange(int(seconds * RATE)) / RATE
    return (level * np.sin(2 * np.pi * 180 * t)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * RATE), dtype=np.float32)


def build(*parts: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(np.concatenate(parts))


def analyze_signal(samples: np.ndarray):
    duration = len(samples) / RATE
    levels, times = frame_rms(samples, RATE)
    findings, leading, trailing = find_silences(levels, times, duration)
    return findings, leading, trailing, levels, times, duration


# ---------------------------------------------------------------------------
# Silence measurement
# ---------------------------------------------------------------------------

def test_measures_leading_and_trailing_silence():
    samples = build(silence(3.0), speech(4.0), silence(3.0))
    _, leading, trailing, *_ = analyze_signal(samples)
    assert leading == pytest.approx(3.0, abs=0.05)
    assert trailing == pytest.approx(3.0, abs=0.05)


def test_finds_internal_gap():
    samples = build(speech(2.0), silence(3.4), speech(2.0))
    findings, *_ = analyze_signal(samples)
    gaps = [f for f in findings if f.type == "internal_silence"]
    assert len(gaps) == 1
    assert gaps[0].end_s - gaps[0].start_s == pytest.approx(3.4, abs=0.1)


def test_fully_silent_file_is_high_severity():
    findings, *_ = analyze_signal(silence(5.0))
    assert [f.type for f in findings] == ["silent_file"]
    assert findings[0].severity == "high"


# ---------------------------------------------------------------------------
# Clipping and abrupt ends
# ---------------------------------------------------------------------------

def test_detects_clipping():
    samples = build(speech(1.0))
    samples[5000:5040] = 1.0
    findings = find_clipping(samples, RATE)
    assert len(findings) == 1
    assert findings[0].severity == "high"


def test_ignores_a_single_hot_sample():
    samples = build(speech(1.0))
    samples[5000] = 1.0
    assert find_clipping(samples, RATE) == []


def test_detects_abrupt_end():
    """Speech running to the last sample with no trailing room."""
    samples = build(speech(3.0))
    _, _, trailing, levels, times, duration = analyze_signal(samples)
    findings = find_abrupt_end(levels, times, duration, trailing)
    assert [f.type for f in findings] == ["abrupt_end"]
    assert findings[0].severity == "high"


def test_normal_tail_is_not_abrupt():
    samples = build(speech(3.0), silence(3.0))
    _, _, trailing, levels, times, duration = analyze_signal(samples)
    assert find_abrupt_end(levels, times, duration, trailing) == []


# ---------------------------------------------------------------------------
# Course conventions
# ---------------------------------------------------------------------------

def make_result(topic: str, gaps: list[float], leading=3.0, trailing=3.0) -> dict:
    clock = leading
    findings = []
    for length in gaps:
        clock += 20.0
        findings.append(
            {
                "type": "internal_silence",
                "start_s": round(clock, 2),
                "end_s": round(clock + length, 2),
                "detail": "",
                "severity": "candidate",
            }
        )
        clock += length
    return {
        "topic": topic,
        "duration_s": round(clock + trailing, 2),
        "leading_silence_s": leading,
        "trailing_silence_s": trailing,
        "findings": findings,
    }


def test_house_style_gaps_are_absorbed_as_convention():
    results = [make_result(f"0{i}", [3.35, 3.37, 3.36]) for i in range(1, 5)]
    conventions = measure_conventions(results)
    assert conventions["slide_gap_s"] == pytest.approx(3.36, abs=0.02)
    applied = apply_conventions(results[0], conventions)
    assert applied["findings"] == []
    assert applied["conventional_gaps"] == 3


def test_gap_that_breaks_the_house_style_is_reported():
    results = [make_result(f"0{i}", [3.35, 3.36, 3.37]) for i in range(1, 5)]
    outlier = make_result("05", [3.36, 12.0, 3.35])
    conventions = measure_conventions(results + [outlier])
    applied = apply_conventions(outlier, conventions)
    reported = [f for f in applied["findings"] if f["type"] == "internal_silence"]
    assert len(reported) == 1
    assert reported[0]["end_s"] - reported[0]["start_s"] == pytest.approx(12.0, abs=0.1)


def test_a_file_with_its_own_rhythm_uses_its_own_norm():
    """Course 10's demo pauses 1.35 s where its decks pause 3.36 s."""
    decks = [make_result(f"0{i}", [3.35, 3.36, 3.37]) for i in range(1, 5)]
    demo = make_result("09", [1.35] * CONVENTION_MIN_SAMPLES)
    conventions = measure_conventions(decks + [demo])
    applied = apply_conventions(demo, conventions)
    assert applied["gap_norm_source"] == "file"
    assert applied["gap_norm_s"] == pytest.approx(1.35, abs=0.02)
    assert applied["findings"] == []


def test_a_file_with_too_few_gaps_falls_back_to_the_course_norm():
    decks = [make_result(f"0{i}", [3.35, 3.36, 3.37]) for i in range(1, 5)]
    odd = make_result("09", [1.2, 1.2])
    conventions = measure_conventions(decks + [odd])
    applied = apply_conventions(odd, conventions)
    assert applied["gap_norm_source"] == "course"
    assert len(applied["findings"]) == 2


def test_edge_padding_deviation_is_reported():
    results = [make_result(f"0{i}", [3.36, 3.35, 3.37]) for i in range(1, 5)]
    odd = make_result("05", [3.36, 3.35, 3.37], leading=0.05, trailing=3.0)
    conventions = measure_conventions(results + [odd])
    applied = apply_conventions(odd, conventions)
    assert any(f["type"] == "leading_silence_deviation" for f in applied["findings"])
