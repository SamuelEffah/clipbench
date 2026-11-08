import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class CaptionModeTargetsPerformance(unittest.TestCase):
    def test_inherited_captions_are_resolved_once_for_bulk_modes(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        text = (ui / 'textpanel.js').read_text()
        targets = 'function captionModeTargets(' + text.split('function captionModeTargets(', 1)[1].split('async function applyCaptionMode(', 1)[0]
        short = (ui / 'short.js').read_text()
        runs = 'function captionRuns(' + short.split('function captionRuns(', 1)[1].split('\nfunction textRow(', 1)[0]
        captions = (ui / 'captions.js').read_text()
        caption = 'function captionOf(' + captions.split('function captionOf(', 1)[1].split('\nfunction paintCaption(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const state={project:{clips:[]}},isTop=c=>!c.lane||c.lane==='top',isSynced=c=>Boolean(c.synced);
''' + runs + caption + targets + r'''
let reads=0;
state.project.clips=Array.from({length:2000},(_,i)=>({get caption(){reads++;return i===0?'Carry':'';}}));
const got=captionModeTargets(state.project.clips,0,true);
assert.deepEqual(got,Array.from({length:2000},(_,i)=>i));
assert.ok(reads<=4000,`${reads} caption reads for a single inherited caption`);
let seed=11;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
 const clips=Array.from({length:40},(_,i)=>({caption:rand()<.25?`Text${i}`:'',lane:rand()<.3?'lower':'top',capStop:rand()<.2,synced:rand()<.3}));
 state.project.clips=clips;
 for(const all of [false,true])for(const here of [-1,0,15,39]) {
  const expected=clips.map((_,n)=>n).filter(n=>(n===here||all)&&isTop(clips[n])&&captionOf(clips[n]));
  assert.deepEqual(captionModeTargets(clips,here,all),expected);
 }
}
assert.deepEqual(captionModeTargets([], -1, true),[]);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
