import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class CaptionEditPerformance(unittest.TestCase):
    def test_caption_styles_preserve_unaffected_clip_objects_and_cached_cues(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/short.js').read_text()
        def function(name):
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
const state={project:{name:'project',clips:[]}},isTop=c=>!c.lane||c.lane==='top',isSynced=c=>Boolean(c.synced);
let changedArgs;const changed=(...args)=>changedArgs=args;
''' + function('captionRuns') + function('captionRunOf') + function('styleCaption') + r'''
const clips=Array.from({length:2000},(_,i)=>({caption:i===1?'':`Text${i}`,capX:.5,capScale:1}));
clips[2].lane='lower';state.project.clips=clips;
const cache=new WeakMap(clips.map(c=>[c,{cached:true}]));
styleCaption(1,{capX:.2,capScale:2},'drag');
const next=state.project.clips;
assert.equal(next.filter((c,i)=>c!==clips[i]).length,2,'only the caption run should allocate clip copies');
assert.equal(next[0].capX,.2);assert.equal(next[0].capScale,2);assert.equal(next[1].capX,null);assert.equal(next[1].capScale,null);
for(let i=2;i<clips.length;i++){assert.equal(next[i],clips[i]);assert.equal(cache.has(next[i]),true);}
assert.deepEqual(changedArgs,[true,'drag']);assert.equal(state.project.name,'project');assert.equal(clips[0].capX,.5);
// Compare field values with the previous implementation across carry, stops, timed
// captions, and explicit per-clip patches, while keeping unaffected object identities.
let seed=21;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
 const list=Array.from({length:40},(_,i)=>({caption:rand()<.3?`Text${i}`:'',lane:rand()<.25?'lower':'top',capStop:rand()<.2,synced:rand()<.3,capScale:rand()+.5}));
 state.project.clips=list;const i=Math.floor(rand()*list.length),patch={capScale:2,capRot:30},own=run%2?{caption:'Own'}:{};
 const {head,last}=captionRunOf(i),unset=Object.fromEntries(Object.keys(patch).map(k=>[k,null]));
 const expected=list.map((c,n)=>{const mine=n===i?own:{};return n===head?{...c,...patch,...mine}:n>head&&n<=last&&isTop(c)?{...c,...unset,...mine}:{...c,...mine};});
 styleCaption(i,patch,'style',false,own);assert.deepEqual(state.project.clips,expected);assert.deepEqual(changedArgs,[false,'style']);
 state.project.clips.forEach((c,n)=>{if(n!==i&&n!==head&&!(n>head&&n<=last&&isTop(c)))assert.equal(c,list[n]);});
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
