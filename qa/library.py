"""Where courses live once the app owns them.

Courses are data, not code, so the library sits outside the repository. That
is not tidiness: storyboards and narration are customer material, and a
library inside a public repository would be one bad ignore rule away from
being published. Keeping it out of the tree means no edit to .gitignore can
ever leak a course.

Resolution order, first match wins:

    1. an explicit path, passed by a caller or a --library flag
    2. the AUDIO_QA_LIBRARY environment variable
    3. the "library" key in the user config file
    4. the platform data directory

Both the environment variable and the config file exist on purpose. The
variable is how a server, a container or a scripted run gets configured. The
file is how someone who never opens a terminal points the app somewhere else
once, from the web UI, which is the entire point of that front door.

The library is designed for a local filesystem. Deliveries are downloaded from
SharePoint to each person's own machine, and each person's library is their
own; there is no shared or networked case to support.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .util import QAError

APP_NAME = "audio-qa"
ENV_VAR = "AUDIO_QA_LIBRARY"
CONFIG_NAME = "config.json"
LIBRARY_DIR = "library"


class LibraryError(QAError):
    pass


# ---------------------------------------------------------------------------
# Platform directories, hand rolled
# ---------------------------------------------------------------------------
# Twenty lines against a dependency. The rules are stable and the failure mode
# of getting them wrong is visible immediately, so platformdirs would be
# carrying its own weight and little else.

def _home() -> Path:
    return Path.home()


def normalize(path: Path | str) -> Path:
    """Absolute and tidy, without following links.

    Deliberately not Path.resolve(). resolve() follows junctions and reparse
    points, and it behaves differently depending on whether the path exists
    yet, so the library location displayed before the first course was created
    did not match the one displayed afterwards. On Windows it also resolves
    through packaged-app redirection, turning a plain AppData path into a path
    inside some other application's private cache. The library location a
    person configured is the one they should be shown.
    """
    return Path(os.path.normpath(os.path.abspath(os.path.expanduser(str(path)))))


def user_data_dir() -> Path:
    """Where this app's data belongs on this platform."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (_home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or (_home() / ".local" / "share")
    return Path(base) / APP_NAME


def user_config_dir() -> Path:
    """Where this app's settings belong on this platform."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (_home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or (_home() / ".config")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return user_config_dir() / CONFIG_NAME


def default_library() -> Path:
    return user_data_dir() / LIBRARY_DIR


# ---------------------------------------------------------------------------
# Settings file
# ---------------------------------------------------------------------------
# JSON rather than TOML: the standard library reads both but writes neither,
# and JSON escapes Windows paths correctly for free. A settings file this app
# writes on the user's behalf must not be a place where quoting can go wrong.

def read_settings() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A corrupt settings file must not stop the app. Fall back to defaults
        # and let the caller notice the setting did not stick.
        return {}
    return data if isinstance(data, dict) else {}


def write_settings(settings: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return path


def set_library(path: Path) -> Path:
    """Persist a library location chosen by a human."""
    settings = read_settings()
    settings["library"] = str(normalize(path))
    write_settings(settings)
    return Path(settings["library"])


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Resolution:
    """Where the library is, and which layer decided it."""

    path: Path
    source: str  # "argument", "environment", "settings" or "default"


def resolve_library(explicit: Path | str | None = None) -> Resolution:
    if explicit:
        return Resolution(normalize(explicit), "argument")

    from_env = os.environ.get(ENV_VAR)
    if from_env and from_env.strip():
        return Resolution(normalize(from_env), "environment")

    from_file = read_settings().get("library")
    if from_file and str(from_file).strip():
        return Resolution(normalize(from_file), "settings")

    return Resolution(normalize(default_library()), "default")


def library_root(explicit: Path | str | None = None, create: bool = False) -> Path:
    """The library directory. Creates it only when asked to."""
    root = resolve_library(explicit).path
    if create:
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LibraryError(
                f"Cannot create the course library at {root}:\n  {exc}\n"
                f"  Set {ENV_VAR}, or choose another location in the app."
            ) from exc
    return root


# ---------------------------------------------------------------------------
# Locating a course inside it
# ---------------------------------------------------------------------------

def course_folder_name(course_number: str) -> str:
    """Zero padded, so course01 sorts ahead of course10 in any listing."""
    return f"course{int(course_number):02d}"


def course_path(root: Path, learning_path: str, course_number: str) -> Path:
    return Path(root) / learning_path / course_folder_name(course_number)


def is_ingested(course_dir: Path) -> bool:
    """A course the app has already taken in, as opposed to an empty folder."""
    return (Path(course_dir) / "course.yaml").exists()


@dataclass(frozen=True)
class LibraryCourse:
    learning_path: str
    course_number: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.learning_path} / course {self.course_number}"


def list_courses(root: Path) -> list[LibraryCourse]:
    """Every ingested course in the library, learning path then course order."""
    root = Path(root)
    if not root.is_dir():
        return []
    found: list[LibraryCourse] = []
    for path_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for course_dir in sorted(p for p in path_dir.iterdir() if p.is_dir()):
            if not is_ingested(course_dir):
                continue
            digits = "".join(ch for ch in course_dir.name if ch.isdigit())
            found.append(
                LibraryCourse(
                    learning_path=path_dir.name,
                    course_number=digits or course_dir.name,
                    path=course_dir,
                )
            )
    return found
