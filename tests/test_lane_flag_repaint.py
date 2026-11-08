"""Muting or locking a lane repaints the timeline at once, so the header button and the lane show the new state."""
import shutil
import subprocess
import unittest
from pathlib import Path

LANES = Path(__file__).resolve().parents[1] / "scripts/clipper_ui/lanes.js"


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class LaneFlagRepaintTests(unittest.TestCase):
    def test_a_flag_change_repaints_the_timeline(self):
        source = LANES.read_text()
        code = "function setLaneFlag(" + source.split("function setLaneFlag(", 1)[1].split("\n// Make the sound", 1)[0]
        script = r'''
const assert = require('node:assert/strict');
const state = {project: {}};
const calls = [];
const changed = (keep, key) => calls.push(`changed:${keep}:${key}`);
const renderShortTl = () => calls.push('paint');
''' + code + r'''
setLaneFlag('laneMute', 'top', true);
assert.deepEqual(calls, ['changed:true:laneMute:top', 'paint']);
assert.deepEqual(state.project.laneMute, {top: true});
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
