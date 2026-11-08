import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class ClipTimeMappingPerformance(unittest.TestCase):
    def test_time_mapping_reads_timing_fields_once_per_needed_value(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        timing = 'const speedOf' + source.split('const speedOf', 1)[1].split('\nfunction speedAt(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
''' + timing + r'''
let ins=0,outs=0,speeds=0;
const clip={get in(){ins++;return 2;},get out(){outs++;return 12;},get speed(){speeds++;return 2;},ramp:'hero'};
for(let i=0;i<120;i++)outTimeAt(clip,11);
assert.equal(ins,240,'read the in point for the span and fraction only');assert.equal(outs,120);assert.equal(speeds,120,'read speed once rather than once per ramp piece');
speeds=0;assert.equal(outTimeAt(clip,1),0);assert.equal(speeds,0,'time before the clip needs no speed calculation');
function previous(c,t){const u=fractionAt(c,t),span=c.out-c.in;let acc=0;for(const[a,b,r]of stretches(c)){if(u<=a)break;acc+=(Math.min(u,b)-a)*span/(speedOf(c)*r);}return acc;}
let seed=54;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let i=0;i<10000;i++) {
 const start=rand()*1000,c={in:start,out:start+rand()*100,speed:[undefined,0,.5,1,1.5,2,4][i%7],ramp:[undefined,'none','hero','slowdown','speedup','unknown'][i%6]};
 const t=start+(c.out-start)*(rand()*1.4-.2);assert.equal(outTimeAt(c,t),previous(c,t));
 for(const boundary of [c.in,c.out])assert.equal(outTimeAt(c,boundary),previous(c,boundary));
}
for(const c of [{in:0,out:0},{in:0,out:-0},{in:2,out:1},{in:0,out:Infinity},{in:NaN,out:1}])for(const t of [-1,0,1,NaN,Infinity])assert.equal(outTimeAt(c,t),previous(c,t));
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
