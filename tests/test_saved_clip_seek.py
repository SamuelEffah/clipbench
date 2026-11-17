import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class SavedClipSeek(unittest.TestCase):
    def test_selection_seeks_current_source_and_opens_other_source_at_clip_start(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        helper = 'function select(' + source.split('function select(', 1)[1].split('\nfunction showOverlay', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
const clips = [{src:'a',in:16.5,out:19.7},{src:'b',in:8,out:12},{src:'missing',in:0,out:30}];
const state = {sel:-1,current:{id:'a'},project:{clips},clipStop:{out:1}};
const video = {currentTime:11};
const byPath = src => src === 'missing' ? null : {id:src};
let opened, visible, updates=0, paints=0;
const openVideo = (v,t) => {opened=[v.id,t];};
const ensureVisible = (a,b) => {visible=[a,b];};
const updateTime = () => updates++;
const render = () => paints++;
''' + helper + r'''
select(0,true);
assert.equal(video.currentTime,16.5); assert.equal(state.sel,0);
assert.equal(state.clipStop,null); assert.equal(updates,1);
assert.deepEqual(visible,[16.5,19.7]); assert.equal(paints,1);
video.currentTime=18; select(0); assert.equal(video.currentTime,18,'ordinary selection preserves playhead');
select(1,true); assert.deepEqual(opened,['b',8]); assert.equal(video.currentTime,18);
opened=null; select(2,true); assert.equal(opened,null); assert.equal(video.currentTime,18,'missing source must not seek another video');
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
