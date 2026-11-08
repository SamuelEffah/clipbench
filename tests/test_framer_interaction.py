import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class FramerInteraction(unittest.TestCase):
    def test_gesture_stays_on_lane_and_readout_uses_current_clip(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/framer.js').read_text()
        show = 'function showFrameBox(' + source.split('function showFrameBox(', 1)[1].split('\nfunction setFrame', 1)[0]
        move = 'function moveFrame(' + source.split('function moveFrame(', 1)[1].split('\nfunction endFrame', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
const state = {project:{clips:[{zoom:2},{zoom:1}]}};
const frameBox = {style:{}}, framer = {dataset:{}}, read = {}, track = {dataset:{}};
const $ = id => id === 'frameRead' ? read : track;
const zoomOf = c => c.zoom, dragKind = () => 'focus', trackingOn = () => false;
let frameLane;
const lane = {i:0,box:[0,0,1,.5],clip:{zoom:1}};
''' + show + r'''
showFrameBox(lane);
assert.equal(read.textContent,'2.0x','readout must use updated immutable clip');
let shown;
const mirror = {width:1080,height:1920};
const FRAME_ZOOM = {min:.25,max:4,snap:.04};
let frameGesture = {kind:'zoom',lane,x:0,y:0,scale:1,zoom:1,center:{x:0,y:0},dist:100};
const setFrame = (i,patch) => Object.assign(state.project.clips[i],patch);
const laneUnder = () => ({i:1});
''' + move.replace('showFrameBox(g.lane)', 'shown = g.lane') + r'''
moveFrame({clientX:200,clientY:0});
assert.equal(state.project.clips[0].zoom,2);
assert.equal(shown.i,0,'crossing a split must not transfer the active frame');
const fitOf = () => 'fill';
const clampFrame = v => Math.max(0,Math.min(1,Number(v.toFixed(3))));
lane.vid = {videoWidth:1920,videoHeight:1080};
frameGesture = {kind:'focus',lane,x:0,y:0,scale:1,zoom:1.11,pan:.5,zx:.5,zy:.5};
moveFrame({clientX:-2000,clientY:0});
assert.equal(state.project.clips[0].pan,1,'zoomed Fill drag must reach source right edge');
assert.equal(state.project.clips[0].zx,1);
moveFrame({clientX:2000,clientY:0});
assert.equal(state.project.clips[0].pan,0,'zoomed Fill drag must reach source left edge');
assert.equal(state.project.clips[0].zx,0);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
