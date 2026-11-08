import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class TimelineDragPerformance(unittest.TestCase):
    def test_drag_measures_before_writes_and_keeps_gap_positions(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        app = (ui / 'app.js').read_text()
        helper = 'function setPlaybackValue(' + app.split('function setPlaybackValue(', 1)[1].split('\nfunction placePlayhead', 1)[0]
        short = (ui / 'short.js').read_text()
        room = 'function makeRoom(' + short.split('function makeRoom(', 1)[1].split('\nfunction showSlot(', 1)[0]
        slot = 'function slotFromX(' + short.split('function slotFromX(', 1)[1].split('// Width in pixels', 1)[0]
        show = 'function showSlot(' + short.split('function showSlot(', 1)[1].split('\nconst clipPeaks', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let writes=0,ghostReads=0,readsAfterWrite=0,dirty=false,dragPx=50;
const style=()=>new Proxy({transform:''},{set(t,k,v){writes++;dirty=true;t[k]=v;return true;}});
const measure=v=>{if(dirty)readsAfterWrite++;return v;};
let blocks=[],ghost,outsider={style:style()};
const track={querySelectorAll:()=>[...blocks,ghost],contains:b=>blocks.includes(b)||b===ghost};
const stlBody={classList:{add(){}},querySelectorAll:()=>[...blocks,outsider]};
function setup(count,origin,local=true) {
 blocks=Array.from({length:count},(_,i)=>({style:style(),
 get offsetLeft(){return measure((i<origin?i:i+1)*100);},get offsetWidth(){return measure(100);}}));
 ghost={parentElement:local?track:{},style:style(),get offsetLeft(){ghostReads++;return measure(origin*100);}};
 writes=0;ghostReads=0;readsAfterWrite=0;dirty=false;
}
''' + helper + room + slot + show + r'''
setup(1000,3);
makeRoom(track,blocks,ghost,6);
assert.equal(ghostReads,1,'measure the dragged clip position only once');
assert.equal(readsAfterWrite,0,'finish layout reads before changing transforms');
assert.equal(blocks[2].style.transform,'');assert.equal(blocks[3].style.transform,'translateX(-50px)');
assert.equal(blocks[6].style.transform,'');assert.equal(ghost.style.transform,'translateX(350px)');
writes=0;dirty=false;makeRoom(track,blocks,ghost,6);
assert.equal(writes,0,'unchanged drag slots should not rewrite transforms');
// Gap placement for every slot, including external drags and an empty lane.
for(const local of [true,false])for(let count=0;count<12;count++)for(let origin=0;origin<=count;origin++)for(let k=0;k<=count;k++) {
 setup(count,origin,local);
 const positions=blocks.map(b=>b.offsetLeft),ghostLeft=origin*100;
 const oldOrigin=local?positions.filter(x=>x<ghostLeft).length:null;
 const shift=j=>(j>=k?50:0)-(oldOrigin!==null&&j>=oldOrigin?50:0);
 const at=k<count?positions[k]+shift(k)-50:count?positions.at(-1)+100+shift(count-1):0;
 makeRoom(track,blocks,ghost,k);
 blocks.forEach((b,j)=>assert.equal(b.style.transform,shift(j)?`translateX(${shift(j)}px)`:''));
 assert.equal(ghost.style.transform,local?`translateX(${at-ghostLeft}px)`:'');
}
setup(10,3);
let queries=0;
track.querySelectorAll=selector=>{
 if(selector.includes(':not')){queries++;return blocks;}
 return [...blocks,ghost];
};
track.classList={add(){}};
stlBody.querySelector=()=>ghost;
blocks.forEach((b,i)=>b.getBoundingClientRect=()=>({left:i*100,width:100}));
function laneTrack(){return track;}
function clearMarks(){}
showSlot({clientX:550},'top');assert.equal(queries,1,'reuse the slot block list');
assert.equal(slotFromX({clientX:550},'top'),6,'drop callers still query their own blocks');
assert.equal(queries,2);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
