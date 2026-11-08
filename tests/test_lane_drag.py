"""Moving a clip along or between lanes follows the pointer: a ghost under the hand, the other clips sliding to make room,
the lane picked from where the pointer is, and Escape letting go. The browser's own drag and drop is not used, since it
gives a frozen snapshot, coarse events and no scrolling at the edges."""
import shutil
import subprocess
import unittest
from pathlib import Path

LANEDRAG = Path(__file__).resolve().parents[1] / "scripts/clipper_ui/lanedrag.js"

STUBS = r'''
const assert = require('node:assert/strict');
const calls = [];
const listeners = {};
const window = {
  addEventListener: (type, fn) => { (listeners[type] ||= new Set()).add(fn); },
  removeEventListener: (type, fn) => { listeners[type]?.delete(fn); },
};
const fire = (type, ev) => { for (const fn of [...(listeners[type] || [])]) fn({type, preventDefault() {}, ...ev}); };
const live = () => Object.values(listeners).reduce((n, set) => n + set.size, 0);
const classes = () => { const set = new Set(); return {add: (...c) => c.forEach(x => set.add(x)), remove: (...c) => c.forEach(x => set.delete(x)), contains: c => set.has(c), toggle(c, on) { on ? set.add(c) : set.delete(c); }}; };
const ghosts = [];
const makeBlock = () => ({
  style: {}, dataset: {}, classList: classes(), offsetWidth: 120, offsetHeight: 40,
  getBoundingClientRect: () => ({left: 80, top: 40, width: 120, height: 40}),
  cloneNode() { const g = {style: {}, classList: classes(), removed: false, remove() { this.removed = true; }, querySelectorAll: () => []}; ghosts.push(g); return g; },
  closest: () => null,
});
const document = {body: {append(el) { calls.push('ghost:append'); }, classList: classes()}};
const tracks = [
  {dataset: {lane: 'top'}, getBoundingClientRect: () => ({top: 30, bottom: 80})},
  {dataset: {lane: 'bottom'}, getBoundingClientRect: () => ({top: 100, bottom: 150})},
];
const stlBody = {scrollLeft: 0, clientWidth: 800, scrollWidth: 2000, classList: classes(),
  getBoundingClientRect: () => ({left: 0, width: 800}), querySelectorAll: sel => (sel.includes('stl-track') ? tracks : [])};
let dragPx = 0;
const state = {sel: 0, project: {clips: [{src: 'a', in: 0, out: 5}, {src: 'b', in: 0, out: 5, lane: 'bottom'}], laneLock: {}}};
const laneOf = c => c.lane || 'top';
const laneLocked = lane => Boolean(state.project.laneLock[lane]);
const lockedToast = () => calls.push('locked');
const showSlot = (e, lane) => calls.push(`slot:${lane}@${e.clientX}`);
const clearSlots = () => calls.push('clear');
const slotFromX = (e, lane) => 2;
const moveClip = (from, lane, k) => { calls.push(`move:${from}>${lane}#${k}`); state.sel = 1; };
const changed = () => calls.push('changed');
const restartPreviewAt = i => calls.push(`restart:${i}`);
const requestAnimationFrame = fn => 0, cancelAnimationFrame = () => {};
'''


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class LaneDragTests(unittest.TestCase):
    def run_node(self, script):
        result = subprocess.run(["node", "-e", STUBS + LANEDRAG.read_text() + script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_drag_shows_a_ghost_picks_the_lane_under_the_pointer_and_moves_the_clip_on_release(self):
        self.run_node(r'''
const block = makeBlock();
startLaneDrag({button: 0, clientX: 100, clientY: 50, target: block, preventDefault() {}}, 0, block);
fire('pointermove', {clientX: 102, clientY: 50});
assert.equal(ghosts.length, 0, 'a couple of pixels is a click, not a drag');
fire('pointermove', {clientX: 120, clientY: 55});
assert.equal(ghosts.length, 1, 'past the threshold a ghost appears');
assert.ok(block.classList.contains('dragging'));
assert.equal(dragPx, 120, 'the others open a gap the size of the clip');
assert.deepEqual(calls.filter(c => c.startsWith('slot')), ['slot:top@120']);
assert.equal(ghosts[0].style.left, '100px', 'the ghost keeps the grab point under the hand');
fire('pointermove', {clientX: 300, clientY: 120});
assert.equal(calls.filter(c => c.startsWith('slot')).at(-1), 'slot:bottom@300', 'the lane under the pointer takes it');
fire('pointerup', {clientX: 300, clientY: 120});
assert.ok(ghosts[0].removed);
assert.ok(!block.classList.contains('dragging'));
assert.equal(dragPx, 0);
assert.deepEqual(calls.slice(-4), ['clear', 'move:0>bottom#2', 'changed', 'restart:1']);
assert.equal(block.dataset.moved, '1', 'the click that follows a drag is not a pick');
assert.equal(live(), 0, 'nothing is left listening');
''')

    def test_escape_lets_go_and_a_locked_lane_refuses(self):
        self.run_node(r'''
const block = makeBlock();
startLaneDrag({button: 0, clientX: 100, clientY: 50, target: block, preventDefault() {}}, 0, block);
fire('pointermove', {clientX: 140, clientY: 50});
fire('keydown', {key: 'Escape'});
assert.ok(ghosts[0].removed);
assert.ok(!calls.some(c => c.startsWith('move')));
assert.equal(calls.at(-1), 'clear');
assert.equal(live(), 0);
calls.length = 0;
state.project.laneLock.bottom = true;
startLaneDrag({button: 0, clientX: 100, clientY: 50, target: block, preventDefault() {}}, 0, block);
fire('pointermove', {clientX: 140, clientY: 120});
fire('pointerup', {clientX: 140, clientY: 120});
assert.ok(calls.includes('locked'));
assert.ok(!calls.some(c => c.startsWith('move')));
''')

    def test_a_pointer_near_an_edge_scrolls_the_timeline(self):
        self.run_node(r'''
const box = {left: 0, width: 800};
assert.ok(edgeScrollStep(10, box) < 0, 'near the left edge the timeline scrolls back');
assert.ok(edgeScrollStep(795, box) > 0, 'near the right edge it scrolls on');
assert.equal(edgeScrollStep(400, box), 0);
assert.ok(Math.abs(edgeScrollStep(2, box)) > Math.abs(edgeScrollStep(30, box)), 'closer to the edge scrolls faster');
assert.equal(laneAtY(tracks, 55), 'top');
assert.equal(laneAtY(tracks, 120), 'bottom');
assert.equal(laneAtY(tracks, 90), 'top', 'between lanes the nearer one takes it');
assert.equal(laneAtY(tracks, 95), 'bottom');
''')


if __name__ == "__main__":
    unittest.main()
