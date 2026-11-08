import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class CollapsedSoundPerformance(unittest.TestCase):
    def test_collapsed_track_skips_clips_and_expanded_track_keeps_alignment(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/short.js').read_text()
        row = 'function soundRow(' + source.split('function soundRow(', 1)[1].split('\nfunction renderShortTl(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const document={createElement:()=>({children:[],append(...els){this.children.push(...els);},appendChild(el){this.children.push(el);}})};
let collapsed=true,checks=0,reads=0;
const soundCollapsed=lane=>{checks++;return collapsed;},laneOf=c=>c.lane||'top';
const seamOverlap=(prev,c)=>prev?(c.overlap||0):0,outLen=c=>c.out-c.in;
const byPath=src=>src==='missing'?null:{path:src};
const soundBlock=(c,index,at,pps,v)=>({index,at,pps,src:v.path});
''' + row + r'''
const clips=new Proxy(Array.from({length:2000},()=>({src:'a',in:0,out:5})),{get(t,k,r){if(/^\d+$/.test(String(k)))reads++;return Reflect.get(t,k,r);}});
const hidden=soundRow('top',clips,20);
assert.equal(reads,0,'collapsed sound tracks must not inspect clips');
assert.equal(checks,1);assert.equal(hidden.hidden,true);
assert.equal(hidden.className,'stl-lane');assert.equal(hidden.children.length,1);
assert.equal(hidden.children[0].className,'stl-track clipsound');
assert.equal(hidden.children[0].children.length,0);
collapsed=false;checks=0;
const mixed=[{src:'a',in:0,out:5},{src:'b',lane:'lower',in:0,out:8},{src:'missing',in:0,out:3,overlap:.2},{src:'c',in:1,out:5,overlap:.4}];
const visible=soundRow('top',mixed,20);
assert.equal(checks,1);assert.equal(visible.hidden,false);
assert.deepEqual(visible.children[0].children,[{index:0,at:0,pps:20,src:'a'},{index:3,at:7.3999999999999995,pps:20,src:'c'}]);
assert.equal(soundRow('empty',mixed,20).hidden,true);
assert.equal(soundRow('top',[],20).hidden,true);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
