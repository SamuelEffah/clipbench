import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class BulkMediaOptionsPerformance(unittest.TestCase):
    def test_bulk_tracking_and_original_sound_do_not_search_selection_per_clip(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        def function(file, name):
            source = (ui / file).read_text()
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
let searches=0,changes=[],messages=[];
const state={project:{name:'project',clips:[]}},changed=(...args)=>changes.push(args),toast=text=>messages.push(text);
const includes=Array.prototype.includes;
Array.prototype.includes=function(...args){searches++;return includes.apply(this,args);};
''' + function('reframe.js', 'setTracking') + function('voice.js', 'useOriginalSound') + r'''
const clips=Array.from({length:2000},(_,i)=>({src:`v${i}`,voice:i%2===0}));
const ids=clips.map((_,i)=>i);
state.project.clips=clips;setTracking(ids,true);
assert.equal(searches,0,'tracking must not search the selected array for each clip');
assert.ok(state.project.clips.every(c=>c.tracking));assert.equal(changes.length,1);assert.equal(changes[0][0],false);assert.ok(changes[0][1].startsWith('tracking:'));assert.equal(messages[0],'Tracking on');
for(let i=0;i<clips.length;i++)assert.notEqual(state.project.clips[i],clips[i]);
const tracked=state.project.clips;useOriginalSound(ids);
assert.equal(searches,0,'original sound must not search the selected array for each clip');
for(let i=0;i<clips.length;i++) {
 assert.equal(state.project.clips[i].voice,false);
 if(i%2)assert.equal(state.project.clips[i],tracked[i]);else assert.notEqual(state.project.clips[i],tracked[i]);
}
assert.equal(messages[1],'Back to the original sound');assert.equal(state.project.name,'project');
// Sparse and empty selections retain unchanged references and the same undo behavior.
state.project.clips=clips.slice(0,5);changes=[];setTracking([3,1],false);
assert.equal(state.project.clips[0],clips[0]);assert.equal(state.project.clips[2],clips[2]);assert.equal(state.project.clips[1].tracking,false);assert.equal(state.project.clips[3].tracking,false);
const sparse=state.project.clips;useOriginalSound([4,1]);
assert.equal(state.project.clips[0],sparse[0]);assert.equal(state.project.clips[1],sparse[1]);assert.equal(state.project.clips[4].voice,false);
const before=state.project.clips;setTracking([],true);assert.deepEqual(state.project.clips,before);useOriginalSound([]);assert.deepEqual(state.project.clips,before);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
