"""Tests for composing a finished run into readable results.

Everything here asserts composition, not calculation: the numbers must come
from the stages' own outputs unchanged. The one thing worth guarding hardest is
that this layer never assigns a verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qa.results import (
    DIFFERENCES,
    FLAGGED,
    LISTEN,
    NO_DIFFERENCES,
    UNSCRIPTED,
    ResultsError,
    build_stats,
    collect_listen_items,
    find_packet,
    load_results,
)


@pytest.fixture
def course(tmp_path) -> Path:
    course_dir = tmp_path / "course11"
    (course_dir / "qa_work").mkdir(parents=True)
    (course_dir / "qa_out").mkdir(parents=True)
    return course_dir


def write(course: Path, name: str, payload: dict) -> None:
    (course / "qa_work" / name).write_text(json.dumps(payload), encoding="utf-8")


def topic_row(topic: str, **overrides) -> dict:
    row = {
        "topic": topic,
        "slides": [1, 4],
        "scripted": True,
        "duration_s": 300.0,
        "coverage": 1.0,
        "discrepancies": 0,
        "listen_items": 0,
        "flags": [],
        "asr_anomalies": [],
        "audio_findings": [],
        "suppressed_asr_duplicates": 0,
        "low_confidence_share": 0.004,
    }
    row.update(overrides)
    return row


def write_checks(course: Path, rows: list[dict], **summary) -> None:
    base = {
        "course_code": "it_spisccc26_11_enus",
        "course_number": "11",
        "project_type": "VENDOR",
        "topic_count": len(rows),
        "mean_coverage": 0.995,
        "total_discrepancies": sum(r["discrepancies"] for r in rows),
        "total_listen_items": sum(r["listen_items"] for r in rows),
        "total_suppressed": 0,
        "flagged_topics": [r["topic"] for r in rows if r["flags"]],
    }
    base.update(summary)
    write(course, "checks.json", {"summary": base, "topics": rows})


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def test_a_course_that_has_not_run_says_so(course):
    with pytest.raises(ResultsError, match="No results"):
        load_results(course)


def test_headline_numbers_come_straight_from_checks(course):
    write_checks(
        course,
        [topic_row("01", discrepancies=3), topic_row("02")],
        mean_coverage=0.9912,
    )
    results = load_results(course)
    assert results.course_code == "it_spisccc26_11_enus"
    assert results.project_type == "VENDOR"
    assert results.topic_count == 2
    assert results.mean_coverage == 0.9912
    assert results.total_differences == 3


def test_topic_state_is_measured_not_judged(course):
    """No verdict vocabulary may appear here; that belongs to the prompt."""
    write_checks(
        course,
        [
            topic_row("01"),
            topic_row("02", discrepancies=4),
            topic_row("03", listen_items=2),
            topic_row("04", flags=["PROBABLE MAPPING ERROR"]),
            topic_row("05", scripted=False, coverage=None),
        ],
    )
    results = load_results(course)
    states = {t.topic: t.state for t in results.topics}
    assert states["01"] == NO_DIFFERENCES
    assert states["02"] == DIFFERENCES
    assert states["03"] == LISTEN
    assert states["04"] == FLAGGED
    assert states["05"] == UNSCRIPTED

    forbidden = {"CLEAN", "FIX RECOMMENDED", "SHOWSTOPPER"}
    for value in states.values():
        assert value.upper() not in forbidden


def test_no_verdict_vocabulary_in_the_results_module():
    """A guard with teeth: judgment must not migrate into the app."""
    source = Path("qa/results.py").read_text(encoding="utf-8")
    body = source.split('"""', 2)[-1]  # skip the module docstring, which names them
    for verdict in ("SHOWSTOPPER", "FIX RECOMMENDED"):
        assert verdict not in body, f"{verdict} must come from the judgment step"


def test_a_flag_outranks_a_difference(course):
    """A flagged topic is a validation problem before a narration question."""
    write_checks(course, [topic_row("01", discrepancies=9, flags=["LOW COVERAGE"])])
    assert load_results(course).topics[0].state == FLAGGED


# ---------------------------------------------------------------------------
# The listen list
# ---------------------------------------------------------------------------

