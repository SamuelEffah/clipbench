import shutil
import subprocess
import unittest
from pathlib import Path

TOP_START = (Path(__file__).resolve().parent / 'reference_top_start.js').read_text()


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class ScrubLookupPerformance(unittest.TestCase):
    def test_scrubbing_scans_once_and_preserves_transition_and_hold_behavior(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        source = (ui / 'audio.js').read_text()
        seek = 'function seekShort(' + source.split('function seekShort(', 1)[1].split('// The row whose', 1)[0]
        start = TOP_START
        script = r'''
const assert=require('node:assert/strict');
let reads=0;
const isTop=c=>{reads++;return !c.lane||c.lane==='top';};
const outLen=c=>c.len,seamOverlap=(prev,c)=>prev?Math.min(prev.len/2,c.len/2,c.overlap||0):0;
const movingLen=c=>c.len-(c.freeze||0),sourceAt=(c,t)=>c.in+t,baseOf=()=>2;
const state={project:{clips:[]},clipStop:null},preview={idx:-1,done:false,elapsed:-1},video={currentTime:-1};
let started=null;const startPreviewAt=(...args)=>started=args;
''' + start + seek + r'''
state.project.clips=Array.from({length:2000},()=>({in:0,len:5}));
seekShort(9000);assert.ok(reads<=4000,`scrub made ${reads} lane checks`);
assert.deepEqual(started,[1800,0]);
let seed=33;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
 const clips=Array.from({length:Math.floor(rand()*40)},()=>({lane:rand()<.3?'lower':'top',in:rand()*5,len:rand()*10,overlap:rand(),freeze:rand()*.2}));
 state.project.clips=clips;
 for(const T of [-1,0,.0001,5,10,1000,...clips.map((_,i)=>topStart(i))]) {
  let idx=-1;clips.forEach((c,n)=>{if(isTop(c)&&topStart(n)<=T+.0001)idx=n;});
  const src=idx<0?null:sourceAt(clips[idx],Math.min(Math.max(0,T-topStart(idx)),movingLen(clips[idx])));
  for(const same of [false,true]) {
   preview.idx=same?idx:-1;preview.done=false;preview.elapsed=-1;started=null;video.currentTime=-1;
   const stop={holding:123,clip:clips[idx]};state.clipStop=stop;
   seekShort(T);
   if(idx<0){assert.equal(preview.elapsed,-1);assert.equal(video.currentTime,-1);assert.equal(started,null);continue;}
   assert.equal(preview.elapsed,T);
   if(same){assert.equal(video.currentTime,Math.max(0,src-2));assert.equal(state.clipStop.holding,0);assert.equal(started,null);}
   else {assert.deepEqual(started,[idx,src]);assert.equal(state.clipStop,stop);}
  }
 }
}
preview.idx=0;preview.done=true;state.project.clips=[{in:3,len:5}];started=null;
seekShort(1);assert.deepEqual(started,[0,4]);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
