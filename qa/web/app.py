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

from qa.device import DEVICE_NOTE, default_device, effective_device, probe
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
    OUTPUT_ENV_VAR,
    list_courses,
    resolve_library,
    resolve_output,
    set_library,
    set_output,
)
from qa.script_source import (
    DOCX_BUS,
    FREEFORM,
    NONE,
    OUTLINE,
    SOURCE_LABEL,
    SOURCE_SUFFIX,
    VERBATIM,
    default_source,
)
from qa.util import QAError

PAGE_TITLE = "Audio QA"


def _init_state() -> None:
    st.session_state.setdefault("paths", [])
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("removed", None)
    st.session_state.setdefault("watching", None)
    st.session_state.setdefault("started_here", None)


@st.cache_data(show_spinner=False)
def _devices():
    """Probed once per session; hardware does not change while the app runs."""
    return probe()


# ---------------------------------------------------------------------------
# Sidebar: where things live, and what this machine can do
# ---------------------------------------------------------------------------

SOURCE_NOTE = {
    "argument": "set for this run",
    "environment": "set by {var}",
    "settings": "saved setting",
    "default": "default location for this machine",
}


def _open_button(path: Path, key: str) -> None:
    """A button that shows a folder in the machine's own file browser."""
    from qa.web import reveal

    if not reveal.available():
        return
    if st.sidebar.button("Open folder", key=key):
        error = reveal.open_folder(path)
        if error:
            st.sidebar.warning(error)


