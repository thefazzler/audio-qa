"""Getting the disk back, and saying what that costs before it is spent.

Every number and every deletion here comes from `qa.cleanup`. This file
arranges them and asks for confirmation; it does not decide what is safe to
remove, and it must not, because the rule that findings are never deleted has
to hold for the command line too.

Two things this page is careful about, both learned elsewhere in this codebase:

**It says what will happen before it happens.** Each action names the files,
the size and the consequence, and the destructive one is behind a checkbox
whose label is the consequence rather than the word "confirm".

**It never claims more than it did.** A reclaim reports what was actually
freed, read back from the filesystem, and lists anything it refused. A tidy-up
that silently skipped half a course while reporting success is the same class
of fault as a transcriber that skipped a file without saying so.
"""

from __future__ import annotations

import streamlit as st

from qa.cleanup import (
    CleanupError,
    archive_packets,
    delete_packets,
    human,
    library_survey,
    packet_space,
    reclaim,
)
from qa.library import resolve_library, resolve_output
from qa.util import QAError
from qa.web.helptext import concept

CONFIRM_MEDIA = "storage-confirm-media"
CONFIRM_PACKETS = "storage-confirm-packets"


def _outcome(results: list) -> None:
    """What actually happened, counted from what was actually removed."""
    freed = sum(r.freed_bytes for r in results)
    files = sum(len(r.removed) for r in results)
    refused = [(p, why) for r in results for p, why in r.failed]

    if files:
        st.success(f"Freed {human(freed)} across {files} files.")
    else:
        st.info("Nothing to remove; those files had already gone.")
    if refused:
        st.warning(f"{len(refused)} files were not removed:")
        for path, why in refused[:20]:
            st.caption(f"`{path.name}` — {why}")


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------

def _courses_panel(spaces) -> None:
    st.subheader("Course files", help=concept("storage_kept"))

    reclaimable = sum(s.reclaimable_bytes for s in spaces)
    kept = sum(s.kept_bytes for s in spaces)
    columns = st.columns(3)
    columns[0].metric("Courses", len(spaces))
    columns[1].metric(
        "Can be freed", human(reclaimable), help=concept("storage_reclaimable")
    )
    columns[2].metric("Findings kept", human(kept), help=concept("storage_kept"))

    st.dataframe(
        [
            {
                "course": s.label,
                "total": human(s.total_bytes),
                "scratch audio": human(s.scratch.bytes),
                "media and script": human(s.media.bytes),
                "findings": human(s.kept_bytes),
                "state": (
                    f"run in progress ({s.running})"
                    if s.running
                    else ("media removed " + s.reclaimed_at)
                    if s.reclaimed_at
                    else "ready to run"
                ),
            }
            for s in spaces
        ],
        width="stretch",
        hide_index=True,
        column_config={
            "scratch audio": st.column_config.TextColumn(
                "scratch audio", help=concept("scratch")
            ),
            "media and script": st.column_config.TextColumn(
                "media and script", help=concept("media")
            ),
            "findings": st.column_config.TextColumn(
                "findings", help=concept("findings_kept")
            ),
        },
    )

    _scratch_action(spaces)
    _media_action(spaces)


def _scratch_action(spaces) -> None:
    total = sum(s.scratch.bytes for s in spaces)
    st.markdown("**Scratch audio**", help=concept("scratch"))
    st.caption(
        f"{human(total)} of demuxed audio across {len(spaces)} courses. The "
        "ingest stage rebuilds it in seconds and every course stays runnable, "
        "so there is nothing to weigh up here."
    )
    if st.button(
        f"Free {human(total)} of scratch audio",
        type="primary",
        disabled=total == 0,
        key="storage-scratch",
    ):
        results = []
        for space in spaces:
            try:
                results.append(reclaim(space.course_dir))
            except (CleanupError, QAError) as exc:
                st.error(str(exc))
        _outcome(results)
        st.rerun()


