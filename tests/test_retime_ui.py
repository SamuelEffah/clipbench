"""A trim that takes a clip past the speech that was timed gets its captions timed again, once the edits stop,
unless the caption was edited by hand or that range was already tried."""
import shutil
import subprocess
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "scripts" / "clipper_ui"

PRELUDE = r'''
const assert = require('assert');
const isTop = c => c.lane === "top";
const uncovered = c => c.out > c.wordsIn + c.wordsLen + 0.1;
const words = (...t) => t.map((w, i) => [w, i, i + 0.5]);
const clip = (over = {}) => ({lane: "top", src: "a", in: 10, out: 30, wordsIn: 10, wordsLen: 8, words: words("one", "two"), heard: words("one", "two"), caption: "one two", ...over});
'''


def run_js(body):
    source = (UI / "retime.js").read_text()
    return subprocess.run(["node", "-e", PRELUDE + source + body], capture_output=True, text=True)


@unittest.skipUnless(shutil.which("node"), "Node required")
class Retime(unittest.TestCase):
    def check(self, body):
        result = run_js(body)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_clip_trimmed_past_its_timed_speech_is_retimed_once_per_range(self):
        self.check(r"""
const tried = new Set();
assert.equal(retimeable(clip(), tried), true);
tried.add(retimeKey(clip()));
assert.equal(retimeable(clip(), tried), false, 'not the same range twice');
assert.equal(retimeable(clip({out: 31}), tried), true, 'a new range is tried');
assert.equal(retimeable(clip({out: 15}), new Set()), false, 'trimmed inward, the timed speech still covers it');
""")

    def test_a_caption_edited_by_hand_or_a_lower_lane_is_left_alone(self):
        self.check(r"""
assert.equal(retimeable(clip({caption: "one, two!"}), new Set()), false);
assert.equal(retimeable(clip({words: words("one", "too")}), new Set()), false);
assert.equal(retimeable(clip({lane: "bottom"}), new Set()), false);
""")

    def test_the_editor_asks_for_a_retime_after_each_change(self):
        app = (UI / "app.js").read_text()
        changed = app.split("function changed(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("scheduleRetime", changed)
        self.assertIn("/retime.js", (UI / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
