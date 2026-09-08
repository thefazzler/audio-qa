"""The help and training layer: one source of words, one budget, one tour.

Three surfaces share one module, so the things worth holding are properties of
that module rather than of any page: it fits on a page, it covers the fields
that were chosen to carry a tooltip, its pointers land on real sections, the
tour appears once and comes back on request, and the Docs tab reads documents
without ever writing one.

Rendering is not tested, for the reason test_web_shell.py gives: a Streamlit
page needs a browser to mean anything, and a test that imports one only proves
it imports.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from qa.web import docs_view, helptext, tour
from qa.web.helptext import BUDGET, DOCS, TOOLTIPS, TOUR, tooltip, word_count

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------

def test_the_whole_layer_fits_on_one_page():
    """The rule is cut until it fits, never raise the number. See D30."""
    total = word_count()
    assert total <= BUDGET, (
        f"the help layer is {total} words, over the {BUDGET} word budget by "
        f"{total - BUDGET}. Cut something in qa/web/helptext.py; do not raise "
        "BUDGET."
    )


def test_the_budget_is_one_page():
    assert BUDGET == 500


def test_the_budget_is_actually_measuring_something():
    """A counter that returns zero would pass the budget test forever."""
    assert word_count() > 300


# ---------------------------------------------------------------------------
# Tooltips
# ---------------------------------------------------------------------------

# The fields chosen to carry one, each because getting it wrong costs
# something a label cannot convey.
REQUIRED = (
    "project_type",
    "outline_only",
    "device",
    "reviewed_by",
    "watchlist_column",
    "listen_list",
    "stats_panel",
)


@pytest.mark.parametrize("key", REQUIRED)
def test_every_field_that_was_promised_a_tooltip_has_one(key):
    assert tooltip(key).strip()


def test_an_unknown_tooltip_key_is_a_hard_error():
    """A silently empty tooltip is a field that quietly stopped explaining."""
    with pytest.raises(KeyError):
        tooltip("no-such-field")


@pytest.mark.parametrize("key", sorted(TOOLTIPS))
def test_a_tooltip_is_at_most_two_sentences(key):
    """One sentence, two at the absolute most. Longer is not read on hover."""
    text = TOOLTIPS[key].text
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    assert len(sentences) <= 2, f"{key} is {len(sentences)} sentences: {text}"


def test_the_device_tooltip_explains_the_greyed_out_state():
    """The hover has to answer why it is grey and what happens instead."""
    text = tooltip("device")
    assert "unavailable" in text
    assert "reason" in text
    assert "CPU" in text


def test_the_watchlist_tooltip_says_what_a_match_does_not_mean():
    text = tooltip("watchlist_column")
    assert "MISHEARD" in text
    assert "MATCH" in text
    assert "orthography" in text


def test_the_reviewer_tooltip_says_where_the_name_ends_up():
    text = tooltip("reviewed_by")
    assert "course.yaml" in text
    assert "packet" in text


# Learn-more links resolve in tests/test_docs.py, with the other cross
# reference tests: a dangling pointer is the same fault whether it is in a
# document or in a tooltip.


# ---------------------------------------------------------------------------
# The tour
# ---------------------------------------------------------------------------

def test_the_tour_is_six_or_seven_steps():
    assert 6 <= len(TOUR) <= 7


@pytest.mark.parametrize("step", TOUR, ids=lambda s: s.key)
def test_a_tour_step_is_two_or_three_sentences_about_one_area(step):
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", step.body.strip()) if s]
    assert 2 <= len(sentences) <= 3, f"{step.key} is {len(sentences)} sentences"
    assert step.title.strip()
    assert step.where.strip()


def test_the_tour_covers_the_loop():
    keys = [step.key for step in TOUR]
    for expected in ("intake", "run", "results", "listen"):
        assert expected in keys


def test_the_last_step_is_the_one_idea_the_tool_most_needs_held():
    last = TOUR[-1]
    body = last.render()
    assert "measurement, not a defect" in body
    assert "MATCH" in body and "pronounced correctly" in body
    assert "listen list" in body


# ---------------------------------------------------------------------------
# Tour state: once on a fresh profile, then only on request
# ---------------------------------------------------------------------------

@pytest.fixture
def profile(tmp_path, monkeypatch):
    """A machine that has never run this app, with its own settings file."""
    monkeypatch.setattr(
        "qa.library.config_path", lambda: tmp_path / "config.json"
    )
    return tmp_path


def test_the_tour_shows_itself_on_a_fresh_profile(profile):
    session: dict = {}
    assert tour.autostart(session) is True
    assert tour.is_open(session)
    assert tour.step_index(session) == 0


def test_the_tour_is_offered_once_per_session_not_once_per_render(profile):
    """Every rerun calls autostart; only the first one may act on it."""
    session: dict = {}
    assert tour.autostart(session) is True
    tour.finish(session)
    assert tour.autostart(session) is False
    assert not tour.is_open(session)


def test_finishing_the_tour_stops_it_coming_back(profile):
    session: dict = {}
    tour.autostart(session)
    for _ in range(len(TOUR)):
        tour.advance(session)
    assert not tour.is_open(session)
    assert tour.seen()
    assert tour.autostart({}) is False


def test_skipping_the_tour_stops_it_coming_back_too(profile):
    """Skip and finish record the same thing: the person has decided."""
    session: dict = {}
    tour.autostart(session)
    tour.finish(session)
    assert tour.seen()
    assert tour.autostart({}) is False


def test_the_link_relaunches_it_after_it_has_been_seen(profile):
    tour.mark_seen()
    session: dict = {}
    assert tour.autostart(session) is False
    tour.open_tour(session)
    assert tour.is_open(session)
    assert tour.step_index(session) == 0


def test_stepping_backwards_and_forwards_stays_inside_the_tour(profile):
    session: dict = {}
    tour.open_tour(session)
    tour.retreat(session)
    assert tour.step_index(session) == 0
    for _ in range(len(TOUR) - 1):
        tour.advance(session)
    assert tour.step_index(session) == len(TOUR) - 1
    assert tour.is_open(session)
    tour.advance(session)
    assert not tour.is_open(session), "the last Next finishes rather than overruns"


def test_a_corrupt_step_number_does_not_break_the_tour(profile):
    session = {tour.OPEN: True, tour.STEP: 99}
    assert tour.step_index(session) == len(TOUR) - 1


def test_forgetting_makes_the_machine_fresh_again(profile):
    tour.mark_seen()
    tour.forget()
    assert not tour.seen()
    assert tour.autostart({}) is True


def test_the_tour_flag_does_not_disturb_the_other_settings(profile):
    from qa.library import read_settings, set_output

    set_output(profile / "packets")
    tour.mark_seen()
    settings = read_settings()
    assert settings[tour.SETTING] is True
    assert "output" in settings


# ---------------------------------------------------------------------------
# The Docs tab
# ---------------------------------------------------------------------------

def test_the_docs_tab_lists_the_documents_a_new_person_is_sent_to():
    keys = [doc.key for doc in DOCS]
    for expected in ("HANDOVER.md", "COMMANDS.md", "README.md"):
        assert expected in keys
    # Where the pronunciation layer's levels are written down: D15.
    assert "DECISIONS.md" in keys


@pytest.mark.parametrize("doc", DOCS, ids=lambda d: d.key)
def test_every_listed_document_is_really_there_and_renders(doc):
    assert doc.exists, f"{doc.key} is listed in the Docs tab but not in the repo"
    text = docs_view.load(doc.key)
    assert text and text.strip()
    assert docs_view.headings(text), f"{doc.key} rendered with no headings"


def test_a_document_this_installation_does_not_have_is_not_an_error():
    """A wheel carries qa/ and not the markdown beside it."""
    assert docs_view.load("NOT_A_DOCUMENT.md") is None
    assert docs_view.find("NOT_A_DOCUMENT.md") is None


def test_reading_a_document_does_not_touch_it():
    path = ROOT / "COMMANDS.md"
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    docs_view.load("COMMANDS.md")
    docs_view.load("COMMANDS.md")
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


# The portal displays documents and never stores or edits them; git remains the
# only way content changes. A write path added later would be a change with no
# commit and no review, in the files a successor is told to trust.
WRITE_PATHS = (
    "write_text",
    "write_bytes",
    "open(",
    "unlink",
    "mkdir",
    "rename",
    "shutil",
    "st.text_area",
    "st.data_editor",
    "st.file_uploader",
    "st.form",
)


@pytest.mark.parametrize("forbidden", WRITE_PATHS)
def test_the_docs_tab_has_no_write_path(forbidden):
    source = Path(docs_view.__file__).read_text(encoding="utf-8")
    assert forbidden not in source, (
        f"qa/web/docs_view.py contains {forbidden!r}. The Docs tab is read-only: "
        "git is the only way a document changes."
    )


def test_the_docs_tab_reads_through_one_function():
    """One reader, so read-only is a property of the module rather than a habit."""
    source = Path(docs_view.__file__).read_text(encoding="utf-8")
    assert source.count("read_text") == 1


def test_the_help_module_holds_the_words_and_the_pages_do_not():
    """The whole point of the layer: one place to prune."""
    for name in ("app.py", "run_view.py", "results_view.py"):
        source = (ROOT / "qa" / "web" / name).read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped.startswith("help="):
                continue
            assert "tooltip(" in stripped, (
                f"qa/web/{name} writes a tooltip inline: {stripped}"
            )


def test_the_helptext_module_is_the_only_place_the_words_live():
    source = Path(helptext.__file__).read_text(encoding="utf-8")
    assert "TOOLTIPS" in source and "TOUR" in source
