#!/bin/sh
# Check this machine and set it up. Run this first:  ./qa-setup.sh
#
# It reports every prerequisite, installs the ones that are safe to install
# into a local environment, prints the exact command for anything system wide
# that it will not install for you, and finishes by running the whole pipeline
# on a generated fixture to prove the result actually works.
#
# Safe to run again at any time. It is also the troubleshooting tool when
# something breaks after a Python or driver upgrade:  ./qa-setup.sh --check
#
# On macOS, qa-setup.command is this file for double-clicking in Finder.

cd "$(dirname "$0")" || exit 1

# The project's own environment when it exists, otherwise a Python that can
# run the setup module, because the first job of setup is to create that
# environment. Each candidate is actually run, not just found: on a fresh Mac
# /usr/bin/python3 is a stub that offers to install developer tools instead.
PY=""
if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  for candidate in python3.12 python3.13 python3.11 python3 python; do
    path="$(command -v "$candidate" 2>/dev/null)" || continue
    if [ "$(uname)" = "Darwin" ] && [ "$path" = "/usr/bin/python3" ]; then
      xcode-select -p >/dev/null 2>&1 || continue
    fi
    if "$path" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      PY="$path"
      break
    fi
  done
fi

if [ -z "$PY" ]; then
  # Setup is written in Python, so this is the one prerequisite it cannot
  # report on its own. Say exactly what to do, the same way it would have.
  echo
  echo "  PREREQUISITE  STATUS   FOUND"
  echo "  ------------------------------------------------------------"
  echo "  Python        MISSING  no Python 3 on this machine"
  echo
  echo "  What to do:"
  echo
  echo "  Python: MISSING"
  echo "    required: 3.11 or newer, below 3.14"
  case "$(uname)" in
    Darwin)
      echo "    fix:      brew install python@3.12"
      echo "              (no Homebrew? install it from https://brew.sh, or use the"
      echo "              macOS installer at https://python.org/downloads)"
      ;;
    *)
      if [ -r /etc/os-release ] && grep -qiE '^(ID|ID_LIKE)=.*(rhel|fedora|centos|rocky|alma)' /etc/os-release; then
        echo "    fix:      sudo dnf install -y python3.12"
      elif [ -r /etc/os-release ] && grep -qiE '^(ID|ID_LIKE)=.*arch' /etc/os-release; then
        echo "    fix:      sudo pacman -S --needed python"
      else
        echo "    fix:      sudo apt-get install -y python3.12 python3.12-venv"
        echo "              (Ubuntu 22.04 or older: sudo add-apt-repository ppa:deadsnakes/ppa first)"
      fi
      ;;
  esac
  echo
  echo "    then run this again."
  echo
  exit 1
fi

echo
"$PY" -m qa.setup "$@"
CODE=$?

echo
if [ "$CODE" -eq 0 ]; then
  echo "  Ready. Run ./qa-web.sh to open the interface."
else
  echo "  Not ready yet. The table above says what is missing and how to fix it."
  echo "  Run this again after fixing it."
fi
echo
exit "$CODE"
