"""Everything the server says on stderr, including request tracebacks, must also land in a
log file under the workspace, so a problem can be read after the terminal has scrolled."""
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import logbook  # noqa: E402


class LogbookTests(unittest.TestCase):
    def test_lines_reach_both_the_terminal_and_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs/clipbench.log"
            terminal = io.StringIO()
            tee = logbook.start(path, terminal)
            print("listen vid failed: boom", file=tee)
            tee.flush()
            self.assertIn("listen vid failed: boom", terminal.getvalue())
            self.assertIn("listen vid failed: boom", path.read_text())

    def test_each_line_in_the_file_carries_a_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clipbench.log"
            tee = logbook.start(path, io.StringIO())
            tee.write("one\ntwo\n")
            tee.flush()
            lines = path.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertRegex(lines[0], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} one$")
            self.assertRegex(lines[1], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} two$")

    def test_a_partial_line_is_stamped_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clipbench.log"
            tee = logbook.start(path, io.StringIO())
            tee.write("Trace")
            tee.write("back\n")
            tee.flush()
            self.assertEqual(len(path.read_text().splitlines()), 1)
            self.assertTrue(path.read_text().rstrip().endswith(" Traceback"))

    def test_an_oversized_log_is_kept_once_as_the_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clipbench.log"
            path.write_text("x" * (logbook.MAX_BYTES + 1))
            logbook.start(path, io.StringIO())
            self.assertEqual(path.read_text(), "")
            self.assertEqual(len((Path(tmp) / "clipbench.previous.log").read_text()), logbook.MAX_BYTES + 1)

    def test_a_missing_log_folder_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a/b/clipbench.log"
            logbook.start(path, io.StringIO()).write("hi\n")
            self.assertTrue(path.is_file())

    def test_the_terminal_still_works_when_the_file_cannot_be_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / "file"
            blocked.write_text("")
            terminal = io.StringIO()
            tee = logbook.start(blocked / "clipbench.log", terminal)
            tee.write("still here\n")
            self.assertIn("still here", terminal.getvalue())
            self.assertIn("clipbench.log", terminal.getvalue())


import logging  # noqa: E402
import time  # noqa: E402
from unittest import mock  # noqa: E402

import clipper  # noqa: E402


class StructuredLoggingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "clipbench.log"
        self.terminal = io.StringIO()
        self.addCleanup(logbook.stop)

    def test_logger_lines_carry_level_and_name_in_the_file_and_only_the_message_on_the_terminal(self):
        logbook.start(self.path, self.terminal)
        logging.getLogger("clipbench.render").info("render %s done in %.1fs", "ep1", 3.2)
        self.assertRegex(self.path.read_text(), r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} INFO clipbench\.render: render ep1 done in 3\.2s")
        self.assertEqual(self.terminal.getvalue(), "render ep1 done in 3.2s\n")

    def test_a_traceback_goes_to_the_file_and_one_line_to_the_terminal(self):
        logbook.start(self.path, self.terminal)
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            logging.getLogger("clipbench").exception("listen %s failed", "ep1")
        text = self.path.read_text()
        self.assertIn("ERROR clipbench: listen ep1 failed", text)
        self.assertIn("Traceback (most recent call last)", text)
        self.assertIn("RuntimeError: boom", text)
        terminal = self.terminal.getvalue()
        self.assertEqual(len(terminal.strip().splitlines()), 1)
        self.assertIn("listen ep1 failed: RuntimeError: boom", terminal)
        self.assertIn("traceback in", terminal)

    def test_debug_lines_are_kept_only_when_asked(self):
        logbook.start(self.path, self.terminal)
        logging.getLogger("clipbench.http").debug("GET /api/library 200 3ms")
        self.assertNotIn("/api/library", self.path.read_text())
        logbook.stop()
        logbook.start(self.path, self.terminal, level="debug")
        logging.getLogger("clipbench.http").debug("GET /api/library 200 3ms")
        self.assertIn("/api/library", self.path.read_text())
        self.assertNotIn("/api/library", self.terminal.getvalue(), "debug noise stays off the terminal")

    def test_starting_twice_does_not_double_the_lines(self):
        logbook.start(self.path, self.terminal)
        logbook.start(self.path, self.terminal)
        logging.getLogger("clipbench").info("once")
        self.assertEqual(self.path.read_text().count("once"), 1)
        self.assertEqual(self.terminal.getvalue().count("once"), 1)


class RequestLevelTests(unittest.TestCase):
    def test_static_files_are_not_logged_unless_they_fail(self):
        self.assertIsNone(logbook.request_level("GET", "/app.js", 200))
        self.assertIsNone(logbook.request_level("GET", "/media/ep1.mp4", 206))
        self.assertEqual(logbook.request_level("GET", "/missing.css", 404), logging.WARNING)

    def test_api_reads_are_debug_and_api_writes_are_info(self):
        self.assertEqual(logbook.request_level("GET", "/api/library", 200), logging.DEBUG)
        self.assertEqual(logbook.request_level("POST", "/api/cut", 200), logging.INFO)

    def test_failures_are_warnings_and_server_errors_are_errors(self):
        self.assertEqual(logbook.request_level("POST", "/api/reframe", 400), logging.WARNING)
        self.assertEqual(logbook.request_level("GET", "/api/library", 500), logging.ERROR)


class HandlerRequestLogTests(unittest.TestCase):
    def test_each_api_request_is_logged_with_its_status_and_duration(self):
        handler = mock.Mock(command="POST", path="/api/cut", started=time.monotonic() - 0.05)
        with self.assertLogs("clipbench.http", "INFO") as logs:
            clipper.Handler.log_request(handler, 200)
        self.assertEqual(len(logs.output), 1)
        self.assertRegex(logs.output[0], r"INFO:clipbench\.http:POST /api/cut 200 \d+ms")

    def test_a_request_without_a_start_time_is_still_logged(self):
        handler = mock.Mock(command="GET", path="/api/library", spec=["command", "path"])
        with self.assertLogs("clipbench.http", "DEBUG") as logs:
            clipper.Handler.log_request(handler, 500)
        self.assertIn("GET /api/library 500", logs.output[0])
