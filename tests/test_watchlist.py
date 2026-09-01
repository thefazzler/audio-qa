"""Tests for the pronunciation watchlist layer.

Three things have to hold. The watchlist file parses in the notation a human
would actually write. Matching goes through normalize.py, so notation is never
a miss. And the three classifications route correctly, with every LOW
CONFIDENCE and MISHEARD site becoming a listen item.

Nothing here asserts that a term was pronounced correctly, because the layer
cannot know that and neither can a test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from qa.packet import _watchlist_section
from qa.terms import extract_tokens, render_candidates, run_terms
from qa.watchlist import (
    LOW,
    MATCH,
    MISHEARD,
    WatchlistError,
    build_section,
    check_topic,
    load_watchlist,
    normalize_phrase,
    parse_watchlist,
    watchlist_path,
)


def words(pairs, step: float = 0.4, start: float = 1.0):
    """Fake transcript words: (text, confidence) with plausible timestamps."""
    out = []
    clock = start
    for text, p in pairs:
        out.append({"w": text, "start": round(clock, 2), "end": round(clock + step, 2), "p": p})
        clock += step
    return out


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------

def test_minimal_entry_defaults_expect_to_the_term():
    terms = parse_watchlist([{"term": "SIEM"}], "test")
    assert len(terms) == 1
    assert terms[0].expect == ("SIEM",)
    assert terms[0].say is None
    assert terms[0].key == ("siem",)


def test_say_is_optional_and_never_used_for_matching():
    with_say = parse_watchlist(
        [{"term": "SIEM", "say": "seem, one syllable, not spelled out"}], "test"
    )[0]
    without = parse_watchlist([{"term": "SIEM"}], "test")[0]
    assert with_say.say == "seem, one syllable, not spelled out"
    # The pronunciation note changes nothing the matcher looks at.
    assert with_say.key == without.key
    assert with_say.expect_keys == without.expect_keys


def test_multi_expect_accepts_a_list():
    """An acronym may legitimately be spelled out."""
    term = parse_watchlist(
        [{"term": "SIEM", "expect": ["SIEM", "S I E M"]}], "test"
    )[0]
    assert term.expect == ("SIEM", "S I E M")
    assert ("siem",) in term.expect_keys
    assert ("s", "i", "e", "m") in term.expect_keys


def test_matching_goes_through_the_shared_normalizer():
    """Notation differences must not read as misses.

    "IaaS" written out letter by letter collapses through the existing
    equivalence table, which is the point of not building a second normalizer.
    """
    assert normalize_phrase("IaaS") == ("iaas",)
    assert normalize_phrase("I a a S") == ("iaas",)
    assert normalize_phrase("Cyber-Kill Chain") == ("cyber", "kill", "chain")


def test_a_yaml_boolean_term_is_a_clean_error():
    """Bare NO parses as False in YAML and would silently rename the term."""
    with pytest.raises(WatchlistError, match="boolean"):
        parse_watchlist([{"term": False}], "test")


def test_unknown_keys_are_rejected_but_candidate_keys_are_not():
    with pytest.raises(WatchlistError, match="unrecognized"):
        parse_watchlist([{"term": "SIEM", "expects": "SIEM"}], "test")
    # qa-terms writes these two; promoting a candidate should be a copy.
    assert parse_watchlist(
        [{"term": "SIEM", "occurrences": 9, "seen_in": "course11:01"}], "test"
    )[0].term == "SIEM"


def test_duplicate_terms_are_rejected():
    with pytest.raises(WatchlistError, match="more than once"):
        parse_watchlist([{"term": "SIEM"}, {"term": "siem"}], "test")


def test_watchlist_lives_one_level_above_the_course(tmp_path):
    course = tmp_path / "spisccc26" / "course11"
    course.mkdir(parents=True)
    assert watchlist_path(course) == tmp_path / "spisccc26" / "watchlist.yaml"


def test_round_trip_through_a_real_file(tmp_path):
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        '- term: "SIEM"\n'
        '  expect: ["SIEM", "S I E M"]\n'
        '  say: "seem, one syllable"\n'
        '- term: "IaaS"\n',
        encoding="utf-8",
    )
    terms = load_watchlist(path)
    assert [t.term for t in terms] == ["SIEM", "IaaS"]
    assert terms[1].expect == ("IaaS",)
    assert terms[1].say is None


# ---------------------------------------------------------------------------
# The check: one MATCH, one LOW CONFIDENCE, one MISHEARD
# ---------------------------------------------------------------------------

SENTENCES = [
    "A SIEM platform correlates events.",
    "The SIEM console shows alerts.",
    "Analysts review the SIEM dashboard daily.",
]

# Site 1 heard correctly and confidently. Site 2 heard correctly but the
# decoder was unsure. Site 3 heard as something else entirely, which is the
# shape the reference course produced. The wrong token here is invented, not
# the one that course actually yielded. See D16.
TRANSCRIPT = words(
    [
        ("A", 0.99), ("SIEM", 0.95), ("platform", 0.99), ("correlates", 0.98), ("events.", 0.99),
        ("The", 0.99), ("SIEM", 0.41), ("console", 0.98), ("shows", 0.99), ("alerts.", 0.99),
        ("Analysts", 0.99), ("review", 0.99), ("the", 0.98), ("seam", 0.47),
        ("dashboard", 0.99), ("daily.", 0.99),
    ]
)


@pytest.fixture
def siem():
    return parse_watchlist([{"term": "SIEM"}], "test")


def test_the_three_classifications(siem):
    sites = check_topic(SENTENCES, TRANSCRIPT, siem)
    assert [s["status"] for s in sites] == [MATCH, LOW, MISHEARD]


def test_each_site_carries_its_evidence(siem):
    matched, low, misheard = check_topic(SENTENCES, TRANSCRIPT, siem)

    assert matched["heard"] == "SIEM" and matched["confidence"] == 0.95
    assert low["heard"] == "SIEM" and low["confidence"] == 0.41
    assert misheard["heard"] == "seam" and misheard["confidence"] == 0.47

    for site in (matched, low, misheard):
        assert site["term"] == "SIEM"
        assert site["start_s"] is not None
    # Timestamps advance with the audio, so a human can go to the site.
    assert matched["start_s"] < low["start_s"] < misheard["start_s"]


def test_every_occurrence_is_examined_not_only_the_flagged_ones(siem):
    """The whole point of a separate pass: three sites in, three sites out."""
    assert len(check_topic(SENTENCES, TRANSCRIPT, siem)) == 3


def test_low_confidence_and_misheard_become_listen_items(siem):
    sites = check_topic(SENTENCES, TRANSCRIPT, siem)
    section = build_section(siem, Path("tests/x/watchlist.yaml"), {"01": sites})

    row = section["terms"][0]
    assert (row["occurrences"], row["matched"], row["low_confidence"], row["misheard"]) == (3, 1, 1, 1)

    items = section["listen_items"]
    assert len(items) == 2
    assert {i["status"] for i in items} == {LOW, MISHEARD}
    assert all(i["tag"] == "pronunciation candidate" for i in items)
    assert all(i["topic"] == "01" for i in items)
    # A confident match is never routed to a human.
    assert all(i["confidence"] < 0.6 for i in items)


def test_the_worst_site_is_the_misheard_one(siem):
    sites = check_topic(SENTENCES, TRANSCRIPT, siem)
    section = build_section(siem, Path("x/watchlist.yaml"), {"01": sites})
    worst = section["terms"][0]["worst"]
    assert worst["status"] == MISHEARD
    assert worst["heard"] == "seam"


def test_a_spelled_out_acronym_is_a_match_when_expect_allows_it():
    terms = parse_watchlist([{"term": "SIEM", "expect": ["SIEM", "S I E M"]}], "test")
    transcript = words([("A", 0.99), ("S", 0.9), ("I", 0.9), ("E", 0.9), ("M", 0.9),
                        ("platform", 0.99), ("correlates", 0.99), ("events.", 0.99)])
    site = check_topic([SENTENCES[0]], transcript, terms)[0]
    assert site["status"] == MATCH


def test_nothing_here_is_a_defect(siem):
    """The layer routes; it never classifies. No status is a defect verdict."""
    sites = check_topic(SENTENCES, TRANSCRIPT, siem)
    assert {s["status"] for s in sites} <= {MATCH, LOW, MISHEARD}
    for site in sites:
        assert "defect" not in repr(site).lower()
        assert "severity" not in site


def test_a_term_absent_from_the_script_yields_no_sites():
    terms = parse_watchlist([{"term": "NIST"}], "test")
    assert check_topic(SENTENCES, TRANSCRIPT, terms) == []


# ---------------------------------------------------------------------------
# No watchlist at all
# ---------------------------------------------------------------------------

def test_absent_watchlist_is_skipped_not_an_error():
    section = build_section(None, Path("tests/spisccc26/watchlist.yaml"), {})
    assert section["present"] is False
    assert "run qa-terms" in section["reason"]
    assert section["terms"] == [] and section["listen_items"] == []


def test_packet_says_so_in_one_line_when_there_is_no_watchlist():
    section = build_section(None, Path("tests/spisccc26/watchlist.yaml"), {})
    text = "\n".join(_watchlist_section({"watchlist": section}))
    assert "## Watchlist" in text
    assert "no watchlist for this learning path; run qa-terms to seed one" in text
    assert "| Term |" not in text


def test_packet_watchlist_table_carries_the_disclaimer(siem):
    sites = check_topic(SENTENCES, TRANSCRIPT, siem)
    section = build_section(siem, Path("tests/spisccc26/watchlist.yaml"), {"01": sites})
    text = "\n".join(_watchlist_section({"watchlist": section}))

    assert "never certifies pronunciation as correct or wrong" in text
    assert "| Term | Occurrences | Matched | Low confidence | Misheard |" in text
    assert "pronunciation candidate" in text
    assert "seam" in text


def test_packet_omits_the_section_for_checks_json_without_one():
    """Old checks.json predates this layer; the packet must not crash on it."""
    assert _watchlist_section({"summary": {}, "topics": []}) == []


# ---------------------------------------------------------------------------
# qa-terms
# ---------------------------------------------------------------------------

def test_extraction_pulls_acronyms_and_identifier_shaped_tokens():
    found = extract_tokens(
        "A SIEM platform and NIST guidance cover IaaS, PaaS and DevSecOps for the SOC."
    )
    assert set(found) == {"SIEM", "NIST", "IaaS", "PaaS", "DevSecOps", "SOC"}


def test_extraction_ignores_ordinary_words_and_sentence_openers():
    assert extract_tokens("The analyst reviewed Windows logs in the morning.") == []


def test_extraction_folds_plural_and_possessive_acronyms():
    assert extract_tokens("Two SIEMs and the SIEM's console.") == ["SIEM", "SIEM"]


def _plant_course(root: Path, name: str, sentences: list[str]) -> Path:
    course = root / name
    (course / "qa_work").mkdir(parents=True)
    (course / "course.yaml").write_text(
        'course_number: "11"\nproject_type: VENDOR\n'
        "course_code: it_spisccc26_11_enus\n",
        encoding="utf-8",
    )
    (course / "qa_work" / "script.json").write_text(
        json.dumps({"topics": [{"topic": "01", "scripted": True, "sentences": sentences}]}),
        encoding="utf-8",
    )
    return course


def test_qa_terms_counts_occurrences_and_records_where(tmp_path):
    path_dir = tmp_path / "spisccc26"
    _plant_course(
        path_dir,
        "course11",
        ["A SIEM platform.", "The SIEM console and NIST guidance."],
    )
    result = run_terms(path_dir)

    assert result["learning_path"] == "spisccc26"
    assert dict(result["top"])["SIEM"] == 2
    assert dict(result["top"])["NIST"] == 1

    written = yaml.safe_load(Path(result["path"]).read_text(encoding="utf-8"))
    siem = next(e for e in written if e["term"] == "SIEM")
    assert siem["occurrences"] == 2
    assert siem["seen_in"] == "course11:01"
    assert siem["say"] == "TODO"


def test_qa_terms_unions_across_the_learning_path(tmp_path):
    path_dir = tmp_path / "spisccc26"
    _plant_course(path_dir, "course10", ["An IaaS deployment."])
    _plant_course(path_dir, "course11", ["A SIEM platform."])
    result = run_terms(path_dir)
    assert {t for t, _ in result["top"]} == {"IaaS", "SIEM"}
    assert result["courses"] == ["course10", "course11"]


def test_qa_terms_never_overwrites_the_watchlist(tmp_path):
    path_dir = tmp_path / "spisccc26"
    _plant_course(path_dir, "course11", ["A SIEM platform and NIST guidance."])
    watchlist = path_dir / "watchlist.yaml"
    original = '- term: "SIEM"\n  say: "seem"\n'
    watchlist.write_text(original, encoding="utf-8")

    result = run_terms(path_dir)

    assert watchlist.read_text(encoding="utf-8") == original
    # A term already promoted is not proposed again.
    assert {t for t, _ in result["top"]} == {"NIST"}
    assert result["already_listed"] == 1


def test_candidates_file_quotes_terms_that_yaml_would_read_as_booleans():
    from collections import Counter

    text = render_candidates({"NO": Counter({"course11:01": 1})}, {"NO": {"course11:01"}}, "p", set())
    assert yaml.safe_load(text)[0]["term"] == "NO"



# ---------------------------------------------------------------------------
# The script author's own pronunciation guide
# ---------------------------------------------------------------------------

def _plant_guide(course: Path, guide: list[dict]) -> None:
    """Add a Pronunciation Guide to a planted course's script.json."""
    path = course / "qa_work" / "script.json"
    script = json.loads(path.read_text(encoding="utf-8"))
    script["pronunciation_guide"] = guide
    path.write_text(json.dumps(script), encoding="utf-8")


