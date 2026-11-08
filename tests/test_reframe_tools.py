import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ReframeTools(unittest.TestCase):
    def test_move_subject_and_locked_crop(self):
        src = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/reframebox.js').read_text()
        start = 'function startBox(' + src.split('function startBox(', 1)[1].split('\nfunction moveBox', 1)[0]
        box = 'function boxFrom(' + src.split('function boxFrom(', 1)[1].split('\nconst reframeUi', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const BOX_MIN=.06;
let rf={size:[1920,1080],cell:[1080,960],box:{x:.3,y:.1,w:.4,h:.6},view:{},tool:'move'};
const pointOn=e=>[e.x,e.y], viewOf=()=>({fw:.633});
const document={getElementById:()=>({setPointerCapture(){}})};
const paintBox=()=>{},setReframeTool=t=>rf.tool=t;
const event=(x,y)=>({x,y,button:0,target:{closest:()=>null},preventDefault(){}});
''' + start + box + r'''
startBox(event(.9,.9));
assert.equal(rf.gesture.kind,'move','outside click must not redraw in Move mode');
rf.tool='draw';startBox(event(.2,.2));assert.equal(rf.gesture.kind,'grow');
rf.tool='subject';startBox(event(.95,.95));
assert.equal(rf.box.x,.6);assert.equal(rf.box.y,.4);assert.equal(rf.tool,'move');
for(const x of [.001,.2,.999]) for(const y of [.001,.3,.999]) {
 const b=boxFrom(x,y,1,1,1.5,.6);
 assert.ok(b.x>=0 && b.y>=0 && b.x+b.w<=1.000001 && b.y+b.h<=1.000001);
 assert.ok(Math.abs(b.h/b.w-1.5)<1e-6);
}
'''
        result=subprocess.run(['node','-e',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
