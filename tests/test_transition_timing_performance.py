import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class TransitionTimingPerformance(unittest.TestCase):
    def test_preview_reuses_durations_for_transition_overlap(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        app = (ui / 'app.js').read_text()
        short = (ui / 'short.js').read_text()
        def function(source, name):
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
let durations=0;
const outLen=c=>{durations++;return c.len;},laneOf=c=>c.lane||'top',isTop=c=>laneOf(c)==='top';
const transitionOf=c=>c.transition||'none',tlenOf=c=>c.tlen||.3;
const state={project:{clips:[]}},preview={idx:1000};
''' + function(app, 'seamOverlap') + function(app, 'previewTiming') + function(app, 'topStart') + function(short, 'laneTotal') + r'''
state.project.clips=Array.from({length:2000},()=>({len:5,transition:'fade'}));
const got=previewTiming();assert.equal(durations,2000,'transition preview must calculate each duration only once');
const reference=()=>{const lens=state.project.clips.map(c=>isTop(c)?outLen(c):0);return {lens,total:laneTotal('top',state.project.clips),start:topStart(preview.idx),tops:lens.filter(Boolean).length,place:lens.slice(0,preview.idx+1).filter(Boolean).length};};
assert.deepEqual(got,reference());
let seed=84;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
 state.project.clips=Array.from({length:40},()=>({len:rand()<.2?0:rand()*10,transition:rand()<.3?'none':'fade',lane:rand()<.3?'lower':'top',tlen:rand()*2}));
 for(const idx of [-1,0,1,20,39,40]){preview.idx=idx;assert.deepEqual(previewTiming(),reference());}
 const [a,b]=state.project.clips;
 const before=outLen(a),current=outLen(b),expected=seamOverlap(a,b);
 durations=0;assert.equal(seamOverlap(a,b,before,current),expected);assert.equal(durations,0,'supplied durations must bypass timing work');
}
// Existing two-argument callers retain clamping, rounding, and transition exclusions.
durations=0;assert.equal(seamOverlap({len:5},{len:5,transition:'fade'}),.3);assert.equal(durations,2);
assert.equal(seamOverlap({len:.05},{len:5,transition:'fade'}),0);
assert.equal(seamOverlap({len:1},{len:5,transition:'fade',tlen:1.5}),.5);
assert.equal(seamOverlap({len:5},{len:5}),0);assert.equal(seamOverlap(null,{len:5,transition:'fade'}),0);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
