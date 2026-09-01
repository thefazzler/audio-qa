"""Course 11 known answer test: the pronunciation watchlist.

Course 11 is the first course other than Course 10 the pipeline has run, and it
produced the evidence that motivated the watchlist layer. The ASR fails to hear
the term SIEM in three of the thirteen topics, at low confidence. General
alignment surfaced those incidentally, mixed into thirty other differences. The
watchlist has to find them deliberately, and has to examine all fourteen sites
rather than only the ones that happened to deviate.

These tests assert which topics carry the problem and which site is worst, not
how many sites there are or what confidence each one decoded at. D23 measured
those figures moving between CPU and GPU; D25 is the standing instruction not
to pin them. CPU int8 reports three misheard sites and GPU float16 four, and
both agree on everything a person acts on.

What the ASR heard at each site is pinned by digest rather than quoted, because
this repository is public and transcripts of customer narration do not belong
in it. See DECISIONS.md D13 and tests/textdigest.py.

These tests read the pipeline outputs in tests/spisccc26/course11/qa_work. They
skip when those are absent, because the narration audio and the storyboard are
Skillsoft source material and are not in version control. To produce them:

    qa-run tests/spisccc26/course11 --date 2026-08-30
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from textdigest import digest

COURSE = Path(__file__).parent / "spisccc26" / "course11"
WORK = COURSE / "qa_work"
OUT = COURSE / "qa_out"

pytestmark = pytest.mark.skipif(
    not (WORK / "checks.json").exists(),
    reason="Course 11 outputs absent; run qa-run tests/spisccc26/course11 first",
)


@pytest.fixture(scope="module")
def watchlist() -> dict:
    checks = json.loads((WORK / "checks.json").read_text(encoding="utf-8"))
    section = checks.get("watchlist")
    if not section or not section.get("present"):
        pytest.skip("no watchlist seeded for spisccc26")
    return section


@pytest.fixture(scope="module")
def siem(watchlist) -> dict:
    return next(row for row in watchlist["terms"] if row["term"] == "SIEM")


# The three topics where SIEM is misheard, and the topic a listener should
# reach for first. Not the site count, not a confidence, not the token that was
# heard: those are the figures D23 measured moving between CPU and GPU, and D25
# is the standing instruction not to pin them.
#
# CPU int8 finds three misheard sites, one per topic. GPU float16 finds four,
# because topic 11 splits into two tokens where CPU produced one. Both decodes
# agree on which topics carry the problem and on which site is worst, and those
# are the claims that reach a person.
#
# GOLDEN VALUE STATUS: pending confirmation by ear, in the same way D5's tail
# assertion was. The pipeline's claim is that these are mishearings of a
# correctly or incorrectly voiced SIEM, and only a human listening at these
# timestamps can say which. If a listen finds the term voiced correctly at all
# three, these stay as they are: the layer is allowed to route a false alarm to
# a human, and is not allowed to miss one.
MISHEARD_TOPICS = {"01", "11", "13"}
WORST_TOPIC = "11"


def test_siem_is_misheard_in_the_three_known_topics(siem):
    misheard = [s for s in siem["sites"] if s["status"] == "MISHEARD"]
    assert len(misheard) >= 3
    assert {s["topic"] for s in misheard} == MISHEARD_TOPICS

    for site in misheard:
        # Whatever was heard, it was not the expected spelling; that is what
        # MISHEARD means, and the digest proves it without quoting customer
        # narration into a public repository.
        assert digest(site["heard"]) != digest(siem["term"])
        assert site["start_s"] is not None
        assert 0.0 <= site["confidence"] <= 1.0


def test_every_siem_site_is_examined_not_only_the_deviating_ones(siem):
    """The reason this is a separate pass from alignment.

    Alignment reports differences. It says nothing at all about the sites where
    the term was heard correctly, so it cannot answer "was this term checked
    everywhere". The watchlist can.
    """
    assert siem["occurrences"] == 14
    assert siem["misheard"] >= 3
    assert siem["matched"] >= 10
    assert siem["matched"] + siem["low_confidence"] + siem["misheard"] == siem["occurrences"]


def test_the_worst_site_is_the_least_confident_one(siem):
    """What a human should listen to first."""
    assert siem["worst"]["topic"] == WORST_TOPIC
    assert digest(siem["worst"]["heard"]) != digest(siem["term"])
    assert siem["worst"]["confidence"] == min(
        s["confidence"] for s in siem["sites"] if s["status"] != "MATCH"
    )


def test_each_misheard_site_routes_to_a_listen_item(watchlist, siem):
    items = [i for i in watchlist["listen_items"] if i["term"] == "SIEM"]
    assert len(items) == siem["misheard"] + siem["low_confidence"]
    assert all(i["tag"] == "pronunciation candidate" for i in items)
    assert {i["topic"] for i in items} == MISHEARD_TOPICS
    # Every one carries a timestamp, because a listen item without one is not
    # actionable.
    assert all(i["start_s"] is not None for i in items)


def test_a_term_absent_from_this_course_reports_zero_not_a_finding(watchlist):
    """SaaS is on the path watchlist but does not appear in Course 11's script."""
    saas = next(row for row in watchlist["terms"] if row["term"] == "SaaS")
    assert saas["occurrences"] == 0
    assert saas["worst"] is None


def test_the_watchlist_never_certifies_pronunciation(watchlist):
    """No status in this layer is a pass or a defect verdict."""
    statuses = {s["status"] for row in watchlist["terms"] for s in row["sites"]}
    assert statuses <= {"MATCH", "LOW CONFIDENCE", "MISHEARD"}


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


def test_packet_carries_the_watchlist_table(packet_text, siem):
    """The row is built from the measured counts, not from a pasted string."""
    section = packet_text.split("## Watchlist")[1].split("## Per topic evidence")[0]
    row = (
        f"| {siem['term']} | {siem['occurrences']} | {siem['matched']} "
        f"| {siem['low_confidence']} | {siem['misheard']} |"
    )
    assert row in section
    # The worst site is named with its confidence so a human knows where to
    # start listening.
    assert f"(p {siem['worst']['confidence']:.3f})" in section
    assert f"{siem['misheard']} pronunciation candidates" in section


def test_packet_states_that_the_layer_does_not_certify(packet_text):
    """The disclaimer is what stops a clean table reading as a pass."""
    section = packet_text.split("## Watchlist")[1].split("## Per topic evidence")[0]
    assert "never certifies pronunciation as correct or wrong" in section
