import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class ClipDurationPerformance(unittest.TestCase):
    def test_normal_duration_avoids_ramp_reduction_and_ramps_read_fields_once(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        timing = 'const speedOf' + source.split('const speedOf', 1)[1].split('\nfunction outTimeAt(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
''' + timing + r'''
let reductions=0;const reduce=RAMPS.none.reduce;
RAMPS.none.reduce=function(...args){reductions++;return reduce.apply(this,args);};
for(let i=0;i<120;i++)assert.equal(movingLen({in:2,out:12,speed:2}),5);
assert.equal(reductions,0,'normal-speed profiles must not allocate and run a ramp reducer');
let ins=0,outs=0,speeds=0;
const clip={ramp:'hero',get in(){ins++;return 2;},get out(){outs++;return 12;},get speed(){speeds++;return 2;}};
movingLen(clip);assert.equal(ins,1);assert.equal(outs,1);assert.equal(speeds,1);
const previous=c=>stretches(c).reduce((sum,[a,b,r])=>sum+(b-a)*(c.out-c.in)/(speedOf(c)*r),0);
let seed=12;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let i=0;i<10000;i++) {
 const start=rand()*1000,c={in:start,out:start+rand()*100,speed:[undefined,0,.5,1,1.5,2,4][i%7],ramp:[undefined,'none','hero','slowdown','speedup','unknown'][i%6],freeze:rand()*3};
 assert.equal(movingLen(c),previous(c));assert.equal(outLen(c),previous(c)+freezeOf(c));
}
for(const c of [{in:0,out:0},{in:0,out:-0},{in:2,out:1},{in:0,out:Infinity},{in:NaN,out:1}])assert.equal(movingLen(c),previous(c));
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
