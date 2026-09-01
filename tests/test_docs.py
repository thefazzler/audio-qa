"""The documents must not point at decisions that do not exist.

A dangling cross reference is invisible until someone follows it, and the one
that prompted this test pointed at a decision that had never been written: the
reasoning lived only in a code comment and its tests, which is exactly where a
decision is easiest to undo by accident.

These tests are cheap and they run on every suite, so a reference to a missing
decision fails the build rather than waiting for a reader to notice.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "DECISIONS.md"

# Documents that are allowed to cite decisions.
CITING = ("HANDOVER.md", "README.md", "COMMANDS.md")

# "D21", "**D21**", "D21." but not the "3D" in a product name.
REFERENCE = re.compile(r"\bD(\d+)\b")
HEADING = re.compile(r"^## D(\d+)\.", re.MULTILINE)


def decision_numbers() -> set[int]:
    return {int(n) for n in HEADING.findall(DECISIONS.read_text(encoding="utf-8"))}


def references(text: str) -> set[int]:
    return {int(n) for n in REFERENCE.findall(text)}


def test_decisions_file_has_entries():
    assert len(decision_numbers()) >= 20


def test_decision_numbers_are_unique_and_unbroken():
    """A duplicated or skipped number makes every citation ambiguous."""
    numbers = HEADING.findall(DECISIONS.read_text(encoding="utf-8"))
    as_ints = [int(n) for n in numbers]
    assert len(as_ints) == len(set(as_ints)), "a decision number is used twice"
    assert as_ints == sorted(as_ints), "decisions are out of order"
    assert as_ints == list(range(1, len(as_ints) + 1)), "a decision number is skipped"


@pytest.mark.parametrize("name", CITING)
def test_every_decision_reference_resolves(name):
    path = ROOT / name
    if not path.exists():
        pytest.skip(f"{name} is not in this repository")
    known = decision_numbers()
    cited = references(path.read_text(encoding="utf-8"))
    missing = sorted(n for n in cited if n not in known)
    assert not missing, (
        f"{name} cites decisions that do not exist in DECISIONS.md: "
        + ", ".join(f"D{n}" for n in missing)
    )


def test_decisions_may_cite_each_other_safely():
    known = decision_numbers()
    cited = references(DECISIONS.read_text(encoding="utf-8"))
    missing = sorted(n for n in cited if n not in known)
    assert not missing, (
        "DECISIONS.md cites decisions that do not exist: "
        + ", ".join(f"D{n}" for n in missing)
    )


def test_no_placeholder_references_survive():
    """The shape of the bug this file exists for: a reference never filled in."""
    patterns = ("D-comment", "D-entry", "see D)", "(D?)", "DXX", "TBD")
    for name in CITING + ("DECISIONS.md",):
        path = ROOT / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            assert pattern not in text, f"{name} still contains {pattern!r}"


def test_the_standing_rule_is_recorded():
    """The rule that keeps reasoning out of code-comment-only exile."""
    text = DECISIONS.read_text(encoding="utf-8")
    assert "How this file is maintained" in text
    assert "earns an entry here" in text
