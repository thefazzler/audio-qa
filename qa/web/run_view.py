"""Starting a run, and watching one.

Everything here reads a job record and draws it. It starts runs through
qa.jobs.submit and never executes pipeline work itself, so closing this page,
or the whole web server, does not touch a run in progress.

The progress fragment reruns on a timer rather than the whole page, so a
watcher does not lose their scroll position every two seconds.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from qa.device import TRANSCRIBE_SUPPORTS_GPU, default_device, effective_device, probe
from qa.jobs import DONE, FAILED, RUNNING, FileJobStore, JobError, submit
from qa.library import list_courses, resolve_library
from qa.util import QAError

REFRESH_S = 2


def _store() -> FileJobStore:
    return FileJobStore()


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {rest:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


# ---------------------------------------------------------------------------
# Starting
# ---------------------------------------------------------------------------

def start_panel() -> None:
    st.subheader("Run a course")
    library = resolve_library().path
    courses = list_courses(library)
    if not courses:
        st.info(
            "No courses in the library yet. Bring one in from the Intake tab "
            "and it will appear here."
        )
        return

    labels = {c.label: c for c in courses}
    chosen = st.selectbox("Course", options=list(labels))
    course = labels[chosen]

    devices = probe()
    names = {d.key: d.display for d in devices}
    columns = st.columns(3)
    device = columns[0].radio(
        "Device",
        options=[d.key for d in devices],
        index=[d.key for d in devices].index(default_device(devices)),
        format_func=lambda key: names[key],
        horizontal=True,
    )
    model = columns[1].selectbox(
        "Model", options=["large-v3", "medium"], help="medium is faster and rougher"
    )
    force = columns[2].checkbox(
        "Re-transcribe everything",
        help=(
            "Off, only files whose contents changed are transcribed again. "
            "On, every topic is decoded from scratch."
        ),
    )

    used, note = effective_device(device)
    if note:
        st.caption(note)
    elif not TRANSCRIBE_SUPPORTS_GPU:
        st.caption("Device affects speed only, never the transcript.")

    if st.button("Start run", type="primary"):
        try:
            status = submit(
                course.path,
                {"device": used, "model": model, "force": force},
                _store(),
            )
        except QAError as exc:
            st.error(str(exc))
            return
        st.session_state.watching = status.id
        st.rerun()


# ---------------------------------------------------------------------------
# Watching
# ---------------------------------------------------------------------------

def _headline(status) -> None:
    if status.state == RUNNING:
        st.info(f"Running: **{status.stage or 'starting'}**")
    elif status.state == DONE:
        st.success(f"Finished in {_clock(status.elapsed_s)}")
    elif status.state == FAILED:
        st.error(f"Failed during {status.stage or 'startup'}")
        if status.error:
            st.code(status.error)
    else:
        st.info("Queued")


def _numbers(status) -> None:
    columns = st.columns(4)
    columns[0].metric(
        "Topics decoded", f"{status.decoded_count} of {status.topic_total}"
    )
    if status.reused_count:
        columns[0].caption(f"{status.reused_count} reused, unchanged since the last run")
    columns[1].metric(
        "Audio", f"{status.audio_done_s / 60:.0f} of {status.audio_total_s / 60:.0f} min"
    )
    columns[2].metric(
        "Speed",
        f"{status.rate_realtime:.2f}x realtime" if status.rate_realtime else "measuring",
    )
    columns[3].metric(
        "Time remaining", _clock(status.eta_s) if status.eta_s is not None else "measuring"
    )
    if status.eta_basis:
        st.caption(f"Estimate: {status.eta_basis}. Measured on this machine, this run.")


def _stage_row(status) -> None:
    from qa.cli import STAGE_NAMES

    done_names = STAGE_NAMES[: max(0, status.stage_index - 1)]
    marks = []
    for name in STAGE_NAMES:
        if name in done_names or status.state == DONE:
            marks.append(f"~~{name}~~")
        elif name == status.stage:
            marks.append(f"**{name}**")
        else:
            marks.append(name)
    st.caption(" → ".join(marks))


def _topics(status) -> None:
    if not status.topics:
        st.caption("Reading the delivered files...")
        return
    rows = []
    for topic in status.topics:
        rows.append(
            {
                "topic": topic.topic,
                "state": topic.state,
                "audio": f"{topic.duration_s / 60:.1f} min",
                "decode": f"{topic.decode_seconds:.0f}s" if topic.decode_seconds else "",
                "words": topic.words or "",
                "wpm": topic.wpm or "",
                "coverage": (
                    f"{topic.coverage * 100:.2f}%" if topic.coverage is not None else ""
                ),
                "differences": (
                    "outline only"
                    if not topic.scripted and topic.state == "aligned"
                    else ("" if topic.discrepancies is None else topic.discrepancies)
                ),
                "listen": topic.listen_items or "",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)
    if status.state == RUNNING:
        st.caption(
            "Results appear per topic as each one finishes, so early topics can "
            "be read while later ones are still decoding."
        )


def _draw(status) -> None:
    _headline(status)
    if status.topic_total:
        st.progress(status.topic_done / status.topic_total)
    _stage_row(status)
    _numbers(status)
    _topics(status)
    for warning in status.warnings:
        st.warning(warning)


@st.fragment(run_every=REFRESH_S)
def _live(job_id: str) -> None:
    """Only this fragment reruns on the timer, so the page stays still."""
    try:
        status = _store().read(job_id)
    except JobError as exc:
        st.error(str(exc))
        return
    _draw(status)
    if status.state == DONE:
        st.caption(
            "Next: the packet is ready for the judgment step. Open the Results "
            "tab."
        )


def watch_panel() -> None:
    store = _store()
    jobs = store.list()
    if not jobs:
        return

    st.subheader("Runs")
    labels = {}
    for job in jobs:
        when = "running" if job.state == RUNNING else job.state
        labels[f"{job.course_code or Path(job.course_dir).name} · {when} · {job.id}"] = job.id

    default = st.session_state.get("watching")
    keys = list(labels)
    index = 0
    if default:
        for position, key in enumerate(keys):
            if labels[key] == default:
                index = position
                break
    chosen = st.selectbox("Which run", options=keys, index=index)
    job_id = labels[chosen]
    st.session_state.watching = job_id

    status = store.read(job_id)
    st.caption(f"Course folder `{status.course_dir}`")
    if status.state == RUNNING:
        _live(job_id)
        st.caption(
            "This run is a separate process. Closing this tab, or the app, does "
            "not stop it."
        )
    else:
        _draw(status)
