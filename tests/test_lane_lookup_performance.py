import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class LaneLookupPerformance(unittest.TestCase):
    def test_lookup_stops_at_active_clip_and_matches_previous_rules(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        source = (ui / 'app.js').read_text()
        lookup = 'function laneAt(' + source.split('function laneAt(', 1)[1].split('\nfunction syncLanes()', 1)[0]
        source = (ui / 'short.js').read_text()
        total = 'function laneTotal(' + source.split('function laneTotal(', 1)[1].split('// How far apart', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
let reads=0;
const laneOf=c=>{reads++;return c.lane||'top';};
const outLen=c=>c.len;
const seamOverlap=(a,b)=>a ? Math.min(a.len/2,b.len/2,b.overlap||0) : 0;
const state={project:{clips:[]}};
function previous(lane,t) {
  const clips=state.project.clips.filter(c=>laneOf(c)===lane);
  let at=0;
  for(const c of clips) {
    const len=outLen(c);
    if(t<at+len) return {clip:c,pos:t-at,held:false};
    at+=len;
  }
  const last=clips[clips.length-1];
  return last ? {clip:last,pos:outLen(last),held:true} : null;
}
function previousTotal(lane,list) {
  const clips=list.filter(c=>laneOf(c)===lane);
  return clips.reduce((sum,c,n)=>sum+outLen(c)-seamOverlap(clips[n-1],c),0);
}
''' + lookup + total + r'''
state.project.clips=Array.from({length:4000},(_,i)=>({lane:i%2?'top':'bottom',len:5}));
reads=0;
assert.equal(laneAt('bottom',1).clip,state.project.clips[0]);
assert.equal(reads,1,'stop scanning once the active clip is found');
// Duration calculation must not build a filtered array.
const list=state.project.clips;
list.filter=()=>{throw Error('filtered lane array allocated');};
assert.equal(laneTotal('bottom',list),10000);
delete list.filter;
// Deterministic differential coverage: interleaved lanes, empty lanes, boundaries,
// zero-length clips, final holds, transitions, and edits made in place.
let seed=19;
const random=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
  const clips=Array.from({length:Math.floor(random()*60)},()=>({
    lane:['top','bottom','left','right'][Math.floor(random()*4)],
    len:Math.floor(random()*20)/2,overlap:random()*3
  }));
  state.project.clips=clips;
  for(const lane of ['top','bottom','left','right','missing']) {
    assert.equal(laneTotal(lane,clips),previousTotal(lane,clips));
    for(const t of [-1,0,0.5,5,10,1000,NaN,Infinity])
      assert.deepEqual(laneAt(lane,t),previous(lane,t));
    let at=0;
    for(const c of clips.filter(c=>laneOf(c)===lane)) {
      at+=c.len;
      assert.deepEqual(laneAt(lane,at),previous(lane,at));
    }
  }
  if(clips.length) {
    clips[0].lane='bottom'; clips[0].len=100;
    assert.deepEqual(laneAt('bottom',50),previous('bottom',50));
  }
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
