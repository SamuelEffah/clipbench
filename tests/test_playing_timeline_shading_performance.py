import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class PlayingTimelineShadingPerformance(unittest.TestCase):
    def test_live_progress_reuses_block_bounds_and_formats_only_active_ranges(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        app = (ui / 'app.js').read_text()
        setter = 'function setPlaybackValue(' + app.split('function setPlaybackValue(', 1)[1].split('\nfunction placePlayhead(', 1)[0]
        audio = (ui / 'audio.js').read_text()
        paint = 'function paintPlayhead(' + audio.split('function paintPlayhead(', 1)[1].split('// ----- Details', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let reads=0,queries=0,cssReads=0,formats=0,head=null;
const originalFixed=Number.prototype.toFixed;Number.prototype.toFixed=function(...args){formats++;return originalFixed.apply(this,args);};
const makeBlock=(start,end)=>{const values={};return {dataset:{get t0(){reads++;return String(start);},get t1(){reads++;return String(end);}},values,style:{getPropertyValue:k=>{cssReads++;return values[k]||'';},setProperty(k,v){values[k]=v;},removeProperty(k){delete values[k];}}};};
let blocks=Array.from({length:2000},(_,i)=>makeBlock(i*5,i*5+5));
const body={querySelector:()=>head,querySelectorAll:()=>{queries++;return blocks;},appendChild(el){head=el;}};
const track={offsetLeft:40,offsetTop:20},$=()=>body,timeTrack=()=>track;
const document={createElement:()=>({style:{},firstChild:{textContent:''},remove(){head=null;}})};
const startScrub=()=>{},followPlayhead=()=>{},preview={on:true,elapsed:2},audioScale={pps:40};let scrub=null;
''' + setter + paint + r'''
paintPlayhead();reads=queries=cssReads=formats=0;
for(let i=1;i<=120;i++){preview.elapsed=2+i*.016;paintPlayhead();}
assert.equal(reads,0,'moving playheads must reuse immutable block timestamps');assert.equal(queries,0,'moving playheads must not re-query timeline blocks');
assert.ok(cssReads<=120,`${cssReads} CSS reads for 120 frames with one active block`);assert.ok(formats<=240,`${formats} number formats for 120 frames`);
assert.equal(blocks[0].values['--played'],'78.4%');assert.equal(blocks[1].values['--played'],'0.0%');
preview.elapsed=10000;paintPlayhead();assert.ok(blocks.every(b=>b.values['--played']==='100.0%'));
preview.elapsed=2;paintPlayhead();assert.equal(blocks[0].values['--played'],'40.0%');assert.equal(blocks[1].values['--played'],'0.0%');
// Rebuilding the timeline refreshes cached bounds and preserves the original clamp behavior.
head=null;blocks=[[5,5],[10,9],[0,Infinity],[NaN,5],[1,3]].map(([a,b])=>makeBlock(a,b));
for(const t of [-1,0,1,2,5,5.0005,10,NaN,Infinity]) {
 preview.elapsed=t;paintPlayhead();const now=t||0;
 for(const block of blocks){const a=Number(block.dataset.t0),b=Number(block.dataset.t1),done=Math.min(1,Math.max(0,(now-a)/Math.max(.001,b-a)));assert.equal(block.values['--played'],`${(done*100).toFixed(1)}%`);}
}
preview.on=false;paintPlayhead();assert.equal(head,null);assert.ok(blocks.every(b=>b.values['--played']===undefined));
preview.on=true;preview.elapsed=2;queries=0;paintPlayhead();assert.equal(queries,1);assert.equal(blocks[4].values['--played'],'50.0%');
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
