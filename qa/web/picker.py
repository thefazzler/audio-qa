"""A native file dialog, for an app that needs real paths.

Streamlit's own uploader hands over file contents, not locations. That does not
fit this intake: verifying a copy against its source, and offering to clean up
the originals afterwards, both need to know where the files actually are. A
128 MB demo video also has no business travelling through a browser upload on
a machine that already has the file.

So the Browse button opens the operating system's own dialog. It runs in a
short lived subprocess rather than in the Streamlit process, because a Tk main
loop started inside a web server's worker thread hangs on some platforms and
takes the app down with it. A subprocess either prints paths or it does not.

If Tk is missing, the caller falls back to pasting paths. Nothing here is the
only way in.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# Runs in the child. Kept as a string so the parent never imports Tk.
_DIALOG = r"""
import json, sys
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception as exc:
    print(json.dumps({"error": f"no native file dialog available: {exc}"}))
    sys.exit(0)

root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
try:
    if sys.argv[1] == "files":
        chosen = filedialog.askopenfilenames(
            title="Select the storyboard and every narration file",
            filetypes=[
                ("Course files", "*.pptx *.mp3 *.mp4 *.m4a *.wav *.mov *.mkv"),
                ("All files", "*.*"),
            ],
        )
        paths = list(chosen)
    else:
        chosen = filedialog.askdirectory(title="Select a folder")
        paths = [chosen] if chosen else []
except Exception as exc:
    print(json.dumps({"error": str(exc)}))
    sys.exit(0)
finally:
    root.destroy()

print(json.dumps({"paths": [p for p in paths if p]}))
"""

TIMEOUT_S = 600


def _run(mode: str) -> dict:
    try:
        done = subprocess.run(
            [sys.executable, "-c", _DIALOG, mode],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {"error": "the file dialog was left open too long", "paths": []}
    except OSError as exc:
        return {"error": f"could not open a file dialog: {exc}", "paths": []}

    line = (done.stdout or "").strip().splitlines()
    if not line:
        return {"error": done.stderr.strip() or "the file dialog returned nothing", "paths": []}
    try:
        payload = json.loads(line[-1])
    except ValueError:
        return {"error": "the file dialog returned something unreadable", "paths": []}
    payload.setdefault("paths", [])
    return payload


def pick_files() -> tuple[list[Path], str]:
    """Multi select files. Returns the paths and an error string, not both."""
    result = _run("files")
    return [Path(p) for p in result.get("paths", [])], result.get("error", "")


def pick_folder() -> tuple[Path | None, str]:
    result = _run("folder")
    paths = result.get("paths", [])
    return (Path(paths[0]) if paths else None), result.get("error", "")


def available() -> bool:
    """Whether this machine can show a native dialog at all."""
    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    return True