def test_listen_items_merge_alignment_and_watchlist(course):
    write_checks(course, [topic_row("01", listen_items=1)])
    write(
        course,
        "discrepancies_01.json",
        {
            "discrepancies": [
                {
                    "listen_item": True,
                    "start_s": 90.16,
                    "script_says": "alpha",
                    "voice_said": "beta",
                    "reason": "ASR confidence 0.31 below 0.6",
                    "min_confidence": 0.31,
                },
                {"listen_item": False, "start_s": 12.0, "script_says": "x", "voice_said": "y"},
            ]
        },
    )
    checks = json.loads((course / "qa_work" / "checks.json").read_text(encoding="utf-8"))
    checks["watchlist"] = {
        "present": True,
        "totals": {"terms": 1, "occurrences": 4, "matched": 3, "misheard": 1},
        "listen_items": [
            {
                "topic": "01",
                "term": "TERM",
                "heard": "other",
                "status": "MISHEARD",
                "start_s": 250.0,
                "confidence": 0.28,
                "tag": "pronunciation candidate",
            }
        ],
    }
    write(course, "checks.json", checks)

    items = collect_listen_items(course / "qa_work", checks)
    kinds = {i.kind for i in items}
    assert kinds == {"alignment", "pronunciation candidate"}
    assert len(items) == 2, "a site that is not a listen item must not appear"


def test_two_detectors_on_one_site_are_marked_corroborated(course):
    """Agreement between independent detectors is where to listen first."""
    write_checks(course, [topic_row("01")])
    write(
        course,
        "discrepancies_01.json",
        {
            "discrepancies": [
                {
                    "listen_item": True,
                    "start_s": 90.16,
                    "script_says": "TERM",
                    "voice_said": "other",
                    "reason": "low confidence",
                    "min_confidence": 0.47,
                }
            ]
        },
    )
    checks = json.loads((course / "qa_work" / "checks.json").read_text(encoding="utf-8"))
    checks["watchlist"] = {
        "present": True,
        "listen_items": [
            {
                "topic": "01",
                "term": "TERM",
                "heard": "other",
                "status": "MISHEARD",
                "start_s": 90.16,
                "confidence": 0.47,
            }
        ],
    }
    items = collect_listen_items(course / "qa_work", checks)
    assert len(items) == 2
    assert all(i.corroborated for i in items)


def test_unrelated_sites_are_not_marked_corroborated(course):
    write_checks(course, [topic_row("01")])
    write(
        course,
        "discrepancies_01.json",
        {
            "discrepancies": [
                {
                    "listen_item": True,
                    "start_s": 10.0,
                    "script_says": "a",
                    "voice_said": "b",
                    "reason": "low confidence",
                    "min_confidence": 0.4,
                }
            ]
        },
    )
    checks = json.loads((course / "qa_work" / "checks.json").read_text(encoding="utf-8"))
    checks["watchlist"] = {
        "present": True,
        "listen_items": [
            {"topic": "01", "term": "T", "heard": "x", "status": "MISHEARD", "start_s": 400.0}
        ],
    }
    items = collect_listen_items(course / "qa_work", checks)
    assert not any(i.corroborated for i in items)


def test_an_unscripted_topic_is_a_listen_item_in_itself(course):
    write_checks(course, [topic_row("09", scripted=False, coverage=None)])
    checks = json.loads((course / "qa_work" / "checks.json").read_text(encoding="utf-8"))
    items = collect_listen_items(course / "qa_work", checks)
    assert len(items) == 1
    assert items[0].kind == "outline only"
    assert "outline" in items[0].detail


