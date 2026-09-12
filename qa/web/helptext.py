"""Every word of help and training in the interface, in one place.

Three surfaces, one source. A field's hover tooltip, a step of the first-run
tour and a "learn more" pointer into the Docs tab all read from this module,
so the voice cannot drift between them and the whole layer is reviewable on
one screen. Pruning it is a single edit to a single file; that is the point.

**Three budgets, because there are three kinds of reading.** `TOOLTIPS` and
the tour are what somebody reads *while working*: a form field, a walkthrough
on the first launch. They are capped at `BUDGET_FIELDS`. `CONCEPTS` is what
somebody reads *while learning*: what a stage does, what a metric means, what
a panel is for. They are capped at `BUDGET_CONCEPTS`. `COLUMNS` is what
somebody reads *while reading a table*: what one column of the topics, listen
list or checks table means. They are capped at `BUDGET_COLUMNS`.

A test holds each. When a draft goes over, cut until it fits rather than
raising the number: terse and read beats thorough and skipped. The budgets
went from one to two, and then to three, because the layer grew a surface
each time, not because a draft ran long. See DECISIONS.md D30, D31 and D36.

Every accessor answers None when contextual help is switched off in the
sidebar (qa/web/prefs.py), which is how one checkbox removes every question
mark at once. The words are still here and the key is still checked, so a
misspelt key fails the same way with help off as with it on.

What a tooltip says: what to enter and what getting it wrong costs, not a
definition. A field whose label already says everything gets none, and no
tooltip goes inside a results table cell — if a result needs explaining it is
explained once, in the column header. What a column says: how to read the
value, and what the value does not mean.

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
BUDGET_COLUMNS = 500

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
# GLOSSARY.md is last because it is not read in order: it is where a hover
# mark sends somebody who wants the longer answer to "what does this word mean".
DOCS: tuple[Doc, ...] = (
    Doc("HANDOVER.md", ROOT / "HANDOVER.md"),
    Doc("README.md", ROOT / "README.md"),
    Doc("COMMANDS.md", ROOT / "COMMANDS.md"),
    Doc("DECISIONS.md", ROOT / "DECISIONS.md"),
    Doc("GLOSSARY.md", ROOT / "GLOSSARY.md"),
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


def _shown(tip: Tip) -> str | None:
    """The text, or None when this tab has turned contextual help off.

    Streamlit draws no mark for help=None, so one checkbox in the sidebar
    removes every question mark in the app. Looked up after the key, so an
    unknown key is still a KeyError whether help is on or off.
    """
    from qa.web import prefs

    return tip.render() if prefs.help_enabled() else None


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
    "stats_panel": Tip(
        "What this run measured about itself and this machine: engine, device, "
        "decode speed, quality signals and the course's audio conventions. "
        "Telemetry lives here and nowhere else."
    ),
}


def tooltip(key: str) -> str | None:
    """The rendered hover text for a field. Raises on an unknown key."""
    return _shown(TOOLTIPS[key])


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


def concept(key: str) -> str | None:
    """The rendered hover text for a panel, metric or stage row."""
    return _shown(CONCEPTS[key])


# ---------------------------------------------------------------------------
# Columns: how to read one column of a table, and what it does not mean
# ---------------------------------------------------------------------------
# Three tables carry these: the topics table on Runs, and the listen list and
# checks table on Results. A key is table name, then column name. Every column
# gets one, including the ones whose label seems to say everything, because
# the reader who needs to be told what "topic" means is the reader this layer
# exists for. The mark hangs on the header, never in a cell, as D30 says.

COLUMNS: dict[str, Tip] = {
    # Runs: topics decoded
    "topics_topic": Tip(
        "The topic number from the delivered filename. Rows fill in as each "
        "topic finishes."
    ),
    "topics_state": Tip(
        "pending is waiting, transcribed was decoded this run, cached was "
        "reused from an earlier run, aligned is compared against the script."
    ),
    "topics_audio": Tip(
        "Length of this topic's narration. Decode time scales with it."
    ),
    "topics_coverage": Tip(
        "Share of the script's words the transcript matched. Below 97% the "
        "checks stage flags it."
    ),
    "topics_differences": Tip(
        "Places script and transcript disagree, word by word: a measurement, "
        "not a verdict. Outline only means no word-level check was possible."
    ),
    "topics_listen": Tip(
        "Places in this topic that need a person with headphones, listed on "
        "the Results tab."
    ),
    # Results: listen list
    "listen_topic": Tip("Which topic file to open. Sorted by topic, then time."),
    "listen_at": Tip(
        "Minutes and seconds into the file, from the transcriber's word "
        "timings, so the audio can be scrubbed straight there."
    ),
    "listen_found_by": Tip(
        "Which detector raised it: alignment, the pronunciation watchlist, a "
        "voiced symbol, an unverifiable duplication, or a topic with no "
        "verbatim script. ++ means two independent detectors agreed here; "
        "listen there first."
    ),
    "listen_what": Tip(
        "What the script says beside what the voice said. (nothing) on one "
        "side means a word was added or dropped."
    ),
    "listen_confidence": Tip(
        "The transcriber's certainty about what it heard here, 0 to 1, from "
        "its least certain word at the site. Below 0.6 it may have misheard, "
        "so the difference may be its mistake rather than the narrator's; "
        "near 1 the words really do differ. It measures the decode, never "
        "the pronunciation.",
        Link("GLOSSARY.md", "Confidence"),
    ),
    "listen_why": Tip(
        "The detector's reason. MISHEARD means the ASR wrote something other "
        "than the expected spelling: a reason to listen, not a defect. A "
        "MATCH is orthography, not proof of correct pronunciation.",
        Link("README.md", "Pronunciation watchlist"),
    ),
    # Results: checks
    "checks_topic": Tip("One row per topic, in delivery order."),
    "checks_from": Tip(
        "Where in the script document this topic came from: slides for a "
        "storyboard, a block heading for a Word script, a filename for its "
        "own document."
    ),
    "checks_script": Tip(
        "What Intake recorded: verbatim is word-for-word narration, outline "
        "is notes only, none is no script, freeform is a document of its own. "
        "Only verbatim topics are checked word by word."
    ),
    "checks_state": Tip(
        "Measured, not a verdict. ok is no differences, review is differences "
        "found, listen is listen items only, flag is a check flag, outline "
        "and no script could not be aligned."
    ),
    "checks_coverage": Tip(
        "Share of script words the transcript matched. Below 97% is LOW "
        "COVERAGE; below 85% a slide mapping error is likelier. n/a without "
        "a verbatim script."
    ),
    "checks_differences": Tip(
        "Word-level disagreements, counted: measurements, not defects. not "
        "aligned means there was no verbatim script to compare against."
    ),
    "checks_listen": Tip("Places in this topic on the listen list above."),
    "checks_flags": Tip(
        "Problems the checks stage raised: pace far from the script's, low "
        "coverage, a probable mapping error, an unmatched last sentence, long "
        "trailing silence, a decoder that stopped early, an audio artifact. "
        "Read the flag first; a mapping error makes the differences noise."
    ),
    "checks_audio": Tip(
        "What the artifacts stage heard: clipping, silence inside the "
        "narration, a silent file, an abrupt end. Pauses matching this "
        "course's own conventions are not listed."
    ),
    "checks_suppressed": Tip(
        "Segment boundary duplications the transcriber produced and the "
        "pipeline removed as engine artifacts. Not narration, not counted as "
        "differences."
    ),
}


def column(key: str) -> str | None:
    """The rendered hover text for a table column header."""
    return _shown(COLUMNS[key])


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


def column_words() -> int:
    """What a reader reads while reading a table: one column at a time."""
    return sum(_words(tip.render()) for tip in COLUMNS.values())


# The name D30 used. It counted one budget because there was one.
word_count = field_words


def links() -> tuple[Link, ...]:
    """Every learn-more link, for the test that resolves them."""
    found = [tip.link for tip in TOOLTIPS.values() if tip.link]
    found += [tip.link for tip in CONCEPTS.values() if tip.link]
    found += [tip.link for tip in COLUMNS.values() if tip.link]
    found += [step.link for step in TOUR if step.link]
    return tuple(found)
