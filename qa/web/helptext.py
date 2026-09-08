"""Every word of help and training in the interface, in one place.

Three surfaces, one source. A field's hover tooltip, a step of the first-run
tour and a "learn more" pointer into the Docs tab all read from this module,
so the voice cannot drift between them and the whole layer is reviewable on
one screen. Pruning it is a single edit to a single file; that is the point.

**Two budgets, because there are two kinds of reading.** `TOOLTIPS` and the
tour are what somebody reads *while working*: a form field, a results column,
a walkthrough on the first launch. They are capped at `BUDGET_FIELDS`.
`CONCEPTS` is what somebody reads *while learning*: what a stage does, what a
metric means, what a panel is for. They are capped at `BUDGET_CONCEPTS`.

A test holds each. When a draft goes over, cut until it fits rather than
raising the number: terse and read beats thorough and skipped. The budgets
went from one to two because the layer grew a second surface, not because a
draft ran long. See DECISIONS.md D30 and D31.

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

# One page each. Not targets to grow into.
BUDGET_FIELDS = 500
BUDGET_CONCEPTS = 500

# The name D30 used, kept pointing at the budget D30 was written about.
BUDGET = BUDGET_FIELDS

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
# Concepts: what a stage, a metric or a panel is, and why it matters
# ---------------------------------------------------------------------------
# Read once, while learning, rather than every time a form is filled. That is
# why they are a separate budget and why one of them, `stages`, is allowed to
# be a short glossary: the stage row is a single caption and Streamlit can
# hang exactly one mark on it, so the alternative to one list is nothing.

CONCEPTS: dict[str, Tip] = {
    "stages": Tip(
        "The eight stages, in order. "
        "**ingest** identifies each delivered file by its header and demuxes "
        "video. "
        "**config** reads course.yaml and measures every topic's duration. "
        "**script** pulls the narration out of the script document and maps "
        "topics to it. "
        "**transcribe** decodes the audio, and is the only slow one. "
        "**align** compares script against transcript word by word; the "
        "differences come from here. "
        "**artifacts** measures the audio against the course's own "
        "conventions. "
        "**checks** rolls it up per topic and flags what needs attention. "
        "**packet** writes the evidence the judgment step reads. "
        "A stage whose output already exists is skipped, so a rerun redoes "
        "only what went stale."
    ),
    "elapsed": Tip(
        "How long this run took, on the device it actually used. Measured on "
        "this project's laptop, a 75.7 minute course decoded in 7.8 minutes on "
        "GPU float16 and 32.9 on CPU int8: the same course, roughly four times "
        "apart."
    ),
    "time_remaining": Tip(
        "Computed from this machine's own decode rate over the topics already "
        "finished, not from an assumption. It appears once the first topic is "
        "done."
    ),
    "headline": Tip(
        "Four measurements, not verdicts. Coverage is the share of script "
        "words matched, differences are places script and transcript disagree, "
        "and listen items are what only a person can settle."
    ),
    "checks_table": Tip(
        "One row per topic, as measured. A topic with no differences is not a "
        "certified topic: pronunciation and delivery are not measured at all."
    ),
    "packet": Tip(
        "The evidence file this run wrote, and the input to the judgment step. "
        "Verdicts and the edit sheet come from that step, not from this page."
    ),
    "storage": Tip(
        "What the library is using and what of it can go. Findings and packets "
        "are never removed here; they are a fraction of a percent of a "
        "course's size."
    ),
    "storage_reclaimable": Tip(
        "Scratch audio plus delivered media, across every course. Removing all "
        "of it leaves every result readable and every packet where it is."
    ),
    "storage_kept": Tip(
        "The findings themselves: coverage, differences, listen items, "
        "telemetry. Kept whatever else goes, because nothing can produce them "
        "again."
    ),
    "scratch": Tip(
        "The wav the ingest stage demuxes from each delivered file. A working "
        "copy: it rebuilds in seconds and the course stays runnable without it."
    ),
    "media": Tip(
        "The narration files and the script document, as delivered. Removing "
        "them frees most of a course and costs the ability to run it until "
        "they are downloaded again."
    ),
    "findings_kept": Tip(
        "Every JSON the run wrote, including the per-topic files the listen list "
        "is rebuilt from. Deleting those empties a listen list rather than "
        "failing, which is why they never go."
    ),
    "storage_packets": Tip(
        "Finished packets, and any archives beside them. This folder is the "
        "run history: each packet is named for the run that made it and "
        "nothing overwrites one.",
        Link("DECISIONS.md", "D28. Where finished packets go, and why they are never overwritten", "D28"),
    ),
    "archive": Tip(
        "Zips the chosen packets into this same folder and, if asked, removes "
        "the originals afterwards, but only once the archive has been read "
        "back and seen to hold them."
    ),
    "delete_packets": Tip(
        "Removes packets outright, with no copy kept. Once a course's files "
        "are gone, its packet is the only record of what that run found."
    ),
}


def concept(key: str) -> str:
    """The rendered hover text for a panel, metric or stage row."""
    return CONCEPTS[key].render()


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


def field_words() -> int:
    """What a reader reads while working: field tooltips and the tour.

    Link text counts, because a reader reads it. `Step.where` does not: it is
    the label already printed on the tab it points at.

    The tour is counted here rather than with the concepts because it is the
    walkthrough of doing the work, and because this is the budget D30 sized it
    against; moving it would make that number mean something else.
    """
    total = sum(_words(tip.render()) for tip in TOOLTIPS.values())
    total += sum(_words(step.title) + _words(step.render()) for step in TOUR)
    return total


def concept_words() -> int:
    """What a reader reads while learning: stages, metrics, panels."""
    return sum(_words(tip.render()) for tip in CONCEPTS.values())


# The name D30 used. It counted one budget because there was one.
word_count = field_words


def links() -> tuple[Link, ...]:
    """Every learn-more link, for the test that resolves them."""
    found = [tip.link for tip in TOOLTIPS.values() if tip.link]
    found += [tip.link for tip in CONCEPTS.values() if tip.link]
    found += [step.link for step in TOUR if step.link]
    return tuple(found)
