"""Settings a person can change while the app is open, in the sidebar.

Session-scoped, on purpose. Every one of these is a preference about how this
tab reads, not a fact about the machine, so it lives in the session and comes
back to its default on the next launch. Contextual help in particular defaults
to on every time: the person who turned it off yesterday knew the interface
yesterday, and the person opening the app today may not be them.

The settings that are facts about the machine, whether the tour has been
seen and how the interface should look, live in the settings file and are
handled in tour.py and look.py. The Appearance controls are drawn inside this
module's Settings section so a person finds every setting in one place.

Every function takes a plain mapping, as tour.py does, so the rules a test
cares about hold without a browser: help is on by default, turning it off
makes every hover mark disappear, turning it back on brings them back.
`st.session_state` is mapping-shaped and is passed straight in.

`help_enabled()` with no mapping is the form the help module calls. It finds
the running session on its own and answers True when there is none, which is
what a test, or a bare interpreter, sees.
"""

from __future__ import annotations

from typing import Mapping, MutableMapping

# Session keys. The checkbox widgets bind to these directly, so a rerun reads
# the same value the click wrote.
HELP = "prefs_help_on"
STATS_OPEN = "prefs_stats_open"

DEFAULTS = {HELP: True, STATS_OPEN: False}


def init(session: MutableMapping) -> None:
    """Defaults, set once per session so the widgets have a value to bind to."""
    for key, value in DEFAULTS.items():
        session.setdefault(key, value)


def _session() -> Mapping | None:
    """The running Streamlit session, or None outside one.

    Asked through the script run context rather than by touching
    `st.session_state`, which logs a warning in bare mode on every call.
    """
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except ImportError:
        return None
    if get_script_run_ctx(suppress_warning=True) is None:
        return None
    import streamlit as st

    return st.session_state


def help_enabled(session: Mapping | None = None) -> bool:
    """Whether the hover marks are shown. On unless this tab turned them off."""
    if session is None:
        session = _session()
    if session is None:
        return DEFAULTS[HELP]
    return bool(session.get(HELP, DEFAULTS[HELP]))


def set_help(session: MutableMapping, on: bool) -> None:
    session[HELP] = bool(on)


def stats_open(session: Mapping) -> bool:
    """Whether the telemetry panel on Results opens expanded."""
    return bool(session.get(STATS_OPEN, DEFAULTS[STATS_OPEN]))


# ---------------------------------------------------------------------------
# Drawing it
# ---------------------------------------------------------------------------

def sidebar(session: MutableMapping) -> None:
    """The Settings section at the foot of the sidebar."""
    import streamlit as st

    init(session)
    with st.sidebar.expander("Settings"):
        st.checkbox("Contextual help", key=HELP)
        st.caption(
            "The question marks beside fields, headings and table columns. "
            "Off hides every one of them until the app is next started."
        )
        st.checkbox("Open Stats for nerds by default", key=STATS_OPEN)
        st.caption("The telemetry panel on the Results tab, expanded on arrival.")

        from qa.web import look

        look.controls()
