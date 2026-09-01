"""Open a folder in the machine's own file browser.

The app is local by design: the server and the browser are the same computer,
and the audio never leaves it. That is what makes this possible at all, and it
is the only reason it is defensible. A hosted app opening a folder would be
opening the *server's* folder, which is useless at best.

So this is UI, not pipeline. It lives here because moving the app to a server
should delete it rather than port it.

Nothing here ever deletes, moves or writes. It asks the desktop to show a
folder, and reports honestly when it cannot rather than pretending it worked.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def available() -> bool:
    """Whether this platform has a file browser this module knows how to ask."""
    if sys.platform == "win32":
        return hasattr(os, "startfile")
    if sys.platform == "darwin":
        return True
    return bool(_which("xdg-open"))


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def open_folder(path: Path | str) -> str:
    """Show a folder. Returns "" on success, or a sentence saying why not.

    A file path is accepted and its containing folder is shown, because "where
    is my packet" and "show me the packet" are the same request.
    """
    target = Path(path)
    if target.is_file():
        target = target.parent
    if not target.is_dir():
        return f"{target} does not exist yet."

    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # noqa: S606 - the whole point
            return ""
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        if _which(opener) is None:
            return (
                f"This machine has no {opener}, so the folder cannot be opened "
                f"from here. It is at {target}."
            )
        subprocess.Popen(
            [opener, str(target)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return ""
    except OSError as exc:
        return f"Could not open {target}: {exc}"
