import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class LaneInsertLookupPerformance(unittest.TestCase):
    def test_slots_stop_scanning_when_known_and_preserve_indices(self):
        text = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/short.js').read_text()
        lookup = 'function laneInsertAt(' + text.split('function laneInsertAt(', 1)[1].split('\nfunction insertClip(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');let reads=0;
const laneOf=c=>{reads++;return c.lane||'top';};
''' + lookup + r'''
const clips=Array.from({length:2000},()=>({lane:'top'}));
assert.equal(laneInsertAt(clips,'top',0),0);assert.equal(reads,1);
reads=0;assert.equal(laneInsertAt(clips,'top',Infinity),2000);assert.equal(reads,1);
function previous(list,lane,k){
 const positions=list.flatMap((c,i)=>laneOf(c)===lane?[i]:[]);
 if(k<positions.length)return positions[k];
 return positions.length?positions.at(-1)+1:list.length;
}
let seed=19;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let n=0;n<500;n++){
 const list=Array.from({length:n%50},()=>({lane:rand()<.4?'bottom':'top'}));
 if(list.length>2&&n%3===0)delete list[1];
 for(const lane of ['top','bottom','missing'])for(const k of [0,1,5,49,Infinity,-1,.5,NaN,undefined,'1','01',null])
  assert.equal(laneInsertAt(list,lane,k),previous(list,lane,k));
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
