import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class CaptionLookupPerformance(unittest.TestCase):
    def test_paused_caption_lookup_uses_one_scan_and_preserves_cue_selection(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/captions.js').read_text()
        lookup = 'function captionAt(' + source.split('function captionAt(', 1)[1].split('// A plain caption', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
let reads=0,cues=[];
const orderedCueLists=new WeakSet();
const isSynced=c=>c.synced, captionOf=c=>c.caption||'',syncedCues=()=>cues;
const clip={synced:true};
function previous(c,pos,live) {
  if(!c)return null;
  if(!isSynced(c)){const text=captionOf(c);return text?{key:`s:${text}`,words:[text],lit:-1}:null;}
  let cue=cues.find(q=>pos>=q.a&&pos<q.b);
  if(!cue&&!live)cue=[...cues].reverse().find(q=>q.a<=pos)||cues[0];
  return cue?{...cue,key:`${cue.words.join(' ')}|${cue.lit}`}:null;
}
''' + lookup + r'''
cues=new Proxy(Array.from({length:400},(_,i)=>({a:i*2,b:i*2+1,words:[`word${i}`],lit:0})),{
 get(target,key,receiver){if(/^\d+$/.test(String(key)))reads++;return Reflect.get(target,key,receiver);}
});
assert.equal(captionAt(clip,1000,false).words[0],'word399');
assert.equal(reads,400,'paused gap lookup should read each cue only once');
// Differential coverage includes unordered and overlapping cues so the first active
// cue and the last preceding cue keep their existing priority.
let seed=29;
const random=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
  cues=Array.from({length:Math.floor(random()*30)},(_,i)=>{
    const a=Math.floor(random()*30)/2;
    return {a,b:a+random()*3,words:[`word${i}`,'caption'],lit:i%2};
  });
  const snapshot=JSON.stringify(cues);
  const times=[-1,0,1,5,30,NaN,Infinity,...cues.flatMap(q=>[q.a,q.b])];
  for(const live of [true,false])for(const t of times)
    assert.deepEqual(captionAt(clip,t,live),previous(clip,t,live));
  assert.equal(JSON.stringify(cues),snapshot);
}
assert.equal(captionAt(null,0,false),null);
assert.deepEqual(captionAt({caption:'Plain'},0,true),{key:'s:Plain',words:['Plain'],lit:-1});
assert.equal(captionAt({},0,false),null);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
