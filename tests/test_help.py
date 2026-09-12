"""The help and training layer: one source of words, three budgets, one tour.

Four surfaces share one module, so the things worth holding are properties of
that module rather than of any page: each budget fits on a page, it covers the
fields that were chosen to carry a tooltip and every column of every table,
its pointers land on real sections, the tour appears once and comes back on
request, one checkbox turns every mark off and on again, and the Docs tab
reads documents without ever writing one.

Rendering is not tested, for the reason test_web_shell.py gives: a Streamlit
page needs a browser to mean anything, and a test that imports one only proves
it imports.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from qa.web import docs_view, helptext, prefs, tour
from qa.web.helptext import (
    BUDGET_COLUMNS,
    BUDGET_CONCEPTS,
    BUDGET_FIELDS,
    COLUMNS,
    CONCEPTS,
    DOCS,
    TOOLTIPS,
    TOUR,
    column,
    column_words,
    concept,
    concept_words,
    field_words,
    tooltip,
)

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------

def test_what_you_read_while_working_fits_on_one_page():
    """The rule is cut until it fits, never raise the number. See D30."""
    total = field_words()
    assert total <= BUDGET_FIELDS, (
        f"field tooltips and the tour come to {total} words, over the "
        f"{BUDGET_FIELDS} word budget by {total - BUDGET_FIELDS}. Cut "
        "something in qa/web/helptext.py; do not raise the budget."
    )


def test_what_you_read_while_learning_fits_on_one_page():
    """The second budget, added when the layer grew a second surface. See D31."""
    total = concept_words()
    assert total <= BUDGET_CONCEPTS, (
        f"the concept texts come to {total} words, over the "
        f"{BUDGET_CONCEPTS} word budget by {total - BUDGET_CONCEPTS}. Cut "
        "something in qa/web/helptext.py; do not raise the budget."
    )


def test_what_you_read_at_a_table_fits_on_one_page():
    """The third budget, added when every column got a mark. See D36."""
    total = column_words()
    assert total <= BUDGET_COLUMNS, (
        f"the column texts come to {total} words, over the "
        f"{BUDGET_COLUMNS} word budget by {total - BUDGET_COLUMNS}. Cut "
        "something in qa/web/helptext.py; do not raise the budget."
    )


def test_every_budget_is_one_page():
    assert BUDGET_FIELDS == 500
    assert BUDGET_CONCEPTS == 500
    assert BUDGET_COLUMNS == 500


def test_the_budgets_are_actually_measuring_something():
    """A counter that returns zero would pass a budget test forever."""
    assert field_words() > 300
    assert concept_words() > 300
    assert column_words() > 300


def test_the_three_budgets_count_different_words():
    """Nothing may be counted twice, or in neither, to duck a cap."""
    assert set(TOOLTIPS) & set(CONCEPTS) == set()
    assert set(TOOLTIPS) & set(COLUMNS) == set()
    assert set(CONCEPTS) & set(COLUMNS) == set()


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


def test_the_reviewer_tooltip_says_where_the_name_ends_up():
    text = tooltip("reviewed_by")
    assert "course.yaml" in text
    assert "packet" in text


# ---------------------------------------------------------------------------
# Concepts
# ---------------------------------------------------------------------------

# The elements a person watching a run or reading results asked to have
# explained: what the pipeline is doing, and what a number means.
REQUIRED_CONCEPTS = (
    "stages",
    "elapsed",
    "time_remaining",
    "headline",
    "checks_table",
    "packet",
    "storage",
    "scratch",
    "media",
    "findings_kept",
    "archive",
    "delete_packets",
)


@pytest.mark.parametrize("key", REQUIRED_CONCEPTS)
def test_every_element_that_was_promised_an_explanation_has_one(key):
    assert concept(key).strip()


def test_an_unknown_concept_key_is_a_hard_error():
    with pytest.raises(KeyError):
        concept("no-such-panel")


@pytest.mark.parametrize("key", sorted(CONCEPTS))
def test_no_single_explanation_becomes_a_wall(key):
    """A hover nobody finishes reading is a hover nobody read."""
    words = len(CONCEPTS[key].render().split())
    assert words <= 120, f"{key} is {words} words"


def test_the_stage_glossary_names_every_stage_the_pipeline_runs():
    """The row explains the run, so a stage the run has cannot be missing."""
    from qa.cli import STAGE_NAMES

    text = concept("stages")
    missing = [name for name in STAGE_NAMES if name not in text]
    assert not missing, "the stage row explains: " + ", ".join(missing)


def test_the_elapsed_explanation_puts_the_number_in_context():
    """"Took 8m" means nothing without knowing what it would be elsewhere."""
    text = concept("elapsed")
    assert "GPU" in text and "CPU" in text


def test_the_storage_explanations_say_what_survives():
    assert "rebuilds" in concept("scratch")
    assert "downloaded again" in concept("media")
    assert "listen list" in concept("findings_kept")


# ---------------------------------------------------------------------------
# Columns: every header of every table
# ---------------------------------------------------------------------------

# The tables, and their columns, as the pages draw them. Every column gets a
# mark, including the ones whose label seems to say everything: the reader
# who needs "topic" explained is the reader the layer is for.
TABLES = {
    "topics": ("topic", "state", "audio", "coverage", "differences", "listen"),
    "listen": ("topic", "at", "found_by", "what", "confidence", "why"),
    "checks": (
        "topic",
        "from",
        "script",
        "state",
        "coverage",
        "differences",
        "listen",
        "flags",
        "audio",
        "suppressed",
    ),
}

EVERY_COLUMN = tuple(
    f"{table}_{name}" for table, names in TABLES.items() for name in names
)


@pytest.mark.parametrize("key", EVERY_COLUMN)
def test_every_column_of_every_table_is_explained(key):
    assert column(key).strip()


def test_no_column_text_is_written_for_a_column_no_table_has():
    assert set(COLUMNS) == set(EVERY_COLUMN)


def test_an_unknown_column_key_is_a_hard_error():
    with pytest.raises(KeyError):
        column("no_such_column")


@pytest.mark.parametrize("key", sorted(COLUMNS))
def test_a_column_text_is_at_most_three_sentences(key):
    """Two, or three where the column is a set of values to spell out."""
    text = COLUMNS[key].text
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    assert len(sentences) <= 3, f"{key} is {len(sentences)} sentences: {text}"


def test_the_confidence_column_says_what_the_number_is_and_is_not():
    """The column a new reviewer asked about, and the one nothing explained.

    It has to say whose certainty it is, where the floor is, what a low value
    means for the difference beside it, and that it is not pronunciation.
    """
    text = column("listen_confidence")
    assert "transcriber" in text
    assert "0.6" in text
    assert "misheard" in text
    assert "pronunciation" in text
    assert "GLOSSARY.md" in text


def test_the_confidence_floor_in_the_help_is_the_one_the_pipeline_uses():
    from qa.align import LOW_CONFIDENCE

    assert str(LOW_CONFIDENCE) in column("listen_confidence")


def test_the_why_column_says_what_a_match_does_not_mean():
    text = column("listen_why")
    assert "MISHEARD" in text
    assert "MATCH" in text
    assert "orthography" in text


# The columns a new reader hovers first and understands least. Each mark
# points at the glossary, so the glossary is found from the table rather
# than by wandering into the Docs tab. Few on purpose, per D30: the entry
# behind each of these says something the column text does not.
GLOSSARY_POINTERS = ("listen_confidence", "listen_why", "checks_coverage", "checks_flags")


@pytest.mark.parametrize("key", GLOSSARY_POINTERS)
def test_the_glossary_is_reachable_from_the_columns_people_ask_about(key):
    link = COLUMNS[key].link
    assert link is not None and link.doc == "GLOSSARY.md", key


def test_glossary_pointers_from_columns_stay_few():
    """A pointer that leads to a restatement teaches people to stop clicking."""
    pointed = [k for k, tip in COLUMNS.items() if tip.link and tip.link.doc == "GLOSSARY.md"]
    assert set(pointed) == set(GLOSSARY_POINTERS)


def test_the_coverage_columns_quote_the_floors_the_checks_stage_uses():
    from qa.checks import COVERAGE_FLOOR, MAPPING_ERROR_FLOOR

    text = column("checks_coverage")
    assert f"{COVERAGE_FLOOR * 100:.0f}%" in text
    assert f"{MAPPING_ERROR_FLOOR * 100:.0f}%" in text
    assert f"{COVERAGE_FLOOR * 100:.0f}%" in column("topics_coverage")


def test_the_state_column_names_every_state_a_topic_can_have_during_a_run():
    text = column("topics_state")
    for state in ("pending", "transcribed", "cached", "aligned"):
        assert state in text


def test_the_checks_state_column_names_every_word_the_table_can_show():
    from qa.web.results_view import STATE_ICON

    text = column("checks_state")
    for shown in STATE_ICON.values():
        assert shown in text, f"the state column can say {shown!r} and does not explain it"


# Learn-more links resolve in tests/test_docs.py, with the other cross
# reference tests: a dangling pointer is the same fault whether it is in a
# document or in a tooltip.


# ---------------------------------------------------------------------------
# The switch: one checkbox, every mark
# ---------------------------------------------------------------------------
# Session-scoped and on by default, so every launch starts with the marks
# showing. The accessor finds the session itself; outside Streamlit there is
# none, and the answer is the default.

@pytest.fixture
def session(monkeypatch):
    """A tab of the app, as the help accessors see it."""
    state: dict = {}
    prefs.init(state)
    monkeypatch.setattr(prefs, "_session", lambda: state)
    return state


def test_contextual_help_is_on_by_default():
    assert prefs.help_enabled({}) is True
    assert prefs.help_enabled() is True, "outside the app, the default"
    fresh: dict = {}
    prefs.init(fresh)
    assert prefs.help_enabled(fresh) is True


def test_turning_help_off_removes_every_mark(session):
    prefs.set_help(session, False)
    assert tooltip("device") is None
    assert concept("stages") is None
    assert column("listen_confidence") is None


def test_turning_help_back_on_brings_every_mark_back(session):
    prefs.set_help(session, False)
    prefs.set_help(session, True)
    assert tooltip("device")
    assert concept("stages")
    assert column("listen_confidence")


def test_a_wrong_key_fails_the_same_way_with_help_off(session):
    """Off must not hide a misspelt key until the day somebody turns it on."""
    prefs.set_help(session, False)
    with pytest.raises(KeyError):
        tooltip("no-such-field")
    with pytest.raises(KeyError):
        column("no_such_column")


def test_the_switch_is_a_session_setting_not_a_machine_one(session, tmp_path, monkeypatch):
    """Off today must be on tomorrow: the default is per launch."""
    monkeypatch.setattr("qa.library.config_path", lambda: tmp_path / "config.json")
    from qa.library import read_settings

    prefs.set_help(session, False)
    assert read_settings() == {}, "help state must not touch the settings file"


def test_the_stats_panel_is_closed_by_default():
    fresh: dict = {}
    prefs.init(fresh)
    assert prefs.stats_open(fresh) is False
    assert prefs.stats_open({}) is False


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
    # The third way to learn a word, after the hover mark and the tour.
    assert "GLOSSARY.md" in keys


def test_the_glossary_is_alphabetical_and_one_heading_per_term():
    """A glossary out of order is a list nobody can scan."""
    text = docs_view.load("GLOSSARY.md")
    terms = docs_view.sections(text)
    assert len(terms) >= 40
    assert terms == sorted(terms, key=str.casefold), "GLOSSARY.md is out of order"
    assert len(terms) == len(set(terms)), "a term is defined twice"


def test_the_glossary_defines_the_words_the_column_help_uses():
    """Every column text leans on a word; the glossary must carry it."""
    text = docs_view.load("GLOSSARY.md")
    terms = {t.casefold() for t in docs_view.sections(text)}
    for word in (
        "confidence",
        "coverage",
        "difference",
        "listen item",
        "flag",
        "watchlist",
        "outline only",
        "voiced symbol",
        "suppressed duplication",
        "corroborated",
    ):
        assert word in terms, f"GLOSSARY.md has no entry for {word!r}"


def test_the_glossary_confidence_entry_says_why_it_matters():
    """The one term a new reviewer most needs, and the one nothing explained."""
    text = docs_view.load("GLOSSARY.md")
    start = text.index("## Confidence")
    end = text.index("## ", start + 3)
    entry = text[start:end]
    assert "Why it matters" in entry
    assert "0.6" in entry
    assert "pronunciation" in entry.casefold()


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
    pages = ("app.py", "run_view.py", "results_view.py", "storage_view.py")
    for name in pages:
        source = (ROOT / "qa" / "web" / name).read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped.startswith("help="):
                continue
            assert (
                "tooltip(" in stripped or "concept(" in stripped or "column(" in stripped
            ), f"qa/web/{name} writes help text inline: {stripped}"


# Every key a page asks for, read out of the pages themselves.
KEY_CALL = re.compile('(tooltip|concept|column)[(]["]([a-z_]+)["][)]')


def help_keys() -> set[tuple[str, str, str]]:
    found = set()
    for path in sorted((ROOT / "qa" / "web").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for accessor, key in KEY_CALL.findall(text):
            found.add((path.name, accessor, key))
    return found


def test_the_pages_do_ask_for_help_text():
    """A regex that matches nothing would pass the next test forever."""
    assert len(help_keys()) > 20


def test_every_key_a_page_asks_for_exists():
    """The direction the other guard does not cover.

    Trimming the module to fit the budget removed two keys and left the calls
    behind, and the first anyone knew of it was a KeyError traceback where the
    Storage tab should have been. Pruning words is meant to be safe, so the
    thing that makes it safe is this test rather than care.
    """
    known = {"tooltip": set(TOOLTIPS), "concept": set(CONCEPTS), "column": set(COLUMNS)}
    missing = [
        f"{page} asks for {accessor}({key!r})"
        for page, accessor, key in sorted(help_keys())
        if key not in known[accessor]
    ]
    assert not missing, "; ".join(missing)


def test_no_help_text_is_written_and_never_shown():
    """Words in the module that no page asks for are words nobody reads.

    Not a failure, but the budget is spent on them, so they are worth seeing.
    """
    asked = {key for _, _, key in help_keys()}
    unused = sorted((set(TOOLTIPS) | set(CONCEPTS) | set(COLUMNS)) - asked)
    assert not unused, "written but never shown: " + ", ".join(unused)


def test_the_helptext_module_is_the_only_place_the_words_live():
    source = Path(helptext.__file__).read_text(encoding="utf-8")
    assert "TOOLTIPS" in source and "TOUR" in source and "COLUMNS" in source
