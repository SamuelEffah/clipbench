import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class HiddenEffectsPerformance(unittest.TestCase):
    def test_hidden_effects_skip_tiles_and_opening_refreshes_selection(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        def function(name):
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
let created=0,scans=0,applied=null;
const element=()=>({children:[],attrs:{},hidden:false,replaceChildren(...els){this.children=els;},appendChild(el){this.children.push(el);},setAttribute(k,v){this.attrs[k]=v;}});
const ids=new Map(),$=id=>{if(!ids.has(id))ids.set(id,element());return ids.get(id);};
const document={createElement:()=>{created++;return element();},body:{classList:{add(){},remove(){}}}};
const state={mode:'clip',sel:0,project:{clips:[{effect:'none'}]}};
const usesEffects=c=>{scans++;return c.effect!=='none';},inShort=()=>state.mode==='short';
const GROUPS=[{group:'Look',items:[['none','None',{effect:'none'}],['bw','Black and white',{effect:'bw'}]]},{group:'Transitions',shortOnly:true,items:[['fade','Fade',{transition:'fade'}]]}];
const swatchHtml=id=>id,matchesPatch=(c,patch)=>Object.entries(patch).every(([k,v])=>c[k]===v),applyPatch=(...args)=>applied=args;
const renderLibrary=()=>{},renderFavs=()=>{};
''' + function('renderFx') + function('setSideTab') + r'''
$('fxPanel').hidden=true;renderFx();assert.equal(created,0);assert.equal(scans,0);
setSideTab('fx');assert.equal($('fxGrid').children.length,2);assert.equal(created,4);assert.equal(scans,1);
let buttons=$('fxGrid').children[1].children;assert.equal(buttons[0].attrs['aria-pressed'],true);assert.equal(buttons[1].attrs['aria-pressed'],false);
buttons[1].onclick();assert.deepEqual(applied,[0,{effect:'bw'},'Black and white']);
setSideTab('media');created=0;scans=0;state.project.clips=[{effect:'bw'}];
for(let i=0;i<120;i++)renderFx();assert.equal(created,0);assert.equal(scans,0);
setSideTab('fx');buttons=$('fxGrid').children[1].children;assert.equal(buttons[0].attrs['aria-pressed'],false);assert.equal(buttons[1].attrs['aria-pressed'],true);
// The Short has its own rail: the sidebar grid stays hidden even when its tab flag is selected.
state.mode='short';created=0;scans=0;setSideTab('fx');renderFx();assert.equal(created,0);assert.equal(scans,0);
state.mode='clip';setSideTab('fx');assert.equal(created,4);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
