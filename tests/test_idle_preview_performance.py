import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class IdlePreviewTests(unittest.TestCase):
    def test_paused_frames_reuse_canvas_with_media_edit_and_transition_invalidation(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        code = 'function drawMirror() {' + source.split('function drawMirror() {', 1)[1].split('\nlet rendering =', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let fills=0,pictures=0,hidden=false;
const $=()=>({hidden}),mirror={width:480,height:270};
const mctx={fillRect(){fills++;},save(){},restore(){},beginPath(){},rect(){},clip(){},translate(){},fillText(){}};
const media=()=>({paused:true,seeking:false,readyState:4,currentTime:2,videoWidth:1920,videoHeight:1080,src:'a',dataset:{id:'a',base:'0'}});
const video=media(),laneVids=[media(),media(),media()];
let lowNow=[];
const state={mode:'short',project:{clips:[{effect:'none'}],watermark:false},clipStop:null};
const preview={on:true,idx:0,elapsed:2,done:false},blendRun={from:null};
const inShort=()=>true,splitOn=()=>!!state.project.split,laneCount=()=>2;
const laneBoxes=()=>[[0,0,1,.5],[0,.5,1,.5]];
const paintClip=()=>pictures++,paintTransition=()=>{},fadeAmount=()=>0,drawBlurBackground=()=>{};
''' + code + r'''
drawMirror();pictures=0;fills=0;
for(let i=0;i<120;i++)drawMirror();
assert.equal(pictures,0,'paused stable preview must not copy 120 identical video frames');assert.equal(fills,0);
const redraw=fn=>{const n=pictures;fn();drawMirror();assert.ok(pictures>n);};
redraw(()=>video.currentTime=3);
redraw(()=>state.project={...state.project,clips:[{effect:'bw'}]});
redraw(()=>mirror.width=640);
redraw(()=>video.src='b');
redraw(()=>preview.idx=1);
redraw(()=>preview.idx=0);
hidden=true;drawMirror();hidden=false;redraw(()=>{});
video.paused=false;redraw(()=>{});redraw(()=>{});video.paused=true;drawMirror();
blendRun.from={};redraw(()=>{});redraw(()=>{});blendRun.from=null;drawMirror();
state.clipStop={holding:1};redraw(()=>{});redraw(()=>{});state.clipStop=null;
state.project={...state.project,split:true};lowNow=[{clip:{effect:'none'}}];drawMirror();
const before=pictures;for(let i=0;i<120;i++)drawMirror();assert.equal(pictures,before);
redraw(()=>laneVids[0].currentTime=5);
redraw(()=>laneVids[0].seeking=true);
redraw(()=>laneVids[0].seeking=false);
redraw(()=>lowNow=[{clip:{effect:'bw'}}]);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
