#!/bin/sh
# Double-click this in Finder. It opens Terminal and runs qa-setup.sh from
# this folder. Both files are the same program; this one only has the
# extension Finder needs. The first time, macOS may ask you to allow it.
cd "$(dirname "$0")" && exec sh ./qa-setup.sh "$@"
