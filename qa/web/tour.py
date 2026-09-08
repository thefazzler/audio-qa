"""The first-run tour: shown once, skippable from the first step, always reopenable.

Two kinds of state, deliberately kept apart.

**Whether this person has seen it** is a fact about the machine, not about the
browser tab, so it lives in the settings file next to the library and packet
locations. Session state would show the tour again on every refresh, which is
the behaviour a first-run tour must never have.

**Where they are in it** is a fact about this tab, so it lives in the session.

Every transition here takes a plain mapping rather than reaching into
`st.session_state`, so the rules a test cares about — appears on a fresh
profile, never again after finishing or skipping, reopens from the link — can
be exercised without a browser. `st.session_state` is mapping-shaped and is
passed straight in.

Skipping and finishing record the same thing. Somebody who skipped has decided
they do not want it; showing it again tomorrow because they did not press the
last button would be the tool arguing with them. The link is how it comes back.
"""

from __future__ import annotations

from typing import MutableMapping

from ..library import read_settings, write_settings
from .helptext import TOUR

# Settings file, shared with the library and output locations.
SETTING = "tour_seen"

# Session keys.
OPEN = "tour_open"
STEP = "tour_step"
OFFERED = "tour_offered"


# ---------------------------------------------------------------------------
# What the machine remembers
# ---------------------------------------------------------------------------

def seen() -> bool:
    return bool(read_settings().get(SETTING))


def mark_seen() -> None:
    """Recorded on finish and on skip alike; both mean "not again"."""
    settings = read_settings()
    settings[SETTING] = True
    write_settings(settings)


def forget() -> None:
    """Make this machine a fresh profile again. Nothing in the UI calls it."""
    settings = read_settings()
    settings.pop(SETTING, None)
    write_settings(settings)


# ---------------------------------------------------------------------------
# Where this tab is in it
# ---------------------------------------------------------------------------

def is_open(session: MutableMapping) -> bool:
    return bool(session.get(OPEN))


def step_index(session: MutableMapping) -> int:
    return max(0, min(int(session.get(STEP, 0)), len(TOUR) - 1))


def open_tour(session: MutableMapping) -> None:
    """The "Tour" link. Opens at step one whether or not it has been seen."""
    session[OPEN] = True
    session[STEP] = 0
    session[OFFERED] = True


def advance(session: MutableMapping) -> None:
    if step_index(session) >= len(TOUR) - 1:
        finish(session)
        return
    session[STEP] = step_index(session) + 1


def retreat(session: MutableMapping) -> None:
    session[STEP] = max(0, step_index(session) - 1)


def finish(session: MutableMapping) -> None:
    """Reached the end, or pressed Skip. Same record either way."""
    session[OPEN] = False
    session[STEP] = 0
    mark_seen()


def autostart(session: MutableMapping) -> bool:
    """Open the tour if this is the first launch on this machine.

    Asked once per session and answered once: the flag it sets is what stops a
    person who skipped on the first render from being offered it again on the
    rerun that the skip itself caused.
    """
    if session.get(OFFERED):
        return False
    session[OFFERED] = True
    if seen():
        return False
    session[OPEN] = True
    session[STEP] = 0
    return True


# ---------------------------------------------------------------------------
# Drawing it
# ---------------------------------------------------------------------------
# A modal rather than a coach mark on the page itself. Streamlit renders a
# page as a tree it owns, so there is nothing to attach a spotlight to; the
# step names its area in words instead, using the label already on the tab.

def panel(session) -> None:
    """Draw the tour if this tab has it open. Cheap no-op when it does not."""
    import streamlit as st

    if not is_open(session):
        return

    # Dismissing with the X, Esc or a click outside records what Skip records.
    # Without the callback the session still holds the tour open, so the next
    # widget click anywhere in the app pops it straight back up: a dialog that
    # will not take no for an answer.
    @st.dialog("Audio QA tour", on_dismiss=lambda: finish(session))
    def _show() -> None:
        index = step_index(session)
        step = TOUR[index]
        st.caption(f"Step {index + 1} of {len(TOUR)} · {step.where}")
        st.subheader(step.title)
        st.write(step.render())

        last = index == len(TOUR) - 1
        columns = st.columns(3)
        # Skip is on every step, and on the first one especially: a tour a
        # person cannot leave is an obstacle rather than an offer.
        if columns[0].button("Skip", key="tour-skip"):
            finish(session)
            st.rerun()
        if index and columns[1].button("Back", key="tour-back"):
            retreat(session)
            st.rerun()
        if columns[2].button(
            "Finish" if last else "Next", key="tour-next", type="primary"
        ):
            advance(session)
            st.rerun()

    _show()


def link(session) -> None:
    """The small "Tour" link that brings it back, forever after."""
    import streamlit as st

    if st.sidebar.button("Tour", key="tour-link", type="tertiary"):
        open_tour(session)
        st.rerun()
