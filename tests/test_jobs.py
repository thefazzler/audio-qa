"""Tests for detached runs, progress and the learned ETA.

No pipeline is executed here. The watcher reads the files the pipeline writes,
so a test can write those files itself and drive progress exactly, including
the awkward orderings a real run produces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
import time
from pathlib import Path

import pytest

from qa.jobs import (
    DONE,
    FAILED,
    RUNNING,
    FileJobStore,
    JobError,
    JobStatus,
    ProgressWatcher,
    TopicProgress,
)

SCRIPT = [
    "The gardener waters the seedlings each morning.",
    "Volunteers repot the tallest cuttings before the weekend arrives.",
]


@pytest.fixture
def store(tmp_path) -> FileJobStore:
    return FileJobStore(tmp_path / "jobs")


@pytest.fixture
def course(tmp_path) -> Path:
    course_dir = tmp_path / "course11"
    (course_dir / "qa_work").mkdir(parents=True)
    return course_dir


def write_manifest(course: Path, topics: dict[str, float], scripted=()) -> None:
    (course / "qa_work" / "manifest.json").write_text(
        json.dumps(
            {
                "course_code": "it_spisccc26_11_enus",
                "total_duration_s": sum(topics.values()),
                "topics": [
                    {
                        "topic": t,
                        "duration_s": d,
                        "scripted": (t in scripted) if scripted else True,
                    }
                    for t, d in topics.items()
                ],
            }
        ),
        encoding="utf-8",
    )


def write_script(course: Path, topics: list[str], unscripted=()) -> None:
    (course / "qa_work" / "script.json").write_text(
        json.dumps(
            {
                "topics": [
                    {
                        "topic": t,
                        "scripted": t not in unscripted,
                        "sentences": SCRIPT,
                        "slides": [1, 2],
                    }
                    for t in topics
                ]
            }
        ),
        encoding="utf-8",
    )


def write_transcript(course: Path, topic: str, duration: float, decode: float, text=None):
    words = []
    clock = 0.0
    for token in (text or " ".join(SCRIPT)).split():
        words.append(
            {"w": token, "start": round(clock, 2), "end": round(clock + 0.4, 2), "p": 0.97}
        )
        clock += 0.4
    (course / "qa_work" / f"transcript_{topic}.json").write_text(
        json.dumps(
            {
                "topic": topic,
                "duration_s": duration,
                "decode_seconds": decode,
                "word_count": len(words),
                "low_confidence_share": 0.004,
                "anomalies": [],
                "words": words,
                "segments": [{"text": " ".join(SCRIPT), "start": 0.0, "end": clock}],
            }
        ),
        encoding="utf-8",
    )


def new_status(course: Path) -> JobStatus:
    return JobStatus(id="test01", course_dir=str(course), started_at=time.time())


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def test_a_record_round_trips(store, course):
    status = new_status(course)
    status.topics = [TopicProgress(topic="01", duration_s=84.0)]
    store.write(status)
    again = store.read(status.id)
    assert again.id == status.id
    assert again.topics[0].topic == "01"
    assert again.course_dir == str(course)


def test_reading_an_unknown_job_says_so(store):
    with pytest.raises(JobError, match="No such job"):
        store.read("nope")


def test_listing_is_newest_first(store, course):
    for index, when in enumerate([100.0, 300.0, 200.0]):
        status = new_status(course)
        status.id = f"job{index}"
        status.started_at = when
        store.write(status)
    assert [s.started_at for s in store.list()] == [300.0, 200.0, 100.0]


def test_a_record_is_written_atomically(store, course):
    """A page polling this file must never read half of it."""
    status = new_status(course)
    store.write(status)
    assert not list(store.root.glob("*.tmp"))
    assert json.loads(store.path(status.id).read_text(encoding="utf-8"))["id"] == "test01"


def test_a_junk_file_does_not_break_listing(store, course):
    store.write(new_status(course))
    (store.root / "garbage.json").write_text("{oops", encoding="utf-8")
    assert len(store.list()) == 1


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

def test_topics_appear_once_the_manifest_exists(store, course):
    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)

    watcher.scan()
    assert status.topics == [], "nothing is known before the manifest is written"

    write_manifest(course, {"01": 84.0, "02": 418.0})
    watcher.scan()
    assert [t.topic for t in status.topics] == ["01", "02"]
    assert status.audio_total_s == pytest.approx(502.0)
    assert status.topic_done == 0


def test_progress_advances_as_each_transcript_lands(store, course):
    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)
    write_manifest(course, {"01": 84.0, "02": 418.0, "03": 350.0})
    watcher.scan()

    write_transcript(course, "01", 84.0, 35.0)
    watcher.scan()
    assert status.topic_done == 1
    assert status.topics[0].decode_seconds == 35.0
    assert status.topics[0].words > 0

    write_transcript(course, "02", 418.0, 176.0)
    watcher.scan()
    assert status.topic_done == 2


def test_the_eta_is_measured_not_assumed(store, course):
    """The first finished topic gives this machine's real rate."""
    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)
    write_manifest(course, {"01": 100.0, "02": 200.0, "03": 300.0})
    watcher.scan()

    assert status.eta_s is None
    assert "first topic" in status.eta_basis

    # 100 s of audio in 50 s of decode is 2x realtime; 500 s remain.
    write_transcript(course, "01", 100.0, 50.0)
    watcher.scan()
    assert status.rate_realtime == pytest.approx(2.0)
    assert status.eta_s == pytest.approx(250.0)


