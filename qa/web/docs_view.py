"""The Docs tab: the repository's own documents, rendered read-only.

The words a new person needs already exist, in HANDOVER.md, README.md,
COMMANDS.md and DECISIONS.md. Copying them into the interface would create a
second version that drifts from the first, and the first is the one under
version control. So this renders them where they are.

**Read-only is a rule, not an omission.** The portal displays documents and
never stores or edits them; git remains the only way their content changes. A
document edited through a web form would be a change with no commit, no
review and no history, in the one file a successor is told to trust. There is
no write path in this module and a test asserts there is none.

The list is `helptext.DOCS`, so the "learn more" pointers in tooltips and tour
steps and the tab that resolves them cannot disagree about what exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

from .helptext import DOCS, Doc

# "## Choosing a device", not "#include" and not a fenced code comment.
HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)


def find(key: str) -> Doc | None:
    for doc in DOCS:
        if doc.key == key:
            return doc
    return None


def load(key: str) -> str | None:
    """One document's text, or None when this installation has no copy of it.

    An installed wheel carries `qa/` and not the markdown beside it, so a
    missing document is a normal state rather than an error. Reading is the
    only thing this module does to a file.
    """
    doc = find(key)
    if doc is None or not doc.exists:
        return None
    try:
        return doc.path.read_text(encoding="utf-8")
    except OSError:
        return None


def headings(text: str) -> list[str]:
    """Every heading in the document, its title included."""
    return [match.group(2) for match in HEADING.finditer(text)]


def sections(text: str) -> list[str]:
    """The headings under the title, which is what a reader navigates by."""
    return headings(text)[1:]


def resolves(key: str, heading: str) -> bool:
    """Whether a learn-more pointer lands on a real heading of a real file."""
    text = load(key)
    return text is not None and heading in headings(text)


# ---------------------------------------------------------------------------

def docs_panel() -> None:
    st.subheader("Docs")
    st.caption(
        "The repository's own documents, shown as they are. This tab reads "
        "them and never writes them: git is the only way any of it changes."
    )

    available = [doc for doc in DOCS if doc.exists]
    if not available:
        st.info(
            "This installation has no copy of the documents. They live beside "
            "the code in the repository."
        )
        return

    chosen = st.selectbox(
        "Document", options=[doc.key for doc in available], key="docs-file"
    )
    text = load(chosen)
    if text is None:
        st.warning(f"{chosen} could not be read from this installation.")
        return

    found = sections(text)
    if found:
        with st.expander(f"Sections ({len(found)})"):
            for name in found:
                st.write(f"- {name}")

    st.divider()
    st.markdown(text)
