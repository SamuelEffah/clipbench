"""Trimming a clip on the timeline moves everything that depends on it while the handle is still held: the clips after
it in the lane, their sound, and the caption chips, so nothing jumps when the handle is let go. The clip's left edge
stays where it is on either trim, because a lane is a chain and the clip still starts where the one before it ends."""
import shutil
import subprocess
import unittest
from pathlib import Path

SHORT = Path(__file__).resolve().parents[1] / "scripts/clipper_ui/short.js"

STUBS = r'''
const assert = require('node:assert/strict');
const calls = [];
const classes = () => { const set = new Set(); return {add: (...c) => c.forEach(x => set.add(x)), remove: (...c) => c.forEach(x => set.delete(x)), contains: c => set.has(c)}; };
const node = (extra = {}) => { const listeners = {}; return {style: {}, dataset: {}, classList: classes(),
  addEventListener: (t, fn) => { listeners[t] = fn; }, removeEventListener: t => { delete listeners[t]; }, setPointerCapture() {},
  fire: (t, ev) => listeners[t] && listeners[t]({preventDefault() {}, stopPropagation() {}, ...ev}), listening: () => Object.keys(listeners).length, ...extra}; };
const clips = [{src: 'a', in: 0, out: 10}, {src: 'a', in: 20, out: 25}, {src: 'a', in: 0, out: 8, lane: 'bottom'}, {src: 'a', in: 30, out: 32}];
const state = {project: {clips}};
const blocks = clips.map((c, gi) => Object.assign(node(), {dataset: {gi: String(gi), lane: c.lane || 'top'}}));
blocks[0].style = {left: '0px', width: '100px'}; blocks[1].style = {left: '100px', width: '50px'}; blocks[2].style = {left: '0px', width: '80px'}; blocks[3].style = {left: '150px', width: '20px'};
const snds = clips.map((c, gi) => Object.assign(node(), {dataset: {gi: String(gi)}, style: {width: `${(c.out - c.in) * 10}px`}}));
const chips = [Object.assign(node(), {dataset: {head: '0', last: '0'}, style: {width: '100px'}}), Object.assign(node(), {dataset: {head: '1', last: '3'}, style: {width: '70px'}})];
const stlBody = {classList: classes(), querySelectorAll: sel => (sel.includes('stl-clip') ? blocks : sel.includes('stl-snd') ? snds : sel.includes('stl-cap') ? chips : [])};
const laneOf = c => c.lane || 'top';
const outLen = c => c.out - c.in;
const blockedByLock = () => false, rollOnTimeline = () => false, byPath = () => ({duration: 100}), speedOf = () => 1;
const stlPps = 10, MIN_CLIP = 0.2;
const snapTrim = next => next, hideSnapLine = () => {};
const setClipField = (i, patch) => calls.push(['set', i, patch]);
const restartPreviewAt = i => calls.push(['restart', i]);
'''


def code():
    source = SHORT.read_text()
    return "function rippleLane(" + source.split("function rippleLane(", 1)[1].split("\nfunction laneRow(", 1)[0]


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class TrimRippleTests(unittest.TestCase):
    def run_node(self, script):
        result = subprocess.run(["node", "-e", STUBS + code() + script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_lane_follows_a_trim_of_the_end_live_and_settles_once_on_release(self):
        self.run_node(r'''
const block = blocks[0];
trimOnTimeline({button: 0, clientX: 100, pointerId: 1, preventDefault() {}, stopPropagation() {}}, 0, 'r', block);
block.fire('pointermove', {clientX: 130});
assert.equal(block.style.width, '130px');
assert.equal(block.style.left, '0px');
assert.equal(blocks[1].style.transform, 'translateX(30px)', 'the next clip in the lane moves along');
assert.equal(blocks[3].style.transform, 'translateX(30px)');
assert.equal(blocks[2].style.transform, undefined, 'another lane is not touched');
assert.equal(snds[0].style.width, '130px', 'the clip\'s own sound grows with it');
assert.equal(snds[1].style.transform, 'translateX(30px)');
assert.equal(snds[2].style.transform, undefined);
assert.equal(chips[0].style.width, '130px', 'the caption over the clip grows with it');
assert.equal(chips[1].style.transform, 'translateX(30px)');
assert.ok(stlBody.classList.contains('trimming'));
block.fire('pointermove', {clientX: 90});
assert.equal(blocks[1].style.transform, 'translateX(-10px)');
block.fire('pointerup', {});
assert.equal(blocks[1].style.transform, '', 'transforms are gone before the rebuild');
assert.equal(snds[1].style.transform, '');
assert.equal(chips[1].style.transform, '');
assert.ok(!stlBody.classList.contains('trimming'));
assert.deepEqual(calls, [['set', 0, {in: 0, out: 9}], ['restart', 0]]);
assert.equal(block.listening(), 0);
''')

    def test_a_trim_of_the_start_keeps_the_clip_where_it_begins(self):
        self.run_node(r'''
const block = blocks[0];
trimOnTimeline({button: 0, clientX: 0, pointerId: 1, preventDefault() {}, stopPropagation() {}}, 0, 'l', block);
block.fire('pointermove', {clientX: 20});
assert.equal(block.style.left, '0px', 'a lane is a chain: the clip still starts where the one before it ends');
assert.equal(block.style.width, '80px');
assert.equal(blocks[1].style.transform, 'translateX(-20px)');
assert.equal(chips[0].style.width, '80px');
block.fire('pointerup', {});
assert.deepEqual(calls, [['set', 0, {in: 2, out: 10}], ['restart', 0]]);
''')

    def test_letting_go_without_moving_changes_nothing(self):
        self.run_node(r'''
const block = blocks[1];
trimOnTimeline({button: 0, clientX: 150, pointerId: 1, preventDefault() {}, stopPropagation() {}}, 1, 'r', block);
block.fire('pointerup', {});
assert.deepEqual(calls, []);
assert.ok(!stlBody.classList.contains('trimming'));
''')


if __name__ == "__main__":
    unittest.main()
