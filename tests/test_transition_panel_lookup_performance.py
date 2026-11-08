import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class TransitionPanelLookupPerformance(unittest.TestCase):
    def test_panel_finds_lane_position_without_scanning_later_clips(self):
        text = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/panels.js').read_text()
        paint = 'function paintTransitions() {' + text.split('function paintTransitions() {', 1)[1].split('// ----- Music', 1)[0]
        script = r'''
const assert=require('node:assert/strict');let reads=0,message='';
const state={sel:0,project:{clips:[]}},laneOf=c=>{reads++;return c?.lane||'top';};
const nodes={},$=id=>nodes[id]??={children:[],replaceChildren(...a){this.children=a;}};
const document={createElement:()=>({setAttribute(k,v){this[k]=v;}})};
const TRANSITION_TILES=[['fade','Fade']],TILE_LOOK={fade:'black'},transitionOf=c=>c.transition||'none';
const setClipField=()=>{},toast=m=>message=m,zoomSlider=(...a)=>a,tlenOf=()=>.5;
''' + paint + r'''
state.project.clips=Array.from({length:2000},()=>({lane:'top'}));paintTransitions();
assert.ok(reads<=2,`${reads} lane reads for the first clip`);
nodes.trGrid.children[0].onclick();assert.equal(message,'Fade from black into the clip');
let seed=37;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let n=0;n<500;n++){
 const clips=Array.from({length:n%40},()=>({lane:rand()<.3?'bottom':'top',transition:rand()<.3?'fade':'none'}));
 if(clips.length>3&&n%3===0)delete clips[1];
 if(clips.length>5&&n%5===0)clips[4]=clips[0];
 state.project.clips=clips;state.sel=n%45-1;
 const c=clips[state.sel],lane=c?clips.filter(x=>laneOf(x)===laneOf(c)):[],at=c?lane.indexOf(c):-1;
 paintTransitions();const first=!c||at<=0;
 const note=!c?'Select a clip on the timeline first.':first?'Start of the clip. It fades in from black. Click a transition to apply it.':`Between clip ${at} and clip ${at+1}.`;
 assert.equal(nodes.trNote.textContent,note);assert.equal(nodes.trGrid.children[0].disabled,!c);
 assert.equal(nodes.trLen.children.length,c&&transitionOf(c)!=='none'?1:0);
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
