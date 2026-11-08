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

    def test_the_pick_is_one_moment_of_short_length_else_the_best(self):
        self.check(r'''
const moments = [{in: 0, out: 12}, {in: 20, out: 55}, {in: 100, out: 170}];
assert.equal(draftPick(moments).in, 20);
assert.equal(draftPick(moments.slice(0, 1)).in, 0);
assert.equal(draftPick([]), null);
''')

    def test_it_never_creates_a_project(self):
        source = (UI / "drafts.js").read_text()
        self.assertNotIn("/api/project", source)
        self.assertNotIn("loadProject", source)


if __name__ == "__main__":
    unittest.main()
