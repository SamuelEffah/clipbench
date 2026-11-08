import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class MirrorDrawing(unittest.TestCase):
    def test_hidden_preview_skips_canvas_work_but_visible_preview_draws(self):
        source = (Path(__file__).resolve().parents[1] / "scripts/clipper_ui/app.js").read_text()
        draw = source.split("function drawMirror() {", 1)[1].split("\nlet rendering =", 1)[0]
        script = """
const assert = require('node:assert/strict');
let hidden = true, fills = 0, pictures = 0;
const $ = id => { assert.equal(id, 'theater'); return {hidden}; };
const video = {videoWidth: 1920};
const mirror = {width: 480, height: 270};
const mctx = {fillRect() { fills++; }};
const inShort = () => false;
const preview = {on: false};
const paintClip = () => pictures++;
const paintTransition = () => {};
""" + "\nfunction drawMirror() {" + draw + """
for (let i = 0; i < 120; i++) drawMirror();
assert.equal(fills, 0);
assert.equal(pictures, 0);
hidden = false;
drawMirror();
assert.equal(fills, 1);
assert.equal(pictures, 1);
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
