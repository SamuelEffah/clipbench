import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class CaptionStyleLookup(unittest.TestCase):
    def test_long_caption_carry_is_linear_and_preserves_style_rules(self):
        ui = Path(__file__).resolve().parents[1] / "scripts/clipper_ui"
        source = (ui / "app.js").read_text()
        style = "function capStyleOf(clip) {" + source.split("function capStyleOf(clip) {", 1)[1].split("// The caption sits", 1)[0]
        captions = (ui / "captions.js").read_text()
        carry = "function captionOf(c) {" + captions.split("function captionOf(c) {", 1)[1].split("\nfunction paintCaption", 1)[0]
        script = """
const assert = require('node:assert/strict');
let reads = 0;
const state = {project: {clips: []}};
const isTop = c => !c.lane || c.lane === 'top';
const isSynced = c => Boolean(c.synced);
const capMoved = c => c.capX !== undefined && c.capY !== undefined;
const DEFAULT_LOOK = 'plain', DEFAULT_HIGHLIGHT = 'white';
state.project.clips = Array.from({length: 2000}, (_, i) => ({
  get caption() { reads++; return i === 0 ? 'Hello' : ''; }, capScale: i === 0 ? 2 : 9
}));
""" + style + carry + """
assert.equal(capStyleOf(state.project.clips.at(-1)).scale, 2);
assert.ok(reads < 20000, `${reads} caption reads`);
state.project.clips = [
  {caption:'First', capScale:2, capX:0.2, capY:0.3, capLook:'bold'},
  {caption:'', capScale:9},
  {lane:'bottom', caption:'Other lane', capScale:8},
  {caption:'', capStop:true, capScale:3},
  {caption:'', capRot:25},
  {caption:'Timed', synced:true, capScale:4},
  {caption:'', capScale:5, capHi:'blue'},
  {caption:'New', capScale:6},
  {caption:'', capScale:10},
];
const clips = state.project.clips;
assert.equal(capStyleOf(clips[1]).scale, 2);
assert.equal(capStyleOf(clips[2]).scale, 2);
assert.equal(capStyleOf(clips[3]).scale, 3);
assert.equal(capStyleOf(clips[4]).rot, 25);
assert.equal(capStyleOf(clips[6]).scale, 5);
assert.equal(capStyleOf(clips[8]).scale, 6);
assert.deepEqual(capStyleOf(clips[8]).at, [0.2, 0.3]);
assert.equal(capStyleOf(clips[8]).hi, 'blue');
assert.equal(capStyleOf({}).scale, 1);
clips[0].capScale = 7;
assert.equal(capStyleOf(clips[1]).scale, 7);
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
