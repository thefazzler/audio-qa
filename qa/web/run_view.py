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

from qa.device import DEVICE_NOTE, default_device, effective_device, probe
from qa.jobs import (
    DONE,
    FAILED,
    PENDING,
    RUNNING,
    FileJobStore,
    JobError,
    resolve,
    submit,
)
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
    st.caption(DEVICE_NOTE)

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
        # Not "Queued". Nothing is queued here: there is one run and it is
        # starting a process. "Queued" reads as waiting for something else to
        # finish, which is what a stuck progress view already looked like.
        st.info("Starting the run...")


def _numbers(status) -> None:
    """Only what a person waiting needs: how far along, and how long left.

    Device, model, measured rate and per topic decode times deliberately do not
    appear here. They live once, in the stats panel on the Results tab. The
    same numbers in two places drift, and a progress view is not the place to
    read telemetry.
    """
    columns = st.columns(2)
    columns[0].metric(
        "Topics decoded", f"{status.decoded_count} of {status.topic_total}"
    )
    if status.reused_count:
        columns[0].caption(
            f"{status.reused_count} reused, unchanged since the last run"
        )
    columns[1].metric(
        "Time remaining",
        _clock(status.eta_s) if status.eta_s is not None else "measuring",
    )
    if status.eta_s is None:
        st.caption("The estimate appears once the first topic has finished.")


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
                "coverage": (
                    f"{topic.coverage * 100:.2f}%" if topic.coverage is not None else ""
                ),
                # Strings throughout. A column that mixes integers with
                # "outline only" has no type Arrow can settle on, and every
                # page refresh printed a pyarrow traceback saying so. The
                # column is prose either way; making that explicit is both
                # quieter and more honest than a column that is a number
                # except when it is not.
                "differences": (
                    "outline only"
                    if not topic.scripted and topic.state == "aligned"
                    else ("" if topic.discrepancies is None else str(topic.discrepancies))
                ),
                "listen": str(topic.listen_items) if topic.listen_items else "",
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)
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
    store = _store()
    try:
        status = resolve(store.read(job_id), store)
    except JobError as exc:
        st.error(str(exc))
        return
    _draw(status)
    if status.state == DONE:
        st.caption(
            "Finished. The checks, the listen list and the packet are on the "
            "Results tab."
        )


def live_panel(job_id: str) -> None:
    """One run's progress, for any page that wants to show it.

    The intake page uses this so that starting a run lands on the run, rather
    than on a form that looks idle.
    """
    store = _store()
    try:
        status = resolve(store.read(job_id), store)
    except JobError as exc:
        st.error(str(exc))
        return
    _panel(status)


def should_refresh(status) -> bool:
    """Whether this run could still change, and so needs the live fragment.

    The refreshing fragment used to be armed only for RUNNING. A job submitted
    a moment ago is PENDING, because the subprocess has not started yet and has
    not flipped it, so the page rendered once, statically, and never looked
    again: it said "Queued / Reading the delivered files..." while the run went
    all the way through and wrote its packet. PENDING is the state where the
    refresh matters most, and was the one state without it.

    A predicate rather than a branch inside the drawing code, because it is the
    thing that was wrong and a test can hold it without a browser.
    """
    return status.state not in {DONE, FAILED}


def _panel(status) -> None:
    """Draw a run, refreshing on a timer while it could still change."""
    if not should_refresh(status):
        _draw(status)
        return
    _live(status.id)
    st.caption(
        "This run is a separate process. Closing this tab, or the app, does "
        "not stop it."
    )


def run_label(job) -> str:
    """A run, described so two runs of one course are told apart.

    Course, when it started, what it ran on, how long it took and what it
    found. The picker used to say course, status and run id, which is the same
    label for every run of a course except for a hex string nobody can read.
    """
    import datetime

    course = job.course_code or Path(job.course_dir).name
    started = (
        datetime.datetime.fromtimestamp(job.started_at).strftime("%Y-%m-%d %H:%M")
        if job.started_at
        else "not started"
    )
    # A run that has not reached the transcribe stage does not know its device
    # yet, and "device unknown · 0s" describes the label's ignorance rather
    # than the run's state. Say what is happening instead.
    if job.state == PENDING and not job.device_used:
        return " · ".join([course, started, "starting"])

    device = job.device_used or job.device_requested or "device not recorded"
    if job.compute_type:
        device = f"{device} {job.compute_type}"

    parts = [course, started, device]
    # Stale before running: a job whose process died still says RUNNING in its
    # record, and calling that "running" is the one thing this label must not
    # do, because it is what makes someone wait for a run that is not there.
    if job.stale:
        parts.append("abandoned")
    elif job.state == RUNNING:
        parts.append(f"running, {_clock(job.elapsed_s)} so far")
    elif job.state == FAILED:
        parts.append("failed")
    else:
        parts.append(_clock(job.elapsed_s))

    if job.state == DONE:
        found = sum(t.discrepancies or 0 for t in job.topics)
        parts.append(f"{found} difference{'' if found == 1 else 's'}")
    if job.reviewed_by:
        parts.append(job.reviewed_by)
    return " · ".join(parts)


def pick_index(keys: list[str], labels: dict[str, str], watching: str | None) -> int:
    """Which run the picker should open on.

    The run this session most recently started, when it is still in the list;
    otherwise the newest, because the list is newest first and "the one I just
    did" is what somebody opening this tab is looking for. Never an arbitrary
    position: a picker that opens on a run from last week, with no indication
    that it has, is how "Run it now" appeared to do nothing.
    """
    if watching:
        for position, key in enumerate(keys):
            if labels[key] == watching:
                return position
    return 0


def watch_panel() -> None:
    store = _store()
    jobs = [resolve(job, store) for job in store.list()]
    if not jobs:
        return

    st.subheader("Runs")
    labels: dict[str, str] = {}
    for job in jobs:
        label = run_label(job)
        # Two runs a minute apart on one device would collide. The run id is
        # the tiebreaker, not the label.
        while label in labels:
            label += " "
        labels[label] = job.id

    keys = list(labels)
    index = pick_index(keys, labels, st.session_state.get("watching"))
    chosen = st.selectbox(
        "Which run",
        options=keys,
        index=index,
        help="Course, start time, device, duration, differences found, reviewer.",
    )
    job_id = labels[chosen]
    st.session_state.watching = job_id

    status = resolve(store.read(job_id), store)
    st.caption(f"Run `{status.id}`, course folder `{status.course_dir}`")
    _panel(status)
