import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ScrubGesturePerformance(unittest.TestCase):
    def test_large_project_reuses_timing_across_scrub_positions_and_invalidates_edits(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/audio.js').read_text()
        code = 'function seekShort(' + source.split('function seekShort(', 1)[1].split('// The row whose', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let reads=0,editCount=0,started;
const isTop=c=>{reads++;return !c.lane||c.lane==='top';};
const outLen=c=>c.len,seamOverlap=(prev,c)=>prev?Math.min(prev.len/2,c.len/2,c.overlap||0):0;
const movingLen=c=>c.len-(c.freeze||0),sourceAt=(c,t)=>c.in+t,baseOf=()=>0;
const state={project:{clips:Array.from({length:2000},()=>({in:0,len:5}))},clipStop:null};
const preview={idx:-1,done:false},video={currentTime:0};
const startPreviewAt=(...args)=>started=args;
'''+code+r'''
for(let i=0;i<120;i++)seekShort(8000+i*.1);
assert.ok(reads<=4000,`120 scrub positions made ${reads} lane checks; expected one timing build`);
assert.equal(started[0],1602);
state.project.clips[0].len=10;editCount++;
seekShort(8000);assert.deepEqual(started,[1599,0]);
state.project.clips.push({in:0,len:5});seekShort(10004);assert.equal(started[0],1999);
'''
        result=subprocess.run(['node','-e',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
