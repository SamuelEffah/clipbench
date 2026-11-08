import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class CaptionRunLookupPerformance(unittest.TestCase):
    def test_lookup_visits_only_the_relevant_run_and_keeps_all_boundary_rules(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/short.js').read_text()
        def function(name):
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
let reads=0;
const state={project:{clips:[]}},isTop=c=>!c?.lane||c.lane==='top',isSynced=c=>Boolean(c.synced);
''' + function('captionRuns') + function('captionRunOf') + r'''
const track=list=>new Proxy(list,{get(t,k,r){if(/^\d+$/.test(String(k)))reads++;return Reflect.get(t,k,r);}});
state.project.clips=track(Array.from({length:2000},(_,i)=>({caption:`Text${i}`})));
assert.deepEqual(captionRunOf(0),{head:0,last:0,text:'Text0'});assert.ok(reads<=4,`${reads} clip reads for the first independent caption`);
reads=0;assert.deepEqual(captionRunOf(1000),{head:1000,last:1000,text:'Text1000'});assert.ok(reads<=4);
state.project.clips=track(Array.from({length:2000},(_,i)=>({caption:i===0?'Carry':''})));
reads=0;assert.deepEqual(captionRunOf(1500),{head:0,last:1999,text:'Carry'});assert.ok(reads<=2002,`${reads} clip reads for an inherited caption`);
let seed=29;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
 const clips=Array.from({length:40},(_,i)=>({caption:rand()<.3?`Text${i}`:'',lane:rand()<.3?'lower':'top',capStop:rand()<.2,synced:rand()<.3}));
 state.project.clips=clips;
 for(let i=-1;i<=clips.length;i++) {
  const found=captionRuns(clips).find(r=>i>=r.head&&i<=r.last&&isTop(clips[i]));
  assert.deepEqual(captionRunOf(i),found||{head:i,last:i});
 }
}
state.project.clips=[];assert.deepEqual(captionRunOf(0),{head:0,last:0});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
