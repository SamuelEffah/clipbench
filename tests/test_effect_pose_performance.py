import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class EffectPosePerformance(unittest.TestCase):
    def test_static_effects_skip_timing_and_animated_effects_keep_their_pose(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        pose = 'function effectPose(' + source.split('function effectPose(', 1)[1].split('\nlet monitorFxOn', 1)[0]
        glitch = 'const GLITCH_SLOT' + source.split('const GLITCH_SLOT', 1)[1].split('\nfunction effectPose', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let timings=0;
const video={currentTime:2};
const effectOf=c=>c.effect||'none';
const movingLen=c=>{timings++;return (c.out-c.in)/(c.speed||1);};
const outTimeAt=(c,t)=>{timings++;return (t-c.in)/(c.speed||1);};
const tnow=v=>v.currentTime;
''' + glitch + pose + r'''
const neutral={zoom:1,dx:0,dy:0,flash:0,gray:false,vignette:false,glitch:null};
for(const effect of ['none','bw','vignette',undefined]) {
  timings=0;
  for(let n=0;n<120;n++) {
    const actual=effectPose({in:0,out:10,effect});
    assert.deepEqual(actual,{...neutral,gray:effect==='bw',vignette:effect==='vignette'});
  }
  assert.equal(timings,0,`${effect}: static effects must not calculate playback timing`);
}
// Compare every timed effect against its existing formula, including another video element.
for(const effect of ['zoom_in','zoom_out','punch','shake','flash','glitch','unknown']) {
  for(let n=0;n<200;n++) {
    const clip={in:2,out:10,speed:0.5+n%4,effect}, player={currentTime:n/10};
    const len=(clip.out-clip.in)/clip.speed,t=Math.min(len,(player.currentTime-clip.in)/clip.speed);
    const expected={...neutral};
    if(effect==='zoom_in')expected.zoom=1+0.15*t/len;
    else if(effect==='zoom_out')expected.zoom=1.15-0.15*t/len;
    else if(effect==='punch')expected.zoom=1+0.2*Math.pow(Math.max(0,1-t/0.35),2);
    else if(effect==='shake')Object.assign(expected,{zoom:1.06,dx:0.012*Math.sin(t*37),dy:0.008*Math.sin(t*41+1)});
    else if(effect==='flash')expected.flash=Math.max(0,1-t/0.25);
    else if(effect==='glitch')expected.glitch=glitchAt(t);
    assert.deepEqual(effectPose(clip,player),expected);
  }
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
