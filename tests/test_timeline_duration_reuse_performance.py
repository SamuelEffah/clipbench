import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class TimelineDurationReusePerformance(unittest.TestCase):
    def test_timeline_metrics_share_durations_with_transition_calculation(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        def function(file, name):
            source = (ui / file).read_text()
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
let durations=0;
const outLen=c=>{durations++;return c.len;},laneOf=c=>c.lane||'top';
const transitionOf=c=>c.transition||'none',tlenOf=c=>c.tlen||.3;
''' + function('app.js', 'seamOverlap') + function('short.js', 'laneTotal') + function('short.js', 'laneTotals') + function('timeline.js', 'clipStarts') + r'''
const lanes=['top','bottom','left','right'];
const clips=Array.from({length:2000},(_,i)=>({lane:lanes[i%4],len:5,transition:'fade'}));
clipStarts(clips);assert.ok(durations<=3996,'clip positions should avoid redundant current-duration calculations');
durations=0;laneTotals(clips);assert.ok(durations<=3996,'all-lane totals should avoid redundant current-duration calculations');
durations=0;laneTotal('top',clips);assert.equal(durations,500,'single-lane totals should calculate each matching duration once');
function previousStarts(list) {
 const at={},prev={};return list.map(c=>{const lane=laneOf(c);at[lane]=(at[lane]||0)-seamOverlap(prev[lane],c);const start=at[lane];at[lane]+=outLen(c);prev[lane]=c;return start;});
}
function previousTotal(lane,list) {
 let sum=0,prev;for(const c of list){if(laneOf(c)!==lane)continue;sum=sum+outLen(c)-seamOverlap(prev,c);prev=c;}return sum;
}
let seed=42;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
 const list=Array.from({length:Math.floor(rand()*60)},()=>({lane:lanes[Math.floor(rand()*4)],len:rand()<.2?0:rand()*10,transition:rand()<.3?'none':'fade',tlen:rand()*2}));
 assert.deepEqual(clipStarts(list),previousStarts(list));
 const sums=laneTotals(list);
 for(const lane of lanes){const expected=previousTotal(lane,list);assert.equal(laneTotal(lane,list),expected);assert.equal(sums.get(lane)??0,expected);}
 const selected=laneTotals(list,['top','left']);assert.equal(selected.has('bottom'),false);assert.equal(selected.has('right'),false);
 for(const lane of ['top','left'])assert.equal(selected.get(lane)??0,previousTotal(lane,list));
 if(list.length){list[0].len=20;list[0].lane='top';assert.deepEqual(clipStarts(list),previousStarts(list));assert.equal(laneTotal('top',list),previousTotal('top',list));}
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
