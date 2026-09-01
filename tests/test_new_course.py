"""Tests for the course scaffolder.

The scaffolder's whole job is to read the delivered filenames correctly and to
write a course.yaml the config loader accepts, so that is what is asserted:
parsing against real Skillsoft names, and a round trip through
`load_course_yaml`. No audio is involved.
"""

from __future__ import annotations

import io

import pytest

from qa.config import load_course_yaml
from qa.new_course import (
    ask_project_type,
    parse_delivery_name,
    read_delivery,
    render_course_yaml,
    scaffold,
)
from qa.util import ScaffoldError

COURSE_10 = "it_spisccc26_10_enus_01.mp3"


# ---------------------------------------------------------------------------
# Reading the delivered filenames
# ---------------------------------------------------------------------------

def test_parses_the_course_out_of_a_delivered_filename():
    d = parse_delivery_name(COURSE_10)
    assert d.learning_path == "spisccc26"
    assert d.course_number == "10"
    assert d.course_code == "it_spisccc26_10_enus"
    assert d.topic == "01"


def test_compound_topic_ids_parse():
    """Topic ids may be compound, as in the demo file named _09_01."""
    assert parse_delivery_name("it_spisccc26_10_enus_09_01.mp4").topic == "09_01"


def test_course_folder_is_zero_padded():
    """course01 has to sort ahead of course10 in a plain directory listing."""
    assert parse_delivery_name("it_path_1_enus_01.mp3").course_folder == "course01"
    assert parse_delivery_name(COURSE_10).course_folder == "course10"


def test_a_name_that_is_not_a_delivery_is_a_clean_error():
    with pytest.raises(ScaffoldError, match="Cannot read a course"):
        parse_delivery_name("narration_final_v2.mp3")


def test_reads_a_delivery_folder_and_reports_its_topics(tmp_path):
    for topic in ("01", "02", "03"):
        (tmp_path / f"it_spisccc26_11_enus_{topic}.mp3").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("not media", encoding="utf-8")

    delivery, topics = read_delivery(tmp_path)
    assert delivery.course_code == "it_spisccc26_11_enus"
    assert topics == ["01", "02", "03"]


def test_two_courses_in_one_folder_halt(tmp_path):
    (tmp_path / "it_spisccc26_11_enus_01.mp3").write_bytes(b"")
    (tmp_path / "it_spisccc26_12_enus_01.mp3").write_bytes(b"")
    with pytest.raises(ScaffoldError, match="more than one course"):
        read_delivery(tmp_path)


def test_an_empty_delivery_folder_halts(tmp_path):
    with pytest.raises(ScaffoldError, match="No media files"):
        read_delivery(tmp_path)


# ---------------------------------------------------------------------------
# The prompt: project_type is the one thing the filenames cannot answer
# ---------------------------------------------------------------------------

def test_project_type_prompt_accepts_either_case():
    assert ask_project_type(io.StringIO("vendor\n")) == "VENDOR"
    assert ask_project_type(io.StringIO("CGT\n")) == "CGT"


def test_project_type_prompt_reasks_until_valid():
    assert ask_project_type(io.StringIO("mp3\nyes\nCGT\n")) == "CGT"


def test_project_type_prompt_fails_cleanly_on_no_answer():
    with pytest.raises(ScaffoldError, match="No answer given"):
        ask_project_type(io.StringIO(""))


# ---------------------------------------------------------------------------
# What gets written
# ---------------------------------------------------------------------------

def test_scaffold_builds_the_learning_path_structure(tmp_path):
    delivery = parse_delivery_name("it_spisccc26_11_enus_01.mp3")
    course_dir = scaffold(delivery, tmp_path, "VENDOR")

    assert course_dir == tmp_path / "spisccc26" / "course11"
    assert (course_dir / "audio").is_dir()
    assert (course_dir / "course.yaml").is_file()


def test_scaffold_refuses_to_clobber_an_existing_course(tmp_path):
    delivery = parse_delivery_name("it_spisccc26_11_enus_01.mp3")
    scaffold(delivery, tmp_path, "VENDOR")
    with pytest.raises(ScaffoldError, match="already exists"):
        scaffold(delivery, tmp_path, "CGT")
    assert scaffold(delivery, tmp_path, "CGT", force=True)


def test_unscripted_topics_are_left_blank_with_a_reminder():
    """The human fills these in after reading the storyboard, not before."""
    text = render_course_yaml(parse_delivery_name(COURSE_10), "VENDOR")
    assert "unscripted_topics: []" in text
    assert "TODO" in text and "storyboard" in text


def test_the_yaml_says_nothing_about_file_formats():
    """Ingest sniffs each file and demuxes what it must; see DECISIONS.md D1."""
    text = render_course_yaml(parse_delivery_name(COURSE_10), "CGT")
    for word in ("mp3", "mp4", "format", "demux"):
        assert word not in text.lower()


def test_scaffolded_course_loads_through_the_config_stage(tmp_path):
    """The real check: config.py accepts what the scaffolder writes.

    A storyboard has to exist for load_course_yaml to return, which is the
    human step the scaffolder deliberately leaves undone; plant an empty one.
    """
    delivery = parse_delivery_name("it_spisccc26_11_enus_01.mp3")
    course_dir = scaffold(delivery, tmp_path, "CGT")
    (course_dir / "it_spisccc26_11_storyboard.pptx").write_bytes(b"")

    cfg = load_course_yaml(course_dir)
    assert cfg.course_number == "11"
    assert cfg.project_type == "CGT"
    assert cfg.course_code == "it_spisccc26_11_enus"
    assert cfg.unscripted_topics == ()
    assert cfg.slide_map == {}


def test_generated_yaml_matches_course_10s_key_set():
    """Course 10's course.yaml is the shape every scaffolded course follows."""
    from pathlib import Path

    import yaml

    reference = Path(__file__).parent / "spisccc26" / "course10" / "course.yaml"
    if not reference.exists():  # pragma: no cover - reference is in git
        pytest.skip("Course 10 course.yaml absent")

    expected = yaml.safe_load(reference.read_text(encoding="utf-8"))
    generated = yaml.safe_load(render_course_yaml(parse_delivery_name(COURSE_10), "VENDOR"))
    assert set(generated) == set(expected)
    assert generated["course_number"] == expected["course_number"]
    assert generated["project_type"] == expected["project_type"]
    assert generated["course_code"] == expected["course_code"]
    assert generated["unscripted_topics"] == []
