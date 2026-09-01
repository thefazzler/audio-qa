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

# Everything Streamlit does on startup that is about Streamlit rather than
# about this app. Passed as flags rather than written into a config file, so
# launching qa-web changes nothing on the machine and a person who runs
# streamlit by hand still gets its normal behaviour.
#
# Each of these was watched confusing somebody in the first pilot session:
#
#   showEmailPrompt      a first run pauses on "Email:" and waits. A new user
#                        reads a paused prompt as a hang, and there is nothing
#                        on screen to say otherwise.
#   hideWelcomeMessage   also suppresses the "Help agents write better
#                        Streamlit apps?" recommendation, which is advice to a
#                        developer appearing in front of a content reviewer.
#                        The URL it also hides is printed by this command
#                        anyway, two lines earlier.
#   toolbarMode minimal  hides the Deploy button and the developer menu. Deploy
#                        invites pushing customer narration to Streamlit's
#                        cloud, which is the one thing this tool exists to
#                        avoid: everything runs on this machine and the audio
#                        never leaves it.
#   gatherUsageStats     off, for the same reason.
STREAMLIT_QUIET = (
    "--server.showEmailPrompt", "false",
    "--logger.hideWelcomeMessage", "true",
    "--client.toolbarMode", "minimal",
    "--browser.gatherUsageStats", "false",
)


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
        *STREAMLIT_QUIET,
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
