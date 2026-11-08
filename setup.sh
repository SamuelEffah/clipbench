#!/bin/bash
# Run from any directory; repeat safely without replacing local user data.
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin ]]; then
  echo 'This starter currently supports macOS (the renderer uses macOS fonts).' >&2
  exit 1
fi
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --ai ) ]]; then
  echo 'Usage: ./setup.sh [--ai]' >&2
  exit 2
fi
if ! command -v brew >/dev/null; then
  echo 'Install Homebrew from https://brew.sh, then rerun ./setup.sh.' >&2
  exit 1
fi
# ffmpeg-full, not ffmpeg: the plain formula no longer has the drawtext and subtitles filters.
brew install python@3.11 ffmpeg-full
# The bottle Homebrew just poured is not always usable on this exact macOS build, so take
# the first interpreter that actually works rather than the one that was just installed.
PYTHON="$(tools/pick_python.sh \
  "$(brew --prefix python@3.11)/bin/python3.11" \
  "$(brew --prefix)/bin/python3.12" "$(brew --prefix)/bin/python3.13" \
  "$(brew --prefix)/bin/python3.14" python3)"
echo "Using $PYTHON"
if [[ -e .venv ]] && ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  echo 'Replacing the incomplete .venv left by an earlier attempt.'
  rm -rf .venv
fi
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
requirements=requirements.txt
if [[ "${1:-}" == --ai ]]; then requirements=requirements-ai.txt; fi
.venv/bin/python -m pip install -r "$requirements"
export PATH="$PWD/.venv/bin:$PATH"
.venv/bin/python tools/relocate.py
.venv/bin/python tools/workspace.py
if [[ "${1:-}" == --ai ]]; then .venv/bin/python tools/setup_models.py; fi
.venv/bin/python tools/check_setup.py
echo 'Ready. Start with ./start.sh'
