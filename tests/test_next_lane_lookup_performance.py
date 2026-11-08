import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class NextLaneLookupPerformance(unittest.TestCase):
    def test_neighbor_lookup_skips_prefix_and_keeps_first_matching_neighbor(self):
        short = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/short.js').read_text()
        lookup = 'function nextInLane(' + short.split('function nextInLane(', 1)[1].split('\nfunction removeFromTimeline(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');let reads=0;
const state={project:{clips:[]}},laneOf=c=>(c&&c.lane)||'top';
''' + lookup + r'''
const list=Array.from({length:2000},()=>({lane:'top'}));
state.project.clips=new Proxy(list,{get(a,k){if(/^\d+$/.test(String(k)))reads++;return a[k];}});
assert.equal(nextInLane(1998),1999);assert.ok(reads<=2,`${reads} clip reads to find the adjacent clip`);
reads=0;assert.equal(nextInLane(1999),-1);assert.equal(reads,0);
let seed=23;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let n=0;n<500;n++){
 const clips=Array.from({length:n%40},()=>({lane:rand()<.4?'bottom':'top'}));
 if(clips.length>2&&n%3===0)delete clips[1];
 state.project.clips=clips;
 for(const i of [-2,-1,0,1,3,20,39,40,Infinity,-Infinity,NaN,undefined,'1',.5]){
  const expected=clips.findIndex((c,j)=>j>i&&laneOf(c)===laneOf(clips[i]));
  assert.equal(nextInLane(i),expected);
 }
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