def _sidebar() -> None:
    st.sidebar.header("Library")
    resolution = resolve_library()
    st.sidebar.write(f"`{resolution.path}`")
    st.sidebar.caption(SOURCE_NOTE[resolution.source].format(var=ENV_VAR))
    _open_button(resolution.path, "open-library")

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

    st.sidebar.header("Packets")
    output = resolve_output()
    st.sidebar.write(f"`{output.path}`")
    st.sidebar.caption(SOURCE_NOTE[output.source].format(var=OUTPUT_ENV_VAR))
    _open_button(output.path, "open-output")
    st.sidebar.caption(
        "Finished packets land here, named by course, time and device, and are "
        "never overwritten, so this folder is the run history. Working files "
        "stay in the library."
    )

    with st.sidebar.expander("Change packet folder"):
        typed_out = st.text_input("Packet folder", value=str(output.path))
        if st.button("Save packet folder"):
            try:
                saved = set_output(Path(typed_out))
                st.success(f"Packets will be written to {saved}")
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
        "The script document and every narration file, from wherever you "
        "downloaded them. A VENDOR course's script is the PowerPoint "
        "storyboard; a CGT course's is the Word script in the BUS Writing "
        "Template. They are copied into the library; the originals are left "
        "alone."
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
        st.session_state.started_here = None

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
    columns[3].metric(
        "Script documents", len(selection.documents) + bool(selection.storyboard)
    )

    st.write(f"Course code `{selection.course_code}`")
    st.write("Topics found: " + ", ".join(f"`{t}`" for t in selection.topics))

    if selection.ignored:
        st.caption(
            "Ignored, neither a script document nor media: "
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

def _script_source_panel(selection, project_type: str) -> bool:
    """Confirm which document carries the script. Detected, not asked.

    Once the project type is known the answer is already in the selection: a
    VENDOR course's script is the storyboard, a CGT course's is the Word
    document. When the expected one is absent this says so and stops, because
    reading the other one would align the whole course against text that is
    not its script.
    """
    source = default_source(project_type)
    document = selection.script_document(project_type)
    if document is None:
        st.error(
            f"A {project_type} course's script is a {SOURCE_SUFFIX[source]} "
            f"({SOURCE_LABEL[source]}), and exactly one was not found among the "
            "files you chose. Add it and submit again."
        )
        return False
    st.success(f"Script source: `{document.name}` ({SOURCE_LABEL[source]})")
    return True


def _script_controls(selection, project_type: str) -> dict[str, tuple[str, str]]:
    """Per-topic script state, for the topics that are not verbatim.

    Hidden for CGT: a BUS script is verbatim for every topic including the
    demos, so there is nothing to choose. Shown for VENDOR, where a demo may be
    scripted in the deck, outlined in the deck, scripted in a document of its
    own, or not scripted anywhere.
    """
    if default_source(project_type) == DOCX_BUS:
        st.caption(
            "Every topic of a CGT course is verbatim, demos included, so there "
            "is nothing to set per topic."
        )
        return {}

    candidates = [p.name for p in selection.freeform_candidates(project_type)]
    st.caption(
        "Every topic is verbatim unless you say otherwise. Container format is "
        "not a hint: topics normally arrive as mp4 on both project types, and a "
        "demo may be scripted, outlined, or not scripted at all."
    )
    chosen: dict[str, tuple[str, str]] = {}
    for topic in selection.topics:
        columns = st.columns([1, 2, 3])
        columns[0].write(f"`{topic}`")
        state = columns[1].selectbox(
            "script",
            options=[VERBATIM, OUTLINE, NONE, FREEFORM],
            key=f"script-{topic}",
            label_visibility="collapsed",
        )
        document = ""
        if state == FREEFORM:
            if candidates:
                document = columns[2].selectbox(
                    "document",
                    options=candidates,
                    key=f"script-file-{topic}",
                    label_visibility="collapsed",
                )
            else:
                columns[2].caption(
                    "No document was selected that could be this topic's script. "
                    "Add a .docx or .txt above."
                )
        if state != VERBATIM:
            chosen[topic] = (state, document)
    return chosen


def _form(selection) -> IntakeForm | None:
    st.subheader("3. The questions the filenames cannot answer")

    project_type = st.selectbox(
        "Project type",
        options=["VENDOR", "CGT"],
        help="VENDOR routes findings to an edit sheet; CGT to a remediation plan.",
    )
    ready = _script_source_panel(selection, project_type)

    st.write("**Script per topic**")
    topic_scripts = _script_controls(selection, project_type)

    with st.form("intake"):
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
        st.caption(DEVICE_NOTE)

        reviewed_by = st.text_input(
            "Reviewed by",
            help="Recorded with the run and carried into the packet.",
        )
        notes = st.text_area("Notes", height=80, placeholder="Optional")

        submitted = st.form_submit_button("Submit", type="primary", disabled=not ready)

    if not submitted:
        return None
    _ = usable
    return IntakeForm(
        project_type=project_type,
        unscripted_topics=(),
        device=device,
        reviewed_by=reviewed_by,
        notes=notes,
        topic_scripts=topic_scripts,
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

    started = st.session_state.get("started_here")
    if started:
        # Show the run this page just started, here, rather than telling
        # someone to go and find it. Clicking "Run it now" and then landing on
        # a form that looks idle invites a second click, which the
        # one-run-per-course guard then has to catch.
        from qa.web.run_view import live_panel

        st.success(f"Run {started} is under way.")
        live_panel(started)
        st.caption(
            "This run is a separate process. Closing this tab, or the app, "
            "does not stop it. The Runs tab shows the same thing."
        )
    elif st.button("Run it now", type="primary"):
        from qa.jobs import submit
        from qa.device import default_device, effective_device

        used, _ = effective_device(default_device())
        try:
            status = submit(result.course_dir, {"device": used}, None)
        except QAError as exc:
            st.error(str(exc))
        else:
            st.session_state.watching = status.id
            st.session_state.started_here = status.id
            st.rerun()
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

    intake_tab, runs_tab, results_tab = st.tabs(["Intake", "Runs", "Results"])
    with runs_tab:
        from qa.jobs import FileJobStore
        from qa.web.run_view import start_panel, watch_panel

        # Progress first when there is a run to watch. The start form used to
        # be at the top, so clicking "Run it now" and switching to this tab
        # landed on a form that looked idle, which invited a second click that
        # the one-run-per-course guard then had to catch.
        if FileJobStore().list():
            watch_panel()
            st.divider()
            with st.expander("Run another course"):
                start_panel()
        else:
            start_panel()

    with results_tab:
        from qa.web.results_view import results_panel

        results_panel()

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
    st.session_state.started_here = None
    st.rerun()


main()
