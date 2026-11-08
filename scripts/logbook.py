"""A log file that mirrors the terminal.

The server reports failures by printing to stderr, and the HTTP server prints request
tracebacks there too. `start` returns a writer that passes everything through to the
terminal and also appends it, one timestamp per line, to a file under the workspace, so a
problem can still be read after the terminal has scrolled or been closed.
"""
import time
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
PREVIOUS_SUFFIX = ".previous.log"


class Tee:
    def __init__(self, terminal, file):
        self.terminal = terminal
        self.file = file
        self.at_line_start = True

    def write(self, text):
        self.terminal.write(text)
        if self.file is None or not text:
            return
        stamp = time.strftime("%Y-%m-%d %H:%M:%S ")
        out = []
        for piece in text.splitlines(keepends=True):
            out.append((stamp if self.at_line_start else "") + piece)
            self.at_line_start = piece.endswith("\n")
        self.file.write("".join(out))

    def flush(self):
        self.terminal.flush()
        if self.file is not None:
            self.file.flush()

    def isatty(self):
        return getattr(self.terminal, "isatty", lambda: False)()

    def fileno(self):
        return self.terminal.fileno()


def _rotate(path):
    if path.is_file() and path.stat().st_size > MAX_BYTES:
        path.replace(path.with_name(path.stem + PREVIOUS_SUFFIX))


def start(path, terminal):
    """A Tee over `terminal` that also appends to `path`; the terminal alone when the file cannot be opened."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate(path)
        file = open(path, "a", buffering=1, encoding="utf-8")
    except OSError as err:
        print(f"Not keeping a log file at {path}: {err}", file=terminal)
        file = None
    return Tee(terminal, file)
