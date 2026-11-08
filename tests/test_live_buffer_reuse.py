import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class LiveBufferReuseTests(unittest.TestCase):
    def test_ticks_and_markers_reuse_nodes_and_track_window_changes(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/live.js').read_text()
        fn = 'function paintBuffer() {' + source.split('function paintBuffer() {', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');let created=0;
function node(){return {children:[],style:{},classList:{toggle(){}},textContent:'',appendChild(c){this.children.push(c);c.remove=()=>this.children.splice(this.children.indexOf(c),1);},get lastChild(){return this.children.at(-1)},replaceChildren(){this.children=[]}};}
const elements=new Map(),liveEl=id=>{if(!elements.has(id))elements.set(id,node());return elements.get(id)};
const document={createElement(){created++;return node()}};
let bounds={lo:0,hi:100};const domain=()=>bounds,bufferView=d=>d;
const live={ranges:[],player:true,isLive:true,start:null,buffer:100,kind:'youtube'};
let made=[{start:10,end:20},{start:40,end:50}],syncing=false;
const paintMoments=()=>{};
const PAD=0,TWITCH_LIVE_HINT='',clock=String,stamp=String,mmss=String,behindText=()=>'',streamTitle=()=>'',checkPreview=()=>{},syncRanges=()=>{},liveNow=()=>30;
const place=(el,d,a,b)=>{el.style.left=(a-d.lo)/(d.hi-d.lo);el.style.width=(b-a)/(d.hi-d.lo)};
''' + fn + r'''
paintBuffer();assert.equal(created,6);const ticks=[...liveEl('bufTicks').children],markers=[...liveEl('bufMade').children];
created=0;for(let i=0;i<120;i++)paintBuffer();assert.equal(created,0);
assert.equal(liveEl('bufTicks').children[0],ticks[0]);assert.equal(liveEl('bufMade').children[0],markers[0]);
bounds={lo:30,hi:130};paintBuffer();assert.equal(liveEl('bufMade').children.length,1);assert.equal(liveEl('bufMade').children[0].style.left,.1);
live.isLive=false;paintBuffer();assert.equal(ticks[0].textContent,'30');assert.equal(ticks[3].textContent,'130');
bounds=null;paintBuffer();assert.equal(liveEl('bufTicks').children.length,0);assert.equal(liveEl('bufMade').children.length,0);
bounds={lo:0,hi:100};paintBuffer();assert.equal(liveEl('bufTicks').children.length,4);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
