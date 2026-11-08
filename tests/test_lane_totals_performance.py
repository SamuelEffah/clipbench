import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class LaneTotalsPerformance(unittest.TestCase):
    def test_timeline_render_collects_durations_once_and_preserves_active_lane_span(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/short.js').read_text()
        totals = 'function laneTotal(' + source.split('function laneTotal(', 1)[1].split('// How far apart', 1)[0]
        render = 'function renderShortTl(' + source.split('function renderShortTl(', 1)[1].split('// Split a clip', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let reads=0,lengthReads=0,count=4,stlPps=0,stlBasePps=0,tlZoom=2,rulerArgs,heads=0,playheads=0;
const LANES=['top','bottom','left','right'],TL_SECONDS=60,SHORT_LIMIT=60;
const laneOf=c=>{reads++;return c.lane||'top';},outLen=c=>{lengthReads++;return c.len;},seamOverlap=(prev,c)=>prev?Math.min(prev.len/2,c.len/2,c.overlap||0):0;
const state={project:{clips:[]}},laneCount=()=>count,syncPicked=()=>{};
function clipBlock(){}function soundBlock(){}
const shortRuler=(...args)=>{rulerArgs=args;return {};},laneRow=()=>({}),soundRow=()=>({}),textRow=()=>({}),audioLane=()=>({});
const stlBody={clientWidth:1028,scrollLeft:45,style:{setProperty(k,v){this[k]=v;}},classList:{toggle(){}},replaceChildren(){},querySelector:()=>null,append(){}};
const document={createElement:()=>({style:{}})},paintLaneHeads=()=>heads++,paintPlayhead=()=>playheads++;
''' + totals + render + r'''
state.project.clips=Array.from({length:2000},(_,i)=>({lane:LANES[i%4],len:5}));
renderShortTl();assert.equal(reads,2000,'timeline duration calculation must scan clips once');assert.equal(lengthReads,2000);
assert.deepEqual(rulerArgs,[2500,2500]);assert.equal(stlPps,2);assert.equal(stlBody.style['--tlw'],'5000px');assert.equal(stlBody.scrollLeft,45);
assert.equal(heads,1);assert.equal(playheads,1);
let seed=14;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
 const clips=Array.from({length:Math.floor(rand()*60)},()=>({lane:LANES[Math.floor(rand()*4)],len:rand()<.2?0:rand()*10,overlap:rand()}));
 state.project.clips=clips;const sums=laneTotals(clips);
 for(const lane of LANES)assert.equal(sums.get(lane)??0,laneTotal(lane,clips));
 count=1+Math.floor(rand()*4);renderShortTl();
 const top=laneTotal('top',clips),longest=Math.max(top,...LANES.slice(0,count).map(l=>laneTotal(l,clips)));
 assert.deepEqual(rulerArgs,[Math.max(TL_SECONDS,Math.ceil(longest/10)*10),top]);
}
// Hidden lanes do not widen a one-lane timeline; edits are measured on the next render.
count=1;state.project.clips=[{len:5},{lane:'right',len:1000}];lengthReads=0;renderShortTl();assert.deepEqual(rulerArgs,[60,5]);assert.equal(lengthReads,1);
state.project.clips[0].len=75;renderShortTl();assert.deepEqual(rulerArgs,[80,75]);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
