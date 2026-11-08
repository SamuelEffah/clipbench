import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class RollGestureTimingPerformance(unittest.TestCase):
    def test_roll_prepares_positions_once_and_refreshes_after_external_edits(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/timeline.js').read_text()
        source = 'function rollOnTimeline(' + source.split('function rollOnTimeline(', 1)[1]
        script = r'''
const assert=require('node:assert/strict');
let scans=0,skips=0,editCount=0,expectedAt=2;
const state={project:{clips:Array.from({length:2000},()=>({src:'video',in:1,out:3}))}};
const nextInLane=i=>i+1,prevInLane=i=>i-1,byPath=()=>({duration:20}),speedOf=()=>1;
const MIN_CLIP=.2,stlPps=40;
const nodes=Array.from({length:2},()=>({offsetWidth:100,offsetLeft:100,style:{},events:{},
 setPointerCapture(){},addEventListener(k,fn){this.events[k]=fn},removeEventListener(k){delete this.events[k]}}));
const clipBlockAt=i=>nodes[i];
const clipStarts=clips=>{scans++;let at=0;return clips.map(c=>{const start=at;at+=c.out-c.in;return start})};
const laterInLane=()=>{skips++;return new Set([0,1])};
const snapNear=(times,options,bypass)=>{
 if(bypass)return null;
 const starts=options.starts||clipStarts(state.project.clips);
 assert.equal(starts[1],expectedAt);assert(options.skipClips.has(0));return null;
};
const showSnapLine=()=>{},hideSnapLine=()=>{},showSndTip=()=>{},hideSndTip=()=>{},render=()=>{},changed=()=>{},restartPreviewAt=()=>{};
''' + source + r'''
assert.equal(rollOnTimeline({clientX:0,pointerId:1,preventDefault(){},stopPropagation(){}},0,'r',nodes[0]),true);
const move=()=>nodes[0].events.pointermove({clientX:20,clientY:10,altKey:false});
for(let i=0;i<120;i++)move();
assert.equal(scans,1,'one gesture must reuse its prepared clip starts');
assert.equal(skips,1,'the skipped lane does not change on every pointer move');
state.project={clips:state.project.clips.map(c=>({...c}))};move();assert.equal(scans,2);assert.equal(skips,2);
state.project.clips[0].out=4;editCount++;expectedAt=3;move();assert.equal(scans,3);assert.equal(skips,3);
nodes[0].events.pointerup();assert.equal(nodes[0].events.pointermove,undefined);
assert.equal(state.project.clips[0].out,3.5);assert.equal(state.project.clips[1].in,1.5);
'''
        out = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