def _media_action(spaces) -> None:
    candidates = [s for s in spaces if s.media.present]
    total = sum(s.media.bytes for s in candidates)

    st.markdown("**Delivered media and script documents**", help=concept("media"))
    if not candidates:
        st.caption("No delivered media left in the library.")
        return
    st.caption(
        f"{human(total)} across {len(candidates)} courses. Everything these "
        "runs found stays where it is and every packet is untouched; what goes "
        "is the narration and the script document, which come from SharePoint "
        "again when a course needs re-running."
    )

    chosen = st.multiselect(
        "Courses",
        options=[s.label for s in candidates],
        default=[s.label for s in candidates],
        key="storage-media-courses",
    )
    picked = [s for s in candidates if s.label in chosen]
    picking = sum(s.media.bytes for s in picked)

    with st.expander(f"What would be removed ({human(picking)})"):
        for space in picked:
            st.write(f"**{space.label}** — {human(space.media.bytes)}")
            for path in space.media.paths:
                st.caption(f"`{path.name}`")

    # The label is the consequence, not the word "confirm". Somebody ticking
    # this has read what it costs rather than agreed to a formality.
    understood = st.checkbox(
        "These courses will need their files downloaded again before they can "
        "be run. Their results and packets stay.",
        key=CONFIRM_MEDIA,
    )
    if st.button(
        f"Remove media for {len(picked)} course{'' if len(picked) == 1 else 's'}",
        disabled=not understood or not picked,
        key="storage-media",
    ):
        results = []
        for space in picked:
            try:
                results.append(reclaim(space.course_dir, media=True))
            except (CleanupError, QAError) as exc:
                st.error(str(exc))
        _outcome(results)
        st.session_state[CONFIRM_MEDIA] = False
        st.rerun()


# ---------------------------------------------------------------------------
# Packets
# ---------------------------------------------------------------------------

def _packets_panel() -> None:
    st.subheader("Reports and packets", help=concept("storage_packets"))
    space = packet_space()
    st.caption(f"`{space.directory}`")

    columns = st.columns(3)
    columns[0].metric("Packets", space.count)
    columns[1].metric("Size", human(space.bytes))
    columns[2].metric(
        "Archives", f"{len(space.archives)} · {human(space.archived_bytes)}"
    )

    if not space.count:
        st.info("No packets in this folder yet.")
        return

    names = [p.name for p in space.markdown + space.payloads]
    chosen = st.multiselect(
        "Packets",
        options=names,
        default=names,
        key="storage-packets",
    )
    by_name = {p.name: p for p in space.markdown + space.payloads}
    picked = [by_name[n] for n in chosen]

    st.markdown("**Archive**", help=concept("archive"))
    st.caption(
        "Zipped into this same folder, so the run history stays in one place. "
        "Markdown compresses hard; the originals are only removed once the "
        "archive has been read back and seen to hold them."
    )
    columns = st.columns(2)
    if columns[0].button("Archive, keep the originals", disabled=not picked):
        _archive(picked, delete=False)
    if columns[1].button(
        "Archive and remove the originals", type="primary", disabled=not picked
    ):
        _archive(picked, delete=True)

    st.markdown("**Delete without archiving**", help=concept("delete_packets"))
    st.caption(
        "A packet is the only record of what a run found once its course "
        "files are gone. There is nothing to undo this with."
    )
    understood = st.checkbox(
        f"Permanently delete {len(picked)} packet files with no copy kept.",
        key=CONFIRM_PACKETS,
    )
    if st.button(
        "Delete permanently", disabled=not understood or not picked, key="storage-del"
    ):
        try:
            result = delete_packets(picked, space.directory)
        except (CleanupError, QAError) as exc:
            st.error(str(exc))
            return
        st.success(f"Deleted {len(result.deleted)} files, {human(result.bytes_before)}.")
        for path, why in result.failed:
            st.warning(f"`{path.name}` — {why}")
        st.session_state[CONFIRM_PACKETS] = False
        st.rerun()


def _archive(picked, delete: bool) -> None:
    try:
        result = archive_packets(paths=picked, delete=delete)
    except (CleanupError, QAError) as exc:
        st.error(str(exc))
        return
    st.success(
        f"Archived {len(result.packed)} packets into `{result.archive.name}`, "
        f"{human(result.bytes_before)} down to {human(result.bytes_after)}."
    )
    if delete:
        st.write(f"{len(result.deleted)} originals removed.")
    for path, why in result.failed:
        st.warning(f"`{path.name}` — {why}")
    st.rerun()


# ---------------------------------------------------------------------------

def storage_panel() -> None:
    st.subheader("Storage", help=concept("storage"))
    st.caption(
        f"Library `{resolve_library().path}` · packets "
        f"`{resolve_output().path}`. Nothing here ever removes what a run "
        "found: the findings a course keeps are a fraction of a percent of its "
        "size, and the listen list is rebuilt from them every time you open "
        "Results."
    )

    try:
        spaces = library_survey()
    except QAError as exc:
        st.error(str(exc))
        return

    if not spaces:
        st.info("No courses in the library yet.")
    else:
        _courses_panel(spaces)

    st.divider()
    _packets_panel()
