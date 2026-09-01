"""The intake page.

One job: take a pile of files from wherever the browser dropped them and turn
them into a course in the library, verified. Everything the filenames carry is
shown for confirmation rather than typed. The form asks only what a filename
cannot answer.

No pipeline logic lives here. This page calls qa.intake, qa.library and
qa.device and does nothing those modules could not do without it. That is the
test of the layering: if moving this app to a server would change only this
file, the split is right.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from qa.device import TRANSCRIBE_SUPPORTS_GPU, default_device, effective_device, probe
from qa.intake import (
    IntakeForm,
    IntakeError,
    find_recent_deliveries,
    ingest_selection,
    read_selection,
    remove_originals,
)
from qa.library import (
    ENV_VAR,
    list_courses,
    resolve_library,
    set_library,
)
from qa.util import QAError

PAGE_TITLE = "Audio QA"


def _init_state() -> None:
    st.session_state.setdefault("paths", [])
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("removed", None)
    st.session_state.setdefault("watching", None)


@st.cache_data(show_spinner=False)
def _devices():
    """Probed once per session; hardware does not change while the app runs."""
    return probe()


# ---------------------------------------------------------------------------
# Sidebar: where things live, and what this machine can do
# ---------------------------------------------------------------------------

def _sidebar() -> None:
    st.sidebar.header("Library")
    resolution = resolve_library()
    st.sidebar.write(f"`{resolution.path}`")
    explanation = {
        "argument": "set for this run",
        "environment": f"set by {ENV_VAR}",
        "settings": "saved setting",
        "default": "default location for this machine",
    }[resolution.source]
    st.sidebar.caption(explanation)

    courses = list_courses(resolution.path)
    st.sidebar.caption(
        f"{len(courses)} course{'' if len(courses) == 1 else 's'} in the library"
    )

    with st.sidebar.expander("Change location"):
        st.caption(
            "Courses are stored outside the code, so nothing here is ever "
            "committed to a repository by accident."
        )
        typed = st.text_input("Library folder", value=str(resolution.path))
        if st.button("Save location"):
            try:
                saved = set_library(Path(typed))
                st.success(f"Library set to {saved}")
                st.rerun()
            except OSError as exc:
                st.error(f"Could not save that location: {exc}")

    st.sidebar.header("This machine")
    for device in _devices():
        if device.available:
            st.sidebar.write(f"**{device.label}** available")
            if device.detail:
                st.sidebar.caption(device.detail)
        else:
            st.sidebar.write(f"~~{device.label}~~ unavailable")
            st.sidebar.caption(device.reason)


# ---------------------------------------------------------------------------
# Choosing the files
# ---------------------------------------------------------------------------

def _choose_files() -> None:
    st.subheader("1. Choose the delivered files")
    st.caption(
        "The storyboard and every narration file, from wherever you downloaded "
        "them. They are copied into the library; the originals are left alone."
    )

    from qa.web import picker

    columns = st.columns([1, 1, 2])
    if columns[0].button("Browse", type="primary", disabled=not picker.available()):
        chosen, error = picker.pick_files()
        if error:
            st.error(error)
        elif chosen:
            st.session_state.paths = [str(p) for p in chosen]
            st.session_state.result = None

    if columns[1].button("Clear"):
        st.session_state.paths = []
        st.session_state.result = None

    if not picker.available():
        st.info(
            "This machine has no native file dialog, so paste full paths below "
            "instead, one per line."
        )

    with st.expander("Or paste paths", expanded=not picker.available()):
        pasted = st.text_area("One path per line", height=120)
        if st.button("Use these paths") and pasted.strip():
            st.session_state.paths = [
                line.strip().strip('"') for line in pasted.splitlines() if line.strip()
            ]
            st.session_state.result = None

    _suggestions()


def _suggestions() -> None:
    with st.expander("Find recent course files"):
        st.caption(
            "Looks in your usual download folders for files named like a "
            "delivery. A suggestion only: nothing is used until you choose it."
        )
        if st.button("Look for recent deliveries"):
            try:
                found = find_recent_deliveries()
            except QAError as exc:
                st.error(str(exc))
                found = []
            if not found:
                st.write("Nothing that looks like a course delivery turned up.")
            for suggestion in found:
                label = (
                    f"{suggestion.course_code}: {len(suggestion.media)} files, "
                    f"topics {', '.join(suggestion.topics)}"
                )
                if st.button(f"Use {label}", key=f"use-{suggestion.course_code}"):
                    paths = [str(m.path) for m in suggestion.media]
                    if suggestion.storyboard:
                        paths.append(str(suggestion.storyboard))
                    st.session_state.paths = paths
                    st.session_state.result = None
                    st.rerun()


# ---------------------------------------------------------------------------
# What the filenames say
# ---------------------------------------------------------------------------

def _show_derived(selection) -> None:
    st.subheader("2. Confirm what the filenames say")
    columns = st.columns(4)
    columns[0].metric("Learning path", selection.learning_path)
    columns[1].metric("Course", selection.course_number)
    columns[2].metric("Topics", len(selection.media))
    columns[3].metric("Storyboard", "yes" if selection.storyboard else "missing")

    st.write(f"Course code `{selection.course_code}`")
    st.write("Topics found: " + ", ".join(f"`{t}`" for t in selection.topics))

    if selection.storyboard is None:
        st.warning(
            "No storyboard was selected. The pipeline needs exactly one .pptx "
            "before it can align anything."
        )
    if selection.ignored:
        st.caption(
            "Ignored, neither storyboard nor media: "
            + ", ".join(p.name for p in selection.ignored)
        )

    with st.expander("Files"):
        st.table(
            [
                {
                    "topic": m.topic,
                    "file": m.name,
                    "type": m.container,
                    "video": "yes" if m.is_video else "",
                }
                for m in selection.media
            ]
        )


# ---------------------------------------------------------------------------
# The form
# ---------------------------------------------------------------------------

def _form(selection) -> IntakeForm | None:
    st.subheader("3. The questions the filenames cannot answer")

    with st.form("intake"):
        project_type = st.selectbox(
            "Project type",
            options=["VENDOR", "CGT"],
            help="VENDOR routes findings to an edit sheet; CGT to a remediation plan.",
        )

        video_topics = selection.video_topics
        if video_topics:
            st.caption(
                "Topic "
                + ", ".join(video_topics)
                + " arrived as video, which often means a screen capture demo "
                "whose slides carry an outline rather than a script. Being a "
                "video and being outline-only are separate facts, so confirm it "
                "rather than assuming."
            )
        unscripted = st.multiselect(
            "Outline-only topics",
            options=selection.topics,
            default=[],
            help=(
                "Topics whose slides carry an outline rather than verbatim "
                "narration. They are excluded from word-level alignment and "
                "their transcripts run at full length in the packet."
            ),
        )

        devices = _devices()
        labels = {d.key: d.display for d in devices}
        usable = [d.key for d in devices if d.available]
        unusable = [d for d in devices if not d.available]
        device = st.radio(
            "Device",
            options=[d.key for d in devices],
            index=[d.key for d in devices].index(default_device(devices)),
            format_func=lambda key: labels[key],
            horizontal=True,
        )
        for missing in unusable:
            st.caption(f"{missing.label} unavailable: {missing.reason}")
        st.caption(
            "Device affects speed only. The same audio produces the same "
            "transcript either way."
        )
        if not TRANSCRIBE_SUPPORTS_GPU:
            st.caption("Transcription runs on CPU in this build.")

        reviewed_by = st.text_input(
            "Reviewed by",
            help="Recorded with the run and carried into the packet.",
        )
        notes = st.text_area("Notes", height=80, placeholder="Optional")

        submitted = st.form_submit_button("Submit", type="primary")

    if not submitted:
        return None
    _ = usable
    return IntakeForm(
        project_type=project_type,
        unscripted_topics=tuple(unscripted),
        device=device,
        reviewed_by=reviewed_by,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# The outcome
# ---------------------------------------------------------------------------

def _show_result(result) -> None:
    st.subheader("Ingested")
    if result.resubmission:
        st.info(
            "This course was already in the library, so this is a re-submission. "
            "Only files whose contents changed will be transcribed again."
        )
    st.success(f"Course folder: `{result.course_dir}`")

    verified = sum(1 for c in result.copied if c.verified)
    st.write(
        f"{verified} of {len(result.copied)} files copied and verified by hash "
        "against the originals."
    )

    if result.changed_topics:
        st.write("New or changed topics: " + ", ".join(sorted(result.changed_topics)))
    if result.unchanged_topics:
        st.write("Unchanged topics: " + ", ".join(sorted(result.unchanged_topics)))
    for warning in result.warnings:
        st.warning(warning)

    with st.expander("Copied files"):
        st.table(
            [
                {
                    "file": c.destination.name,
                    "from": str(c.source.parent),
                    "sha256": c.sha256[:16],
                    "verified": "yes" if c.verified else "NO",
                }
                for c in result.copied
            ]
        )

    st.subheader("Next")
    st.write("The course is in the library and ready to run.")
    if st.button("Run it now", type="primary"):
        from qa.jobs import submit
        from qa.device import default_device, effective_device

        used, _ = effective_device(default_device())
        try:
            status = submit(result.course_dir, {"device": used}, None)
        except QAError as exc:
            st.error(str(exc))
        else:
            st.session_state.watching = status.id
            st.success(f"Run {status.id} started. Open the Runs tab to watch it.")
    st.caption("Or from a terminal:")
    st.code(f"qa-run {result.course_dir}", language="bash")

    st.divider()
    st.caption(
        "The originals are still where you downloaded them. Nothing deletes "
        "them unless you ask."
    )
    if st.session_state.removed is None:
        if st.button("Delete the originals"):
            removed = remove_originals(result)
            st.session_state.removed = removed
            st.rerun()
    else:
        st.write(f"Deleted {len(st.session_state.removed)} original files.")


# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, page_icon="🎧", layout="wide")
    _init_state()

    st.title("Audio QA")
    st.caption(
        "Narration QA for course audio. Everything runs on this machine; audio "
        "never leaves it."
    )
    _sidebar()

    intake_tab, runs_tab = st.tabs(["Intake", "Runs"])
    with runs_tab:
        from qa.web.run_view import start_panel, watch_panel

        start_panel()
        st.divider()
        watch_panel()

    with intake_tab:
        _intake()


def _intake() -> None:
    _choose_files()

    paths = st.session_state.paths
    if not paths:
        st.info("Choose the delivered files to begin.")
        return

    try:
        selection = read_selection([Path(p) for p in paths])
    except QAError as exc:
        st.error(str(exc))
        return

    _show_derived(selection)

    if st.session_state.result is not None:
        _show_result(st.session_state.result)
        return

    form = _form(selection)
    if form is None:
        return

    requested, note = effective_device(form.device)
    if note:
        st.info(note)

    try:
        with st.spinner("Copying and verifying..."):
            result = ingest_selection(selection, form)
    except IntakeError as exc:
        st.error(str(exc))
        return
    except QAError as exc:
        st.error(str(exc))
        return

    st.session_state.result = result
    st.session_state.removed = None
    st.rerun()


main()