def test_the_eta_refines_as_more_topics_finish(store, course):
    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)
    write_manifest(course, {"01": 100.0, "02": 100.0, "03": 100.0})
    watcher.scan()

    write_transcript(course, "01", 100.0, 50.0)   # 2.0x realtime
    watcher.scan()
    assert status.rate_realtime == pytest.approx(2.0)
    assert status.eta_s == pytest.approx(100.0)  # 200 s of audio left at 2.0x

    # A second, slower topic drags the measured rate down to 1.33x. One topic
    # of audio is left, so the estimate falls, but it must fall to the refined
    # rate's answer rather than the first topic's optimistic one.
    write_transcript(course, "02", 100.0, 100.0)
    watcher.scan()
    refined = 200.0 / 150.0
    assert status.rate_realtime == pytest.approx(refined, abs=0.01)
    assert status.eta_s == pytest.approx(100.0 / refined, abs=0.5)
    assert status.eta_s > 100.0 / 2.0, "the stale optimistic rate is not reused"


def test_the_eta_reaches_zero_when_every_topic_is_done(store, course):
    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)
    write_manifest(course, {"01": 100.0, "02": 100.0})
    for topic in ("01", "02"):
        write_transcript(course, topic, 100.0, 50.0)
    watcher.scan()
    assert status.eta_s == 0.0
    assert "every topic" in status.eta_basis


def test_a_transcript_from_an_earlier_run_is_cached_not_progress(store, course):
    """The bug this guards: the bar read ten of ten before decoding began."""
    write_manifest(course, {"01": 100.0, "02": 100.0})
    write_transcript(course, "01", 100.0, 50.0)   # left by a previous run
    old = time.time() - 86400
    __import__("os").utime(course / "qa_work" / "transcript_01.json", (old, old))

    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)
    watcher.scan()

    assert status.topics[0].state == "cached"
    assert status.topics[0].decoded_this_run is False
    assert status.rate_realtime is None, "old work says nothing about this machine now"
    assert status.eta_s is None
    assert "first topic" in status.eta_basis


def test_a_cached_topic_still_streams_its_result(store, course):
    """Reusing a transcript is not a reason to hide what it says."""
    write_manifest(course, {"01": 100.0})
    write_script(course, ["01"])
    write_transcript(course, "01", 100.0, 50.0)
    old = time.time() - 86400
    __import__("os").utime(course / "qa_work" / "transcript_01.json", (old, old))

    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)
    watcher.scan()
    assert status.topics[0].state == "aligned"
    assert status.topics[0].coverage == pytest.approx(1.0)


def test_only_this_runs_decodes_set_the_rate(store, course):
    import os

    write_manifest(course, {"01": 100.0, "02": 100.0, "03": 100.0})
    write_transcript(course, "01", 100.0, 25.0)   # old, and misleadingly fast
    # Age it properly rather than fudging the clock: a previous run happened
    # yesterday, which is what this actually models.
    old = time.time() - 86400
    os.utime(course / "qa_work" / "transcript_01.json", (old, old))

    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)
    watcher.scan()

    write_transcript(course, "02", 100.0, 50.0)   # this run: 2.0x
    watcher.scan()
    assert status.rate_realtime == pytest.approx(2.0), "the cached 4x must not count"
    assert status.eta_s == pytest.approx(50.0), "only topic 03 is left"


