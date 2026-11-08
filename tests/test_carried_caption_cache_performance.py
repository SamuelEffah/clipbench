import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class CarriedCaptionCachePerformance(unittest.TestCase):
    def test_stable_carry_avoids_repeated_scans_and_list_edits_invalidate(self):
        text = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/captions.js').read_text()
        caption = 'function captionOf(c) {' + text.split('function captionOf(c) {', 1)[1].split('\nfunction paintCaption(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');let reads=0;
const state={project:{clips:[]}},isTop=c=>!c.lane||c.lane==='top',isSynced=c=>Boolean(c.synced);
''' + caption + r'''
const clips=Array.from({length:2000},(_,i)=>({caption:i===0?'carry':''}));
state.project.clips=new Proxy(clips,{get(a,k){if(/^\d+$/.test(String(k)))reads++;return a[k];}});
const last=clips.at(-1);assert.equal(captionOf(last),'carry');reads=0;
for(let n=0;n<120;n++)assert.equal(captionOf(last),'carry');
assert.equal(reads,0,`${reads} clip reads for a stable carried caption`);
state.project.clips=[{caption:'edited'},...clips.slice(1)];assert.equal(captionOf(last),'edited');
state.project.clips=[{caption:'edited',synced:true},...clips.slice(1)];assert.equal(captionOf(last),'');
state.project.clips=[{caption:'edited'},{capStop:true},last];assert.equal(captionOf(last),'');
state.project.clips=[last,{caption:'edited'}];assert.equal(captionOf(last),'');
function previous(c){
 if(c.caption||!isTop(c)||c.capStop)return c.caption||'';
 const list=state.project.clips;
 for(let i=list.indexOf(c)-1;i>=0;i--){const p=list[i];if(!isTop(p))continue;if(p.caption)return isSynced(p)?'':p.caption;if(p.capStop)return '';}
 return '';
}
let seed=29;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let n=0;n<500;n++){
 state.project.clips=Array.from({length:40},(_,i)=>({caption:rand()<.2?`text${i}`:'',lane:rand()<.3?'bottom':'top',synced:rand()<.3,capStop:rand()<.2}));
 for(const c of [...state.project.clips,{}]){assert.equal(captionOf(c),previous(c));assert.equal(captionOf(c),previous(c));}
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
