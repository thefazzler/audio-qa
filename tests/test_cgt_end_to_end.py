"""A CGT course through every stage, on generated material.

No real CGT delivery with media exists yet. The extractor is tested against a
real script in `test_bus_template.py`, but a script that parses is not a course
that runs: the manifest, the aligner, the checks, the artifacts and the packet
all had to stop assuming a storyboard, and the only honest way to know they did
is to run one.

So this builds a whole CGT course out of nothing, a generated BUS document and
generated tone, and runs the pipeline end to end. It asserts the plumbing, not
the findings. The narration is a sine wave and the script is about kettles, so
the alignment result is meaningless and is deliberately not checked; what is
checked is that every stage produced its output and that the packet describes a
Word script rather than a PowerPoint that does not exist.

Skipped when no ASR model is cached, in the same way the setup smoke test is.
When a real CGT delivery with media arrives, it becomes the known-answer course
and this stays as the structural test underneath it.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from qa.setup import check_model

pytestmark = pytest.mark.skipif(
    not check_model("tiny").satisfied,
    reason="no tiny ASR model cached; run qa-setup to fetch one",
)

CODE = "it_gen01_02_enus"
COURSE_ID = "it_gen01_02"

BLOCKS = [
    {
        "title": "COURSE OVERVIEW",
        "words": 8,
        "scenes": [("Scene 1: Learning Objectives", "The kettle boils a fresh pot.")],
    },
    {
        "title": "TOPIC 1 TITLE: REPOTTING THE CUTTINGS",
        "words": 6,
        "scenes": [("Scene 1: Why Repot", "Volunteers repot the tallest cuttings.")],
    },
]


def clip(path: Path, seconds: float = 2.0) -> None:
    """A short warble. The recognizer's accuracy is not what is under test."""
    import numpy as np
    import soundfile as sf

    rate = 16000
    time = np.arange(int(seconds * rate)) / rate
    tone = 0.2 * np.sin(2 * np.pi * (180 + 40 * np.sin(2 * np.pi * 0.7 * time)) * time)
    padded = np.concatenate([np.zeros(rate // 2), tone, np.zeros(rate // 2)])
    sf.write(str(path), padded.astype("float32"), rate)


@pytest.fixture(scope="module")
def run(tmp_path_factory) -> dict:
    """Build a CGT course, run every stage, return where things landed."""
    from test_bus_template import make_bus_document

    root = tmp_path_factory.mktemp("cgt")
    course = root / "course02"
    audio = course / "audio"
    audio.mkdir(parents=True)

    make_bus_document(
        course / f"{COURSE_ID}_scripts_v1.docx", course_id=COURSE_ID, blocks=BLOCKS
    )
    for topic in ("01", "02"):
        clip(audio / f"{CODE}_{topic}.wav")

    (course / "course.yaml").write_text(
        'course_number: "02"\n'
        "project_type: CGT\n"
        f"course_code: {CODE}\n"
        "script_source: docx_bus\n"
        "unscripted_topics: []\n"
        "topics: {}\n"
        "asr:\n"
        "  model: tiny\n",
        encoding="utf-8",
    )

    from qa import cli as cli_module

    cli_module._ASR_OVERRIDES = {"model": "tiny", "cpu_threads": None, "device": "cpu"}
    cli_module._ONLY_TOPICS = None
    cli_module._RUN_DATE = "2026-09-01"
    cli_module._OUTPUT_DIR = str(root / "packets")

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        code = cli_module.run(course, None, False)

    return {"course": course, "output": root / "packets", "code": code}


def load(run, name: str) -> dict:
    return json.loads(
        (run["course"] / "qa_work" / name).read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------

def test_every_stage_runs_on_a_course_with_no_powerpoint(run):
    assert run["code"] == 0
    for name in (
        "ingest.json",
        "manifest.json",
        "script.json",
        "transcripts.json",
        "discrepancies.json",
        "artifacts.json",
        "checks.json",
    ):
        assert (run["course"] / "qa_work" / name).exists(), name


def test_the_manifest_records_the_word_script_and_no_storyboard(run):
    manifest = load(run, "manifest.json")
    assert manifest["script_source"] == "docx_bus"
    assert manifest["script_document"].endswith(".docx")
    assert manifest["storyboard"] is None, "a CGT course has no storyboard"
    assert manifest["script_document_sha256"]


def test_the_script_stage_read_the_word_document(run):
    script = load(run, "script.json")
    assert script["script_source"] == "docx_bus"
    assert script["course_id"] == COURSE_ID
    assert [t["topic"] for t in script["topics"]] == ["01", "02"]
    assert all(t["slides"] is None for t in script["topics"])
    assert all(t["script"] == "verbatim" for t in script["topics"])
    assert script["topics"][0]["source_ref"] == "COURSE OVERVIEW"


def test_scene_headers_did_not_reach_the_alignment_text(run):
    script = load(run, "script.json")
    narration = " ".join(s for t in script["topics"] for s in t["sentences"])
    assert "Scene 1" not in narration
    assert all(t["non_narration"] for t in script["topics"])


def test_the_checks_stage_carries_the_script_state_through(run):
    checks = load(run, "checks.json")
    assert checks["summary"]["script_source"] == "docx_bus"
    assert checks["summary"]["script_document"].endswith(".docx")
    for row in checks["topics"]:
        assert row["slides"] is None
        assert row["script"] == "verbatim"
        assert row["source_ref"]


def test_the_packet_describes_a_word_script_not_a_slide_deck(run):
    packets = list(run["output"].glob("*.md"))
    assert len(packets) == 1, [p.name for p in packets]
    text = packets[0].read_text(encoding="utf-8")

    assert "| Script source |" in text
    assert "BUS Writing Template" in text
    assert ".docx" in text
    assert "slides" not in text.split("## Measured audio conventions")[0].lower()
    assert "COURSE OVERVIEW" in text


def test_the_packet_is_named_for_the_run_and_lands_in_the_output_folder(run):
    packet = next(run["output"].glob("*.md"))
    assert packet.name.startswith(f"{CODE}_2026-09-01_")
    assert packet.name.endswith("_cpu-int8.md")
    assert not list((run["course"] / "qa_out").glob("*.md"))
    assert (run["course"] / "qa_out" / "packet_index.json").exists()


def test_the_packet_carries_the_authors_own_pacing_numbers(run):
    text = next(run["output"].glob("*.md")).read_text(encoding="utf-8")
    assert "Author's word count" in text
    assert "0m 06s" in text
