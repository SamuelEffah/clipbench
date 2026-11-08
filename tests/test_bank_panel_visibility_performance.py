import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class BankPanelVisibilityPerformance(unittest.TestCase):
    def test_clips_and_broll_do_not_build_each_others_hidden_cards(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        panels = (ui / 'panels.js').read_text()
        app = (ui / 'app.js').read_text()
        def function(source, name):
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
let bankCalls=0,bankCards=0,brollCards=0,lanes=0,libraryReads=0,railOpen=null;
const clips=Array.from({length:500},(_,i)=>({src:`v${i}`,in:0,out:5,lane:i%2?'lower':'top'}));
let bank=clips.map(c=>({...c}));
const state={project:{clips},library:new Proxy(Array.from({length:100},(_,i)=>({path:`v${i}`,broll:true,duration:5})),{get(t,k,r){if(/^\d+$/.test(String(k)))libraryReads++;return Reflect.get(t,k,r);}})};
const bankOf=()=>{bankCalls++;return bank;},laneOf=c=>{lanes++;return c.lane||'top';};
const sameMoment=(a,b)=>a.src===b.src&&Math.abs(a.in-b.in)<.05&&Math.abs(a.out-b.out)<.05;
const bankRow=(c,where,used,order)=>{bankCards++;return {src:c.src,used,order};};
const brollClip=v=>({src:v.path,in:0,out:Math.min(v.duration,10)}),brollRow=(v,used)=>{brollCards++;return {src:v.path,used};};
const ids=new Map(),$=id=>{if(!ids.has(id))ids.set(id,{children:[],replaceChildren(...els){this.children=els;}});return ids.get(id);};
const paintTransitions=()=>{},paintText=()=>{},paintMusic=()=>{},paintLook=()=>{},paintShortsBadge=()=>{};
''' + function(app, 'momentFinder') + function(panels, 'paintBank') + function(panels, 'paintShortPanels') + r'''
railOpen='broll';paintShortPanels();assert.equal(bankCalls,0,'B-roll must not inspect the hidden clip bank');assert.equal(bankCards,0);assert.equal(brollCards,100);assert.equal(lanes,0,'B-roll needs no clip-card lane ordering');
const broll=$('brollRows').children;assert.equal(broll[3].used,3);
brollCards=0;libraryReads=0;railOpen='clips';paintShortPanels();assert.equal(bankCalls,1);assert.equal(bankCards,500);assert.equal(brollCards,0);assert.equal(libraryReads,0);assert.equal($('brollRows').children,broll);
assert.equal($('bankCount').textContent,'500 of 500 used');assert.equal($('bankRows').children[3].order,2);
const rows=$('bankRows').children;bankCalls=0;bankCards=0;state.project.clips=[];railOpen='broll';paintShortPanels();assert.equal($('bankRows').children,rows);assert.equal(bankCalls,0);assert.equal(bankCards,0);assert.equal($('brollRows').children[0].used,-1);
railOpen='clips';paintShortPanels();assert.equal($('bankCount').textContent,'0 of 500 used');assert.equal($('bankRows').children[0].used,-1);
// Explicit no-argument refreshes used by upload handlers continue to update both lists.
bankCards=0;brollCards=0;paintBank();assert.equal(bankCards,500);assert.equal(brollCards,100);
bank=[];state.library=[];paintBank();assert.ok($('bankRows').innerHTML.includes('No clips yet'));assert.ok($('brollRows').innerHTML.includes('No B-roll yet'));
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
