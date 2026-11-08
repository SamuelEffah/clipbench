import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class LiveCaptionUpdatesTests(unittest.TestCase):
    def test_only_changed_words_are_restyled_and_jumps_match_full_repaint(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/livecap.js').read_text()
        code = 'function lightLiveCue(' + source.split('function lightLiveCue(', 1)[1].split('// Wheel over', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let writes=0,liveAutoY=0;
let liveWordEls=Array.from({length:3000},(_,i)=>({value:'lw',offsetTop:i*2,get className(){return this.value;},set className(v){writes++;this.value=v;}}));
const flow={},box={clientHeight:100},$=id=>id==='lcFlow'?flow:box;
const ranges=Array.from({length:3000},(_,i)=>({a:i,start:Math.floor(i/5)*5,len:5,lit:i%5}));
const liveWordsOf=()=>({ranges}),applyLiveScroll=()=>{};
''' + code + r'''
function check(cap){
 lightLiveCue({},cap);
 const r=cap?ranges[cap.a]:null,end=r?r.start+r.len:0,now=r&&r.lit>=0?r.start+r.lit:-1;
 assert.deepEqual(liveWordEls.map(w=>w.className),liveWordEls.map((_,n)=>`lw${r?(n>=r.start&&n<end?(n===now?' win now':' win'):n<r.start?' before':''):''}`));
}
check({a:2});writes=0;check({a:3});
assert.equal(writes,2,'advancing one word must not rewrite all 3000 words');
let seed=123;
for(let i=0;i<300;i++){seed=(seed*1664525+1013904223)>>>0;check(i%17===0?null:{a:seed%3000});}
// Rebuilt word elements must be initialized even when the cue is unchanged.
liveWordEls=liveWordEls.map(()=>({className:'lw',offsetTop:0}));check({a:100});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
