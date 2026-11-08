import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class TimelineSeamPerformance(unittest.TestCase):
    def test_lane_render_uses_known_first_clip_without_copying_history(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        app = (ui / 'app.js').read_text()
        short = (ui / 'short.js').read_text()
        first = 'function firstInLane(' + app.split('function firstInLane(', 1)[1].split('\nfunction applyPatch(', 1)[0]
        seam = 'function seamButton(' + short.split('function seamButton(', 1)[1].split('\nfunction nextInLane(', 1)[0]
        row = 'function laneRow(' + short.split('function laneRow(', 1)[1].split('// One clip', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const makeElement=()=>({children:[],dataset:{},style:{},attrs:{},classList:{toggle(){}},
 setAttribute(k,v){this.attrs[k]=v;},append(...els){this.children.push(...els);},
 appendChild(el){this.children.push(el);},querySelector(){return this.children.find(c=>c.clip)||null;}});
const document={createElement:makeElement};
const laneOf=c=>c.lane||'top',outLen=c=>5,seamOverlap=()=>0,introLength=()=>1;
const transitionOf=c=>c.transition||'none';
const tlenOf=()=>0.3;
const TRANSITION_NAMES={flash:'Flash'};
let picked,rail;
const pickClip=i=>picked=i,railShow=s=>rail=s;
const clipBlock=(c,i)=>({...makeElement(),clip:true,index:i});
const laneMuted=()=>false,laneDimmedBySolo=()=>false,laneLocked=()=>false;
const state={project:{clips:[]}};
''' + first + seam + row + r'''
let reads=0;
const clips=Array.from({length:2000},()=>({}));
state.project.clips=new Proxy(clips,{get(t,k,r){if(/^\d+$/.test(String(k)))reads++;return Reflect.get(t,k,r);}});
const result=laneRow('top',state.project.clips,10,10000);
assert.ok(reads<=4000,`${reads} clip reads during a 2000-clip lane render`);
const track=result.children[0],buttons=track.children.slice(2000);
assert.equal(buttons.length,2000);
assert.ok(buttons[0].className.includes('intro'));
assert.ok(buttons[0].attrs['aria-label'].includes('from black'));
assert.equal(buttons[0].style.left,'14px');
assert.ok(!buttons[1].className.includes('intro'));
assert.equal(buttons[1].style.left,'50px');
buttons[1].onclick({stopPropagation(){}});assert.equal(picked,1);assert.equal(rail,'transitions');
state.project.clips=[{lane:'top'},{lane:'bottom',transition:'flash'},{lane:'top'},{lane:'bottom'}];
const lower=laneRow('bottom',state.project.clips,10,10).children[0].children.slice(2);
assert.ok(lower[0].className.includes('intro'));
assert.ok(lower[0].className.includes('on'));
assert.ok(lower[0].attrs['aria-label'].includes('Flash from black'));
assert.ok(!lower[1].className.includes('intro'));
// Standalone callers retain automatic first-in-lane detection.
assert.ok(seamButton(state.project.clips[1],1,0).className.includes('intro'));
assert.ok(!seamButton(state.project.clips[3],3,0).className.includes('intro'));
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
