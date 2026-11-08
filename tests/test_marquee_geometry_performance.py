import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class MarqueeGeometryPerformance(unittest.TestCase):
    def test_drag_reuses_clip_bounds_until_scroll_layout_or_content_changes(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/selection.js').read_text()
        source = source[source.index('// ----- Marquee'):source.index('// ----- Razor')]
        script = r'''
const assert=require('node:assert/strict');
let reads=0,left=0,width=1000,stlPps=40,picked=[],renders=0,animating=false;
const state={project:{clips:[]}},events={},listeners={};
const makeNode=i=>({dataset:{gi:String(i)},marked:false,
 classList:{toggle(name,on){this.owner.marked=on},remove(){this.owner.marked=false}},
 getBoundingClientRect(){reads++;const x=left+i*stlPps/4-stlBody.scrollLeft;
 return {left:x,right:x+stlPps/5,top:0,bottom:10}}});
let nodes=Array.from({length:2000},(_,i)=>makeNode(i));
for(const node of nodes)node.classList.owner=node;
const stlBody={scrollLeft:0,scrollTop:0,getAnimations:()=>animating?[{playState:'running'}]:[],addEventListener(k,fn){events[k]=fn},append(){},
 getBoundingClientRect(){return {left,top:0,width,height:100}},
 querySelectorAll(q){return q==='.stl-clip'?nodes:nodes.filter(n=>n.marked)}};
const window={addEventListener(k,fn){listeners[k]=fn},removeEventListener(k){delete listeners[k]}};
const document={createElement(){return {style:{},remove(){}}}};
const inShort=()=>true,setPicked=ids=>picked=ids,setTab=()=>{},render=()=>renders++;
''' + source + r'''
events.pointerdown({button:0,clientX:0,clientY:0,target:{matches:()=>true,closest:()=>null}});
const move=()=>listeners.pointermove({clientX:120,clientY:20});
for(let i=0;i<120;i++)move();
assert.equal(reads,2000,'unchanged drag frames must reuse the same clip rectangles');
stlBody.scrollLeft=20;move();assert.equal(reads,4000,'scrolling invalidates bounds');
stlPps=80;move();assert.equal(reads,6000,'zoom invalidates bounds');
state.project={clips:[]};move();assert.equal(reads,8000,'project edits invalidate bounds');
nodes=[...nodes];nodes[10]=makeNode(10);nodes[10].classList.owner=nodes[10];
move();assert.equal(reads,10000,'replaced clip nodes invalidate bounds');
left=5;move();assert.equal(reads,12000,'moving the timeline invalidates viewport coordinates');
width=1100;move();assert.equal(reads,14000,'resizing the timeline invalidates bounds');
animating=true;move();move();assert.equal(reads,18000,'active transitions require live bounds');
animating=false;move();move();assert.equal(reads,20000,'settled transitions refresh once before reuse');
const expected=nodes.filter((node,i)=>{const x=left+i*stlPps/4-stlBody.scrollLeft;return x<120&&x+stlPps/5>0}).map(n=>Number(n.dataset.gi));
listeners.pointerup();assert.deepEqual(picked,expected);assert.equal(state.sel,expected[0]);assert.equal(renders,1);
assert.equal(listeners.pointermove,undefined);
'''
        out = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
