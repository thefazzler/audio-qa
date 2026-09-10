#!/bin/sh
# Start the Audio QA web interface:  ./qa-web.sh
#
# Everything a colleague needs to run a course is on the other side of this
# one file. Nobody reviewing narration should have to learn what a virtual
# environment is, and the step that used to be "activate the venv, then type
# qa-web" was where the instructions lost people.
#
# Run ./qa-setup.sh first if this says the environment is missing.
# On macOS, qa-web.command is this file for double-clicking in Finder.

cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/python ]; then
  echo
  echo "  No environment here yet."
  echo
  echo "  Run ./qa-setup.sh first. It checks what this machine needs, installs"
  echo "  what is safe to install, and tells you the exact command for anything"
  echo "  it will not install for you."
  echo
  exit 1
fi

echo "Starting the Audio QA interface. Press Ctrl-C, or close this window, to stop the server."
echo "A run already under way keeps going: it is a separate process."
echo
.venv/bin/python -m qa.web.launch "$@"
CODE=$?

if [ "$CODE" -ne 0 ]; then
  echo
  echo "  The interface stopped with an error. The lines above say why."
  echo
fi
exit "$CODE"
