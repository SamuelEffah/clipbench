import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class BankRenderPerformance(unittest.TestCase):
    def test_bank_render_reuses_matches_and_lane_order(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        panels = (ui / 'panels.js').read_text()
        app = (ui / 'app.js').read_text()
        finder = 'function momentFinder(' + app.split('function momentFinder(', 1)[1].split('\nfunction momentLookup(', 1)[0]
        def function(name):
            return 'function ' + name + '(' + panels.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
let reads=0,comparisons=0;
const sameMoment=(a,b)=>{comparisons++;return a.src===b.src&&Math.abs(a.in-b.in)<.05&&Math.abs(a.out-b.out)<.05;};
const laneOf=c=>c.lane||'top',LANES=['top','lower'],laneIndex=c=>Math.max(0,LANES.indexOf(laneOf(c)));
const state={sel:0,project:{clips:[]},library:[{path:'v3',duration:5,broll:true,name:'Broll.mp4'}]};
let bank=[];
const bankOf=()=>bank,usedIndex=c=>state.project.clips.findIndex(t=>sameMoment(c,t));
const element=()=>({children:[],replaceChildren(...els){this.children=els;},querySelector:()=>({})});
const document={createElement:element},elements=new Map(),$=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
const byPath=src=>({name:src+'.mp4'}),outLen=c=>c.out-c.in,esc=s=>s,mmss=String;
const brollClip=v=>({src:v.path,in:0,out:Math.min(v.duration,10)});
''' + finder + function('bankRow') + function('brollRow') + function('paintBank') + r'''
const clips=Array.from({length:2000},(_,i)=>({src:`v${i}`,in:0,out:5,lane:i%2?'lower':'top'}));
state.project.clips=new Proxy(clips,{get(t,k,r){if(/^\d+$/.test(String(k)))reads++;return Reflect.get(t,k,r);}});
bank=clips.map((c,i)=>({...c,in:i%2?.1:0}));
paintBank();assert.ok(reads<=6000,`${reads} timeline reads while painting 2000 bank cards`);assert.ok(comparisons<=2001);
assert.equal($('bankCount').textContent,'1000 of 2000 used');
const rows=$('bankRows').children;assert.equal(rows.length,2000);
assert.ok(rows[0].innerHTML.includes('ord num">1</span>'));assert.ok(rows[0].innerHTML.includes('aria-pressed="true"'));
assert.ok(rows[1].innerHTML.includes('aria-pressed="false"'));assert.ok(rows[2].innerHTML.includes('ord num">2</span>'));
assert.ok($('brollRows').children[0].innerHTML.includes('aria-pressed="true"'));
// The earliest matching trim wins, even when another lane contains another copy.
state.project.clips=[{src:'x',in:0,out:5,lane:'lower'},{src:'x',in:.01,out:5},{src:'y',in:0,out:5,lane:'lower'}];
bank=[{src:'x',in:0,out:5},{src:'y',in:0,out:5}];paintBank();
assert.ok($('bankRows').children[0].innerHTML.includes('ord num b">2.1</span>'));
assert.ok($('bankRows').children[1].innerHTML.includes('ord num b">2.2</span>'));
assert.equal(momentFinder(state.project.clips)(bank[0]),0);
// Standalone card callers still resolve usage and lane order themselves.
assert.ok(bankRow(bank[1],'clips').innerHTML.includes('ord num b">2.2</span>'));
bank=[];state.library=[];paintBank();assert.equal($('bankCount').textContent,'0 of 0 used');assert.ok($('bankRows').innerHTML.includes('No clips yet'));
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
