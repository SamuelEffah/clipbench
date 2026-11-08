import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class BulkDuplicatePerformance(unittest.TestCase):
    def test_bulk_duplicate_uses_direct_membership_and_preserves_selection(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/selection.js').read_text()
        duplicate = 'function duplicateChosen(' + source.split('function duplicateChosen(', 1)[1].split('\nfunction toggleMuteChosen(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let ids=[],searches=0,changes=0,picked=null,restarted=null;
const state={project:{name:'project',clips:[]},sel:-1};
const chosen=()=>ids,setPicked=items=>picked=items,changed=()=>changes++,restartPreviewAt=i=>restarted=i;
const includes=Array.prototype.includes;
Array.prototype.includes=function(...args){searches++;return includes.apply(this,args);};
''' + duplicate + r'''
const clips=Array.from({length:2000},(_,i)=>({src:`v${i}`,in:i,out:i+5}));
state.project.clips=clips;ids=clips.map((_,i)=>i);duplicateChosen();
assert.equal(searches,0,'duplication must not search the selection array for every clip');
assert.equal(changes,1);assert.equal(state.project.name,'project');assert.equal(state.project.clips.length,4000);
assert.equal(state.sel,1);assert.equal(restarted,1);assert.deepEqual(picked,clips.map((_,i)=>i*2+1));
for(let i=0;i<clips.length;i++) {
 assert.equal(state.project.clips[i*2],clips[i]);
 assert.notEqual(state.project.clips[i*2+1],clips[i]);assert.deepEqual(state.project.clips[i*2+1],clips[i]);
}
// Sparse selection, selection ordering, and single/empty cases retain their behavior.
state.project.clips=clips.slice(0,5);ids=[4,1];duplicateChosen();
assert.deepEqual(state.project.clips.map(c=>c.src),['v0','v1','v1','v2','v3','v4','v4']);assert.deepEqual(picked,[2,6]);
state.project.clips=clips.slice(0,2);ids=[1];duplicateChosen();assert.deepEqual(picked,[]);assert.equal(state.sel,2);
ids=[];const project=state.project,before=changes;duplicateChosen();assert.equal(state.project,project);assert.equal(changes,before);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
