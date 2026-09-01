"""The packet's new sections, rendered from data rather than from a run.

The packet is evidence, and these tests are mostly about what it must not say:
no slide numbers for a course that has no slides, no verdict on a listen item,
no silence about a topic that was never checked against anything.
"""

from __future__ import annotations

import pytest

from qa.packet import (
    _author_estimates,
    _decode_line,
    _dropped_blocks,
    _script_source_line,
    _source_span,
    _topic_map,
    _unscripted_section,
    _unverifiable_duplication_section,
    _voiced_symbol_section,
)


def row(topic: str, **overrides) -> dict:
    base = {
        "topic": topic,
        "slides": [4, 8],
        "source_ref": "slides 4-8",
        "script": "verbatim",
        "scripted": True,
        "duration_s": 300.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Where a topic came from
# ---------------------------------------------------------------------------

def test_a_slide_range_reads_as_a_slide_range():
    assert _source_span(row("01")) == "slides 4-8"
    assert _source_span(row("01", slides=[43, 43])) == "slides 43"


def test_a_word_script_names_its_block_instead_of_inventing_slides():
    entry = row("01", slides=None, source_ref="TOPIC 3 TITLE: PROCESS MAPPING")
    assert _source_span(entry) == "TOPIC 3 TITLE: PROCESS MAPPING"


def test_a_freeform_topic_names_its_own_document():
    entry = row("09", slides=None, source_ref="demo_script.docx", script="freeform")
    assert _source_span(entry) == "demo_script.docx"


def test_a_topic_that_knows_nothing_says_so_rather_than_guessing():
    assert _source_span({"topic": "01"}) == "n/a"


# ---------------------------------------------------------------------------
# The topic map
# ---------------------------------------------------------------------------

def test_the_topic_map_states_every_script_state_by_name():
    checks = {
        "topics": [
            row("01"),
            row("02", script="outline", scripted=False),
            row("03", script="none", scripted=False),
            row("04", script="freeform", slides=None, source_ref="demo.docx"),
        ]
    }
    text = "\n".join(_topic_map(checks))
    assert "verbatim script" in text
    assert "outline only, not aligned" in text
    assert "no script, transcript only" in text
    assert "freeform document, aligned" in text
    assert "| Topic | Script source | Script | Duration |" in text


def test_the_topic_map_of_a_word_course_carries_no_slide_numbers():
    checks = {
        "topics": [
            row("01", slides=None, source_ref="COURSE OVERVIEW"),
            row("02", slides=None, source_ref="TOPIC 1 TITLE: THE FIRST ONE"),
        ]
    }
    text = "\n".join(_topic_map(checks))
    assert "slide" not in text.lower()
    assert "COURSE OVERVIEW" in text


def test_a_dropped_block_is_named_on_the_page_with_its_reason():
    script = {
        "mapping": {
            "dropped_blocks": [
                {
                    "block": 10,
                    "title": "TOPIC 9 TITLE: AN ACTIVITY (HTML INTERACTIVITY)",
                    "reason": "the block's script is the placeholder sentence",
                    "word_count": 8,
                }
            ]
        }
    }
    text = "\n".join(_dropped_blocks(script))
    assert "not treated as a topic" in text
    assert "shift every topic after it" in text
    assert "HTML INTERACTIVITY" in text


def test_no_dropped_blocks_means_no_section_at_all():
    assert _dropped_blocks({"mapping": {"dropped_blocks": []}}) == []
    assert _dropped_blocks({}) == []


# ---------------------------------------------------------------------------
# The header rows
# ---------------------------------------------------------------------------

def test_the_script_source_row_names_the_document_and_its_kind():
    line = _script_source_line(
        {"script_source": "docx_bus", "script_document": "it_x_02_scripts.docx"}
    )
    assert "it_x_02_scripts.docx" in line
    assert "BUS Writing Template" in line

    line = _script_source_line(
        {"script_source": "pptx", "script_document": "deck.pptx", "storyboard": "deck.pptx"}
    )
    assert "PowerPoint storyboard notes" in line


def test_an_old_manifest_without_a_source_still_names_its_document():
    assert _script_source_line({"storyboard": "deck.pptx"}) == "deck.pptx"
    assert _script_source_line({}) == "not recorded"


def test_the_decode_row_carries_wall_time_rate_and_machine():
    line = _decode_line(
        {
            "machine": "Monster-MSI (Windows)",
            "topics": [
                {"duration_s": 3000.0, "decode_seconds": 300.0},
                {"duration_s": 600.0, "decode_seconds": 60.0},
            ],
        }
    )
    assert "6.0 min to decode 60.0 min of audio" in line
    assert "10.00x realtime" in line
    assert "Monster-MSI (Windows)" in line


def test_a_run_that_decoded_nothing_says_that_rather_than_dividing_by_zero():
    line = _decode_line({"topics": [{"duration_s": 60.0, "decode_seconds": 0.0}]})
    assert "no decode this run" in line
    assert "not recorded" in line


# ---------------------------------------------------------------------------
# The two script-free sections
# ---------------------------------------------------------------------------

def test_voiced_symbols_are_grouped_with_every_timestamp():
    section = _voiced_symbol_section(
        {
            "voiced_symbols": [
                {
                    "term": "underscore",
                    "occurrences": 3,
                    "first_s": 10.0,
                    "sites": [
                        {"start_s": 10.0, "confidence": 0.1, "heard": "underscore",
                         "context": "project underscore plan"},
                        {"start_s": 70.0, "confidence": 0.2, "heard": "underscore",
                         "context": "shared underscore drive"},
                        {"start_s": 130.0, "confidence": 0.3, "heard": "underscore",
                         "context": "notify underscore team"},
                    ],
                }
            ]
        }
    )
    text = "\n".join(section)
    assert "3 sites across 1 term" in text
    assert "0:10.00, 1:10.00, 2:10.00" in text
    assert "project underscore plan" in text
    assert "not defects" in text
    assert "on purpose" in text


def test_a_topic_with_no_voiced_symbols_gets_no_section():
    assert _voiced_symbol_section({"voiced_symbols": []}) == []
    assert _voiced_symbol_section({}) == []


def test_unverifiable_duplications_say_why_they_are_not_suppressed():
    section = _unverifiable_duplication_section(
        {
            "unverifiable_duplications": [
                {"heard": "document.", "start_s": 5.0, "confidence": 0.09,
                 "low_confidence": True, "context": "the document. document. Next"},
                {"heard": "save.", "start_s": 9.0, "confidence": 0.95,
                 "low_confidence": False, "context": "click Save save. Now"},
            ]
        }
    )
    text = "\n".join(section)
    assert "unverifiable without a script" in text
    assert "0.090 (low)" in text
    assert "0.950" in text and "0.950 (low)" not in text
    assert "alignment has already proved" in text


def test_no_duplications_means_no_section():
    assert _unverifiable_duplication_section({"unverifiable_duplications": []}) == []


# ---------------------------------------------------------------------------
# A topic with no script at all
# ---------------------------------------------------------------------------

def transcript_evidence() -> dict:
    return {
        "segments": [{"start_s": 0.0, "text": "In this demonstration, we begin."}],
        "low_confidence_words": [],
    }


def test_a_none_topic_says_it_was_checked_against_nothing():
    lines = _unscripted_section(
        {"script": "none"}, {}, transcript_evidence()
    )
    text = "\n".join(lines)
    assert "no script" in text
    assert "whole of the evidence" in text
    assert "outline" not in text.lower()
    assert "In this demonstration, we begin." in text


def test_an_outline_topic_still_shows_its_outline():
    lines = _unscripted_section(
        {"script": "outline", "outline": ["Show the sharing dialog."]},
        {},
        transcript_evidence(),
    )
    text = "\n".join(lines)
    assert "Script outline" in text
    assert "Show the sharing dialog." in text
    assert "rather than against wording" in text


def test_an_entry_that_says_nothing_is_treated_as_an_outline():
    """The state existed before the key did; an old script.json still reads."""
    lines = _unscripted_section({}, {}, transcript_evidence())
    assert "outline" in "\n".join(lines).lower()


# ---------------------------------------------------------------------------
# The author's numbers
# ---------------------------------------------------------------------------

def test_the_author_section_says_it_is_not_a_threshold():
    text = "\n".join(
        _author_estimates(
            {
                "topics": [
                    {"topic": "01", "word_count": 863, "author_word_count": 863,
                     "author_estimate": "6m 10s"}
                ]
            }
        )
    )
    assert "reference" in text
    assert "Nothing in the pipeline compares" in text
    assert "6m 10s" in text