def test_listen_timestamps_are_readable(course):
    write_checks(course, [topic_row("01")])
    write(
        course,
        "discrepancies_01.json",
        {
            "discrepancies": [
                {
                    "listen_item": True,
                    "start_s": 144.1,
                    "script_says": "a",
                    "voice_said": "b",
                    "reason": "r",
                    "min_confidence": 0.5,
                }
            ]
        },
    )
    checks = json.loads((course / "qa_work" / "checks.json").read_text(encoding="utf-8"))
    assert collect_listen_items(course / "qa_work", checks)[0].timestamp == "2:24.10"


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def test_stats_are_composed_from_recorded_telemetry(course):
    write_checks(course, [topic_row("01"), topic_row("02")], total_suppressed=14)
    write(
        course,
        "transcripts.json",
        {
            "engine": "faster-whisper",
            "model": "large-v3",
            "settings": {
                "compute_type": "int8",
                "device": "cpu",
                "cpu_threads": 15,
                "beam_size": 5,
                "vad": True,
            },
            "topics": [
                {"topic": "01", "duration_s": 100.0, "decode_seconds": 50.0,
                 "word_count": 200, "anomaly_count": 0},
                {"topic": "02", "duration_s": 200.0, "decode_seconds": 50.0,
                 "word_count": 400, "anomaly_count": 1},
            ],
        },
    )
    checks = json.loads((course / "qa_work" / "checks.json").read_text(encoding="utf-8"))
    stats = build_stats(course / "qa_work", checks)

    assert stats.model == "large-v3"
    assert stats.compute_type == "int8"
    assert stats.cpu_threads == 15
    assert stats.audio_seconds == 300.0
    assert stats.decode_seconds == 100.0
    assert stats.rate_realtime == pytest.approx(3.0)
    assert len(stats.per_topic) == 2
    assert stats.per_topic[0]["realtime"] == pytest.approx(2.0)
    assert stats.suppressed_duplicates == 14


def test_stats_survive_missing_telemetry(course):
    """An old run predates some fields; the panel must still draw."""
    write_checks(course, [topic_row("01")])
    checks = json.loads((course / "qa_work" / "checks.json").read_text(encoding="utf-8"))
    stats = build_stats(course / "qa_work", checks)
    assert stats.model == ""
    assert stats.rate_realtime is None
    assert stats.per_topic == []


def test_memory_is_reported_as_machine_information():
    from qa.device import memory

    reading = memory()
    assert "measured" in reading
    if reading["measured"]:
        assert reading["total_gb"] > 0
        assert "not measured" in reading["note"], "peak decode memory is not claimed"


# ---------------------------------------------------------------------------
# The packet
# ---------------------------------------------------------------------------

def test_the_newest_packet_is_offered(course):
    out = course / "qa_out"
    (out / "reconciliation_packet_x_2026-08-01.md").write_text("old", encoding="utf-8")
    (out / "reconciliation_packet_x_2026-09-01.md").write_text("new", encoding="utf-8")
    markdown, payload = find_packet(course)
    assert markdown.name.endswith("2026-09-01.md")
    assert payload is None


def test_the_packet_json_is_offered_when_present(course):
    out = course / "qa_out"
    (out / "reconciliation_packet_x_2026-09-01.md").write_text("m", encoding="utf-8")
    (out / "reconciliation_packet_x_2026-09-01.json").write_text("{}", encoding="utf-8")
    markdown, payload = find_packet(course)
    assert markdown is not None and payload is not None


def test_no_packet_is_not_an_error(course):
    write_checks(course, [topic_row("01")])
    results = load_results(course)
    assert results.packet_md is None


# ---------------------------------------------------------------------------
# Against the real Course 11 outputs
# ---------------------------------------------------------------------------

REAL = Path(__file__).parent / "spisccc26" / "course11"

pytestmark_real = pytest.mark.skipif(
    not (REAL / "qa_work" / "checks.json").exists(), reason="Course 11 outputs absent"
)


@pytestmark_real
def test_real_course_composes_without_inventing_numbers():
    results = load_results(REAL)
    checks = json.loads(
        (REAL / "qa_work" / "checks.json").read_text(encoding="utf-8")
    )
    assert results.total_differences == checks["summary"]["total_discrepancies"]
    assert results.mean_coverage == checks["summary"]["mean_coverage"]
    assert results.topic_count == checks["summary"]["topic_count"]
    assert len(results.topics) == len(checks["topics"])


@pytestmark_real
def test_real_course_listen_list_includes_pronunciation_candidates():
    results = load_results(REAL)
    kinds = {i.kind for i in results.listen}
    assert "pronunciation candidate" in kinds
    assert "alignment" in kinds
    assert any(i.corroborated for i in results.listen), (
        "alignment and the watchlist both flagged a site; that should be marked"
    )


