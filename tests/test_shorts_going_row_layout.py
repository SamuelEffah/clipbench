"""A Short that is rendering (or has failed) is a row with only a text body and no thumbnail or buttons. The row is a
three column grid built for a finished Short, so that lone body fell into the 46px thumbnail column and wrapped the
name and the status word by word. It spans the whole row instead."""
import re
import unittest
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "scripts/clipper_ui/style.css").read_text()


def rule(selector):
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    return match.group(1) if match else ""


class GoingRowLayoutTests(unittest.TestCase):
    def test_a_body_with_no_thumbnail_spans_the_whole_row(self):
        self.assertIn("grid-column:1/-1", rule(".shrow>.sdbody:only-child").replace(" ", ""))

    def test_its_progress_bar_runs_the_width_of_the_row(self):
        bar = rule(".shrow>.sdbody:only-child .prog").replace(" ", "")
        self.assertIn("max-width:none", bar, "the shared 320px cap would leave it a stub")
        self.assertIn("height:6px", bar)


if __name__ == "__main__":
    unittest.main()
