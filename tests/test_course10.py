"""Course 10 known answer test.

Course 10 was reconciled by hand on 2026-08-25 using two LLM transcribers and
a Claude judgment session. That run's conclusions are the answer this pipeline
has to reproduce, and the places where it does better are asserted too, so a
regression that quietly reintroduces the old failures fails here.

These tests read the pipeline outputs in tests/spisccc26/course10/qa_work and
qa_out. They skip when those are absent, because the narration audio and the
storyboard are Skillsoft source material and are not in version control. To
produce them:

    qa-run tests/spisccc26/course10 --date 2026-08-27
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qa.normalize import build_sequence, script_tokens, transcript_tokens
from textdigest import digest

# Courses live at tests/<learning_path>/<course>/; Course 10 is the tenth
# course of the spisccc26 learning path.
COURSE = Path(__file__).parent / "spisccc26" / "course10"
WORK = COURSE / "qa_work"
OUT = COURSE / "qa_out"

pytestmark = pytest.mark.skipif(
    not (WORK / "checks.json").exists(),
    reason="Course 10 outputs absent; run qa-run tests/spisccc26/course10 first",
)

# The manual run's topic to slide map, assigned by narration continuity and
# marked "verify" in that report. The mapper must reproduce it with no
# slide_map supplied in course.yaml.
KNOWN_MAP = {
    "01": [2, 3],
    "02": [4, 8],
    "03": [9, 12],
    "04": [13, 19],
    "05": [20, 27],
    "06": [28, 32],
    "07": [33, 37],
    "08": [38, 42],
    "09": [43, 43],
    "10": [44, 46],
}

SCRIPTED = [t for t in KNOWN_MAP if t != "09"]

# Expected narration is pinned by digest rather than quoted, because this
# repository is public and the storyboards are customer material. See D13 and
# tests/textdigest.py. A digest fails on exactly the regressions the literal
# string used to catch.
TEASER_DIGEST = "21d420935fdd0d78"          # topic 10's closing sentence, 14 words
TOPIC_01_CLOSE_DIGEST = "7245f06b605943f0"  # topic 01's closing sentence, 29 words
L7_SCRIPT_DIGEST = "cbafbe5ce4c05886"       # listen item L7, what the script says
L7_VOICE_DIGEST = "57866be9414be757"        # listen item L7, what the voice said


def sentence_of(script: dict, topic: str, index: int) -> str:
    """One script sentence, read from pipeline output rather than hardcoded."""
    entry = next(t for t in script["topics"] if t["topic"] == topic)
    return entry["sentences"][index]


def normalized(text: str) -> list[str]:
    """Script text through the pipeline's own normalizer."""
    return [t.norm for t in build_sequence(script_tokens([text]))]


def normalized_words(words: list[dict]) -> list[str]:
    """Transcript words through the same normalizer, so the two compare."""
    return [t.norm for t in build_sequence(transcript_tokens(words))]


def _contains(haystack: list[str], needle: list[str]) -> bool:
    """True when needle appears as a contiguous run inside haystack."""
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[i : i + len(needle)] == needle
        for i in range(len(haystack) - len(needle) + 1)
    )


