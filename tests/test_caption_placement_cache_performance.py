import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class CaptionPlacementCachePerformance(unittest.TestCase):
    def test_stable_preview_reuses_style_and_edits_and_selection_refresh_it(self):
        app = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        style = 'function capStyleOf(clip) {' + app.split('function capStyleOf(clip) {', 1)[1].split('// The caption sits', 1)[0]
        place = 'function placeCaption(clip) {' + app.split('function placeCaption(clip) {', 1)[1].split('// The selection frame', 1)[0]
        script = r'''
const assert=require('node:assert/strict');let reads=0,syncs=0,sizes=[],width=1080,size=40;
const state={project:{clips:[]}},isTop=c=>{reads++;return !c.lane||c.lane==='top';},isSynced=c=>Boolean(c.synced);
const capMoved=c=>c&&c.capX!=null&&c.capY!=null,DEFAULT_LOOK='classic',DEFAULT_HIGHLIGHT='yellow';
const el={dataset:{},style:{}},$=()=>el;let capHome={width:1000,bottom:1800};
const canvasOf=()=>[width,1920],captionSize=()=>size;
const applyCaptionSize=(...args)=>sizes.push(args),syncCapSel=st=>{syncs++;assert.ok(st);};
''' + style + place + r'''
state.project.clips=Array.from({length:2000},(_,i)=>({caption:i===0?'carry':'',capScale:i===0?2:9}));
let clip=state.project.clips.at(-1);placeCaption(clip);assert.equal(sizes.at(-1)[0],2);
reads=0;for(let n=0;n<120;n++)placeCaption(clip);
assert.equal(reads,0,'stable frames should not rescan inherited styles');assert.equal(syncs,121);
// An inherited style edit replaces the list while retaining the current clip.
state.project.clips=state.project.clips.map((c,i)=>i===0?{...c,capScale:3}:c);
placeCaption(clip);assert.equal(sizes.at(-1)[0],3);assert.ok(reads>0);
// The active clip and project changes also invalidate the cached result.
state.project.clips=[{caption:'first',capScale:1},{caption:'second',capScale:1.5}];
placeCaption(state.project.clips[0]);assert.equal(sizes.at(-1)[0],1);
placeCaption(state.project.clips[1]);assert.equal(sizes.at(-1)[0],1.5);
const before=sizes.length;width=720;placeCaption(state.project.clips[1]);assert.equal(sizes.length,before+1);
size=50;placeCaption(state.project.clips[1]);assert.equal(sizes.length,before+2);
placeCaption(null);assert.equal(sizes.at(-1)[0],1);
capHome=null;const count=syncs;placeCaption(clip);assert.equal(syncs,count);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
