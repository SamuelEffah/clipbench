import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class TextPanelCountPerformance(unittest.TestCase):
    def test_caption_controls_stop_after_two_eligible_captions(self):
        text = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/textpanel.js').read_text()
        paint = 'function paintText() {' + text.split('function paintText() {', 1)[1].split('\nconst card =', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const nodes={},$=id=>nodes[id]??=(id==='textGrid'?{replaceChildren(){}}:{});
const state={project:{clips:[]}},textClip=()=>null,paintCaptionMode=()=>{},paintWordColour=()=>{},capsApart=()=>false,CAP_LOOKS={};
let reads=0;const isTop=c=>{reads++;return !c.lane||c.lane==='top';};
''' + paint + r'''
state.project.clips=Array.from({length:2000},()=>({caption:'caption'}));
paintText();
assert.equal(nodes.textSame.hidden,false);assert.equal(nodes.textModeAll.hidden,false);
assert.ok(reads<=2,`${reads} clip checks to find two captions`);
let seed=17;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let n=0;n<500;n++){
 state.project.clips=Array.from({length:n%50},()=>({caption:rand()<.3?'words':'',lane:rand()<.4?'lower':'top'}));
 const several=state.project.clips.filter(c=>isTop(c)&&c.caption).length>1;
 paintText();
 assert.equal(nodes.textSame.hidden,!several);assert.equal(nodes.textModeAll.hidden,!several);
 assert.equal(nodes.textSameBox.checked,true);
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
