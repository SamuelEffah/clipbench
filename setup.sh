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
brew install python@3.11 ffmpeg
PYTHON="$(brew --prefix python@3.11)/bin/python3.11"
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
requirements=requirements.txt
if [[ "${1:-}" == --ai ]]; then requirements=requirements-ai.txt; fi
.venv/bin/python -m pip install -r "$requirements"
export PATH="$PWD/.venv/bin:$PATH"
.venv/bin/python tools/workspace.py
if [[ "${1:-}" == --ai ]]; then .venv/bin/python tools/setup_models.py; fi
.venv/bin/python tools/check_setup.py
echo 'Ready. Start with ./start.sh'
