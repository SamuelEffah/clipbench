import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class TrackingLookupPerformance(unittest.TestCase):
    def test_sorted_tracking_lookup_is_logarithmic_and_preserves_interpolation(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/reframe.js').read_text()
        lookup = 'function trackedFocus(' + source.split('function trackedFocus(', 1)[1].split('\nfunction reframeRow(', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
const trackingOn=c=>Boolean(c&&c.tracking&&c.track&&c.track.length>1);
function previous(clip,t) {
  if(!trackingOn(clip)) return null;
  const keys=clip.track;
  if(t<=keys[0][0]) return [keys[0][1],keys[0][2]];
  for(let n=1;n<keys.length;n++)if(t<=keys[n][0]) {
    const [t0,x0,y0]=keys[n-1],[t1,x1,y1]=keys[n],f=t1>t0?(t-t0)/(t1-t0):1;
    return [x0+(x1-x0)*f,y0+(y1-y0)*f];
  }
  const last=keys[keys.length-1];return [last[1],last[2]];
}
''' + lookup + r'''
let reads=0;
const keys=Array.from({length:120},(_,i)=>[i,i/120,0.5]);
const clip={tracking:true,track:new Proxy(keys,{get(t,k,r){if(/^\d+$/.test(String(k)))reads++;return Reflect.get(t,k,r);}})};
assert.deepEqual(trackedFocus(clip,118.5),previous({tracking:true,track:keys},118.5));
assert.ok(reads<=15,`${reads} keyframe reads for 120 keys`);
let seed=31;
const random=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
  let at=0;
  const keys=Array.from({length:2+Math.floor(random()*119)},()=>{
    at+=Math.floor(random()*4)/2;return [at,random(),random()];
  });
  const c={tracking:true,track:keys};
  for(const t of [-Infinity,-1,0,at+1,Infinity,NaN,...keys.map(k=>k[0]),...keys.map(k=>k[0]+random())])
    assert.deepEqual(trackedFocus(c,t),previous(c,t));
  // Position edits and replacing a track take effect without a stale lookup cache.
  keys[0][1]=0.99;
  assert.deepEqual(trackedFocus(c,-1),previous(c,-1));
  c.track=[[0,.2,.3],[10,.8,.7]];
  assert.deepEqual(trackedFocus(c,5),previous(c,5));
}
for(const c of [null,{}, {tracking:false,track:keys},{tracking:true,track:[]},{tracking:true,track:[[0,.2,.3]]}])
  assert.equal(trackedFocus(c,1),null);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
