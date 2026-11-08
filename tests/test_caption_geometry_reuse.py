import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class CaptionGeometryReuseTests(unittest.TestCase):
    def test_stable_frames_skip_geometry_reads_and_resize_text_and_style_refresh(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        code = 'function syncCapSel(' + source.split('function syncCapSel(', 1)[1].split('// Collect preview timing', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let reads=0,width=100,left=20,onResize;
const el={textContent:'Hello',dataset:{cap:'hello',at:'home'},style:{cssText:'font-size:40px',transform:'none',transformOrigin:'center'}};
for(const key of ['offsetLeft','offsetTop','offsetWidth','offsetHeight'])Object.defineProperty(el,key,{get(){reads++;return key==='offsetWidth'?width:key==='offsetLeft'?left:20;}});
const ids={cCap:el,capSel:{style:{}},capRead:{}},$=id=>ids[id];
const state={mode:'short',project:{clips:[{}]}},preview={idx:0};let capHome={};
const inShort=()=>true,setPlaybackValue=(el,key,value)=>el[key]=value,capStyleOf=()=>({scale:1,rot:0});
class ResizeObserver{constructor(fn){onResize=fn;}observe(){}disconnect(){}}
''' + code + r'''
syncCapSel();reads=0;for(let i=0;i<120;i++)syncCapSel();assert.equal(reads,0,'unchanged frames must not force 480 geometry reads');
width=140;onResize();syncCapSel();assert.equal(ids.capSel.style.width,'140px');assert.equal(reads,4);
el.textContent='Edited';syncCapSel();assert.equal(reads,8);
left=40;el.style.cssText='left:40px';syncCapSel();assert.equal(reads,12);assert.equal(ids.capSel.style.left,'40px');
capHome={};syncCapSel();assert.equal(reads,16);
syncCapSel({scale:2,rot:10});assert.equal(ids.capRead.textContent,'200% · 10°');assert.equal(reads,16);
el.textContent='';syncCapSel();assert.equal(ids.capSel.hidden,true);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
