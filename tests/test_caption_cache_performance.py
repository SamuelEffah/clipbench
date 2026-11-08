import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class CaptionCachePerformance(unittest.TestCase):
    def test_cached_trimmed_captions_skip_word_alignment(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/captions.js').read_text()
        cues = source.split('// What shows over the clip', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
let wordReads = 0;
const track = list => new Proxy(list, {get(target,key,receiver) {
  if (/^\d+$/.test(String(key))) wordReads++;
  return Reflect.get(target,key,receiver);
}});
const outLen = c => (c.out-c.in)/(c.speed||1)+(c.freeze||0);
const outTimeAt = (c,t) => (t-c.in)/(c.speed||1);
''' + cues + r'''
const words=track(Array.from({length:400},(_,i)=>[`word${i}`,i*.2,i*.2+.15]));
const heard=track(Array.from(words));
const clip={in:11,out:20,wordsIn:10,capMode:'word',words,heard};
const first=syncedCues(clip);
assert.ok(first.length>0);
assert.equal(first[0].a,0);
assert.ok(first[0].words.includes('word5'));
const snapshot=JSON.stringify(first);
wordReads=0;
for(let i=0;i<120;i++) assert.equal(syncedCues(clip),first);
assert.equal(wordReads,0,'cached frames must not remap words or heard timings');
assert.equal(JSON.stringify(first),snapshot);
// Normal editing replaces clip objects, so trim/speed/mode edits must rebuild cues.
const edited={...clip,in:12,speed:2,capMode:'phrase',freeze:2};
const next=syncedCues(edited);
assert.notEqual(next,first);
assert.equal(next[0].a,0);
assert.ok(next[0].words.includes('word10'));
assert.ok(next.every(c=>c.lit===-1));
assert.ok(next.at(-1).b<=outLen(edited));
assert.ok(wordReads>0);
assert.equal(syncedCues(clip),first);
// The untrimmed path and empty word lists retain their existing behavior.
const original={...clip,in:10};
assert.equal(aligned(original),original);
assert.ok(syncedCues(original)[0].words.includes('word0'));
assert.deepEqual(syncedCues({...clip,words:[],heard:[]}),[]);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
