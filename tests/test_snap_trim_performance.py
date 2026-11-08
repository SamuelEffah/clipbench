import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class SnapTrimPerformance(unittest.TestCase):
    def test_disabled_snapping_skips_timeline_scans_and_keeps_enabled_trim_rules(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/snap.js').read_text()
        trim = 'function snapTrim(' + source.split('function snapTrim(', 1)[1].split('// Scrubbing the playhead', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let snapOn=true,stlPps=40,scans=0,hidden=0,shown=null,target=null,requests=0;
const state={project:{clips:Array.from({length:2000},()=>({in:0,out:5}))}};
const rampOf=c=>c.ramp||'none',freezeOf=c=>c.freeze||0,speedOf=c=>c.speed||1;
const outLen=c=>(c.out-c.in)/speedOf(c),MIN_CLIP=.2;
const clipStarts=clips=>{scans++;return clips.map((_,i)=>i*5);};
const laterInLane=i=>{scans++;return new Set([i]);};
const hideSnapLine=()=>hidden++,showSnapLine=t=>shown=t;
const snapNear=(times,options,bypass)=>{
 requests++;
 if(!snapOn||bypass||!stlPps)return null;
 assert.deepEqual([...options.skipClips],[1]);assert.equal(times.length,1);
 return target;
};
''' + trim + r'''
const original={in:2,out:10,speed:2},next={...original,out:12};
for(const mode of ['alt','off','no-scale']) {
 snapOn=mode!=='off';stlPps=mode==='no-scale'?0:40;scans=0;hidden=0;requests=0;
 assert.equal(snapTrim(next,original,1,'r',{duration:20},mode==='alt'),next);
 assert.equal(scans,0,`${mode}: bypassed trims must not scan the timeline`);
 assert.equal(hidden,1);assert.equal(requests,0);
}
snapOn=true;stlPps=40;target={delta:1,at:11};
assert.deepEqual(snapTrim(next,original,1,'r',{duration:13},false),{...next,out:13});
assert.equal(shown,11);
assert.deepEqual(snapTrim(next,original,1,'l',null,false),{...next,in:0});
target={delta:-100,at:0};
assert.equal(snapTrim(next,original,1,'r',null,false).out,original.in+MIN_CLIP);
assert.equal(snapTrim(next,original,1,'l',null,false).in,next.out-MIN_CLIP);
target=null;hidden=0;
assert.equal(snapTrim(next,original,1,'r',null,false),next);assert.equal(hidden,1);
for(const patch of [{ramp:'hero'},{freeze:1}]) {
 scans=0;hidden=0;
 const c={...original,...patch};
 assert.equal(snapTrim(next,c,1,'r',null,false),next);
 assert.equal(scans,0);assert.equal(hidden,0);
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
