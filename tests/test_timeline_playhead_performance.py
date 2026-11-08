import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class TimelinePlayheadPerformance(unittest.TestCase):
    def test_unchanged_playhead_skips_writes_and_reads_position_once(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        app = (ui / 'app.js').read_text()
        helper = 'function setPlaybackValue(' + app.split('function setPlaybackValue(', 1)[1].split('\nfunction placePlayhead', 1)[0]
        audio = (ui / 'audio.js').read_text()
        paint = 'function paintPlayhead() {' + audio.split('function paintPlayhead() {', 1)[1].split('// ----- Details', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
let writes=0,leftReads=0,topReads=0,head=null,followed;
const tracked=t=>new Proxy(t,{set(t,k,v){writes++;t[k]=v;return true;}});
let left=40,top=20,available=true;
const track={get offsetLeft(){leftReads++;return left;},get offsetTop(){topReads++;return top;}};
const makeHead=()=>({style:tracked({}),firstChild:tracked({textContent:''}),remove(){head=null;}});
const values={};
const block={dataset:{t0:'0',t1:'10'},style:{
 getPropertyValue:k=>values[k]||'', setProperty(k,v){writes++;values[k]=v;},removeProperty(k){delete values[k];}
}};
const body={querySelector:()=>head,querySelectorAll:()=>[block],appendChild(el){head=el;}};
const $=()=>body;
const timeTrack=()=>available?track:null;
const document={createElement:makeHead};
const startScrub=()=>{},followPlayhead=x=>followed=x;
const preview={on:true,elapsed:2};
const audioScale={pps:40};
let scrub=null;
''' + helper + paint + r'''
paintPlayhead();
assert.equal(head.style.left,'120px'); assert.equal(head.style.top,'14px');
assert.equal(head.firstChild.textContent,'0:02.0');
assert.equal(values['--played'],'20.0%'); assert.equal(followed,120);
writes=0;leftReads=0;topReads=0;
for(let n=0;n<120;n++) paintPlayhead();
assert.equal(leftReads,120,'read horizontal track position once per frame');
assert.equal(topReads,120);
assert.equal(writes,0,'unchanged playhead must not rewrite styles or timestamp');
preview.elapsed=3;paintPlayhead(); assert.equal(head.style.left,'160px');
assert.equal(head.firstChild.textContent,'0:03.0'); assert.equal(values['--played'],'30.0%');
left=60;top=50;audioScale.pps=20;paintPlayhead();
assert.equal(head.style.left,'120px');assert.equal(head.style.top,'44px');assert.equal(followed,120);
scrub={t:65.25};paintPlayhead();assert.equal(head.firstChild.textContent,'1:05.3');
assert.equal(values['--played'],'100.0%');
preview.on=false;paintPlayhead();assert.equal(head,null);assert.equal(values['--played'],undefined);
preview.on=true;available=false;paintPlayhead();assert.equal(head,null);
available=true;scrub=null;paintPlayhead();assert.ok(head);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
