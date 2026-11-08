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
    source = source[:source.index("const draftBtn")]
    return subprocess.run(["node", "-e", PRELUDE + source + body], capture_output=True, text=True)


@unittest.skipUnless(shutil.which("node"), "Node required")
class DraftLogic(unittest.TestCase):
    def check(self, body):
        result = run_js(body)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_moments_of_short_length_come_first_in_their_own_order_then_the_best_of_the_rest(self):
        self.check(r'''
const moments = [{in: 0, out: 12}, {in: 20, out: 55}, {in: 100, out: 170}, {in: 200, out: 232}, {in: 300, out: 345}];
assert.deepEqual(draftPicks(moments).map(m => m.in), [20, 200, 300]);
assert.deepEqual(draftPicks(moments.slice(0, 3)).map(m => m.in), [20, 0, 100]);
assert.deepEqual(draftPicks([]), []);
assert.deepEqual(draftPicks(moments, 1).map(m => m.in), [20]);
''')

    def test_draft_names_follow_the_project_and_skip_names_already_taken(self):
        self.check(r'''
assert.deepEqual(draftNames("jynxzi", ["jynxzi"], 3), ["jynxzi-draft-1", "jynxzi-draft-2", "jynxzi-draft-3"]);
assert.deepEqual(draftNames("jynxzi", ["jynxzi", "jynxzi-draft-1", "jynxzi-draft-3"], 2), ["jynxzi-draft-2", "jynxzi-draft-4"]);
assert.deepEqual(draftNames("jynxzi-draft-2", ["jynxzi-draft-2"], 1), ["jynxzi-draft-1"]);
const long = draftNames("x".repeat(70), [], 1)[0];
assert.ok(long.length <= 60, long);
assert.ok(/^x+-draft-1$/.test(long), long);
''')

    def test_a_draft_project_is_one_top_lane_clip_of_the_moment_in_a_vertical_short(self):
        self.check(r'''
const clip = {src: "/v/a.mp4", in: 20, out: 55, caption: "", fit: "fit", pan: 0.5};
const project = draftProject("jynxzi-draft-1", clip);
assert.equal(project.name, "jynxzi-draft-1");
assert.deepEqual(project.clips.map(c => [c.src, c.in, c.out, c.lane]), [["/v/a.mp4", 20, 55, "top"]]);
assert.deepEqual(project.bank.map(c => c.in), [20]);
assert.equal(project.format, "9:16");
assert.equal(project.template, "full");
assert.equal(project.watermark, true);
assert.deepEqual(project.audio, []);
assert.equal(clip.lane, undefined);
''')


if __name__ == "__main__":
    unittest.main()
