import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class MonitorEffectPerformance(unittest.TestCase):
    def test_monitor_stops_at_first_effect_and_preserves_selection_priority(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        lookup = 'function monitorClip() {' + source.split('function monitorClip() {', 1)[1].split('\nfunction clearMonitorFx()', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
let reads=0;
const state={current:{path:'source'},sel:-1,project:{clips:[]}};
const video={currentTime:2};
const effectOf=c=>c.effect||'none';
''' + lookup + r'''
state.project.clips=Array.from({length:4000},()=>({
  get src(){reads++;return 'source';}, in:0,out:10,effect:'shake'
}));
for(let n=0;n<120;n++) assert.equal(monitorClip(),state.project.clips[0]);
assert.equal(reads,120,'first match should stop the effect search');
const clips=state.project.clips=[
  {src:'other',in:0,out:10,effect:'shake'},
  {src:'source',in:0,out:10},
  {src:'source',in:0,out:2,effect:'flash'},
  {src:'source',in:2,out:10,effect:'shake'},
  {src:'source',in:0,out:10,effect:'bw'},
];
assert.equal(monitorClip(),clips[3]);
state.sel=4; assert.equal(monitorClip(),clips[4]);
state.sel=0; assert.equal(monitorClip(),clips[3]);
state.sel=1; assert.equal(monitorClip(),clips[3]);
state.sel=100; assert.equal(monitorClip(),clips[3]);
clips[3].effect='none'; assert.equal(monitorClip(),clips[4]);
clips[4].effect='none'; assert.equal(monitorClip(),null);
video.currentTime=1; assert.equal(monitorClip(),clips[2]);
state.current=null; reads=0; assert.equal(monitorClip(),null); assert.equal(reads,0);
state.current={path:'missing'}; assert.equal(monitorClip(),null);
state.project.clips=[]; assert.equal(monitorClip(),null);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
