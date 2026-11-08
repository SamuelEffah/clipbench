import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class ShiftSelectionPerformance(unittest.TestCase):
    def test_shift_selection_reads_only_the_requested_range(self):
        text = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/selection.js').read_text()
        pick = 'function pickMore(' + text.split('function pickMore(', 1)[1].split('\nfunction selectAllClips(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');let reads=0,rendered=0;
const picked=new Set(),state={project:{clips:[]},sel:1998},laneOf=c=>(c&&c.lane)||'top';
const setPicked=ids=>{picked.clear();for(const i of ids)picked.add(i);},setTab=()=>{},render=()=>rendered++;
''' + pick + r'''
const list=Array.from({length:2000},()=>({lane:'top'}));
state.project.clips=new Proxy(list,{get(a,k){if(/^\d+$/.test(String(k)))reads++;return a[k];}});
pickMore(1999,{shiftKey:true});assert.deepEqual([...picked],[1998,1999]);assert.equal(state.sel,1999);
assert.ok(reads<=5,`${reads} clip reads for a two-clip shift selection`);assert.equal(rendered,1);
let seed=31;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let n=0;n<500;n++){
 const clips=Array.from({length:40},()=>({lane:rand()<.3?'bottom':'top'}));state.project.clips=clips;
 const selected=Math.floor(rand()*40),gi=Math.floor(rand()*40),shiftKey=rand()<.7;
 state.sel=selected;picked.clear();if(n%2){picked.add(selected);picked.add((selected+1)%40);}
 const expected=picked.size>1?new Set(picked):new Set([selected]);
 if(shiftKey&&laneOf(clips[selected])===laneOf(clips[gi])){
  clips.forEach((c,i)=>{if(i>=Math.min(selected,gi)&&i<=Math.max(selected,gi)&&laneOf(c)===laneOf(clips[gi]))expected.add(i);});
 }else if(expected.has(gi)&&expected.size>1)expected.delete(gi);else expected.add(gi);
 let sel=expected.has(selected)?selected:[...expected][0];if(expected.has(gi))sel=gi;
 pickMore(gi,{shiftKey});assert.equal(state.sel,sel);assert.deepEqual([...picked],expected.size>1?[...expected]:[]);
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