def load(name: str) -> dict:
    return json.loads((WORK / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def checks() -> dict:
    return load("checks.json")


@pytest.fixture(scope="module")
def script() -> dict:
    return load("script.json")


def discrepancies(topic: str) -> dict:
    return load(f"discrepancies_{topic}.json")


def transcript(topic: str) -> dict:
    return load(f"transcript_{topic}.json")


# ---------------------------------------------------------------------------
# Ingest and mapping
# ---------------------------------------------------------------------------

def test_mixed_delivery_is_ingested():
    """Nine mp3s pass through, the one mp4 demo is demuxed."""
    ingest = load("ingest.json")
    assert ingest["counts"]["total"] == 10
    assert ingest["counts"]["passthrough"] == 9
    demuxed = [f for f in ingest["files"] if f["action"] == "demux"]
    assert len(demuxed) == 1
    assert demuxed[0]["container"] == "mp4"
    assert demuxed[0]["audio_path"].endswith(".wav")


def test_container_format_is_recorded_and_never_warned_about():
    """The VENDOR-expects-audio warning fired on every correct delivery.

    Topics normally arrive as mp4 and need demux on both project types, so the
    container says nothing about the project type. See D26.
    """
    ingest = load("ingest.json")
    assert not any("expects" in w for w in ingest["warnings"])
    assert ingest["expected_kind"] == "any"


def test_auto_mapper_reproduces_the_known_slide_map(script):
    """No slide_map is supplied; the mapper has to get here on its own."""
    assert script["mapping"]["source"] == "auto"
    assert {t["topic"]: t["slides"] for t in script["topics"]} == KNOWN_MAP


def test_template_slide_excluded_and_brandfolder_slides_kept(script):
    excluded = {e["slide"] for e in script["mapping"]["excluded_slides"]}
    assert excluded == {1}
    # Slides 12, 19, 28, 32, 37 and 42 carry Brandfolder links as titles but
    # narration in their notes, so they belong to their topics.
    mapped = {n for t in script["topics"] for n in t["slide_numbers"]}
    assert {12, 19, 28, 32, 37, 42} <= mapped


def test_demo_topic_is_unscripted(script):
    demo = next(t for t in script["topics"] if t["topic"] == "09")
    assert demo["scripted"] is False
    assert demo["outline"]


# ---------------------------------------------------------------------------
# The headline result: word level fidelity
# ---------------------------------------------------------------------------

def test_no_deletions_anywhere_in_the_course():
    """The manual run found no missing narration. Neither should this one.

    A deletion here would also be the signature of the duplicate suppression
    going wrong, since suppressing a matched word invents a deletion.
    """
    for topic in SCRIPTED:
        assert discrepancies(topic)["counts"]["deletion"] == 0, topic


def test_coverage_is_effectively_complete(checks):
    assert checks["summary"]["mean_coverage"] >= 0.99
    for row in checks["topics"]:
        if row["scripted"]:
            assert row["coverage"] >= 0.99, row["topic"]


def test_tail_matched_on_every_scripted_topic(checks):
    """The deterministic replacement for the transcriber's FINAL SENTENCE.

    The LLM run truncated 4 of 9 tails without saying so. This is the check
    that makes that failure impossible to hide.
    """
    for row in checks["topics"]:
        if row["scripted"]:
            assert row["tail_matched"] is True, row["topic"]


def test_no_topic_carries_a_check_flag(checks):
    assert checks["summary"]["flagged_topics"] == []


def test_discrepancies_are_few_and_no_content_is_missing():
    """Nothing is deleted anywhere, and what survives is a handful of sites.

    Insertions used to be zero as well. They are not any more, and the reason
    is a real improvement rather than a regression: see the SaaS test below.
    """
    total = 0
    for topic in SCRIPTED:
        result = discrepancies(topic)
        total += len(result["discrepancies"])
        assert result["counts"]["deletion"] == 0, topic
    assert total <= 5, "Course 10 should stay near silent after normalization"


def test_the_saas_family_is_absorbed_rather_than_reported(script):
    """The service-model family never appears as a difference, on any device.

    GPU decode writes "SAS" for "SaaS" at two sites in topic 04 and used to
    report them as substitutions; the narrator said "sass" both times. CPU
    decode writes them differently again, which is exactly why this asserts the
    claim rather than the tokens: whatever the decoder wrote, no member of the
    family reaches the discrepancy table.

    The term is on the watchlist, so it is listened to rather than diffed. An
    equivalence that absorbs a difference without a watchlist entry beside it is
    the pipeline quietly ceasing to look.

    On the GPU run the course total went from 4 differences to 3, not to 2 as
    expected, and the missing one is worth recording. One of the two SAS sites
    had been fused into a single substitution row together with a separate
    low-confidence insertion, so removing the SaaS half leaves that insertion
    standing on its own, correctly, as the listen item it always was.
    """
    family = {"SAS", "SAAS", "IAS", "IAAS", "PAS", "PAAS"}
    for topic in SCRIPTED:
        for item in discrepancies(topic)["discrepancies"]:
            words = (item["script_says"] + " " + item["voice_said"]).split()
            hit = family & {w.strip(" .,").upper() for w in words}
            assert not hit, f"topic {topic} reports {hit} as a difference"


def test_the_absorbed_terms_are_still_in_the_transcript(script):
    """Absorbed means not diffed, not removed. The evidence stays on the page."""
    transcript = json.loads((WORK / "transcript_04.json").read_text(encoding="utf-8"))
    heard = {w["w"].strip(" .,").upper() for w in transcript["words"]}
    assert {"SAS", "SAAS"} & heard, "topic 04 is the service-model topic"


def test_the_absorbed_terms_are_all_on_the_watchlist(checks):
    """Every term EQUIVALENCES folds has to be listened to somewhere."""
    watchlist = checks.get("watchlist") or {}
    if not watchlist.get("present"):
        pytest.skip("no watchlist for this learning path")
    listed = {row["term"] for row in watchlist["terms"]}
    assert {"SaaS", "IaaS", "PaaS"} <= listed


def test_topics_the_manual_run_called_clean_are_clean():
    """02, 03, 07, 08 and 10 had every deviation arbitrated as instrument error."""
    for topic in ("01", "02", "03", "07", "08", "10"):
        assert discrepancies(topic)["discrepancies"] == [], topic


# ---------------------------------------------------------------------------
# Listen item L5: the open question the manual run could not settle
# ---------------------------------------------------------------------------

def test_file_01_does_not_end_with_the_topic_10_teaser(script):
    """L5, settled.

    One transcriber recorded a closing sentence on file 01 that the storyboard
    places on topic 10's final slide. The other did not, but that one was a
    documented final sentence dropper, so its silence cleared nothing and the
    manual run had to leave the question open.

    Pipeline answer, large-v3 int8: the sentence is absent from file 01. The
    transcript ends on topic 01's own closing script sentence at above 0.99
    confidence, then 3.36 s of silence.

    Both sentences are read from script.json at run time and compared through
    the pipeline's own normalizer, so this file quotes no narration and the
    assertion holds against whatever the storyboard actually says rather than
    against a copy of it. See DECISIONS.md D13.

    GOLDEN VALUE STATUS: pending confirmation by ear. If a listen finds the
    sentence present, this test failing is the correct outcome, because that
    would mean the ASR missed it.
    """
    teaser = normalized(sentence_of(script, "10", -1))
    own_close = normalized(sentence_of(script, "01", -1))
    assert digest(sentence_of(script, "10", -1)) == TEASER_DIGEST
    assert digest(sentence_of(script, "01", -1)) == TOPIC_01_CLOSE_DIGEST

    data = transcript("01")
    spoken = normalized_words(data["words"])

    # The teaser does not occur anywhere in file 01.
    assert not _contains(spoken, teaser), "topic 10's closing sentence is in file 01"

    # File 01 ends on its own closing sentence, at high confidence, then goes
    # quiet. Comparing token sequences is stricter than the old substring
    # check and needs no literal text.
    assert spoken[-len(own_close):] == own_close
    assert min(w["p"] for w in data["words"][-5:]) > 0.99
    assert data["duration_s"] - data["last_word_end"] == pytest.approx(3.36, abs=0.1)
    assert discrepancies("01")["tail_matched"] is True


def test_the_teaser_sentence_belongs_to_topic_10(script):
    topic_10 = next(t for t in script["topics"] if t["topic"] == "10")
    last = topic_10["sentences"][-1]
    assert digest(last) == TEASER_DIGEST
    assert len(last.split()) == 14
    assert topic_10["sentence_slides"][-1] == 46


def test_listen_item_l6_clears():
    """Manual L6: one transcriber heard a singular where the script has a plural.

    The script and the other transcriber both had the plural. ASR agrees with
    the script, so the singular was a mishearing and topic 03 is clean.
    """
    assert discrepancies("03")["discrepancies"] == []


def test_listen_item_l7_is_corroborated_not_cleared():
    """Manual L7: one transcriber heard a two word substitution in topic 04.

    The manual run dismissed it as a presumptive mishearing because the second
    transcriber matched the script. Whisper, a third and acoustically
    independent instrument, hears what the first one heard. Two independent
    instruments now read against the script at this site, so it stays open
    rather than cleared.

    Asserted by digest so the site is pinned exactly without quoting either
    the script or the transcript.
    """
    items = discrepancies("04")["discrepancies"]
    match = [d for d in items if digest(d["script_says"]) == L7_SCRIPT_DIGEST]
    assert len(match) == 1, "the L7 site must still be reported"

    site = match[0]
    assert digest(site["voice_said"]) == L7_VOICE_DIGEST
    assert site["type"] == "substitution"
    assert len(site["script_says"].split()) == 2
    assert len(site["voice_said"].split()) == 2
    assert site["start_s"] == pytest.approx(144.1, abs=0.5)

    # The confidence is device dependent and the exact value is not the claim.
    # CPU int8 reports 0.845 here and GPU float16 reports 0.923; D23 measured
    # that difference across the whole course. What must hold on any device is
    # that this site is well clear of the listen item floor, because that is
    # what makes it a corroborated finding rather than an unsure decode.
    assert site["min_confidence"] > 0.6
    assert site["min_confidence"] > 0.75, "a confident reading, on either device"


# ---------------------------------------------------------------------------
# Instrument behavior
# ---------------------------------------------------------------------------

def test_segment_boundary_duplicates_are_suppressed_and_recorded():
    total = sum(
        len(discrepancies(t)["suppressed_asr_duplicates"]) for t in SCRIPTED
    )
    assert total >= 10, "the artifact is reproducible; it should still be caught"
    sample = discrepancies("08")["suppressed_asr_duplicates"]
    assert all(s["start_s"] is not None for s in sample)
    assert all("duplication" in s["reason"] for s in sample)


def test_pace_is_judged_by_ratio_not_by_an_absolute_floor(checks):
    """Course 10 runs about 115 wpm, below the spec's 120 floor.

    Under the original rule nine of ten files would read as POSSIBLE
    TRUNCATION. Under the ratio rule every file is correctly paced.
    """
    for row in checks["topics"]:
        if not row["scripted"]:
            continue
        assert row["transcript_wpm"] < 130, row["topic"]
        assert 0.95 <= row["pace_ratio"] <= 1.05, row["topic"]
        assert not [f for f in row["flags"] if "PACE" in f], row["topic"]


def test_audio_conventions_are_measured_not_flagged():
    """3.00 s pads and 3.36 s slide gaps are house style, not defects."""
    index = load("artifacts.json")
    conventions = index["conventions"]
    assert conventions["leading_pad_s"] == pytest.approx(3.0, abs=0.1)
    assert conventions["trailing_pad_s"] == pytest.approx(3.0, abs=0.1)
    assert conventions["slide_gap_s"] == pytest.approx(3.36, abs=0.2)
    assert index["conventional_gaps"] >= 40
    assert index["total_findings"] == 0


def test_demo_is_judged_against_its_own_rhythm():
    """Topic 09 pauses about 1.35 s where the decks pause 3.36 s."""
    demo = load("artifacts_09.json")
    assert demo["gap_norm_source"] == "file"
    assert demo["gap_norm_s"] == pytest.approx(1.35, abs=0.2)
    assert demo["findings"] == []


def test_low_confidence_anomaly_fires_on_share_not_on_presence(checks):
    """Every file has a few unsure words; that is not an anomaly by itself."""
    flagged = [
        r["topic"] for r in checks["topics"] if "low_confidence_words" in r["asr_anomalies"]
    ]
    assert len(flagged) <= 3
    for row in checks["topics"]:
        if row["low_confidence_share"] is not None and row["low_confidence_share"] < 0.01:
            assert "low_confidence_words" not in row["asr_anomalies"], row["topic"]


# ---------------------------------------------------------------------------
# Packet
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def packet_text() -> str:
    """The packet *this* run produced, read from the marker the stage wrote.

    Deliberately not a glob of qa_out. Packets now go to the output folder and
    are named for the run that made them (D28), so a glob of the course folder
    finds whatever was left there by some earlier build and quietly asserts
    against it. That is exactly how these tests kept passing on wording that
    had already changed.
    """
    marker = OUT / "packet_index.json"
    if not marker.exists():
        pytest.skip("no packet built")
    recorded = json.loads(marker.read_text(encoding="utf-8")).get("path")
    if not recorded or not Path(recorded).exists():
        pytest.fail(
            f"{marker} points at {recorded}, which is not there. Re-run the "
            "course; do not fall back to an older packet."
        )
    return Path(recorded).read_text(encoding="utf-8")


def test_packet_carries_the_demo_transcript_at_full_length(packet_text):
    """Page budget suppression applies to scripted topics only."""
    demo_section = packet_text.split("### Topic 09")[1].split("### Topic 10")[0]
    assert "Script outline" in demo_section
    assert "Full transcript with timestamps" in demo_section
    assert demo_section.count("\n- `") > 90, "demo transcript should not be trimmed"


def test_packet_states_the_measured_conventions(packet_text):
    """Absorbing house style is only honest if the house style is on the page."""
    assert "## Measured audio conventions" in packet_text
    assert "3.36 s between slides" in packet_text
    assert "matching this file's norm" in packet_text


def test_packet_reports_suppressed_duplicates(packet_text):
    assert "segment boundary duplication" in packet_text


def test_packet_scripted_portion_stays_short(packet_text):
    """The 2 to 6 page target holds for the scripted part of the course."""
    demo = packet_text.split("### Topic 09")[1].split("### Topic 10")[0]
    scripted_words = len(packet_text.split()) - len(demo.split())
    assert scripted_words < 2000, "scripted evidence should stay under 4 pages"


def test_packet_names_the_engine_and_coverage(packet_text):
    assert "faster-whisper large-v3" in packet_text
    assert "99.9" in packet_text
