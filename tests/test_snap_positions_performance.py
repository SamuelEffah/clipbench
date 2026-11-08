import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class SnapPositionsPerformance(unittest.TestCase):
    def test_trim_reuses_positions_and_other_callers_stay_fresh(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        source = (ui / 'snap.js').read_text()
        snapping = source.split('function showSnapLine(', 1)[0]
        trim = 'const laterInLane' + source.split('const laterInLane', 1)[1].split('// Scrubbing', 1)[0]
        timeline = (ui / 'timeline.js').read_text()
        positions = 'function clipStarts(' + timeline.split('function clipStarts(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
const state={project:{clips:[],markers:[7.1]}};
const preview={elapsed:2.2},SHORT_LIMIT=60,MIN_CLIP=.2;
let stlPps=20,scans=0;
const laneOf=c=>c.lane||'top',speedOf=c=>c.speed||1;
const outLen=c=>(c.out-c.in)/speedOf(c),seamOverlap=(p,c)=>p?(c.overlap||0):0;
const rampOf=()=> 'none',freezeOf=()=>0;
const audioOf=()=>[{id:'a',start:3.3,dur:2}];
const hideSnapLine=()=>{},showSnapLine=()=>{};
''' + positions + r'''
const calculateStarts=clipStarts;
clipStarts=clips=>{scans++;return calculateStarts(clips);};
''' + snapping + trim + r'''
state.project.clips=Array.from({length:2000},(_,i)=>({in:0,out:5,lane:i%2?'lower':'top',overlap:i%3?.2:0}));
const clips=state.project.clips,gi=1000,c=clips[gi],next={...c,out:5.08};
const starts=clipStarts(clips);
const expectedTargets=snapTargets({skipClips:laterInLane(gi)});
const end=starts[gi]+outLen(next);
let expected=null;
for(const at of expectedTargets){const delta=at-end;if(Math.abs(delta)<=8/stlPps&&(!expected||Math.abs(delta)<Math.abs(expected.delta)))expected={delta,at};}
scans=0;
const result=snapTrim(next,c,gi,'r',null,false);
assert.equal(scans,1,'enabled trim should calculate positions once');
assert.deepEqual(result,expected?{...next,out:Math.max(next.out+expected.delta,MIN_CLIP)}:next);
// Ordinary callers compute fresh positions after edits; supplied positions keep target ordering.
assert.deepEqual(snapTargets({starts}),snapTargets());
clips[0].out=8;
scans=0;
const fresh=snapTargets();assert.equal(scans,1);assert.equal(fresh[8],7.8);
assert.deepEqual(snapNear([3.31],{skipAudio:'a',noHead:true}),null);
assert.deepEqual(snapNear([3.31]),{delta:3.3-3.31,at:3.3});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
