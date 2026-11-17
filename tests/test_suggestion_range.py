import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class SuggestionRange(unittest.TestCase):
    def test_preview_ranges_clip_to_view_and_disappear_outside_review(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/suggest.js').read_text()
        helper = 'function paintSuggestionRange() {' + source.split('function paintSuggestionRange() {', 1)[1].split('\nconst PROFILE_NOTE', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
let elements = [];
const strip = {querySelectorAll: () => [...elements], append: el => elements.push(el)};
const box = {hidden: false};
const $ = id => id === 'strip' ? strip : box;
const state = {mode: 'clip', current: {id: 'v'}};
const view = {s: 10, e: 40};
const suggestion = {vid: 'v', clips: [{in: 0, out: 50, pieces: [[0, 15], [25, 50]]}]};
const suggestionKey = s => `${s.in}:${s.out}`;
let suggestionPreview = '0:50';
const suggestPieces = s => s.pieces || [[s.in, s.out]];
const fmt = String;
const placeRange = (el, c) => { el.bounds = c; };
const document = {createElement: () => ({attributes: {}, children: [],
 setAttribute(k, v) {this.attributes[k] = v;}, append(el) {this.children.push(el);},
 remove() {elements = elements.filter(el => el !== this);}})};
''' + helper + r'''
paintSuggestionRange();
assert.deepEqual(elements.map(el => el.bounds), [{in: 10, out: 15}, {in: 25, out: 40}]);
assert.equal(elements[0].children[0].textContent, 'Preview · 1');
assert.equal(elements[1].attributes['aria-label'], 'Suggested range 25 to 50');
paintSuggestionRange();
assert.equal(elements.length, 2, 'repainting replaces previous overlays');
view.s = 16; view.e = 24; paintSuggestionRange();
assert.equal(elements.length, 0, 'gap between joined moments is not highlighted');
view.s = 0; view.e = 60; paintSuggestionRange(); assert.equal(elements.length, 2);
box.hidden = true; paintSuggestionRange(); assert.equal(elements.length, 0);
box.hidden = false; state.current.id = 'other'; paintSuggestionRange(); assert.equal(elements.length, 0);
state.current.id = 'v'; state.mode = 'short'; paintSuggestionRange(); assert.equal(elements.length, 0);
state.mode = 'clip'; suggestionPreview = null; paintSuggestionRange(); assert.equal(elements.length, 0);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
