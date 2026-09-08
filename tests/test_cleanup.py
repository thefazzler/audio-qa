"""Freeing disk space, and the things that must survive it.

The property that matters is not how much is freed. It is that **nothing a run
discovered is ever removed**, because the failure mode here is not an error
message: it is a Results tab that opens, renders, and says "Nothing on the
listen list" for a course whose listen list was deleted. That is a silent false
clearance in the one place this tool exists to be loud about, so the test that
earns its place is the one that reclaims a course and then reads its listen
list back.

The deletion tests build their own courses in tmp_path and never touch the real
library. See DECISIONS.md D31.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from qa.cleanup import (
    MEDIA_KEY,
    SCRATCH_KEY,
    CleanupError,
    archive_packets,
    delete_packets,
    human,
    library_survey,
    packet_space,
    reclaim,
    reclaimed_at,
    survey,
)
from qa.results import load_results


# ---------------------------------------------------------------------------
# A course on disk, shaped like a real one
# ---------------------------------------------------------------------------

def plant(tmp_path: Path, topics=("01", "02"), listen=True) -> Path:
    """A course with media, scratch audio, findings and a packet marker."""
    course = tmp_path / "library" / "spisccc26" / "course10"
    work = course / "qa_work"
    (work / "audio").mkdir(parents=True)
    (course / "audio").mkdir(parents=True)
    (course / "qa_out").mkdir(parents=True)

    (course / "course.yaml").write_text(
        'course_number: "10"\nproject_type: VENDOR\n'
        "course_code: it_spisccc26_10_enus\n",
        encoding="utf-8",
    )
    (course / "it_spisccc26_10_storyboard.pptx").write_bytes(b"P" * 4096)

    for topic in topics:
        (course / "audio" / f"it_spisccc26_10_enus_{topic}.mp3").write_bytes(b"M" * 8192)
        (work / "audio" / f"it_spisccc26_10_enus_{topic}.wav").write_bytes(b"W" * 65536)
        (work / f"transcript_{topic}.json").write_text("{}", encoding="utf-8")
        (work / f"discrepancies_{topic}.json").write_text(
            json.dumps(
                {
                    "discrepancies": [
                        {
                            "listen_item": listen,
                            "start_s": 12.5,
                            "script_says": "SIEM",
                            "voice_said": "seem",
                            "reason": "below the confidence floor",
                            "min_confidence": 0.41,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    (work / "checks.json").write_text(
        json.dumps(
            {
                "summary": {
                    "course_code": "it_spisccc26_10_enus",
                    "course_number": "10",
                    "project_type": "VENDOR",
                    "topic_count": len(topics),
                    "mean_coverage": 0.999,
                    "total_discrepancies": len(topics),
                    "total_listen_items": len(topics) if listen else 0,
                    "flagged_topics": [],
                },
                "topics": [
                    {
                        "topic": t,
                        "scripted": True,
                        "coverage": 0.999,
                        "discrepancies": 1,
                        "listen_items": 1 if listen else 0,
                        "flags": [],
                    }
                    for t in topics
                ],
            }
        ),
        encoding="utf-8",
    )
    (work / "transcripts.json").write_text(
        json.dumps({"engine": "faster-whisper", "settings": {"compute_type": "int8"}}),
        encoding="utf-8",
    )
    (work / "artifacts.json").write_text("{}", encoding="utf-8")
    (work / "manifest.json").write_text("{}", encoding="utf-8")

    packets = tmp_path / "packets"
    packets.mkdir(parents=True, exist_ok=True)
    packet = packets / "it_spisccc26_10_enus_2026-09-01_1441_cpu-int8.md"
    packet.write_text("# packet\n", encoding="utf-8")
    (course / "qa_out" / "packet_index.json").write_text(
        json.dumps({"path": str(packet), "output_dir": str(packets)}), encoding="utf-8"
    )
    return course


@pytest.fixture
def no_jobs(monkeypatch, tmp_path):
    """No run is in progress, without reaching for the real jobs folder."""
    monkeypatch.setattr("qa.jobs.FileJobStore.__init__", lambda self, root=None: None)
    monkeypatch.setattr("qa.jobs.FileJobStore.list", lambda self: [])


# ---------------------------------------------------------------------------
# Looking changes nothing
# ---------------------------------------------------------------------------

def test_a_survey_separates_what_can_be_remade_from_what_was_found(tmp_path, no_jobs):
    course = plant(tmp_path)
    space = survey(course)

    assert space.scratch.count == 2
    assert space.media.count == 3, "two mp3s and the storyboard"
    assert space.scratch.bytes > 0 and space.media.bytes > 0
    assert space.kept_bytes > 0
    assert space.runnable
    assert space.reclaimed_at == ""


def test_a_survey_deletes_nothing(tmp_path, no_jobs):
    course = plant(tmp_path)
    before = sorted(p.relative_to(course) for p in course.rglob("*") if p.is_file())
    survey(course)
    survey(course)
    after = sorted(p.relative_to(course) for p in course.rglob("*") if p.is_file())
    assert before == after


def test_the_findings_are_never_counted_as_reclaimable(tmp_path, no_jobs):
    """Whatever the buckets hold, none of it may be a finding."""
    course = plant(tmp_path)
    space = survey(course)
    reclaimable = set(space.scratch.paths) | set(space.media.paths)

    for kept in (
        course / "course.yaml",
        course / "qa_work" / "checks.json",
        course / "qa_work" / "transcripts.json",
        course / "qa_work" / "artifacts.json",
        course / "qa_work" / "discrepancies_01.json",
        course / "qa_work" / "transcript_01.json",
        course / "qa_out" / "packet_index.json",
    ):
        assert kept not in reclaimable, kept


# ---------------------------------------------------------------------------
# The tier that costs nothing
# ---------------------------------------------------------------------------

def test_reclaiming_scratch_leaves_the_course_runnable(tmp_path, no_jobs):
    course = plant(tmp_path)
    result = reclaim(course)

    assert result.ok
    assert result.freed_bytes == 2 * 65536
    assert not list((course / "qa_work").glob("audio/*"))
    assert survey(course).runnable, "the delivered media is still here"
    assert reclaimed_at(course) == "", "scratch alone is not worth a marker"


def test_an_emptied_scratch_folder_goes_but_nothing_above_it_does(tmp_path, no_jobs):
    course = plant(tmp_path)
    reclaim(course)
    assert not (course / "qa_work" / "audio").exists()
    assert (course / "qa_work").is_dir()
    assert (course / "qa_work" / "checks.json").is_file()


# ---------------------------------------------------------------------------
# The tier that costs something, and what it must not cost
# ---------------------------------------------------------------------------

def test_reclaiming_media_frees_nearly_everything(tmp_path, no_jobs):
    course = plant(tmp_path)
    before = survey(course)
    result = reclaim(course, media=True)

    assert result.ok
    after = survey(course)
    assert after.reclaimable_bytes == 0
    assert after.total_bytes < before.total_bytes
    assert not after.runnable


def test_the_listen_list_still_loads_after_the_media_is_gone(tmp_path, no_jobs):
    """The test this file exists for.

    An emptied listen list does not raise. It renders as a course with nothing
    to listen to, which is a false clearance, so this asserts the items are
    still there rather than that the page did not crash.
    """
    course = plant(tmp_path)
    before = load_results(course)
    assert len(before.listen) == 2

    reclaim(course, media=True)

    after = load_results(course)
    assert len(after.listen) == 2
    assert [i.topic for i in after.listen] == [i.topic for i in before.listen]
    assert after.mean_coverage == before.mean_coverage
    assert after.total_differences == before.total_differences
    assert after.packet_md is not None, "the packet is somewhere else and stays there"


def test_a_reclaimed_course_says_so_itself(tmp_path, no_jobs):
    course = plant(tmp_path)
    reclaim(course, media=True)

    when = reclaimed_at(course)
    assert when, "a course that cannot be run has to be able to say why"
    marker = json.loads(
        (course / "qa_work" / "reclaimed.json").read_text(encoding="utf-8")
    )
    assert marker["freed_bytes"] > 0
    assert "Ingest the course again" in marker["note"]


def test_a_reclaimed_course_is_still_a_course(tmp_path, no_jobs):
    """course.yaml survives, so the library and the Results tab still list it."""
    from qa.library import list_courses

    course = plant(tmp_path)
    reclaim(course, media=True)
    assert (course / "course.yaml").is_file()
    assert [c.path for c in list_courses(tmp_path / "library")] == [course]


def test_reclaiming_twice_is_not_an_error(tmp_path, no_jobs):
    course = plant(tmp_path)
    reclaim(course, media=True)
    again = reclaim(course, media=True)
    assert again.ok
    assert again.freed_bytes == 0


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------

def test_a_run_in_progress_stops_the_whole_thing(tmp_path, monkeypatch):
    """Deleting the wav a live transcribe is reading would fail it halfway."""
    course = plant(tmp_path)

    class Live:
        id = "abc123"

    monkeypatch.setattr("qa.jobs.running_for", lambda d, s=None: Live())
    with pytest.raises(CleanupError, match="in progress"):
        reclaim(course, media=True)
    assert list((course / "qa_work").glob("audio/*")), "nothing was removed"


def test_a_folder_that_is_not_a_course_is_refused(tmp_path, no_jobs):
    stray = tmp_path / "not-a-course"
    (stray / "audio").mkdir(parents=True)
    (stray / "audio" / "something.mp3").write_bytes(b"x")
    with pytest.raises(CleanupError, match="not an ingested course"):
        reclaim(stray, media=True)
    assert (stray / "audio" / "something.mp3").exists()


def test_nothing_outside_the_course_is_ever_unlinked(tmp_path, no_jobs, monkeypatch):
    """The guard that turns a bug in the survey into a refusal."""
    course = plant(tmp_path)
    outsider = tmp_path / "elsewhere.mp3"
    outsider.write_bytes(b"not yours")

    real = survey(course)
    from qa import cleanup

    def poisoned(course_dir, store=None):
        space = real
        object.__setattr__(space.media, "paths", space.media.paths + (outsider,))
        return space

    monkeypatch.setattr(cleanup, "survey", poisoned)
    result = cleanup.reclaim(course, media=True)

    assert outsider.exists(), "a path outside the course must survive"
    assert any("refused" in reason for _, reason in result.failed)


def test_the_packet_is_never_touched_by_a_course_reclaim(tmp_path, no_jobs):
    course = plant(tmp_path)
    packet = tmp_path / "packets" / "it_spisccc26_10_enus_2026-09-01_1441_cpu-int8.md"
    reclaim(course, media=True)
    assert packet.is_file()
    assert packet.read_text(encoding="utf-8") == "# packet\n"


# ---------------------------------------------------------------------------
# The whole library
# ---------------------------------------------------------------------------

def test_the_library_survey_puts_the_biggest_win_first(tmp_path, no_jobs):
    small = plant(tmp_path, topics=("01",))
    big = small.parent.parent / "spisccc26" / "course11"
    (big / "audio").mkdir(parents=True)
    (big / "course.yaml").write_text('course_number: "11"\n', encoding="utf-8")
    (big / "audio" / "big.mp3").write_bytes(b"M" * 500000)

    spaces = library_survey(tmp_path / "library")
    assert [s.course_dir for s in spaces] == [big, small]


# ---------------------------------------------------------------------------
# Packets: delete, archive, or both
# ---------------------------------------------------------------------------

def packets(tmp_path: Path, count: int = 3) -> Path:
    directory = tmp_path / "packets"
    directory.mkdir(parents=True, exist_ok=True)
    for n in range(count):
        (directory / f"course_2026-09-0{n + 1}_1441_cpu-int8.md").write_text(
            "# packet\n" * 200, encoding="utf-8"
        )
        (directory / f"course_2026-09-0{n + 1}_1441_cpu-int8.json").write_text(
            "{}", encoding="utf-8"
        )
    return directory


def test_a_packet_folder_reports_what_is_in_it(tmp_path):
    directory = packets(tmp_path)
    space = packet_space(directory)
    assert len(space.markdown) == 3
    assert len(space.payloads) == 3
    assert space.count == 6
    assert space.bytes > 0


def test_archiving_writes_a_zip_and_keeps_the_originals(tmp_path):
    directory = packets(tmp_path)
    result = archive_packets(directory)

    assert result.archive is not None and result.archive.is_file()
    assert len(result.packed) == 6
    assert result.deleted == []
    assert all(p.exists() for p in result.packed), "archive alone deletes nothing"
    with zipfile.ZipFile(result.archive) as bundle:
        assert len(bundle.namelist()) == 6


def test_archiving_and_deleting_frees_the_space(tmp_path):
    directory = packets(tmp_path)
    result = archive_packets(directory, delete=True)

    assert len(result.deleted) == 6
    assert not any(p.exists() for p in result.deleted)
    assert result.bytes_after < result.bytes_before
    assert result.archive.is_file()


def test_only_what_the_archive_can_be_seen_to_hold_is_deleted(tmp_path, monkeypatch):
    """Read the members back from the file, not from the list just written."""
    directory = packets(tmp_path, count=1)
    real = zipfile.ZipFile

    class Forgetful(zipfile.ZipFile):
        def write(self, filename, arcname=None, **kwargs):
            if str(filename).endswith(".json"):
                return  # silently writes nothing, which is the fault to survive
            return super().write(filename, arcname=arcname, **kwargs)

    monkeypatch.setattr(zipfile, "ZipFile", Forgetful)
    result = archive_packets(directory, delete=True)
    monkeypatch.setattr(zipfile, "ZipFile", real)

    payload = directory / "course_2026-09-01_1441_cpu-int8.json"
    assert payload.exists(), "a packet the archive does not hold must not be deleted"
    assert any("not found in the archive" in reason for _, reason in result.failed)


def test_an_archive_never_overwrites_an_archive(tmp_path):
    directory = packets(tmp_path)
    first = archive_packets(directory).archive
    second = archive_packets(directory).archive
    assert first != second
    assert first.is_file() and second.is_file()


def test_archiving_nothing_is_not_an_error(tmp_path):
    directory = tmp_path / "packets"
    directory.mkdir()
    result = archive_packets(directory)
    assert result.archive is None
    assert result.packed == []


def test_deleting_packets_removes_exactly_what_was_named(tmp_path):
    directory = packets(tmp_path)
    doomed = sorted(directory.glob("*.md"))[:1]
    result = delete_packets(doomed, directory)
    assert len(result.deleted) == 1
    assert len(list(directory.glob("*.md"))) == 2
    assert len(list(directory.glob("*.json"))) == 3


@pytest.mark.parametrize("action", [archive_packets, delete_packets])
def test_a_path_outside_the_packet_folder_is_refused(tmp_path, action):
    directory = packets(tmp_path)
    outsider = tmp_path / "elsewhere.md"
    outsider.write_text("mine", encoding="utf-8")

    with pytest.raises(CleanupError, match="not in the packet folder"):
        if action is archive_packets:
            action(directory, paths=[outsider])
        else:
            action([outsider], directory)
    assert outsider.exists()


# ---------------------------------------------------------------------------

def test_sizes_are_written_the_way_people_say_them():
    assert human(512) == "512 B"
    assert human(2048) == "2 KB"
    assert human(5 * 1024 * 1024) == "5.0 MB"
    assert human(3 * 1024 * 1024 * 1024) == "3.0 GB"
