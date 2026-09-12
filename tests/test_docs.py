"""The documents must not point at things that do not exist.

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
CITING = (
    "HANDOVER.md",
    "README.md",
    "COMMANDS.md",
    "GLOSSARY.md",
    "LISTENING.md",
    "PILOT.md",
)

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


# ---------------------------------------------------------------------------
# The help layer points into these documents too
# ---------------------------------------------------------------------------
# A "learn more" pointer in a tooltip or a tour step is the same kind of claim
# as a D reference, and fails the same way: invisible until somebody follows
# it. So it is checked here rather than in a parallel file of its own.

def test_there_is_at_least_one_learn_more_link():
    from qa.web.helptext import links

    assert links()


def test_every_learn_more_link_resolves_to_a_real_file_and_heading():
    from qa.web import docs_view
    from qa.web.helptext import links

    broken = []
    for link in links():
        if docs_view.find(link.doc) is None:
            broken.append(f"{link.doc} is not a document the Docs tab lists")
        elif not docs_view.resolves(link.doc, link.heading):
            broken.append(f"{link.doc} has no heading {link.heading!r}")
    assert not broken, "; ".join(broken)


def test_every_document_the_docs_tab_lists_is_in_this_repository():
    from qa.web.helptext import DOCS

    missing = [doc.key for doc in DOCS if not doc.exists]
    assert not missing, "listed in the Docs tab but not here: " + ", ".join(missing)


def test_a_learn_more_link_reads_as_a_pointer_a_person_can_follow():
    from qa.web.helptext import links

    for link in links():
        rendered = link.render()
        assert rendered.startswith("Learn more: ")
        assert link.doc in rendered


# ---------------------------------------------------------------------------
# The outstanding items and the means to close them live together
# ---------------------------------------------------------------------------
# D37: each item the handover lists as unfinished points at the document that
# makes its human step trivial. The pointer and the document are checked here
# because a handover that names a file which is not there is the same fault as
# a decision reference that resolves to nothing.

PREPARED = {
    "LISTENING.md": "LISTENING.md",
    "PILOT.md": "PILOT.md",
    "the desktop runbook": "Confirming VERSION MISMATCH on the desktop",
}


def unfinished_section() -> str:
    text = (ROOT / "HANDOVER.md").read_text(encoding="utf-8")
    start = text.index("## What is unfinished")
    end = text.index("## ", start + 3)
    return text[start:end]


@pytest.mark.parametrize("name", sorted(PREPARED), ids=lambda n: n)
def test_the_handover_points_at_every_prepared_confirmation(name):
    assert PREPARED[name] in unfinished_section(), (
        f"HANDOVER.md's unfinished list no longer points at {name}"
    )


@pytest.mark.parametrize("name", ["LISTENING.md", "PILOT.md"])
def test_a_prepared_confirmation_is_really_there(name):
    assert (ROOT / name).is_file(), f"{name} is named in HANDOVER.md but missing"


def test_the_desktop_runbook_is_where_the_handover_says():
    text = (ROOT / "COMMANDS.md").read_text(encoding="utf-8")
    assert "### Confirming VERSION MISMATCH on the desktop" in text
    assert "qa-setup.cmd --check" in text
    assert "Bring back" in text


def test_the_listening_page_ends_with_the_message_to_paste_back():
    """Both outcomes of both listens must be answerable by one paste."""
    text = (ROOT / "LISTENING.md").read_text(encoding="utf-8")
    block = text[text.index("## The message to paste back"):]
    for expected in ("ABSENT", "PRESENT", "ACCEPTABLE", "WRONG"):
        assert expected in block, f"the paste-back template has no {expected} outcome"
    assert "tests/test_course10.py" in block
    assert "tests/test_course11.py" in block


def test_the_prepared_documents_confirm_nothing():
    """They prepare a confirmation; only the results close one. D37."""
    for name in ("LISTENING.md", "PILOT.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "confirmed by ear on" not in text.lower()
        assert "confirmed live" not in text.lower()
    tests = (ROOT / "tests" / "test_course10.py").read_text(encoding="utf-8")
    tests += (ROOT / "tests" / "test_course11.py").read_text(encoding="utf-8")
    assert tests.count("pending confirmation by ear") == 2, (
        "a golden value was flipped without the listen having happened"
    )


def test_the_standing_rule_is_recorded():
    """The rule that keeps reasoning out of code-comment-only exile."""
    text = DECISIONS.read_text(encoding="utf-8")
    assert "How this file is maintained" in text
    assert "earns an entry here" in text
