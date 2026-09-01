"""The parts of the web layer that are not Streamlit rendering.

Everything here is either a flag passed to Streamlit or a pure function that
turns a record into words. Rendering is not tested; a Streamlit page needs a
browser to mean anything, and a test that imports one only proves it imports.

The launch flags get a test because a flag Streamlit no longer recognizes makes
`qa-web` refuse to start, and that failure appears on someone else's machine
after an upgrade rather than here.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from qa.jobs import DONE, FAILED, RUNNING, JobStatus, TopicProgress, _reviewer
from qa.web.launch import STREAMLIT_QUIET
from qa.web.run_view import run_label


# ---------------------------------------------------------------------------
# What qa-web tells Streamlit to stop doing
# ---------------------------------------------------------------------------

def test_every_quiet_flag_is_a_real_streamlit_option():
    """A flag Streamlit dropped would make qa-web fail to start, elsewhere."""
    streamlit_config = pytest.importorskip("streamlit.config")
    known = streamlit_config._config_options_template

    names = [f[2:] for f in STREAMLIT_QUIET if f.startswith("--")]
    assert names, "the quiet flags went missing"
    unknown = [n for n in names if n not in known]
    assert not unknown, f"streamlit no longer has: {', '.join(unknown)}"


def test_the_flags_cover_what_the_pilot_session_found():
    flags = dict(zip(STREAMLIT_QUIET[::2], STREAMLIT_QUIET[1::2]))
    # The first-run email prompt reads as a hang to a new user.
    assert flags["--server.showEmailPrompt"] == "false"
    # Which also suppresses the "Help agents write better apps" recommendation.
    assert flags["--logger.hideWelcomeMessage"] == "true"
    # Deploy invites pushing customer narration to someone else's cloud.
    assert flags["--client.toolbarMode"] == "minimal"
    assert flags["--browser.gatherUsageStats"] == "false"


def test_every_flag_has_a_value():
    assert len(STREAMLIT_QUIET) % 2 == 0
    assert all(f.startswith("--") for f in STREAMLIT_QUIET[::2])
    assert not any(f.startswith("--") for f in STREAMLIT_QUIET[1::2])


# ---------------------------------------------------------------------------
# Telling two runs of one course apart
# ---------------------------------------------------------------------------

def job(**kwargs) -> JobStatus:
    defaults = dict(
        id="abc123def456",
        course_dir=str(Path("library") / "spisccc26" / "course10"),
        course_code="it_spisccc26_10_enus",
        state=DONE,
        started_at=time.mktime((2026, 9, 1, 14, 41, 0, 0, 0, -1)),
        finished_at=time.mktime((2026, 9, 1, 14, 49, 0, 0, 0, -1)),
        device_used="cuda",
        compute_type="float16",
        reviewed_by="Ryan",
        topics=[TopicProgress(topic="01", discrepancies=3)],
    )
    defaults.update(kwargs)
    return JobStatus(**defaults)


def test_a_run_is_labelled_by_everything_that_distinguishes_it():
    label = run_label(job())
    for part in ("it_spisccc26_10_enus", "2026-09-01 14:41", "cuda float16", "8m 00s"):
        assert part in label, label
    assert "3 differences" in label
    assert label.endswith("Ryan")


def test_two_runs_of_one_course_get_different_labels():
    """The old label was course, status and run id: identical but for a hash."""
    morning = run_label(
        job(
            started_at=time.mktime((2026, 9, 1, 9, 2, 0, 0, 0, -1)),
            finished_at=time.mktime((2026, 9, 1, 9, 35, 0, 0, 0, -1)),
            device_used="cpu",
            compute_type="int8",
        )
    )
    evening = run_label(job())
    assert morning != evening
    assert "cpu int8" in morning
    assert "cuda float16" in evening


def test_a_running_job_says_how_long_it_has_been_going_not_how_many_it_found():
    label = run_label(
        job(
            state=RUNNING,
            finished_at=None,
            started_at=time.time() - 120,
            updated_at=time.time(),
        )
    )
    assert "running" in label
    assert "difference" not in label


def test_a_failed_job_says_so():
    assert "failed" in run_label(job(state=FAILED))


def test_a_job_that_died_without_saying_so_is_labelled_abandoned():
    label = run_label(job(state=RUNNING, finished_at=None, started_at=1.0))
    assert "abandoned" in label


def test_a_label_survives_a_job_that_knows_almost_nothing():
    bare = JobStatus(id="x", course_dir="somewhere/course01")
    label = run_label(bare)
    assert "course01" in label
    assert "not started" in label


# ---------------------------------------------------------------------------
# The reviewer, read from where intake put it
# ---------------------------------------------------------------------------

def test_the_reviewer_comes_from_course_yaml(tmp_path):
    (tmp_path / "course.yaml").write_text(
        'course_number: "10"\nreviewed_by: "Ryan Mount"\n', encoding="utf-8"
    )
    assert _reviewer(tmp_path) == "Ryan Mount"


def test_a_course_with_no_reviewer_is_not_an_error(tmp_path):
    (tmp_path / "course.yaml").write_text('course_number: "10"\n', encoding="utf-8")
    assert _reviewer(tmp_path) == ""


def test_an_unreadable_course_yaml_is_not_an_error(tmp_path):
    (tmp_path / "course.yaml").write_text("{[not yaml", encoding="utf-8")
    assert _reviewer(tmp_path) == ""
    assert _reviewer(tmp_path / "nowhere") == ""


# ---------------------------------------------------------------------------
# Showing a folder
# ---------------------------------------------------------------------------

def test_opening_something_that_is_not_there_says_so(tmp_path):
    from qa.web import reveal

    error = reveal.open_folder(tmp_path / "nowhere")
    assert "does not exist" in error


def test_a_file_path_shows_the_folder_holding_it(tmp_path, monkeypatch):
    """"Where is my packet" and "show me the packet" are the same request."""
    from qa.web import reveal

    packet = tmp_path / "packet.md"
    packet.write_text("x", encoding="utf-8")

    shown: list[str] = []
    monkeypatch.setattr(reveal, "_which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(
        reveal.subprocess, "Popen", lambda cmd, **kw: shown.append(cmd[-1])
    )
    import sys

    if sys.platform == "win32":
        monkeypatch.setattr(reveal.os, "startfile", lambda p: shown.append(p), raising=False)

    assert reveal.open_folder(packet) == ""
    assert shown == [str(tmp_path)]
