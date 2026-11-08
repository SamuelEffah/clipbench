import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class LaneMediaPerformance(unittest.TestCase):
    def test_lane_sync_skips_unchanged_writes_and_repeated_pauses(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        sync = 'function syncLanes(' + source.split('function syncLanes(', 1)[1].split('// Where each lane sits', 1)[0]
        setter = 'function setPlaybackValue(' + source.split('function setPlaybackValue(', 1)[1].split('\nfunction placePlayhead(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let writes=0,pauses=0,plays=0,lowNow=[],previewMuted=false,quiet=false;
const makePlayer=()=>{
 const el={paused:true,dataset:{id:'cut',base:0},readyState:1,seeking:false,duration:10,
 pause(){pauses++;this.paused=true;},play(){plays++;this.paused=false;return Promise.resolve();}};
 for(const [key,value] of Object.entries({volume:.6,muted:false,playbackRate:1,currentTime:2})) {
  let v=value;Object.defineProperty(el,key,{get(){return v;},set(next){writes++;v=next;}});
 }
 return el;
};
const laneVids=[makePlayer(),makePlayer(),makePlayer()],LANES=['top','bottom','left','right'];
const c={in:0,out:10,volume:.6,speed:1};let hit={clip:c,pos:2,held:false},file={id:'cut',base:0,url:'/cut/cut.mp4'};
const state={clipStop:null},preview={on:true,elapsed:2},video={paused:true};
const laneCount=()=>2,laneAt=()=>hit,clipFile=()=>file,fileLoadedIn=()=>null;
const volumeOf=c=>c.volume,playVolume=c=>quiet?0:c.volume,speedOf=c=>c.speed;
const movingLen=c=>c.out-c.in,tnow=el=>el.currentTime+Number(el.dataset.base);
''' + setter + sync + r'''
for(let i=0;i<120;i++)syncLanes();
assert.equal(writes,0,'stable paused lanes must not rewrite media properties');assert.equal(pauses,0,'already paused players need no pause call');assert.equal(plays,0);assert.equal(lowNow[0],hit);
video.paused=false;syncLanes();assert.equal(plays,1);
for(let i=0;i<120;i++)syncLanes();assert.equal(plays,1);assert.equal(writes,0);
c.volume=.3;quiet=true;c.speed=2;hit.pos=1;syncLanes();
assert.equal(laneVids[0].volume,.3);assert.equal(laneVids[0].muted,true);assert.equal(laneVids[0].playbackRate,2);
const changedWrites=writes;syncLanes();assert.equal(writes,changedWrites);
// Held clips pause once and seek to the requested source time; seeking clips avoid extra seeks.
hit.held=true;hit.pos=4;syncLanes();assert.equal(pauses,1);assert.equal(laneVids[0].currentTime,8);
syncLanes();assert.equal(pauses,1);
laneVids[0].seeking=true;hit.pos=3;syncLanes();assert.equal(laneVids[0].currentTime,8);laneVids[0].seeking=false;
hit.held=false;video.paused=true;state.clipStop={holding:123};hit.pos=4;syncLanes();assert.equal(plays,2);
// A missing file or inactive preview stops active playback exactly once.
file=null;syncLanes();assert.equal(pauses,2);syncLanes();assert.equal(pauses,2);assert.equal(lowNow[0],null);
preview.on=false;for(let i=0;i<120;i++)syncLanes();assert.equal(pauses,2);assert.deepEqual(lowNow,[]);
// Loading a new file updates its source and base, even while metadata is pending.
preview.on=true;file={id:'next',base:3,url:'/cut/next.mp4'};laneVids[0].readyState=0;
syncLanes();assert.equal(laneVids[0].src,file.url);assert.equal(laneVids[0].dataset.base,3);assert.equal(lowNow[0],hit);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
