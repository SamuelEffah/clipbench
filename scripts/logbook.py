"""Logging for the server: a file under the workspace plus the terminal.

Loggers are named under `clipbench` (http, prepare, render, youtube...). The file gets
every line at INFO and above, with timestamp, level, name and full tracebacks; the
terminal gets the message alone, and a one-line summary instead of a traceback.
CLIPBENCH_LOG=debug also keeps request-by-request lines in the file.

`start` also returns a Tee for sys.stderr, so anything still printed there (and the
HTTP server's own tracebacks) lands in the same file, one timestamp per line.
"""
import logging
import os
import time
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
PREVIOUS_SUFFIX = ".previous.log"
LEVEL_VAR = "CLIPBENCH_LOG"
FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_handlers = []


class Tee:
    def __init__(self, terminal, file):
        self.terminal = terminal
        self.file = file
        self.at_line_start = True

    def write(self, text):
        self.terminal.write(text)
        if self.file is None or not text:
            return
        stamp = time.strftime(TIME_FORMAT) + " "
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


class TerminalFormatter(logging.Formatter):
    """The message alone; an exception becomes a one-line summary pointing at the file."""

    def __init__(self, log_path):
        super().__init__("%(message)s")
        self.log_path = log_path

    def format(self, record):
        message = record.getMessage()
        if record.exc_info and record.exc_info[1] is not None:
            err = record.exc_info[1]
            where = f" (traceback in {self.log_path})" if self.log_path else ""
            return f"{message}: {type(err).__name__}: {err}{where}"
        return message


def _rotate(path):
    if path.is_file() and path.stat().st_size > MAX_BYTES:
        path.replace(path.with_name(path.stem + PREVIOUS_SUFFIX))


def _open(path, terminal):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate(path)
        return open(path, "a", buffering=1, encoding="utf-8")
    except OSError as err:
        print(f"Not keeping a log file at {path}: {err}", file=terminal)
        return None


def _level(level):
    name = (level or os.environ.get(LEVEL_VAR) or "info").upper()
    return logging.DEBUG if name == "DEBUG" else logging.INFO


def start(path, terminal, level=None):
    """Route the `clipbench` loggers to `path` and `terminal`, and return a Tee for stderr."""
    stop()
    path = Path(path)
    file = _open(path, terminal)
    root = logging.getLogger("clipbench")
    root.setLevel(_level(level))
    root.propagate = False
    if file is not None:
        to_file = logging.StreamHandler(file)
        to_file.setFormatter(logging.Formatter(FILE_FORMAT, TIME_FORMAT))
        _handlers.append(to_file)
    to_terminal = logging.StreamHandler(terminal)
    to_terminal.setLevel(logging.INFO)
    to_terminal.setFormatter(TerminalFormatter(path if file is not None else None))
    _handlers.append(to_terminal)
    for handler in _handlers:
        root.addHandler(handler)
    return Tee(terminal, file)


def stop():
    """Detach the handlers `start` added, so a second start does not double every line."""
    root = logging.getLogger("clipbench")
    while _handlers:
        handler = _handlers.pop()
        root.removeHandler(handler)
        handler.flush()


def request_level(method, path, status):
    """How loud a finished request should be, or None for a quiet static file."""
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    if not path.startswith("/api/"):
        return None
    return logging.INFO if method == "POST" else logging.DEBUG
