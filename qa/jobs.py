"""Detached course runs, and the progress a person can watch.

A course takes tens of minutes. That cannot happen inside a web request, and it
must not die when someone closes the tab. So a run is a separate process with
an id, and its status is a small record on disk that any process can read. A
second person can watch a run they did not start.

Progress comes from the pipeline's own outputs, not from instrumenting the
pipeline. The stages already write one transcript file per topic, each carrying
its decode time and audio duration, so a watcher that reads those files knows
how far along the run is and how fast this machine is actually going. Nothing
in qa/ was modified to make this work.

Two things are deliberate about what gets reported.

The primary progress is per topic, not per stage. Eight stage ticks look frozen
for the twenty minutes transcription takes, which is the only part anyone is
waiting for.

The ETA is measured, never assumed. The first completed topic gives this
machine's real decode rate, and every topic after it refines the estimate. A
hardcoded rate would be wrong on a slower laptop today and wrong again when the
GPU path lands.

The store is a file per job, because this is a local single user tool. It sits
behind an interface so a real queue can replace it without the pages noticing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from .library import user_data_dir
from .util import QAError, read_json, write_json

JOBS_DIR = "jobs"
POLL_S = 1.0

# A run whose record has not been touched for this long, while still claiming
# to be running, is not running: its process died. The watcher writes every
# second, so this is generous by two orders of magnitude.
STALE_AFTER_S = 120

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


class JobError(QAError):
    pass


# ---------------------------------------------------------------------------
# Is that process still there?
# ---------------------------------------------------------------------------
# Twenty lines against a dependency, the same trade library.py makes. The
# alternative to asking the operating system is a timeout, and a timeout
# answers "has it been quiet for a while", which is not the question.

def process_alive(pid: int) -> bool:
    """Whether the process that was running a job still exists.

    Deliberately biased towards saying yes. A recycled pid makes a dead job
    look alive, which costs a wait; the opposite error declares a running
    course dead and invites a second run on the same folder, which is the one
    thing the in-progress guard exists to prevent.

    Never uses os.kill on Windows: there, os.kill with a signal other than the
    two console events calls TerminateProcess, so the liveness probe would kill
    the run it was asking about.
    """
    if not pid:
        return False
    if sys.platform == "win32":
        import ctypes

        SYNCHRONIZE = 0x00100000
        STILL_RUNNING = 0x00000102  # WAIT_TIMEOUT: handle not signalled yet
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == STILL_RUNNING
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Somebody else's process now. Not ours, but it is alive, and the
        # cautious reading is that we cannot prove our run has ended.
        return True
    except OSError:
        return True
    return True


def wrote_a_packet(course_dir: str | Path, since: float) -> bool:
    """Whether a packet was produced for this course after the run started.

    The evidence that a run finished does not have to come from the run. It
    reached the last stage and wrote a file; that is a fact about the world,
    and it outranks a status record that never got its final write.
    """
    marker = Path(course_dir) / "qa_out" / "packet_index.json"
    try:
        return marker.stat().st_mtime >= (since - 1.0)
    except OSError:
        return False


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------

@dataclass
class TopicProgress:
    """One topic's journey, filled in as the pipeline's outputs appear."""

    topic: str
    duration_s: float = 0.0
    # pending  -> not decoded yet
    # cached   -> a current transcript from an earlier run; not decoded now
    # transcribed / aligned -> produced by this run
    state: str = "pending"
    decode_seconds: float | None = None
    words: int | None = None
    wpm: float | None = None
    low_confidence_share: float | None = None
    anomalies: int = 0
    decoded_this_run: bool = False
    coverage: float | None = None
    discrepancies: int | None = None
    listen_items: int | None = None
    scripted: bool = True


@dataclass
class JobStatus:
    id: str
    course_dir: str
    course_code: str = ""
    state: str = PENDING
    stage: str = ""
    stage_index: int = 0
    stage_total: int = 0
    topics: list[TopicProgress] = field(default_factory=list)
    audio_total_s: float = 0.0
    audio_done_s: float = 0.0
    rate_realtime: float | None = None
    device_requested: str = ""
    device_used: str = ""
    compute_type: str = ""
    reviewed_by: str = ""
    fallback_reason: str = ""
    # The process actually doing the work. A record is a claim about a run;
    # this is how a reader checks the claim against the operating system
    # instead of against a timeout. 0 on records written before this existed.
    pid: int = 0
    eta_s: float | None = None
    eta_basis: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    options: dict = field(default_factory=dict)
    started_at: float = 0.0
    updated_at: float = 0.0
    finished_at: float | None = None

    @property
    def topic_total(self) -> int:
        return len(self.topics)

    @property
    def topic_done(self) -> int:
        return sum(1 for t in self.topics if t.state != "pending")

    @property
    def decoded_count(self) -> int:
        """Topics this run actually decoded, as opposed to reused."""
        return sum(1 for t in self.topics if t.decoded_this_run)

    @property
    def reused_count(self) -> int:
        """Topics whose transcript was still current and was kept.

        Worth showing separately: "10 of 10 transcribed" on a run that decoded
        nothing is true and misleading. What a person wants to know is how much
        work this run is doing.
        """
        return sum(
            1 for t in self.topics if t.state != "pending" and not t.decoded_this_run
        )

    @property
    def active(self) -> bool:
        """Running now, as opposed to finished or abandoned."""
        if self.state not in {PENDING, RUNNING}:
            return False
        return (time.time() - (self.updated_at or self.started_at)) < STALE_AFTER_S

    @property
    def stale(self) -> bool:
        """Claims to be running, but nothing has written to it in a long time."""
        return self.state in {PENDING, RUNNING} and not self.active

    @property
    def elapsed_s(self) -> float:
        end = self.finished_at or time.time()
        return max(0.0, end - self.started_at) if self.started_at else 0.0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["topic_total"] = self.topic_total
        data["topic_done"] = self.topic_done
        data["elapsed_s"] = round(self.elapsed_s, 1)
        data["decoded_count"] = self.decoded_count
        data["reused_count"] = self.reused_count
        data["active"] = self.active
        data["stale"] = self.stale
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "JobStatus":
        payload = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        payload["topics"] = [TopicProgress(**t) for t in data.get("topics", [])]
        return cls(**payload)


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

class JobStore(Protocol):
    """Where job records live.

    File backed here. A server would put a queue behind this same shape and
    nothing above would change.
    """

    def write(self, status: JobStatus) -> None: ...

    def read(self, job_id: str) -> JobStatus: ...

    def list(self) -> list[JobStatus]: ...


class FileJobStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else user_data_dir() / JOBS_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def log_path(self, job_id: str) -> Path:
        """Where the run's own output went.

        A detached run used to write to DEVNULL, so a process that died before
        it could record why left nothing at all behind. Whatever it managed to
        say is the only account of that failure there will ever be.
        """
        return self.root / f"{job_id}.log"

    def tail(self, job_id: str, lines: int = 25) -> str:
        try:
            text = self.log_path(job_id).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-lines:]).strip()

    def write(self, status: JobStatus) -> None:
        status.updated_at = time.time()
        # Written atomically: a page polling this file must never read half a
        # record, and on Windows it would fail to parse rather than block.
        target = self.path(status.id)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(status.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(target)

    def read(self, job_id: str) -> JobStatus:
        path = self.path(job_id)
        if not path.exists():
            raise JobError(f"No such job: {job_id}")
        for attempt in range(3):
            try:
                return JobStatus.from_dict(read_json(path))
            except ValueError:
                # Lost a race with a write on a platform without atomic
                # replace semantics. Reading again is cheaper than locking.
                time.sleep(0.05)
        raise JobError(f"Job record for {job_id} could not be read")

    def list(self) -> list[JobStatus]:
        found: list[JobStatus] = []
        for path in self.root.glob("*.json"):
            try:
                found.append(JobStatus.from_dict(read_json(path)))
            except (ValueError, OSError, TypeError):
                continue
        return sorted(found, key=lambda s: s.started_at or 0, reverse=True)


# ---------------------------------------------------------------------------
# Watching the pipeline's outputs
# ---------------------------------------------------------------------------

class ProgressWatcher:
    """Reads the pipeline's own files and turns them into progress.

    Deliberately a reader. The pipeline is not aware this exists, which is what
    keeps the engine free of reporting code.
    """

    def __init__(self, course_dir: Path, status: JobStatus, store: JobStore) -> None:
        self.course_dir = Path(course_dir)
        self.work = self.course_dir / "qa_work"
        self.status = status
        self.store = store
        self._lock = threading.Lock()
        # Anything older than this belongs to a previous run.
        self._run_start = status.started_at or time.time()
        # Last transcript mtime we successfully read, per topic.
        self._mtimes: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._script: dict | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.scan()

    def _loop(self) -> None:
        while not self._stop.wait(POLL_S):
            try:
                self.scan()
            except Exception:
                # A watcher must never take the run down with it. Progress is
                # a convenience; the pipeline's own outputs are the truth.
                continue

    # -- reporting ---------------------------------------------------------

    def set_stage(self, name: str, index: int, total: int) -> None:
        with self._lock:
            self.status.stage = name
            self.status.stage_index = index
            self.status.stage_total = total
        self.store.write(self.status)

    def scan(self) -> None:
        with self._lock:
            self._load_manifest()
            self._load_device()
            self._load_transcripts()
            self._load_alignments()
            self._recompute_eta()
        self.store.write(self.status)

    def _load_manifest(self) -> None:
        if self.status.topics:
            return
        path = self.work / "manifest.json"
        if not path.exists():
            return
        try:
            manifest = read_json(path)
        except (ValueError, OSError):
            return
        self.status.course_code = manifest.get("course_code", "")
        self.status.topics = [
            TopicProgress(
                topic=t["topic"],
                duration_s=t.get("duration_s", 0.0),
                scripted=t.get("scripted", True),
            )
            for t in manifest.get("topics", [])
        ]
        self.status.audio_total_s = manifest.get("total_duration_s", 0.0)

    def _load_device(self) -> None:
        """What device the run is actually using, including a fallback.

        Read from transcripts.json rather than from the job's options, because
        the options say what was asked for and only the pipeline knows what
        happened.
        """
        path = self.work / "transcripts.json"
        if not path.exists():
            return
        try:
            data = read_json(path)
        except (ValueError, OSError):
            return
        settings = data.get("settings") or {}
        self.status.device_requested = (
            data.get("requested_device") or settings.get("requested_device") or ""
        )
        self.status.device_used = data.get("device_used") or settings.get("device", "")
        self.status.compute_type = settings.get("compute_type", "")
        reason = data.get("fallback_reason") or ""
        if reason and reason != self.status.fallback_reason:
            self.status.fallback_reason = reason
            note = (
                f"GPU decode failed and the run continued on CPU: {reason}"
            )
            if note not in self.status.warnings:
                self.status.warnings.append(note)

    def _load_transcripts(self) -> None:
        """Count only what this run produced, plus what it is reusing.

        A transcript file left by an earlier run is not progress. Counting one
        put the bar at ten of ten before decoding had started, and the estimate
        at zero seconds while twenty minutes of work remained, which is exactly
        the false comfort per topic progress exists to prevent. File age
        against the job's start separates the two without the watcher needing
        to know anything about ASR settings.
        """
        for progress in self.status.topics:
            path = self.work / f"transcript_{progress.topic}.json"
            if not path.exists():
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            # Re-read whenever the file changes, not just once. A topic marked
            # cached at the start of a run and then re-decoded during it was
            # otherwise never looked at again, so a run that spent 74 seconds
            # decoding reported that it had decoded nothing.
            if progress.state != "pending" and self._mtimes.get(progress.topic) == mtime:
                continue
            try:
                data = read_json(path)
            except (ValueError, OSError):
                # Caught it mid-write. Do not record the mtime, so the next
                # scan tries again.
                continue
            self._mtimes[progress.topic] = mtime
            fresh = mtime >= self._run_start
            progress.state = "transcribed" if fresh else "cached"
            progress.decode_seconds = data.get("decode_seconds")
            progress.decoded_this_run = fresh
            progress.words = data.get("word_count")
            progress.low_confidence_share = data.get("low_confidence_share")
            progress.anomalies = len(data.get("anomalies") or [])
            duration = data.get("duration_s") or progress.duration_s
            if duration:
                progress.wpm = round((progress.words or 0) / (duration / 60.0), 1)

    def _load_alignments(self) -> None:
        """Align each finished transcript early, so results stream.

        This calls the pipeline's own align_topic, the same function the align
        stage calls, on the same inputs. It is a preview in timing only: the
        align stage still writes the authoritative files, and it cannot
        disagree with this because it is the same code. Without it a person
        waits out the whole decode before seeing anything about topic one.
        """
        if not any(
            t.state in {"transcribed", "cached"} for t in self.status.topics
        ):
            return
        if self._script is None:
            path = self.work / "script.json"
            if not path.exists():
                return
            try:
                self._script = {
                    t["topic"]: t for t in read_json(path).get("topics", [])
                }
            except (ValueError, OSError, KeyError):
                return

        from .align import align_topic

        for progress in self.status.topics:
            if progress.state not in {"transcribed", "cached"}:
                continue
            entry = self._script.get(progress.topic)
            transcript_path = self.work / f"transcript_{progress.topic}.json"
            if entry is None or not transcript_path.exists():
                continue
            try:
                transcript = read_json(transcript_path)
            except (ValueError, OSError):
                continue
            if not entry.get("scripted", True):
                progress.state = "aligned"
                progress.scripted = False
                continue
            try:
                result = align_topic(
                    entry["sentences"], transcript["words"], transcript["segments"]
                )
            except Exception:
                continue
            progress.state = "aligned"
            progress.coverage = result.get("coverage")
            progress.discrepancies = len(result.get("discrepancies", []))
            progress.listen_items = result.get("listen_items", 0)

    def _recompute_eta(self) -> None:
        """Rate measured on this machine, on this run, from finished topics."""
        # Only work this run actually did tells us how fast this machine is.
        finished = [
            t for t in self.status.topics
            if t.decoded_this_run and t.decode_seconds and t.duration_s
        ]
        done_audio = sum(t.duration_s for t in self.status.topics if t.state != "pending")
        self.status.audio_done_s = round(done_audio, 1)

        if not finished:
            self.status.rate_realtime = None
            self.status.eta_s = None
            self.status.eta_basis = "waiting for the first topic to finish"
            return

        audio = sum(t.duration_s for t in finished)
        decode = sum(t.decode_seconds or 0.0 for t in finished)
        rate = audio / decode if decode else None
        self.status.rate_realtime = round(rate, 2) if rate else None

        remaining = sum(t.duration_s for t in self.status.topics if t.state == "pending")
        if rate and remaining > 0:
            self.status.eta_s = round(remaining / rate, 1)
            self.status.eta_basis = (
                f"{len(finished)} of {len(self.status.topics)} topics measured at "
                f"{rate:.2f}x realtime, {remaining / 60:.1f} min of audio left"
            )
        else:
            self.status.eta_s = 0.0
            self.status.eta_basis = "every topic has been transcribed"


# ---------------------------------------------------------------------------
# Running one
# ---------------------------------------------------------------------------

def run_job(job_id: str, store: JobStore | None = None) -> int:
    """Execute a course run, reporting progress as the pipeline writes files."""
    from .cli import STAGES

    store = store or FileJobStore()
    status = store.read(job_id)
    status.state = RUNNING
    status.started_at = status.started_at or time.time()
    status.stage_total = len(STAGES)
    store.write(status)

    course_dir = Path(status.course_dir)
    watcher = ProgressWatcher(course_dir, status, store)
    options = status.options or {}

    # The run's options reach the pipeline the same way the CLI passes them.
    from . import cli as cli_module

    cli_module._ASR_OVERRIDES = {
        "model": options.get("model"),
        "cpu_threads": options.get("threads"),
        "device": options.get("device"),
    }
    cli_module._ONLY_TOPICS = options.get("topics")
    cli_module._RUN_DATE = options.get("date")
    cli_module._OUTPUT_DIR = options.get("output")
    # The packet is named for when the run began, not for when its last stage
    # finished, so the job's own start time is what the stage must see.
    cli_module._RUN_STARTED = status.started_at or time.time()

    watcher.start()
    try:
        for index, stage in enumerate(STAGES, start=1):
            watcher.set_stage(stage.name, index, len(STAGES))
            result = stage.run(course_dir, bool(options.get("force")))
            for warning in result.get("warnings", []) or []:
                if warning not in status.warnings:
                    status.warnings.append(warning)
        status.state = DONE
    except QAError as exc:
        status.state = FAILED
        status.error = str(exc)
    except Exception as exc:  # a crash must still leave a readable record
        status.state = FAILED
        status.error = f"{type(exc).__name__}: {exc}"
    finally:
        watcher.stop()
        status.finished_at = time.time()
        store.write(status)

    return 0 if status.state == DONE else 1


ABANDONED = (
    "The run's process is gone and it never recorded how it ended. "
    "Whatever it managed to print before it died is below."
)


def resolve(status: JobStatus, store: JobStore | None = None) -> JobStatus:
    """What is actually true about a job now, rather than what it last wrote.

    A status record is a claim a process makes about itself, and a process that
    dies stops updating its claim. Read literally, a killed run says PENDING or
    RUNNING for ever, and every reader of it waits for something that is not
    coming. That is the same class of failure as a transcriber that truncates a
    file and does not say so, which is what this whole codebase is built
    against, so the record is checked rather than believed.

    Three outcomes, in order of what the evidence supports:

      the process is alive          nothing to correct; it is still running
      gone, but a packet exists     it finished and lost its last write
      gone, with no packet          it died; say so, with what it printed

    Heals the record when it corrects one, so the picker, the progress view and
    the in-progress guard cannot disagree with each other about one run.
    """
    if status.state in {DONE, FAILED}:
        return status
    if process_alive(status.pid):
        return status
    if status.pid == 0 and status.active:
        # A record written before pids were tracked, or one whose process has
        # not been spawned yet. Fall back to the timeout it was written under.
        return status

    if wrote_a_packet(status.course_dir, status.started_at):
        status.state = DONE
        status.finished_at = status.finished_at or time.time()
        note = (
            "This run finished and produced a packet, but its process ended "
            "before it could record that. The packet is the evidence."
        )
        if note not in status.warnings:
            status.warnings.append(note)
    else:
        status.state = FAILED
        status.finished_at = status.finished_at or time.time()
        printed = store.tail(status.id) if store is not None else ""
        status.error = status.error or (
            ABANDONED + (f"\n\n{printed}" if printed else "\n\n(it printed nothing)")
        )

    if store is not None:
        try:
            store.write(status)
        except OSError:
            # Healing the record is a convenience. Reporting the truth to the
            # caller is not, and must not depend on the disk being writable.
            pass
    return status


def _reviewer(course_dir: Path) -> str:
    """Who took this course in, from course.yaml, for the run listing.

    Read here rather than passed in, because intake already recorded it and a
    second copy typed at run time would be a second answer to one question.
    Absence is normal on a course scaffolded from the command line.
    """
    import yaml

    path = Path(course_dir) / "course.yaml"
    if not path.exists():
        return ""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("reviewed_by") or "").strip()


def submit(
    course_dir: Path, options: dict | None = None, store: JobStore | None = None
) -> JobStatus:
    """Start a detached run and return immediately with its record.

    A subprocess rather than a thread: the run has to survive the tab closing
    and the web server restarting, and a thread survives neither.
    """
    store = store or FileJobStore()
    course_dir = Path(course_dir)
    if not (course_dir / "course.yaml").exists():
        raise JobError(
            f"{course_dir} is not an ingested course.\n"
            "  Submit it through intake first."
        )

    # Two runs on one course would overwrite each other's intermediates and
    # each keep invalidating the other's work. Found the hard way: a forced run
    # and a second run on the same folder both re-transcribed the whole course
    # and neither finished.
    for existing in store.list():
        if Path(existing.course_dir) != course_dir:
            continue
        # Against the process, not against the record. A job whose process has
        # died still claims to be running, and refusing a new run on the
        # strength of a dead one leaves the course unrunnable until somebody
        # deletes a file they have never heard of.
        if resolve(existing, store).state in {DONE, FAILED}:
            continue
        raise JobError(
            f"A run for this course is already in progress ({existing.id}, "
            f"{existing.stage or 'starting'}).\n"
            "  Wait for it to finish, or watch it from the Runs list. Two "
            "runs on one course folder would overwrite each other."
        )

    status = JobStatus(
        id=uuid.uuid4().hex[:12],
        course_dir=str(course_dir),
        state=PENDING,
        options=dict(options or {}),
        reviewed_by=_reviewer(course_dir),
        started_at=time.time(),
    )
    store.write(status)

    root = getattr(store, "root", None)
    command = [sys.executable, "-m", "qa.jobs", "run", status.id]
    if root:
        command += ["--store", str(root)]

    creationflags = 0
    if sys.platform == "win32":
        # Detach from the console so closing the terminal that started the web
        # app does not kill a run in progress.
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    # Everything the run prints goes to a file rather than to DEVNULL. A
    # detached process that dies before it can record why used to leave nothing
    # at all behind, and "it failed" with no reason is barely better than the
    # failure itself.
    log = getattr(store, "log_path", None)
    sink = subprocess.DEVNULL
    if log is not None:
        try:
            sink = open(log(status.id), "wb")
        except OSError:
            sink = subprocess.DEVNULL

    try:
        process = subprocess.Popen(
            command,
            stdout=sink,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=(sys.platform != "win32"),
            cwd=str(Path(__file__).resolve().parent.parent),
            env=os.environ.copy(),
        )
    except OSError as exc:
        status.state = FAILED
        status.error = f"Could not start the run: {exc}"
        store.write(status)
        raise JobError(status.error) from exc
    finally:
        if sink is not subprocess.DEVNULL:
            sink.close()

    # Recorded before returning, so the page that is about to render this run
    # can already check it against the operating system.
    status.pid = process.pid
    store.write(status)
    return status


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="qa-jobs")
    sub = parser.add_subparsers(dest="command", required=True)
    runner = sub.add_parser("run", help="execute a job by id")
    runner.add_argument("job_id")
    runner.add_argument("--store", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.command == "run":
        return run_job(args.job_id, FileJobStore(args.store))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