def test_a_guide_term_carries_its_stated_pronunciation_instead_of_todo(tmp_path):
    """The one thing qa-terms cannot derive, when a human has written it down."""
    path_dir = tmp_path / "spcrisc26"
    course = _plant_course(path_dir, "course02", ["A CRISC certification."])
    _plant_guide(course, [{"term": "CRISC", "say": "see-risk", "source": "", "topic": "1"}])

    result = run_terms(path_dir)
    written = yaml.safe_load(Path(result["path"]).read_text(encoding="utf-8"))
    crisc = next(e for e in written if e["term"] == "CRISC")
    assert crisc["say"] == "see-risk"
    assert result["from_pronunciation_guide"] == ["CRISC"]


def test_a_guide_term_is_merged_with_its_occurrences_not_listed_twice(tmp_path):
    path_dir = tmp_path / "spcrisc26"
    course = _plant_course(path_dir, "course02", ["A SIEM console.", "The SIEM again."])
    _plant_guide(course, [{"term": "SIEM", "say": "seem", "source": "", "topic": "1"}])

    result = run_terms(path_dir)
    written = yaml.safe_load(Path(result["path"]).read_text(encoding="utf-8"))
    assert [e["term"] for e in written].count("SIEM") == 1
    siem = next(e for e in written if e["term"] == "SIEM")
    assert siem["occurrences"] == 2
    assert siem["say"] == "seem"


def test_a_guide_term_that_looks_nothing_like_jargon_is_still_proposed(tmp_path):
    """Shape is a heuristic; the author's own list is evidence."""
    path_dir = tmp_path / "spcrisc26"
    course = _plant_course(path_dir, "course02", ["The kettle boils."])
    _plant_guide(course, [{"term": "Kubernetes", "say": "koo-ber-net-eez", "source": "", "topic": "2"}])

    result = run_terms(path_dir)
    written = yaml.safe_load(Path(result["path"]).read_text(encoding="utf-8"))
    assert [e["term"] for e in written] == ["Kubernetes"]
    assert written[0]["occurrences"] == 0


def test_a_guide_term_already_on_the_watchlist_is_not_proposed_again(tmp_path):
    path_dir = tmp_path / "spcrisc26"
    course = _plant_course(path_dir, "course02", ["A CRISC certification."])
    _plant_guide(course, [{"term": "CRISC", "say": "see-risk", "source": "", "topic": "1"}])
    (path_dir / "watchlist.yaml").write_text(
        '- term: "CRISC"\n  say: "see-risk"\n', encoding="utf-8"
    )

    result = run_terms(path_dir)
    assert result["from_pronunciation_guide"] == []
    assert not [t for t, _ in result["top"]]
