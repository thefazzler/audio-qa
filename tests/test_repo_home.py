"""The repository must not name its own home. See DECISIONS.md D34.

It is moving between GitHub accounts, and may again. Nothing in the pipeline
reads its own URL, so the only way a home gets hard-wired is prose, and prose
is what this scans: every tracked text file, for a URL pointing at a
repository of this name under any owner.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOME = re.compile(r"github\.com[/:][\w.-]+/audio-qa", re.IGNORECASE)
TEXT = {".md", ".py", ".toml", ".cmd", ".sh", ".command", ".yaml", ".yml", ".txt", ".cfg"}

# Files allowed to name a home, each with a reason. Empty on purpose.
EXCEPTIONS: dict[str, str] = {}


def tracked_text_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split("\0")
    return [ROOT / name for name in listed if name and Path(name).suffix in TEXT]


def test_no_tracked_file_names_a_home_for_this_repository():
    files = tracked_text_files()
    assert files, "git ls-files returned nothing; is this a checkout?"
    offenders = []
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        if relative in EXCEPTIONS:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if HOME.search(line):
                offenders.append(f"{relative}:{number}: {line.strip()}")
    assert not offenders, "hard-wired repository home:\n  " + "\n  ".join(offenders)


def test_the_clone_instructions_use_the_placeholder_and_say_where_to_find_it():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "git clone <repository-url>" in text
    assert "**Code** button" in text, "the placeholder must say where the real value is"
