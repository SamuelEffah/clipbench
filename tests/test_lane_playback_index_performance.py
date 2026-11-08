import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class LanePlaybackIndexPerformance(unittest.TestCase):
    def test_playback_reuses_lane_timing_and_preserves_seeks_holds_and_edits(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        source = 'function laneAt(' + source.split('function laneAt(', 1)[1].split('\nfunction syncLanes()', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let durations=0,reads=0,editCount=0;
const laneOf=c=>{reads++;return c.lane||'top'},outLen=c=>{durations++;return c.len};
const state={project:{clips:Array.from({length:4000},(_,i)=>({lane:i%2?'top':'bottom',len:1}))}};
''' + source + r'''
for(let i=0;i<120;i++) assert.equal(laneAt('bottom',1800.25,true).pos,.25);
assert.equal(durations,4000,'stable playback must calculate clip lengths only once');
assert.equal(reads,4000);
laneAt('top',1999.5,true);assert.equal(durations,4000,'all lanes share the same prepared timing');
for(const lane of ['top','bottom','missing'])for(const t of [-1,0,.5,1,1800,1999.5,2000,Infinity,NaN])
 assert.deepEqual(laneAt(lane,t,true),laneAt(lane,t));
state.project.clips[0].len=2;editCount++;
assert.deepEqual(laneAt('bottom',1800,true),laneAt('bottom',1800));
state.project={clips:[{lane:'bottom',len:0},{lane:'bottom',len:2}]};
for(const t of [-1,0,1,2])assert.deepEqual(laneAt('bottom',t,true),laneAt('bottom',t));
state.project.clips.push({lane:'bottom',len:3});
assert.deepEqual(laneAt('bottom',4,true),laneAt('bottom',4));
// Malformed timings retain the original linear lookup rules.
for(const len of [-1,NaN,Infinity]){
 state.project={clips:[{lane:'bottom',len},{lane:'bottom',len:2}]};
 for(const t of [-1,0,1,3,Infinity,NaN])assert.deepEqual(laneAt('bottom',t,true),laneAt('bottom',t));
}
'''
        out = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
