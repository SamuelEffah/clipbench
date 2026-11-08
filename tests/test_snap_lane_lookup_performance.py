import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class SnapLaneLookupPerformance(unittest.TestCase):
    def test_skip_set_visits_only_suffix_and_reads_target_lane_once(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/snap.js').read_text()
        lookup = 'const laterInLane' + source.split('const laterInLane', 1)[1].split('// Trimming:', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let reads=0,lanes=0;
const state={project:{clips:[]}},laneOf=c=>{lanes++;return c?.lane||'top';};
''' + lookup + r'''
const clips=Array.from({length:2000},(_,i)=>({lane:i%2?'lower':'top'}));
state.project.clips=new Proxy(clips,{get(t,k,r){if(/^\d+$/.test(String(k)))reads++;return Reflect.get(t,k,r);}});
assert.deepEqual([...laterInLane(1999)],[1999]);assert.equal(reads,2,'a trim at the end must not inspect earlier clips');assert.equal(lanes,2);
reads=0;lanes=0;assert.equal(laterInLane(0).size,1000);assert.equal(reads,2001);assert.equal(lanes,2001,'read the target lane once, not once per candidate');
const previous=(gi,from=gi)=>{const skip=new Set();state.project.clips.forEach((c,i)=>{if(i>=from&&laneOf(c)===laneOf(state.project.clips[gi]))skip.add(i);});return skip;};
let seed=46;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
 const list=Array.from({length:Math.floor(rand()*60)},()=>({lane:['top','lower','left','right'][Math.floor(rand()*4)]}));
 if(list.length>2&&run%2)delete list[1];
 state.project.clips=list;
 for(const gi of [-1,0,Math.floor(list.length/2),list.length-1,list.length]) {
  assert.deepEqual([...laterInLane(gi)],[...previous(gi)]);
  for(const from of [-10,0,1.5,gi-1,gi,gi+1,list.length+2,Infinity,NaN])
   assert.deepEqual([...laterInLane(gi,from)],[...previous(gi,from)]);
 }
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
