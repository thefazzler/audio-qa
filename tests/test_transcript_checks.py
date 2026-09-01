"""The two checks that need no script.

Both exist because a topic whose script state is `none` still has audio, and
everything alignment normally catches has to come from somewhere else or not at
all. Both produce listen items and neither can produce a defect, which is what
these tests pin: the counts, the grouping, and the refusal to call anything
wrong.
"""

from __future__ import annotations

import pytest

from qa.transcript_checks import unverifiable_duplications, voiced_symbols

LOW = 0.6


def words(*spoken) -> list[dict]:
    """(text, start[, confidence]) tuples into transcript words."""
    made = []
    for item in spoken:
        text, start = item[0], item[1]
        confidence = item[2] if len(item) > 2 else 0.9
        made.append(
            {
                "w": text,
                "start": round(start, 2),
                "end": round(start + 0.1, 2),
                "p": confidence,
            }
        )
    return made


# ---------------------------------------------------------------------------
# Voiced symbols
# ---------------------------------------------------------------------------

def test_a_voiced_underscore_is_found_and_grouped_by_term():
    heard = words(
        ("a", 0.0), ("document", 0.2), ("named", 0.4), ("project", 0.6),
        ("underscore", 0.8), ("plan.", 1.0), ("Open", 5.0), ("project", 5.2),
        ("underscore", 5.4), ("plan", 5.6),
    )
    groups = voiced_symbols(heard)
    assert len(groups) == 1
    assert groups[0]["term"] == "underscore"
    assert groups[0]["occurrences"] == 2
    assert [s["start_s"] for s in groups[0]["sites"]] == [0.8, 5.4]
    assert "project underscore plan" in groups[0]["sites"][0]["context"]


def test_every_symbol_name_and_url_part_is_covered():
    for term in (
        "underscore", "hyphen", "dash", "slash", "backslash", "colon",
        "asterisk", "http", "https", "www",
    ):
        groups = voiced_symbols(words(("say", 0.0), (term, 0.2), ("now", 0.4)))
        assert [g["term"] for g in groups] == [term], term


def test_dot_counts_only_next_to_something_domain_shaped():
    """"Connect the dots" is not a URL, and a check that says it is is noise."""
    ordinary = voiced_symbols(words(("connect", 0.0), ("the", 0.2), ("dot", 0.4)))
    assert ordinary == []

    domain = voiced_symbols(
        words(("techera", 0.0), ("dot", 0.2), ("com", 0.4))
    )
    assert [g["term"] for g in domain] == ["dot"]


def test_punctuation_and_case_do_not_hide_a_voiced_symbol():
    groups = voiced_symbols(words(("plan", 0.0), ("Underscore,", 0.2), ("draft", 0.4)))
    assert [g["term"] for g in groups] == ["underscore"]
    assert groups[0]["sites"][0]["heard"] == "Underscore,"


def test_a_clean_transcript_produces_nothing():
    assert voiced_symbols(words(("the", 0.0), ("kettle", 0.2), ("boils", 0.4))) == []


def test_voiced_symbols_never_carry_a_verdict():
    """Narrators do say "underscore" on purpose. Nothing here may call it wrong."""
    groups = voiced_symbols(words(("project", 0.0), ("underscore", 0.2)))
    assert set(groups[0]) == {"term", "occurrences", "sites", "first_s"}
    assert set(groups[0]["sites"][0]) == {
        "start_s", "confidence", "heard", "context"
    }


# ---------------------------------------------------------------------------
# Unverifiable boundary duplications
# ---------------------------------------------------------------------------

def duplicated() -> tuple[list[dict], list[dict]]:
    """A word re-emitted at the head of the next segment, as faster-whisper does."""
    heard = [
        {"w": "read", "start": 0.0, "end": 0.4, "p": 0.99},
        {"w": "the", "start": 0.4, "end": 0.6, "p": 0.99},
        {"w": "document.", "start": 0.6, "end": 1.2, "p": 0.98},
        {"w": "document.", "start": 1.2, "end": 1.5, "p": 0.09},
        {"w": "Next,", "start": 1.5, "end": 1.8, "p": 0.97},
    ]
    segments = [
        {"start": 0.0, "end": 1.2, "text": "read the document."},
        {"start": 1.2, "end": 1.8, "text": "document. Next,"},
    ]
    return heard, segments


def test_a_boundary_duplication_is_listed_rather_than_dropped():
    heard, segments = duplicated()
    found = unverifiable_duplications(heard, segments, LOW)
    assert len(found) == 1
    assert found[0]["heard"] == "document."
    assert found[0]["start_s"] == 1.2
    assert found[0]["low_confidence"] is True
    assert "document. document." in found[0]["context"]


def test_a_confident_second_copy_is_still_listed():
    """Confidence triages these; it does not decide whether they exist.

    Course 10's demo has one at p 0.958. Filtering on confidence would have
    dropped it, and with no script there is nothing that could have found it
    again.
    """
    heard, segments = duplicated()
    heard[3]["p"] = 0.958
    found = unverifiable_duplications(heard, segments, LOW)
    assert len(found) == 1
    assert found[0]["low_confidence"] is False


def test_a_clean_transcript_has_no_duplications():
    heard = [
        {"w": "read", "start": 0.0, "end": 0.4, "p": 0.99},
        {"w": "the", "start": 0.4, "end": 0.6, "p": 0.99},
        {"w": "document.", "start": 0.6, "end": 1.2, "p": 0.98},
    ]
    segments = [{"start": 0.0, "end": 1.2, "text": "read the document."}]
    assert unverifiable_duplications(heard, segments, LOW) == []


def test_no_segments_means_no_claim():
    heard, _ = duplicated()
    assert unverifiable_duplications(heard, [], LOW) == []


# ---------------------------------------------------------------------------
# How the align stage attaches them
# ---------------------------------------------------------------------------

def test_the_scripted_path_keeps_symbols_and_drops_duplications():
    """Where alignment ran, the duplications are already suppressed with proof."""
    from qa.align import _add_transcript_checks

    heard, segments = duplicated()
    heard.append({"w": "underscore", "start": 2.0, "end": 2.2, "p": 0.4})
    transcript = {"words": heard, "segments": segments}

    scripted: dict = {}
    _add_transcript_checks(scripted, transcript, aligned=True)
    assert scripted["unverifiable_duplications"] == []
    assert [g["term"] for g in scripted["voiced_symbols"]] == ["underscore"]

    unscripted: dict = {}
    _add_transcript_checks(unscripted, transcript, aligned=False)
    assert len(unscripted["unverifiable_duplications"]) == 1
    assert [g["term"] for g in unscripted["voiced_symbols"]] == ["underscore"]
