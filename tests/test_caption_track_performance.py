import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class CaptionTrackPerformance(unittest.TestCase):
    def test_caption_track_scans_linearly_and_preserves_runs_and_selection(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        short = (ui / 'short.js').read_text()
        functions = 'function captionRuns(' + short.split('function captionRuns(', 1)[1].split('\nfunction resizeCaption(', 1)[0]
        captions = (ui / 'captions.js').read_text()
        carry = 'function captionOf(' + captions.split('function captionOf(', 1)[1].split('\nfunction paintCaption(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const state={project:{clips:[]},sel:1},picked=new Set();
const isTop=c=>!c.lane||c.lane==='top',isSynced=c=>Boolean(c.synced);
const seamOverlap=()=>0,outLen=()=>5;
const makeElement=()=>({children:[],style:{},dataset:{},append(...els){this.children.push(...els);},appendChild(el){this.children.push(el);}});
const document={createElement:makeElement};
let chosen,restarted;
const pickClip=i=>chosen=i,restartPreviewAt=i=>restarted=i;
''' + carry + functions + r'''
let reads=0;
const track=list=>new Proxy(list,{get(t,k,r){if(/^\d+$/.test(String(k)))reads++;return Reflect.get(t,k,r);}});
state.project.clips=track(Array.from({length:2000},(_,i)=>({caption:`Caption ${i}`})));
const row=textRow(state.project.clips,10),chips=row.children[0].children;
assert.equal(chips.length,2000);
assert.ok(reads<=10000,`${reads} clip reads for 2000 independent captions`);
assert.equal(chips[1].className,'stl-cap sel');assert.equal(chips[0].className,'stl-cap');
assert.equal(chips[1].style.left,'50px');assert.equal(chips[1].style.width,'50px');
chips[1].onclick();assert.equal(chosen,1);assert.equal(restarted,1);
state.project.clips=track(Array.from({length:2000},(_,i)=>({caption:i===0?'Carry':''})));
reads=0;assert.deepEqual(captionRuns(state.project.clips),[{head:0,last:1999,text:'Carry'}]);
assert.ok(reads<=10000,`${reads} clip reads for a long carried caption`);
function previous(list) {
 const runs=[];
 list.forEach((c,gi)=>{if(!isTop(c))return;if(c.caption)runs.push({head:gi,last:gi,text:c.caption});
 else if(runs.length&&captionOf(c))runs[runs.length-1].last=gi;});return runs;
}
let seed=37;
const random=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
 const list=Array.from({length:40},(_,i)=>({lane:random()<.3?'bottom':'top',caption:random()<.25?`Text ${i}`:'',capStop:random()<.2,synced:random()<.3}));
 state.project.clips=list;
 assert.deepEqual(captionRuns(list),previous(list));
}
state.project.clips=[{caption:'First'},{lane:'bottom'},{},{caption:'Next'}];
state.sel=1;picked.clear();
let rendered=textRow(state.project.clips,10).children[0].children;
assert.equal(rendered[0].className,'stl-cap');assert.equal(rendered[0].style.width,'100px');
picked.add(2);rendered=textRow(state.project.clips,10).children[0].children;
assert.equal(rendered[0].className,'stl-cap sel');
assert.equal(textRow([],10).hidden,true);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
