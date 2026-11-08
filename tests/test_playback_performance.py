import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class PlaybackUpdates(unittest.TestCase):
    def test_unchanged_frames_do_not_rewrite_controls_and_changes_still_appear(self):
        source = (Path(__file__).resolve().parents[1] / "scripts/clipper_ui/app.js").read_text()
        place = "function setPlaybackValue(" + source.split("function setPlaybackValue(", 1)[1].split("\nfunction renderRuler()", 1)[0]
        update = source.split("function updateTime() {", 1)[1].split("\nfunction seekBy", 1)[0]
        script = """
const assert = require('node:assert/strict');
let writes = 0;
function tracked(initial) {
  return new Proxy(initial, {set(target, key, value) {
    writes++; target[key] = value; return true;
  }});
}
const icon = {href: '', getAttribute() { return this.href; },
  setAttribute(key, value) { writes++; this.href = value; }};
const ids = {};
const $ = id => ids[id] ||= tracked({textContent: '', hidden: false,
  style: tracked({left: '', width: ''}), querySelector: () => icon});
const video = {duration: 60, currentTime: 2, paused: true};
const clip = {src: '/video', in: 0, out: 5, caption: 'Hello'};
const state = {current: {duration: 60, path: '/video'},
  project: {clips: [clip]}, pendingIn: null, pendingOut: null};
const view = {s: 0, e: 60};
const fmt = t => String(t);
const pos = t => (t - view.s) / (view.e - view.s) * 100;
""" + "\n" + place + "\nfunction updateTime() {" + update + """
updateTime();
writes = 0;
for (let i = 0; i < 120; i++) updateTime();
assert.equal(writes, 0, 'unchanged paused frames should not mutate DOM');
video.currentTime = 3; video.paused = false;
updateTime();
assert.equal($('tcNow').textContent, '3');
assert.equal(icon.href, '#c-pause');
assert.equal($('playhead').style.left, '5%');
clip.caption = 'Edited'; updateTime();
assert.equal($('srcSub').textContent, 'Edited');
video.currentTime = 6; updateTime();
assert.equal($('srcSub').textContent, '');
state.pendingIn = 2; state.pendingOut = 4; updateTime();
assert.equal($('pendfill').style.width, `${pos(4) - pos(2)}%`);
view.e = 12; updateTime();
assert.equal($('playhead').style.left, '50%');
state.current = null; video.duration = NaN; updateTime();
assert.equal($('phRuler').hidden, true);
assert.equal($('tcTot').textContent, '0');
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
