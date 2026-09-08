"""Every word of help and training in the interface, in one place.

Three surfaces, one source. A field's hover tooltip, a step of the first-run
tour and a "learn more" pointer into the Docs tab all read from this module,
so the voice cannot drift between them and the whole layer is reviewable on
one screen. Pruning it is a single edit to a single file; that is the point.

**One budget.** The combined tooltip and tour text must fit within one page,
`BUDGET` words, and a test holds it. When a draft goes over, cut until it fits
rather than raising the number: terse and read beats thorough and skipped. See
DECISIONS.md D30.

What a tooltip says: what to enter and what getting it wrong costs, not a
definition. A field whose label already says everything gets none, and no
tooltip goes inside a results table cell — if a result needs explaining it is
explained once, in the column header.

A `Link` points at a real heading in a real document, and a test resolves every
one of them. Link only where the section adds something the tooltip did not; a
link that leads to a restatement teaches people to stop clicking.

`Step.where` names an area of the interface by the label already on screen
("Intake", "Results"), so it is a pointer rather than help prose and does not
count against the budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# One page. Not a target to grow into.
BUDGET = 500

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Doc:
    """A document the Docs tab renders, read-only, from the repository."""

    key: str
    path: Path

    @property
    def exists(self) -> bool:
        return self.path.is_file()


# The documents a new person is sent to, in the order HANDOVER.md recommends:
# what this is for, then how to run it, then why it is the way it is.
# DECISIONS.md is here because it is where the pronunciation layer's levels are
# written down (D15) and because HANDOVER.md sends every successor to it.
DOCS: tuple[Doc, ...] = (
    Doc("HANDOVER.md", ROOT / "HANDOVER.md"),
    Doc("README.md", ROOT / "README.md"),
    Doc("COMMANDS.md", ROOT / "COMMANDS.md"),
    Doc("DECISIONS.md", ROOT / "DECISIONS.md"),
)

DOC_KEYS = tuple(d.key for d in DOCS)


@dataclass(frozen=True)
class Link:
    """A pointer into the Docs tab. `heading` must exist in that document."""

    doc: str
    heading: str
    label: str = ""

    @property
    def shown(self) -> str:
        return self.label or self.heading

    def render(self) -> str:
        return f"Learn more: {self.doc}, {self.shown}."


@dataclass(frozen=True)
class Tip:
    text: str
    link: Link | None = None

    def render(self) -> str:
        return f"{self.text} {self.link.render()}" if self.link else self.text


# ---------------------------------------------------------------------------
# Tooltips
# ---------------------------------------------------------------------------

TOOLTIPS: dict[str, Tip] = {
    "project_type": Tip(
        "VENDOR routes findings to a vendor edit sheet, CGT to a remediation "
        "plan. It also decides which document is read as the script, so a "
        "wrong answer aligns against the wrong text."
    ),
    "outline_only": Tip(
        "Topics whose storyboard notes are an outline rather than word-for-word "
        "narration. These skip word-level checking, so marking one wrongly "
        "hides real defects.",
        Link(
            "DECISIONS.md",
            "D26. Script sources: what a course's script is, and what a "
            "topic's state is",
            "D26",
        ),
    ),
    "no_script": Tip(
        "Nothing in the delivery says what these topics should have said. They "
        "are still transcribed and measured, but they cannot have a comparison."
    ),
    "own_script": Tip(
        "For the occasional vendor demo that arrives with its own script."
    ),
    "device": Tip(
        "Where the decode runs; GPU is four times faster. A device marked "
        "unavailable cannot be used here: the reason is shown beneath it, and "
        "the run proceeds on CPU rather than failing.",
        Link("COMMANDS.md", "Choosing a device"),
    ),
    "model": Tip("medium is faster and rougher."),
    "force": Tip(
        "Off, only changed files are decoded again. On, every topic is decoded "
        "from scratch."
    ),
    "reviewed_by": Tip(
        "Recorded in the course's course.yaml, carried into every run and "
        "printed in the packet header, so a finding can be traced to whoever "
        "ran it."
    ),
    "run_picker": Tip(
        "Course, start time, device, duration, differences found, reviewer."
    ),
    "listen_list": Tip(
        "Places where paper has run out: low-confidence sites, identifiers, "
        "watched terms and unscripted topics. Nothing downstream settles these; "
        "a person with headphones does."
    ),
    "watchlist_column": Tip(
        "MISHEARD means the ASR wrote something other than the expected "
        "spelling here. It is a reason to listen, not a defect, and a MATCH is "
        "orthography, not proof of correct pronunciation.",
        Link("README.md", "Pronunciation watchlist"),
    ),
    "stats_panel": Tip(
        "What this run measured about itself and this machine: engine, device, "
        "decode speed, quality signals and the course's audio conventions. "
        "Telemetry lives here and nowhere else."
    ),
}


def tooltip(key: str) -> str:
    """The rendered hover text for a field. Raises on an unknown key."""
    return TOOLTIPS[key].render()


# ---------------------------------------------------------------------------
# The first-run tour
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Step:
    key: str
    title: str
    where: str
    body: str
    link: Link | None = None

    def render(self) -> str:
        return f"{self.body} {self.link.render()}" if self.link else self.body


TOUR: tuple[Step, ...] = (
    Step(
        "loop",
        "The loop",
        "Intake, Runs, Results",
        "Three tabs, in the order the work happens: bring a course in, run it, "
        "read what it found. The run is the only slow part; everything else "
        "takes seconds.",
    ),
    Step(
        "intake",
        "Intake",
        "Intake",
        "Intake reads the delivered filenames and derives the course, its "
        "topics and its code. It asks only what a filename cannot answer: "
        "VENDOR or CGT, and which topics are not word-for-word.",
    ),
    Step(
        "run",
        "The run",
        "Runs",
        "A run transcribes each topic, aligns it against the script and "
        "measures the audio. Expect roughly half the audio's length on CPU, a "
        "quarter of that on GPU, and seconds on a rerun.",
    ),
    Step(
        "results",
        "Results and the packet",
        "Results",
        "Results shows the checks per topic and the packet this run wrote, in "
        "your packets folder. Judgment is a human step: paste the "
        "reconciliation prompt into a Claude chat, attach the packet, and it "
        "returns the findings report.",
    ),
    Step(
        "listen",
        "The listen list",
        "Results",
        "The listen list comes first on Results because it is the only part "
        "that needs a person. Sites two independent detectors both flagged are "
        "marked; start there.",
    ),
    Step(
        "measured",
        "What it does not say",
        "Results",
        "A discrepancy is a measurement, not a defect; the judgment step "
        "decides that. A watchlist MATCH means the term was heard as expected, "
        "not pronounced correctly: pronunciation is not measured at all. The "
        "listen list is the human's job and nothing downstream settles it.",
        Link("HANDOVER.md", "What it measures, and what it does not"),
    ),
)


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------

def _words(text: str) -> int:
    return len(text.split())


def word_count() -> int:
    """Every word a reader reads: tooltips, tour titles and tour bodies.

    Link text counts, because a reader reads it. `Step.where` does not: it is
    the label already printed on the tab it points at.
    """
    total = sum(_words(tip.render()) for tip in TOOLTIPS.values())
    total += sum(_words(step.title) + _words(step.render()) for step in TOUR)
    return total


def links() -> tuple[Link, ...]:
    """Every learn-more link, for the test that resolves them."""
    found = [tip.link for tip in TOOLTIPS.values() if tip.link]
    found += [step.link for step in TOUR if step.link]
    return tuple(found)
