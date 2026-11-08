import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class LibraryRenderPerformance(unittest.TestCase):
    def test_counts_clips_once_and_preserves_source_rows(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        render = 'function renderLibrary() {' + source.split('function renderLibrary() {', 1)[1].split('// A stream', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
let reads = 0, sourceReads = 0, opened, removed;
const clips = Array.from({length: 4000}, (_, i) => ({get src() { reads++; return `p${i % 200}`; }}));
const sources = Array.from({length: 201}, (_, i) => ({path:`p${i}`, id:i, name:`Video ${i}`, duration:10}));
const state = {project:{clips}, current:sources[1]};
const box = {children:[], set innerHTML(v) { this.html=v; this.children=[]; }, appendChild(el) { this.children.push(el); }};
const tab = {};
const $ = id => id === 'library' ? box : tab;
const sourcesOf = () => { sourceReads++; return sources; };
let liveWanted = false;
const liveRowWanted = () => liveWanted;
const liveSourceRow = () => ({live:true});
const fmt = String, esc = String;
const openVideo = v => opened=v;
const askRemoveVideo = v => removed=v;
const document = {createElement() { return {attrs:{}, button:{}, setAttribute(k,v) { this.attrs[k]=v; }, querySelector() { return this.button; }}; }};
''' + render + r'''
renderLibrary();
assert.equal(box.children.length, 201);
assert.ok(box.children[0].innerHTML.includes('20 clips'));
assert.ok(box.children[200].innerHTML.includes('0 clips'));
assert.equal(box.children[1].attrs['aria-current'], true);
box.children[1].onclick(); assert.equal(opened, sources[1]);
box.children[2].onkeydown({key:'Enter'}); assert.equal(opened, sources[2]);
let stopped=false;
box.children[3].button.onclick({stopPropagation(){stopped=true;}});
assert.equal(removed, sources[3]); assert.ok(stopped);
assert.ok(reads <= clips.length, `${reads} clip source reads`);
assert.equal(sourceReads, 1);
// Counts reflect edits on the next render, including singular labels.
state.project.clips = [{src:'p0'}];
renderLibrary(); assert.ok(box.children[0].innerHTML.includes('1 clip</small>'));
sources.length = 0;
renderLibrary(); assert.ok(box.html.includes('No videos yet.'));
liveWanted = true;
renderLibrary(); assert.deepEqual(box.children, [{live:true}]);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
