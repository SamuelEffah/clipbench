import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class PausedTimelineShadingPerformance(unittest.TestCase):
    def test_unchanged_time_skips_block_scans_but_new_heads_repaint(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        app = (ui / 'app.js').read_text()
        setter = 'function setPlaybackValue(' + app.split('function setPlaybackValue(', 1)[1].split('\nfunction placePlayhead(', 1)[0]
        audio = (ui / 'audio.js').read_text()
        paint = 'function paintPlayhead(' + audio.split('function paintPlayhead(', 1)[1].split('// ----- Details', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let reads=0,queries=0,head=null,followed,left=40,top=20;
const makeBlock=i=>{const values={};return {dataset:{get t0(){reads++;return String(i*5);},get t1(){reads++;return String(i*5+5);}},values,style:{getPropertyValue:k=>values[k]||'',setProperty(k,v){values[k]=v;},removeProperty(k){delete values[k];}}};};
let blocks=Array.from({length:2000},(_,i)=>makeBlock(i));
const body={querySelector:()=>head,querySelectorAll:()=>{queries++;return blocks;},appendChild(el){head=el;}};
const $=()=>body,timeTrack=()=>({offsetLeft:left,offsetTop:top});
const document={createElement:()=>({style:{},firstChild:{textContent:''},remove(){head=null;}})};
const startScrub=()=>{},followPlayhead=x=>followed=x,preview={on:true,elapsed:2},audioScale={pps:40};let scrub=null;
''' + setter + paint + r'''
paintPlayhead();assert.equal(blocks[0].values['--played'],'40.0%');assert.equal(blocks[1].values['--played'],'0.0%');
reads=queries=0;for(let i=0;i<120;i++)paintPlayhead();
assert.equal(queries,0,'paused frames must not query all timeline blocks');assert.equal(reads,0,'paused frames must not read block timestamps');
preview.elapsed=7;paintPlayhead();assert.equal(queries,0);assert.equal(blocks[0].values['--played'],'100.0%');assert.equal(blocks[1].values['--played'],'40.0%');
reads=queries=0;left=60;top=50;audioScale.pps=20;paintPlayhead();assert.equal(queries,0);assert.equal(head.style.left,'200px');assert.equal(head.style.top,'44px');assert.equal(followed,200);
scrub={t:3};paintPlayhead();assert.equal(blocks[0].values['--played'],'60.0%');assert.equal(blocks[1].values['--played'],'0.0%');
scrub=null;paintPlayhead();assert.equal(blocks[1].values['--played'],'40.0%');
// renderShortTl replaces the head along with the blocks; the same time must repaint them.
head=null;blocks=Array.from({length:500},(_,i)=>makeBlock(i));reads=queries=0;paintPlayhead();assert.equal(queries,1);assert.equal(blocks[1].values['--played'],'40.0%');
preview.on=false;paintPlayhead();assert.equal(head,null);assert.ok(blocks.every(b=>b.values['--played']===undefined));
preview.on=true;reads=queries=0;paintPlayhead();assert.equal(queries,1);assert.equal(blocks[1].values['--played'],'40.0%');
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
