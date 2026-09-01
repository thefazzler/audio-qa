"""Where a course's script comes from, and what state each topic's script is in.

Vocabulary only. Nothing here opens a file or imports a parser, so config,
intake, the web layer and the extractors can all agree on the words without
any of them depending on the others.

Two separate facts, deliberately not one:

**The source** is a property of the course. A VENDOR course carries its
narration in the speaker notes of a PowerPoint storyboard. A CGT course has no
PowerPoint at all; its narration is a Word document in the BUS Writing
Template. That is the whole of the difference, and it is decided once.

**The state** is a property of a topic. Most topics are verbatim: the document
says exactly what the voice should say. Some are not, and the reasons differ
enough that one flag cannot carry them:

    verbatim   the document is the narration, word for word
    outline    the document describes the topic; the voice improvised around it
    freeform   the narration is in a separate document of its own
    none       there is no script for this topic at all

The first build inferred all of this from file types: a pptx meant VENDOR, an
mp4 among mp3s meant a demo, and a demo meant outline-only. Real deliveries
disproved every step of that chain. Topics normally arrive as mp4 and need
demux on both project types, so the container says nothing about the project;
and a demo may be fully scripted (CGT always is), unscripted (usually VENDOR),
or scripted in a document of its own (occasionally VENDOR). File type carries
no information about any of it, so nothing here is derived from a file type.
See DECISIONS.md D26.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------
# Sources: where the course's script document lives, and what parses it
# --------------------------------------------------------------------------

PPTX = "pptx"
DOCX_BUS = "docx_bus"
FREEFORM = "freeform"
NONE = "none"

SCRIPT_SOURCES: frozenset[str] = frozenset({PPTX, DOCX_BUS, FREEFORM, NONE})

# Sources that describe a whole course, as opposed to one topic. `freeform` and
# `none` are per-topic states that a course-level key may not claim, because a
# course whose every topic is unscripted is not a course this pipeline can say
# anything about, and it should be caught at intake rather than after a decode.
COURSE_SOURCES: frozenset[str] = frozenset({PPTX, DOCX_BUS})

# What project type implies, when course.yaml does not say. This is a default,
# not a rule: the config accepts an explicit script_source that disagrees.
SOURCE_FOR_PROJECT: dict[str, str] = {"VENDOR": PPTX, "CGT": DOCX_BUS}

# The extension each course-level source is carried in.
SOURCE_SUFFIX: dict[str, str] = {PPTX: ".pptx", DOCX_BUS: ".docx"}

SOURCE_LABEL: dict[str, str] = {
    PPTX: "PowerPoint storyboard notes",
    DOCX_BUS: "Word document, BUS Writing Template",
    FREEFORM: "freeform document",
    NONE: "no document",
}


# --------------------------------------------------------------------------
# Per-topic states
# --------------------------------------------------------------------------

VERBATIM = "verbatim"
OUTLINE = "outline"

TOPIC_STATES: frozenset[str] = frozenset({VERBATIM, OUTLINE, FREEFORM, NONE})

# States whose topics are aligned word for word against a script.
ALIGNED_STATES: frozenset[str] = frozenset({VERBATIM, FREEFORM})

# States with no verbatim script, where the packet carries the transcript
# itself and the two script-free checks apply. See qa/transcript_checks.py.
UNALIGNED_STATES: frozenset[str] = frozenset({OUTLINE, NONE})

STATE_LABEL: dict[str, str] = {
    VERBATIM: "verbatim",
    OUTLINE: "outline only",
    FREEFORM: "freeform document",
    NONE: "no script",
}

# What the packet's topic map says in its script column.
STATE_NOTE: dict[str, str] = {
    VERBATIM: "verbatim script",
    OUTLINE: "outline only, not aligned",
    FREEFORM: "freeform document, aligned",
    NONE: "no script, transcript only",
}


@dataclass(frozen=True)
class TopicScript:
    """One topic's script state, and the document it came from when separate."""

    state: str = VERBATIM
    file: str = ""

    @property
    def aligned(self) -> bool:
        return self.state in ALIGNED_STATES

    @property
    def label(self) -> str:
        return STATE_LABEL.get(self.state, self.state)


def default_source(project_type: str) -> str:
    """The source a project type implies, before course.yaml has its say."""
    return SOURCE_FOR_PROJECT.get(project_type.upper(), PPTX)


def describe_source(source: str, document: str | None) -> str:
    """One line naming the source and the document, for the packet header."""
    label = SOURCE_LABEL.get(source, source)
    return f"{document} ({label})" if document else label