# ---------------------------------------------------------------------------
# The checks that need no script, on the listen list
# ---------------------------------------------------------------------------

def _plant_transcript_checks(course, topic, voiced=None, duplications=None):
    """Put voiced-symbol groups and duplications into a topic's evidence file."""
    path = course / "qa_work" / f"discrepancies_{topic}.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.setdefault("discrepancies", [])
    data["voiced_symbols"] = voiced or []
    data["unverifiable_duplications"] = duplications or []
    path.write_text(json.dumps(data), encoding="utf-8")


def _sites(count, term="underscore"):
    return {
        "term": term,
        "occurrences": count,
        "first_s": 10.0,
        "sites": [
            {
                "start_s": 10.0 * (n + 1),
                "confidence": 0.3,
                "heard": term,
                "context": f"project {term} plan",
            }
            for n in range(count)
        ],
    }


def test_a_voiced_symbol_is_one_listen_item_per_term_not_per_site(course):
    """Fourteen rows would be fourteen copies of one question."""
    write_checks(course, [topic_row("09", scripted=False, coverage=None)])
    _plant_transcript_checks(course, "09", voiced=[_sites(14)])

    checks = json.loads((course / "qa_work" / "checks.json").read_text(encoding="utf-8"))
    items = collect_listen_items(course / "qa_work", checks)
    voiced = [i for i in items if i.kind == "voiced symbol"]

    assert len(voiced) == 1
    assert "14 times" in voiced[0].what
    assert voiced[0].start_s == 10.0


def test_a_grouped_listen_item_lists_timestamps_and_then_stops_counting(course):
    write_checks(course, [topic_row("09", scripted=False, coverage=None)])
    _plant_transcript_checks(course, "09", voiced=[_sites(14)])

    checks = json.loads((course / "qa_work" / "checks.json").read_text(encoding="utf-8"))
    item = next(
        i
        for i in collect_listen_items(course / "qa_work", checks)
        if i.kind == "voiced symbol"
    )
    assert item.what.count(":") >= 6
    assert "and 8 more" in item.what


def test_a_voiced_symbol_never_carries_a_verdict(course):
    write_checks(course, [topic_row("09", scripted=False, coverage=None)])
    _plant_transcript_checks(course, "09", voiced=[_sites(2)])

    checks = json.loads((course / "qa_work" / "checks.json").read_text(encoding="utf-8"))
    item = next(
        i
        for i in collect_listen_items(course / "qa_work", checks)
        if i.kind == "voiced symbol"
    )
    assert "on purpose" in item.detail
    for word in ("defect", "error", "wrong", "fix"):
        assert word not in item.detail.lower()


def test_an_unverifiable_duplication_is_one_item_per_site(course):
    """These are individual sites, not repetitions of one question."""
    write_checks(course, [topic_row("09", scripted=False, coverage=None)])
    _plant_transcript_checks(
        course,
        "09",
        duplications=[
            {"heard": "document.", "start_s": 5.0, "confidence": 0.09,
             "low_confidence": True, "context": "the document. document. Next"},
            {"heard": "save.", "start_s": 9.0, "confidence": 0.95,
             "low_confidence": False, "context": "click Save save. Now"},
        ],
    )
    checks = json.loads((course / "qa_work" / "checks.json").read_text(encoding="utf-8"))
    found = [
        i
        for i in collect_listen_items(course / "qa_work", checks)
        if i.kind == "unverifiable duplication"
    ]
    assert len(found) == 2
    assert {i.start_s for i in found} == {5.0, 9.0}


def test_a_topic_with_no_script_says_so_rather_than_saying_outline(course):
    write_checks(
        course, [topic_row("09", scripted=False, coverage=None, script="none")]
    )
    checks = json.loads((course / "qa_work" / "checks.json").read_text(encoding="utf-8"))
    items = collect_listen_items(course / "qa_work", checks)
    whole = next(i for i in items if i.what == "the whole file")
    assert whole.kind == "no script"
    assert "no script" in whole.detail