def test_no_hardcoded_rate_appears_anywhere():
    """The estimate must come from measurement, on any machine."""
    source = Path("qa/jobs.py").read_text(encoding="utf-8")
    assert "realtime" in source
    for invented in ("2.3", "2.4x", "1.5x"):
        assert invented not in source


# ---------------------------------------------------------------------------
# Streaming results
# ---------------------------------------------------------------------------

def test_results_stream_per_topic_before_the_run_finishes(store, course):
    """Topic one can be read while topic three is still decoding."""
    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)
    write_manifest(course, {"01": 100.0, "02": 100.0, "03": 100.0})
    write_script(course, ["01", "02", "03"])
    watcher.scan()

    write_transcript(course, "01", 100.0, 50.0)
    watcher.scan()

    first = status.topics[0]
    assert first.state == "aligned"
    assert first.coverage == pytest.approx(1.0)
    assert first.discrepancies == 0
    assert status.topics[1].state == "pending", "later topics are untouched"


def test_a_streamed_result_matches_the_pipeline_stage(store, course):
    """The preview uses the align stage's own function, so it cannot disagree."""
    from qa.align import align_topic

    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)
    write_manifest(course, {"01": 100.0})
    write_script(course, ["01"])
    spoken = "The gardener soaks the seedlings each morning. " + SCRIPT[1]
    write_transcript(course, "01", 100.0, 50.0, text=spoken)
    watcher.scan()

    transcript = json.loads(
        (course / "qa_work" / "transcript_01.json").read_text(encoding="utf-8")
    )
    authoritative = align_topic(SCRIPT, transcript["words"], transcript["segments"])
    assert status.topics[0].discrepancies == len(authoritative["discrepancies"])
    assert status.topics[0].coverage == authoritative["coverage"]


def test_an_unscripted_topic_streams_without_a_verdict(store, course):
    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)
    write_manifest(course, {"01": 100.0, "09": 500.0})
    write_script(course, ["01", "09"], unscripted=("09",))
    write_transcript(course, "09", 500.0, 200.0)
    watcher.scan()

    demo = next(t for t in status.topics if t.topic == "09")
    assert demo.state == "aligned"
    assert demo.scripted is False
    assert demo.discrepancies is None, "a demo has no word level verdict"


def test_a_broken_transcript_does_not_stop_the_watcher(store, course):
    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)
    write_manifest(course, {"01": 100.0, "02": 100.0})
    write_script(course, ["01", "02"])
    (course / "qa_work" / "transcript_01.json").write_text("{oops", encoding="utf-8")
    write_transcript(course, "02", 100.0, 50.0)

    watcher.scan()
    assert status.topics[0].state == "pending"
    assert status.topics[1].state == "aligned", "one bad file must not block the rest"


# ---------------------------------------------------------------------------
# Stages and lifecycle
# ---------------------------------------------------------------------------

def test_stage_progress_is_recorded(store, course):
    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)
    watcher.set_stage("transcribe", 4, 8)
    assert store.read(status.id).stage == "transcribe"
    assert store.read(status.id).stage_index == 4


def test_submitting_a_folder_that_is_not_a_course_is_refused(tmp_path, store):
    from qa.jobs import submit

    with pytest.raises(JobError, match="not an ingested course"):
        submit(tmp_path / "empty", {}, store)


def test_elapsed_stops_when_the_run_finishes(store, course):
    status = new_status(course)
    status.started_at = 1000.0
    status.finished_at = 1090.0
    assert status.elapsed_s == pytest.approx(90.0)


def test_status_serialization_carries_the_derived_counts(store, course):
    status = new_status(course)
    status.topics = [
        TopicProgress(topic="01", state="aligned"),
        TopicProgress(topic="02"),
    ]
    data = status.to_dict()
    assert data["topic_total"] == 2
    assert data["topic_done"] == 1


# ---------------------------------------------------------------------------
# One run per course
# ---------------------------------------------------------------------------

@dataclass
class FakeProcess:
    """What Popen returns, as far as submit is concerned: a pid.

    Tests that stub Popen have to hand back something with one, because submit
    records the pid so a later reader can ask the operating system whether the
    run is still there rather than waiting out a timeout.
    """

    pid: int = 999999


