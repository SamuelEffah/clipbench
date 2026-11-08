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
