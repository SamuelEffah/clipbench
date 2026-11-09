import shutil
import subprocess
import unittest
from pathlib import Path

TOP_START = (Path(__file__).resolve().parent / 'reference_top_start.js').read_text()


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class PreviewTimingPerformance(unittest.TestCase):
    def test_timing_uses_one_pass_and_matches_previous_calculations(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        source = (ui / 'app.js').read_text()
        def function(source, name):
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        code = function(source, 'previewTiming') + TOP_START
        code += function((ui / 'short.js').read_text(), 'laneTotal')
        script = r'''
const assert=require('node:assert/strict');
let reads=0,lengths=0;
const laneOf=c=>{reads++;return c.lane||'top';},isTop=c=>laneOf(c)==='top';
const outLen=c=>{lengths++;return c.len;},seamOverlap=(prev,c)=>prev?Math.min(prev.len/2,c.len/2,c.overlap||0):0;
const state={project:{clips:[]}},preview={idx:0};
''' + code + r'''
state.project.clips=Array.from({length:2000},()=>({len:5}));preview.idx=1800;
const timing=previewTiming();assert.equal(reads,2000);assert.equal(lengths,2000);
assert.equal(timing.total,10000);assert.equal(timing.start,9000);assert.equal(timing.place,1801);assert.equal(timing.tops,2000);
let seed=71;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
 const clips=Array.from({length:Math.floor(rand()*60)},()=>({lane:rand()<.3?'lower':'top',len:rand()<.2?0:rand()*10,overlap:rand()}));
 state.project.clips=clips;
 for(const idx of [-1,0,1,Math.floor(clips.length/2),clips.length-1,clips.length]) {
  preview.idx=idx;
  const lens=clips.map(c=>isTop(c)?outLen(c):0);
  assert.deepEqual(previewTiming(),{lens,total:laneTotal('top',clips),start:topStart(idx),tops:lens.filter(Boolean).length,place:lens.slice(0,idx+1).filter(Boolean).length});
 }
 // No timing cache may hide an in-place trim or lane edit.
 if(clips.length){clips[0].len=20;clips[0].lane='top';assert.equal(previewTiming().lens[0],20);}
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
