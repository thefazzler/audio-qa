"""Course 11 known answer test: the pronunciation watchlist.

Course 11 is the first course other than Course 10 the pipeline has run, and it
produced the evidence that motivated the watchlist layer. The ASR fails to hear
the term SIEM at three of its fourteen sites, at confidences of 0.474, 0.282
and 0.533. General alignment surfaced those incidentally, mixed into 29 other
differences. The watchlist has to find them deliberately, and has to examine
all fourteen sites rather than only the three that happened to deviate.

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


# The three sites, as the first full run measured them. Confidences are the
# ASR's own and are asserted loosely enough to survive a rounding change but
# tightly enough that a different decode would fail here. What was heard is
# identified by digest; sites 01 and 13 share a digest because the ASR produced
# the same wrong token at both, which is itself part of the expected result.
#
# GOLDEN VALUE STATUS: pending confirmation by ear, in the same way D5's tail
# assertion was. The pipeline's claim is that all three are mishearings of a
# correctly or incorrectly voiced SIEM, and only a human listening at these
# timestamps can say which. If a listen finds the term voiced correctly at all
# three, these stay as they are: the layer is allowed to route a false alarm to
# a human, and is not allowed to miss one.
HEARD_A = "507a9a8be3d145a8"  # sites 01 and 13, a three character token
HEARD_B = "a6b46dd0d1ae5e86"  # site 11, a four character token

KNOWN_SITES = [
    {"topic": "01", "heard": HEARD_A, "confidence": 0.474, "start_s": 90.16},
    {"topic": "11", "heard": HEARD_B, "confidence": 0.282, "start_s": 46.65},
    {"topic": "13", "heard": HEARD_A, "confidence": 0.533, "start_s": 64.57},
]


def test_siem_is_misheard_at_the_three_known_sites(siem):
    misheard = [s for s in siem["sites"] if s["status"] == "MISHEARD"]
    assert len(misheard) == 3

    for site, expected in zip(misheard, KNOWN_SITES):
        assert site["topic"] == expected["topic"], expected
        assert digest(site["heard"]) == expected["heard"], expected
        assert site["confidence"] == pytest.approx(expected["confidence"], abs=0.01)
        assert site["start_s"] == pytest.approx(expected["start_s"], abs=0.5), expected

    # Two of the three sites produced the same wrong token, one produced a
    # different one. A decode that changed what it heard anywhere fails above.
    heard = [digest(s["heard"]) for s in misheard]
    assert heard[0] == heard[2] != heard[1]


def test_every_siem_site_is_examined_not_only_the_deviating_ones(siem):
    """The reason this is a separate pass from alignment.

    Alignment reports differences. It says nothing at all about the sites where
    the term was heard correctly, so it cannot answer "was this term checked
    everywhere". The watchlist can.
    """
    assert siem["occurrences"] == 14
    assert siem["matched"] == 11
    assert siem["misheard"] == 3
    assert siem["matched"] + siem["low_confidence"] + siem["misheard"] == siem["occurrences"]


def test_the_worst_site_is_the_least_confident_one(siem):
    """What a human should listen to first."""
    assert siem["worst"]["topic"] == "11"
    assert digest(siem["worst"]["heard"]) == HEARD_B
    assert siem["worst"]["confidence"] == pytest.approx(0.282, abs=0.01)
    assert siem["worst"]["confidence"] == min(
        s["confidence"] for s in siem["sites"] if s["status"] != "MATCH"
    )


def test_each_misheard_site_routes_to_a_listen_item(watchlist):
    items = [i for i in watchlist["listen_items"] if i["term"] == "SIEM"]
    assert len(items) == 3
    assert all(i["tag"] == "pronunciation candidate" for i in items)
    assert {i["topic"] for i in items} == {"01", "11", "13"}
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
    packets = sorted(OUT.glob("reconciliation_packet_*.md"))
    if not packets:
        pytest.skip("no packet built")
    return packets[-1].read_text(encoding="utf-8")


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
