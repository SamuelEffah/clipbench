import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class SourceClipInspector(unittest.TestCase):
    def test_opening_settings_stops_previous_preview_and_seeks_selected_clip(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/short.js').read_text()
        helper = 'function openSourceClipDetails(i) {' + source.split('function openSourceClipDetails(i) {', 1)[1].split('\nfunction renderSourceClipDetails', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
let short = false, suggestionPreview = 'old', paused = false, reset = false, tab, focused = false;
const state = {project: {clips: [{src: 'first', in: 10}, {src: 'second', in: 42}]}, current: {path: 'first'}, clipStop: {out: 90}, sel: 0};
const video = {currentTime: 19, pause() {paused = true;}};
const inShort = () => short;
const resetPlayback = () => {reset = true;};
const select = i => {state.sel = i;};
const setTab = value => {tab = value;};
const $ = () => ({focus() {focused = true;}});
''' + helper + r'''
openSourceClipDetails(0);
assert.equal(paused, true); assert.equal(reset, true); assert.equal(state.clipStop, null);
assert.equal(suggestionPreview, null); assert.equal(video.currentTime, 10);
assert.equal(tab, 'details'); assert.equal(focused, true);
video.currentTime = 19; openSourceClipDetails(1);
assert.equal(state.sel, 1); assert.equal(video.currentTime, 19, 'do not seek the old video while a different source loads');
short = true; tab = null; openSourceClipDetails(0); assert.equal(tab, null);
short = false; openSourceClipDetails(9); assert.equal(tab, null);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
