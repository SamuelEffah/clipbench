#!/bin/bash
# Print the first candidate that is a usable Python for this app: 3.10 or newer, with a
# standard library that loads. An installed Homebrew bottle can still be broken on the
# machine (its pyexpat refusing to load against the system libexpat); that interpreter
# cannot even create a venv, because ensurepip's pip dies reading the macOS version.
set -uo pipefail
probe='import sys, pyexpat, plistlib, sqlite3, ssl; sys.exit(sys.version_info < (3, 10))'
for candidate in "$@"; do
  resolved="$(command -v "$candidate" 2>/dev/null)" || continue
  [[ -x "$resolved" ]] || continue
  if "$resolved" -c "$probe" >/dev/null 2>&1; then
    printf '%s\n' "$resolved"
    exit 0
  fi
done
{
  echo 'No working Python 3.10 or newer was found. Tried:'
  printf '  %s\n' "$@"
  echo 'Install one with: brew reinstall python@3.13'
} >&2
exit 1
