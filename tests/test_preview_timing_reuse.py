import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class PreviewTimingReuseTests(unittest.TestCase):
    def test_unchanged_frames_reuse_timing_and_edits_undo_and_clip_changes_refresh_it(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        def function(name):
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
let durations=0,editCount=0;
const state={mode:'short',project:{clips:Array.from({length:2000},()=>({len:5}))}};
const preview={idx:1000,live:true,done:false},video={paused:false};
const isTop=()=>true,outLen=c=>{durations++;return c.len;},seamOverlap=()=>0;
const clipPos=()=>2,stampShort=String,captionAt=()=>null,paintCaption=()=>{},paintLiveCap=()=>{},placeCaption=()=>{},syncCapSel=()=>{},capHome={};
const attrs={},icon={getAttribute:k=>attrs[k],setAttribute(k,v){attrs[k]=v;}};
const ids={},$=id=>ids[id]||=( {querySelector:()=>icon,getAttribute:k=>attrs[k],setAttribute(k,v){attrs[k]=v;}} );
const setPlaybackValue=(obj,key,value)=>obj[key]=value;
''' + function('previewTiming') + function('updatePreview') + r'''
for(let i=0;i<120;i++)updatePreview();
assert.equal(durations,2000,'120 stable frames should calculate durations once, not 240000 times');
assert.equal(preview.elapsed,5002);
const original=state.project;
state.project={...original,clips:original.clips.map((c,i)=>i===0?{len:6}:c)};updatePreview();assert.equal(preview.elapsed,5003);
state.project=original;updatePreview();assert.equal(preview.elapsed,5002);
preview.idx=1001;updatePreview();assert.equal(preview.elapsed,5007);
state.project.clips[0].len=7;editCount++;updatePreview();assert.equal(preview.elapsed,5009);
state.project.clips[0].len=8;assert.equal(previewTiming().lens[0],8,'direct timing queries remain fresh for in-place edits');
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
