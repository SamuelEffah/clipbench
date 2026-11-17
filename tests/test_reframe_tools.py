import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ReframeTools(unittest.TestCase):
    def test_direct_move_resize_redraw_recenter_and_cancel(self):
        src = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/reframebox.js').read_text()
        start = 'function startBox(' + src.split('function startBox(', 1)[1].split('\nfunction moveBox', 1)[0]
        box = 'function boxFrom(' + src.split('function boxFrom(', 1)[1].split('\nconst reframeUi', 1)[0]
        move = 'function moveBox(' + src.split('function moveBox(', 1)[1].split('// Tracking runs', 1)[0]
        finish = 'function finishBox(' + src.split('function finishBox(', 1)[1].split('const rfStage', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const BOX_MIN=.06;
let rf={size:[1920,1080],cell:[1080,960],box:{x:.3,y:.1,w:.4,h:.6},view:{z:1,x:0,y:0}};
const pointOn=e=>[e.x,e.y], viewOf=()=>({fw:.633});
const document={getElementById:()=>({setPointerCapture(){}})};
const paintBox=()=>{},paintView=()=>{};
const event=(x,y)=>({x,y,clientX:x*1000,clientY:y*1000,button:0,pointerId:1,type:"pointerup",target:{closest:()=>null},preventDefault(){}});
''' + start + move + finish + box + r'''
// Outside click centers the existing crop; no tool switch is required.
startBox(event(.95,.95));assert.equal(rf.gesture.kind,'draw');
finishBox(event(.95,.95));assert.equal(rf.box.x,.6);assert.equal(rf.box.y,.4);
// Inside drag moves without changing the crop dimensions.
startBox(event(.7,.5));assert.equal(rf.gesture.kind,'move');
moveBox(event(.5,.3));assert.ok(Math.abs(rf.box.x-.4)<1e-9);assert.equal(rf.box.w,.4);
finishBox(event(.5,.3));
// Outside drag draws a new ratio-locked crop.
startBox(event(.1,.1));moveBox(event(.3,.3));
assert.ok(Math.abs(rf.box.h/rf.box.w-(960*1920)/(1080*1080))<1e-9);
finishBox(event(.3,.3));
// Corner handles always resize, including when a handle extends outside the box.
const corner=event(.1,.1);corner.target.closest=()=>({dataset:{h:'nw'}});
startBox(corner);assert.equal(rf.gesture.kind,'grow');finishBox(corner);
// Cancelling a redraw restores the previous box.
const before=rf.box;startBox(event(.9,.9));moveBox(event(.8,.8));
finishBox({...event(.8,.8),type:'pointercancel'});assert.equal(rf.box,before);
rf.space=true;startBox(event(.5,.5));assert.equal(rf.gesture.kind,'pan');rf.space=false;
for(const x of [.001,.2,.999]) for(const y of [.001,.3,.999]) {
 const b=boxFrom(x,y,1,1,1.5,.6);
 assert.ok(b.x>=0 && b.y>=0 && b.x+b.w<=1.000001 && b.y+b.h<=1.000001);
 assert.ok(Math.abs(b.h/b.w-1.5)<1e-6);
}
'''
        result=subprocess.run(['node','-e',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
