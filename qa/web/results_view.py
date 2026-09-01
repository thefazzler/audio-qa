"""What a finished run says, and what a person does next.

The order on the page is the order the work happens in: what the instrument
measured, what it wants you to listen to, and then the packet that goes to the
judgment step. The listen list is not buried in an expander, because it is the
only part that requires a human and the whole pipeline exists to produce it.

Judgment stays manual here. The page hands over a packet and the prompt to use
with it; it does not call an API and it does not assign verdicts. That is
render.py's job, and it is a separate task on purpose.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from qa.library import list_courses, resolve_library
from qa.results import (
    DIFFERENCES,
    FLAGGED,
    LISTEN,
    NO_DIFFERENCES,
    UNSCRIPTED,
    ResultsError,
    load_results,
)
from qa.device import DEVICE_NOTE
from qa.util import QAError

STATE_ICON = {
    NO_DIFFERENCES: "ok",
    DIFFERENCES: "review",
    LISTEN: "listen",
    FLAGGED: "flag",
    UNSCRIPTED: "outline",
}


def _percent(value: float | None) -> str:
    return f"{value * 100:.2f}%" if value is not None else "n/a"


# ---------------------------------------------------------------------------

def _headline(results) -> None:
    columns = st.columns(4)
    columns[0].metric("Topics", results.topic_count)
    columns[1].metric("Mean coverage", _percent(results.mean_coverage))
    columns[2].metric("Differences", results.total_differences)
    columns[3].metric("Listen items", len(results.listen))
    st.caption(
        f"Course {results.course_number} ({results.course_code}), "
        f"{results.project_type}. "
        f"{results.clean_topics} of {results.topic_count} topics show no word "
        "level differences."
    )
    if results.flagged_topics:
        st.warning(
            "Check flags on topic "
            + ", ".join(results.flagged_topics)
            + ". A flagged topic is a validation problem before it is a "
            "narration question; read its flag before reading its differences."
        )


def _checks_table(results) -> None:
    st.subheader("Checks")
    st.caption(
        "Coverage is the share of script tokens matched. A topic with no "
        "differences is not a certified topic: pronunciation and delivery are "
        "not measured at all."
    )
    st.dataframe(
        [
            {
                "topic": t.topic,
                "slides": f"{t.slides[0]}-{t.slides[1]}" if len(t.slides) == 2 and t.slides[0] != t.slides[1] else (str(t.slides[0]) if t.slides else ""),
                "state": STATE_ICON.get(t.state, t.state),
                "coverage": _percent(t.coverage) if t.scripted else "n/a",
                "differences": t.differences if t.scripted else "outline only",
                "listen": t.listen_items or "",
                "flags": ", ".join(t.flags),
                "audio": ", ".join(t.audio_findings),
                "suppressed": t.suppressed or "",
            }
            for t in results.topics
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "Suppressed counts ASR segment boundary duplications removed as engine "
        "artifacts. They are not narration."
    )


def _listen_list(results) -> None:
    st.subheader("Listen list")
    if not results.listen:
        st.success(
            "Nothing on the listen list. Note that this means no site fell "
            "below the confidence floor and no watched term was misheard; it "
            "does not mean pronunciation or delivery were checked."
        )
        return

    corroborated = sum(1 for i in results.listen if i.corroborated)
    st.info(
        f"**{len(results.listen)} places need a human with headphones.** This is "
        "the next step, and nothing downstream can settle these: the pipeline "
        "has taken them as far as paper goes."
    )
    if corroborated:
        st.caption(
            f"{corroborated} of them were flagged by two independent detectors "
            "at the same spot. Those are worth listening to first."
        )

    st.dataframe(
        [
            {
                "topic": item.topic,
                "at": item.timestamp,
                "found by": item.kind + (" ++" if item.corroborated else ""),
                "what": item.what,
                "confidence": (
                    f"{item.confidence:.3f}" if item.confidence is not None else ""
                ),
                "why": item.detail,
            }
            for item in results.listen
        ],
        use_container_width=True,
        hide_index=True,
    )

    watchlist = results.watchlist or {}
    if watchlist.get("present"):
        totals = watchlist.get("totals", {})
        st.caption(
            f"Watchlist: {totals.get('terms', 0)} terms checked at "
            f"{totals.get('occurrences', 0)} sites, {totals.get('matched', 0)} "
            f"matched, {totals.get('misheard', 0)} misheard. A match means the "
            "expected spelling appeared, which is orthography and not "
            "pronunciation, so a clean watchlist clears nothing."
        )
    else:
        st.caption(
            "No watchlist for this learning path, so no term was checked by "
            "name. That is not the same as nothing being wrong."
        )


def _packet_and_judgment(results) -> None:
    st.subheader("Next: judgment")
    if results.packet_md is None:
        st.warning("No packet has been built for this course yet.")
        return

    st.write(
        "The packet below is the evidence for the judgment step. Judgment is "
        "deliberately a human action here: open a Claude chat, paste "
        "`prompts/reconciliation_v2.md`, attach this packet, and it returns the "
        "findings report with verdicts and remediation routing."
    )
    st.caption(
        "Verdicts, the Class 1 to 4 taxonomy and the edit sheet come from that "
        "step, not from this page. Nothing here has judged anything; it has "
        "only measured."
    )

    text = results.packet_md.read_text(encoding="utf-8")
    columns = st.columns(2)
    columns[0].download_button(
        "Download the packet",
        data=text,
        file_name=results.packet_md.name,
        mime="text/markdown",
        type="primary",
    )
    if results.packet_json is not None:
        columns[1].download_button(
            "Download packet JSON",
            data=results.packet_json.read_text(encoding="utf-8"),
            file_name=results.packet_json.name,
            mime="application/json",
        )
    st.caption(f"{len(text.split())} words, about {len(text.split()) / 500:.1f} pages")

    with st.expander("Preview the packet"):
        st.markdown(text)


def _stats(results) -> None:
    """Telemetry, off by default. One home for it, a click away."""
    with st.expander("Stats for nerds"):
        stats = results.stats
        st.caption(
            "Everything here was recorded by the pipeline or measured about "
            "this machine. " + DEVICE_NOTE
        )

        columns = st.columns(3)
        columns[0].write("**Engine**")
        columns[0].write(
            f"{stats.engine or 'unknown'} {stats.model or ''}\n\n"
            f"quantization `{stats.compute_type or 'unknown'}`\n\n"
            f"device `{stats.device or 'not recorded'}`"
            + (
                f" (requested `{stats.device_requested}`)"
                if stats.device_requested and stats.device_requested != stats.device
                else ""
            )
            + "\n\n"
            f"threads {stats.cpu_threads if stats.cpu_threads is not None else 'unknown'}\n\n"
            f"beam {stats.beam_size if stats.beam_size is not None else 'unknown'}, "
            f"VAD {'on' if stats.vad else 'off' if stats.vad is not None else 'unknown'}"
        )
        columns[1].write("**Speed**")
        columns[1].write(
            f"{stats.audio_seconds / 60:.1f} min of audio\n\n"
            f"{stats.decode_seconds / 60:.1f} min decoding\n\n"
            f"**{stats.rate_realtime or 'n/a'}x realtime**\n\n"
            f"{stats.eta_basis}"
        )
        memory = stats.memory or {}
        columns[2].write("**Machine**")
        if memory.get("measured"):
            columns[2].write(
                f"{memory.get('total_gb')} GB total\n\n"
                f"{memory.get('available_gb')} GB free now\n\n"
                f"_{memory.get('note')}_"
            )
        else:
            columns[2].write("memory not measurable on this platform")

        if stats.fallback_reason:
            st.warning(
                f"This run asked for {stats.device_requested or 'a GPU'} and "
                f"decoded on {stats.device}. GPU decode failed and the run "
                f"continued on CPU: {stats.fallback_reason}"
            )

        st.write("**Per topic decode**")
        st.dataframe(
            [
                {
                    "topic": row["topic"],
                    "audio_s": row["audio_s"],
                    "decode_s": row["decode_s"],
                    "xrealtime": row["realtime"],
                    "words": row["words"],
                    "anomalies": row["anomalies"],
                }
                for row in stats.per_topic
            ],
            use_container_width=True,
            hide_index=True,
        )

        st.write("**Quality signals**")
        st.write(
            f"- mean coverage {_percent(stats.mean_coverage)}\n"
            f"- mean low confidence word share "
            f"{_percent(stats.low_confidence_share)}\n"
            f"- {stats.suppressed_duplicates} ASR segment boundary duplications "
            "suppressed as engine artifacts\n"
            f"- decode anomalies: "
            f"{', '.join(stats.anomalies) if stats.anomalies else 'none'}"
        )

        conventions = stats.audio_conventions or {}
        if conventions:
            st.write("**Measured audio conventions**")
            st.write(
                f"- {conventions.get('leading_pad_s')} s lead in, "
                f"{conventions.get('trailing_pad_s')} s tail\n"
                f"- {conventions.get('slide_gap_s')} s between slides, "
                f"{conventions.get('slide_gap_count', 0)} measured\n"
                f"- {stats.conventional_gaps} pauses matched the house style and "
                "were treated as convention rather than findings"
            )


# ---------------------------------------------------------------------------

def results_panel() -> None:
    library = resolve_library().path
    courses = list_courses(library)
    if not courses:
        st.info("No courses in the library yet.")
        return

    labels = {c.label: c for c in courses}
    chosen = st.selectbox("Course", options=list(labels), key="results-course")
    course = labels[chosen]

    try:
        results = load_results(course.path)
    except ResultsError as exc:
        st.info(str(exc))
        return
    except QAError as exc:
        st.error(str(exc))
        return

    _headline(results)
    _listen_list(results)
    _packet_and_judgment(results)
    _checks_table(results)
    _stats(results)
