import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class RailPanelsPerformance(unittest.TestCase):
    def test_only_the_open_tool_renders_and_opening_refreshes_it(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        def function(file, name):
            source = (ui / file).read_text()
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
let railOpen=null,railMode=false,calls=[],badge=0,dropdowns=0,version=0;
const paintBank=()=>calls.push(['bank',version]),paintTransitions=()=>calls.push(['transitions',version]),paintText=()=>calls.push(['text',version]),paintMusic=()=>calls.push(['music',version]),paintLook=()=>calls.push(['look',version]);
const paintShortsBadge=()=>badge++,repaintDropdowns=()=>dropdowns++,setPreviewMuted=()=>{},closeDropdowns=()=>{},updatePreview=()=>{};
const names=['clips','transitions','text','look','broll','music'];
const sections=names.map(name=>({dataset:{panel:name},hidden:true}));
const buttons=names.map(name=>({dataset:{panel:name},attrs:{},setAttribute(k,v){this.attrs[k]=v;}}));
const pop={hidden:true,querySelectorAll:()=>sections},$=()=>pop;
const document={querySelector:()=>({prepend(){}}),querySelectorAll:()=>buttons};
const railClose=()=>railShow(null);
''' + function('panels.js', 'paintShortPanels') + function('rail.js', 'railShow') + function('rail.js', 'railSync') + r'''
for(let i=0;i<120;i++)railSync(true);
assert.equal(calls.length,0,'closed tools must not rebuild during timeline renders');assert.equal(badge,120);assert.equal(dropdowns,120);
for(const name of names) {
 calls=[];version++;railShow(name);
 const expected=name==='clips'||name==='broll'?'bank':name;
 assert.deepEqual(calls,[[expected,version]]);assert.equal(pop.hidden,false);
 assert.equal(sections.find(s=>s.dataset.panel===name).hidden,false);
 assert.equal(buttons.find(b=>b.dataset.panel===name).attrs['aria-pressed'],true);
 calls=[];version++;railSync(true);assert.deepEqual(calls,[[expected,version]],'visible tool follows subsequent edits');
}
railClose();calls=[];for(let i=0;i<120;i++)railSync(true);assert.deepEqual(calls,[]);assert.equal(pop.hidden,true);
railShow('clips');calls=[];railSync(false);assert.deepEqual(calls,[]);assert.equal(railOpen,null);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
