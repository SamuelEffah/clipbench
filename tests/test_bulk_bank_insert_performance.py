import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class BulkBankInsertPerformance(unittest.TestCase):
    def test_bulk_add_inserts_once_and_preserves_order_callbacks_and_selection(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        def function(file, name):
            source = (ui / file).read_text()
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
let laneReads=0,assignments=0,edits=0,restarted=-1,message='',timers=[],captioned=[],bankAnchor=9;
const bankSel=new Set();
const state=new Proxy({mode:'short',sel:-1,project:{clips:[],other:[]}},{set(t,k,v){if(k==='project')assignments++;t[k]=v;return true;}});
const inShort=()=>state.mode==='short',timelineOf=()=>inShort()?state.project.clips:state.project.other,bankOf=()=>inShort()?state.project.other:state.project.clips;
const laneOf=c=>{laneReads++;return c.lane||'top';},splitOn=()=>state.project.template==='split';
const setTimeout=fn=>timers.push(fn),captionFromSubtitles=c=>captioned.push(c),changed=()=>edits++,restartPreviewAt=i=>restarted=i,toast=t=>message=t;
''' + ''.join(function('short.js', name) for name in ['newTimelineItem', 'setTimeline', 'laneInsertAt', 'insertClip']) + function('timeline.js', 'clearBankSel') + function('timeline.js', 'addPickedToShort') + r'''
const initial=Array.from({length:1000},(_,i)=>({src:`old${i}`,in:0,out:5}));
const bank=Array.from({length:1000},(_,i)=>({src:`bank${i}`,in:1,out:6,note:`Note${i}`,volume:i%2?0:undefined}));
state.project={name:'project',template:'split',clips:initial,other:bank};for(let i=999;i>=0;i--)bankSel.add(i);laneReads=assignments=0;
addPickedToShort();assert.equal(assignments,1,'bulk add should replace the timeline once');assert.ok(laneReads<=1000,'bulk add should find the insertion slot at most once');
assert.equal(state.project.clips.length,2000);assert.equal(state.sel,1000);assert.equal(restarted,1000);assert.equal(edits,1);assert.equal(bankSel.size,0);assert.equal(bankAnchor,-1);assert.equal(timers.length,1000);assert.equal(message,'1000 clips added to the timeline');
for(let i=0;i<1000;i++){assert.equal(state.project.clips[i],initial[i]);assert.deepEqual(state.project.clips[1000+i],newTimelineItem(bank[i],'top'));}
for(const timer of timers)timer();assert.deepEqual(captioned,bank);
// Compare with sequential insertion for interleaved lanes, no top lane, both modes,
// sparse selections, and stale selected indices. Existing trailing lower clips stay last.
let seed=28;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<300;run++) {
 const list=Array.from({length:Math.floor(rand()*20)},(_,i)=>({src:`v${i}`,in:0,out:5,lane:['top','bottom','third'][Math.floor(rand()*3)]}));
 const saved=Array.from({length:10},(_,i)=>({src:`b${i}`,in:i,out:i+5,volume:i%3?1:0}));
 state.mode=run%2?'clip':'short';state.project={name:'test',template:run%3?'full':'split',clips:inShort()?list:saved,other:inShort()?saved:list};
 bankSel.clear();for(let i=12;i>=0;i--)if(rand()<.5)bankSel.add(i);
 const picked=[...bankSel].sort((a,b)=>a-b).map(i=>saved[i]).filter(Boolean);
 let expected=list,first=-1;for(const c of picked){const at=laneInsertAt(expected,'top',Infinity);if(first<0)first=at;expected=[...expected.slice(0,at),newTimelineItem(c,'top'),...expected.slice(at)];}
 timers=[];edits=assignments=0;state.sel=-1;const before=state.project;addPickedToShort();
 assert.deepEqual(timelineOf(),expected);assert.equal(edits,picked.length?1:0);assert.equal(assignments,picked.length?1:0);assert.equal(timers.length,picked.length);
 if(picked.length){assert.equal(state.sel,first);assert.equal(restarted,first);}else assert.equal(state.project,before);
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
