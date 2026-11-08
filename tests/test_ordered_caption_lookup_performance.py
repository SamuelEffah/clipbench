import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class OrderedCaptionLookupPerformance(unittest.TestCase):
    def test_generated_ordered_cues_use_binary_lookup_and_keep_fallback_priorities(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/captions.js').read_text().split('// A plain caption', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const outLen=c=>(c.out-c.in)/(c.speed||1)+(c.freeze||0),outTimeAt=(c,t)=>(t-c.in)/(c.speed||1),captionOf=c=>c.caption||'';
''' + source + r'''
const clip={in:0,out:800,capMode:'word',words:Array.from({length:400},(_,i)=>[`word${i}`,i*2,i*2+1])};
const cues=syncedCues(clip);assert.equal(cues.length,400);
let reads=0;for(const q of cues){const start=q.a;Object.defineProperty(q,'a',{get(){reads++;return start;}});}
for(let i=0;i<120;i++)assert.equal(captionAt(clip,799.5,false).words[0],'word399');
assert.ok(reads<=1440,`${reads} timestamp reads for 120 cached lookups`);
function previous(c,pos,live) {
 const list=syncedCues(c);let cue=list.find(q=>pos>=q.a&&pos<q.b);
 if(!cue&&!live)cue=[...list].reverse().find(q=>q.a<=pos)||list[0];
 return cue?{...cue,key:`${cue.words.join(' ')}|${cue.lit}`}:null;
}
let seed=71;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<300;run++) {
 const words=Array.from({length:Math.floor(rand()*40)},(_,i)=>{const a=run%2?i*2:Math.floor(rand()*30);return [`word${i}${i%3?'':'.'}`,a,a+rand()*3];});
 const c={in:0,out:100,capMode:run%3?'word':'phrase',words};
 if(!words.length)continue;
 const list=syncedCues(c),times=[-1,0,1,5,20,100,NaN,Infinity,...list.flatMap(q=>[q.a,q.b])];
 for(const live of [true,false])for(const t of times)assert.deepEqual(captionAt(c,t,live),previous(c,t,live));
}
for(const words of [[['first.',0,3],['second',1,4]],[['later.',5,6],['earlier.',1,2]],[['zero.',1,1],['next',1,2]]]) {
 const c={in:0,out:10,capMode:'word',words};
 for(const live of [true,false])for(const t of [-1,0,1,1.5,2,3,4,5,6,10])assert.deepEqual(captionAt(c,t,live),previous(c,t,live));
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
