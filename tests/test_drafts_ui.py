import shutil
import subprocess
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "scripts" / "clipper_ui"

PRELUDE = r'''
const assert = require('assert');
'''


def run_js(body):
    source = (UI / "drafts.js").read_text()
    source = source[:source.index("draftButtons.forEach(b => b.addEventListener")].replace("const draftButtons = document.querySelectorAll(\"[data-draft]\");", "")
    return subprocess.run(["node", "-e", PRELUDE + source + body], capture_output=True, text=True)


@unittest.skipUnless(shutil.which("node"), "Node required")
class DraftLogic(unittest.TestCase):
    def check(self, body):
        result = run_js(body)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_bank_that_fits_is_used_whole_in_video_order(self):
        self.check(r'''
const bank = [{src: "a", in: 300, out: 320}, {src: "a", in: 100, out: 120}, {src: "b", in: 5, out: 15}];
assert.deepEqual(draftPlan(bank).map(c => [c.src, c.in, c.out]), [["a", 100, 120], ["a", 300, 320], ["b", 5, 15]]);
''')

    def test_a_long_bank_is_cut_down_by_a_share_around_the_best_moments(self):
        self.check(r'''
const bank = [{src: "a", in: 0, out: 70}, {src: "a", in: 200, out: 220}, {src: "a", in: 300, out: 320}];
const moments = src => [{in: 40, out: 50, score: 0.9}, {in: 5, out: 15, score: 0.2}];
const plan = draftPlan(bank, moments);
assert.ok(Math.abs(plan.reduce((n, c) => n + c.out - c.in, 0) - 60) < 0.1);
assert.ok(plan[0].out - plan[0].in > plan[1].out - plan[1].in, 'the long clip keeps the most');
assert.ok(plan.every(c => c.out - c.in >= 8));
assert.ok(plan[0].in <= 40 && plan[0].out >= 50 && plan[0].in >= 0 && plan[0].out <= 70, 'the long one keeps its best moment');
''')

    def test_when_every_clip_is_at_the_floor_the_lowest_scored_are_dropped(self):
        self.check(r'''
const bank = Array.from({length: 10}, (_, i) => ({src: "a", in: i * 100, out: i * 100 + 8}));
const moments = () => [{in: 0, out: 8, score: 0.9}];
const plan = draftPlan(bank, moments);
assert.ok(plan.length <= 7 && plan.reduce((n, c) => n + c.out - c.in, 0) <= 60.05);
assert.equal(plan[0].in, 0, 'the scored one is kept');
''')

    def test_it_never_creates_a_project(self):
        source = (UI / "drafts.js").read_text()
        self.assertNotIn("/api/project", source)
        self.assertNotIn("loadProject", source)

    def test_the_button_is_in_both_clips_panels(self):
        html = (UI / "index.html").read_text()
        rail = html.split('data-panel="clips"', 1)[1].split("</section>", 1)[0]
        station = html.split('id="panelClip"', 1)[1].split('id="liveCaps"', 1)[0]
        self.assertIn("data-draft", rail)
        self.assertIn("data-draft", station)


if __name__ == "__main__":
    unittest.main()
