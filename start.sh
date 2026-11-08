#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo 'Run ./setup.sh first.' >&2
  exit 1
fi
export PATH="$PWD/.venv/bin:$PATH"
.venv/bin/python tools/check_setup.py
exec .venv/bin/python scripts/clipper.py "$@"
