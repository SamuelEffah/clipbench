import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class FramerNoopPerformance(unittest.TestCase):
    def test_quantized_drag_values_skip_unchanged_project_copies_and_saves(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/framer.js').read_text()
        source = 'function setFrame(' + source.split('function setFrame(', 1)[1].split('\nconst clampFrame', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let reads=0,edits=0,lastKey='';
const raw=Array.from({length:2000},(_,i)=>({src:'clip'+i,zoom:1}));
const clips=new Proxy(raw,{get(a,k){if(/^\d+$/.test(String(k)))reads++;return a[k]}});
const state={project:{clips}},original=state.project;
const changed=(keep,key)=>{assert.equal(keep,true);edits++;lastKey=key};
''' + source + r'''
for(let i=0;i<600;i++) setFrame(1000,{zoom:1},'zoom:1000');
assert.equal(edits,0,'stationary/quantized pointer moves must not create edits or reset autosave');
assert.equal(state.project,original);
assert.ok(reads<=600,'unchanged drag values need only inspect the selected clip');
setFrame(1000,{zoom:1.01},'zoom:1000');
assert.equal(edits,1);assert.equal(lastKey,'zoom:1000');
assert.notEqual(state.project.clips[1000],raw[1000]);
assert.equal(state.project.clips[999],raw[999]);
assert.equal(state.project.clips[1000].zoom,1.01);
setFrame(1000,{zx:.4,zy:.5},'focus:1000');assert.equal(edits,2);
for(let i=0;i<600;i++)setFrame(1000,{zx:.4,zy:.5},'focus:1000');
assert.equal(edits,2);
setFrame(1000,{zx:.4,zy:.6},'focus:1000');assert.equal(edits,3);
setFrame(1000,{pan:.5},'pan:1000');assert.equal(edits,4,'first explicit default remains an edit');
setFrame(1000,{pan:.5},'pan:1000');assert.equal(edits,4);
'''
        out = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
