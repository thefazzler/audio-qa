"""The qa-web command: start the local web interface.

Streamlit has to launch its own server rather than being imported, so this
shells out to it and points it at the page. Everything else about the app is
ordinary Python.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ..library import ENV_VAR, resolve_library
from ..util import QAError

APP = Path(__file__).with_name("app.py")


class WebError(QAError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qa-web",
        description="Start the local Audio QA web interface.",
        epilog=(
            "The interface and the qa-run command are two front doors to the "
            "same engine.\nCourses are stored in the library, not in this "
            f"repository; override it with {ENV_VAR}."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--port", type=int, default=8501, help="port to serve on")
    parser.add_argument(
        "--no-browser", action="store_true", help="do not open a browser window"
    )
    args = parser.parse_args(argv)

    try:
        import streamlit  # noqa: F401
    except ImportError:
        print(
            "FAILED: streamlit is not installed.\n"
            "  Install the web extra:  pip install -e .[web]",
            file=sys.stderr,
        )
        return 2

    library = resolve_library()
    print(f"audio-qa web interface")
    print(f"  library: {library.path}  ({library.source})")
    print(f"  serving: http://localhost:{args.port}")

    command = [
        sys.executable, "-m", "streamlit", "run", str(APP),
        "--server.port", str(args.port),
        "--server.headless", "true" if args.no_browser else "false",
        "--browser.gatherUsageStats", "false",
    ]
    try:
        return subprocess.call(command)
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print(f"FAILED: could not start streamlit:\n  {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