def stub_popen(monkeypatch, pid: int = 999999, seen: dict | None = None) -> None:
    def fake(*args, **kwargs):
        if seen is not None:
            seen["started"] = True
            seen["args"] = args
            seen["kwargs"] = kwargs
        return FakeProcess(pid=pid)

    monkeypatch.setattr("qa.jobs.subprocess.Popen", fake)


def make_course(tmp_path: Path, name: str = "course11") -> Path:
    course_dir = tmp_path / name
    (course_dir / "qa_work").mkdir(parents=True)
    (course_dir / "course.yaml").write_text("course_number: '11'\n", encoding="utf-8")
    return course_dir


def test_a_second_run_on_the_same_course_is_refused(tmp_path, store):
    """Two runs would overwrite each other's intermediates."""
    from qa.jobs import RUNNING, submit

    course_dir = make_course(tmp_path)
    running = JobStatus(
        id="live", course_dir=str(course_dir), state=RUNNING, started_at=time.time()
    )
    store.write(running)

    with pytest.raises(JobError, match="already in progress"):
        submit(course_dir, {}, store)


def test_a_run_on_a_different_course_is_allowed(tmp_path, store, monkeypatch):
    from qa.jobs import RUNNING, submit

    first = make_course(tmp_path, "course11")
    second = make_course(tmp_path, "course12")
    store.write(
        JobStatus(id="live", course_dir=str(first), state=RUNNING, started_at=time.time())
    )
    started: dict = {}
    stub_popen(monkeypatch, seen=started)
    assert submit(second, {}, store).course_dir == str(second)
    assert started["started"]


def test_an_abandoned_run_does_not_block_a_new_one(tmp_path, store, monkeypatch):
    """A record still saying "running" after its process died is not a run."""
    from qa.jobs import RUNNING, STALE_AFTER_S, submit

    course_dir = make_course(tmp_path)
    dead = JobStatus(
        id="dead", course_dir=str(course_dir), state=RUNNING, started_at=time.time()
    )
    store.write(dead)
    dead.updated_at = time.time() - STALE_AFTER_S - 60
    store.path(dead.id).write_text(
        json.dumps({**dead.to_dict(), "updated_at": dead.updated_at}), encoding="utf-8"
    )

    assert store.read("dead").stale is True
    assert store.read("dead").active is False
    stub_popen(monkeypatch)
    assert submit(course_dir, {}, store).id != "dead"


def test_a_finished_run_is_neither_active_nor_stale(tmp_path, store):
    course_dir = make_course(tmp_path)
    finished = JobStatus(
        id="ok", course_dir=str(course_dir), state=DONE, started_at=time.time()
    )
    store.write(finished)
    assert store.read("ok").active is False
    assert store.read("ok").stale is False


def test_reused_topics_are_counted_apart_from_decoded_ones(store, course):
    """"10 of 10 transcribed" on a run that decoded nothing is misleading."""
    import os

    write_manifest(course, {"01": 100.0, "02": 100.0})
    write_script(course, ["01", "02"])
    write_transcript(course, "01", 100.0, 50.0)
    old = time.time() - 86400
    os.utime(course / "qa_work" / "transcript_01.json", (old, old))

    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)
    watcher.scan()
    write_transcript(course, "02", 100.0, 50.0)
    watcher.scan()

    assert status.decoded_count == 1
    assert status.reused_count == 1
    assert status.topic_done == 2
    assert store.read(status.id).to_dict()["reused_count"] == 1


def test_a_cached_topic_re_decoded_mid_run_is_noticed(store, course):
    """The bug: a forced run reported decoding nothing after 74 seconds of it.

    Once a topic was marked cached and aligned, the watcher stopped looking at
    its file, so the transcript the run then produced was invisible.
    """
    import os

    write_manifest(course, {"01": 100.0, "02": 100.0})
    write_script(course, ["01", "02"])
    write_transcript(course, "01", 100.0, 25.0)
    old = time.time() - 86400
    os.utime(course / "qa_work" / "transcript_01.json", (old, old))

    status = new_status(course)
    watcher = ProgressWatcher(course, status, store)
    watcher.scan()
    assert status.topics[0].state == "aligned"
    assert status.decoded_count == 0

    # The run re-decodes it, as --force would.
    time.sleep(0.01)
    write_transcript(course, "01", 100.0, 50.0)
    watcher.scan()

    assert status.topics[0].decoded_this_run is True
    assert status.topics[0].decode_seconds == 50.0
    assert status.decoded_count == 1
    assert status.rate_realtime == pytest.approx(2.0)
