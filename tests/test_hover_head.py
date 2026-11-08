"""A faint playhead follows the pointer over the bare Short timeline and says the time there; a click on that bare spot
puts the playhead at exactly that moment. Over a clip, a sound or a caption nothing shows, and a drag is left to the marquee."""
import shutil
import subprocess
import unittest
from pathlib import Path

HOVERHEAD = Path(__file__).resolve().parents[1] / "scripts/clipper_ui/hoverhead.js"

STUBS = r'''
const assert = require('node:assert/strict');
const calls = [];
const classes = () => { const set = new Set(); return {add: (...c) => c.forEach(x => set.add(x)), remove: (...c) => c.forEach(x => set.delete(x)), contains: c => set.has(c)}; };
const listeners = {};
const children = [];
const stlBody = {classList: classes(), contains: el => el !== outsider, addEventListener: (t, fn) => { listeners[t] = fn; }, append: el => children.push(el)};
const fire = (t, ev) => listeners[t](ev);
const document = {body: {classList: classes()}, createElement: () => { const el = {style: {}, firstChild: {}, removed: false, remove() { this.removed = true; }}; Object.defineProperty(el, 'innerHTML', {set() {}}); return el; }};
const track = {offsetLeft: 40, offsetTop: 20};
const bare = {matches: sel => sel.includes('.stl-track')};
const clipBlock = {matches: () => false};
const outsider = {matches: () => true};
let mode = 'short', pps = 10;
const inShort = () => mode === 'short';
const stlPps = pps;
const timeTrack = () => track;
const scrubTime = e => (e.clientX - 100) / 10;
const preview = {on: true};
const openPreview = () => { calls.push('open'); preview.on = true; };
const seekShort = t => calls.push(`seek:${t}`);
const paintPlayhead = () => calls.push('paint');
'''


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class HoverHeadTests(unittest.TestCase):
    def run_node(self, script):
        result = subprocess.run(["node", "-e", STUBS + HOVERHEAD.read_text() + script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_faint_head_follows_the_pointer_over_bare_timeline_and_hides_over_a_clip(self):
        self.run_node(r'''
fire('pointermove', {target: bare, clientX: 250});
assert.equal(children.length, 1);
assert.equal(children[0].style.left, '190px', '40px of header plus 15s at 10px a second');
assert.equal(children[0].firstChild.textContent, '0:15.0');
fire('pointermove', {target: bare, clientX: 1300});
assert.equal(children[0].firstChild.textContent, '2:00.0');
assert.equal(children.length, 1, 'one head, moved, not one per move');
fire('pointermove', {target: clipBlock, clientX: 260});
assert.ok(children[0].removed, 'nothing over a clip');
fire('pointermove', {target: bare, clientX: 260});
assert.equal(children.length, 2);
fire('pointerleave', {});
assert.ok(children[1].removed);
document.body.classList.add('lane-dragging');
fire('pointermove', {target: bare, clientX: 260});
assert.equal(children.length, 2, 'not while a clip is being dragged');
''')

    def test_a_click_on_a_bare_spot_puts_the_playhead_there_and_a_drag_does_not(self):
        self.run_node(r'''
fire('pointerdown', {button: 0, target: bare, clientX: 250, clientY: 50});
fire('pointerup', {clientX: 251, clientY: 50});
assert.deepEqual(calls, ['seek:15', 'paint']);
calls.length = 0;
fire('pointerdown', {button: 0, target: bare, clientX: 250, clientY: 50});
fire('pointerup', {clientX: 300, clientY: 80});
assert.deepEqual(calls, [], 'a drag is the marquee, not a seek');
fire('pointerdown', {button: 0, target: clipBlock, clientX: 250, clientY: 50});
fire('pointerup', {clientX: 250, clientY: 50});
assert.deepEqual(calls, [], 'a click on a clip picks the clip, as before');
fire('pointerdown', {button: 2, target: bare, clientX: 250, clientY: 50});
fire('pointerup', {clientX: 250, clientY: 50});
assert.deepEqual(calls, [], 'the right button opens the menu, as before');
preview.on = false;
fire('pointerdown', {button: 0, target: bare, clientX: 300, clientY: 50});
fire('pointerup', {clientX: 300, clientY: 50});
assert.deepEqual(calls, ['open', 'seek:20', 'paint'], 'with the preview closed, a click opens it at that moment');
''')


if __name__ == "__main__":
    unittest.main()
